"""sentix Bitcoin Sentiment — didigitalkan KODE dari grafik resminya.

SUMBER: https://www.crypto-sentiment.com/bitcoin-sentiment (sentix GmbH).

KENAPA DIDIGITALKAN, BUKAN DIAMBIL ANGKANYA. Sentix TIDAK menerbitkan angka, API, atau
JSON untuk indikator ini — satu-satunya bentuk publiknya adalah gambar PNG. Membiarkan
model "membaca" grafik itu berarti model menebak angka dari gambar, persis yang dilarang
proyek ini. Jadi garisnya diurai piksel demi piksel oleh kode, dengan skala yang
diturunkan dari GEOMETRI grafik itu sendiri (garis nol dan label sumbu), tanpa OCR.

Divalidasi terhadap angka resmi di legenda: digitasi titik terakhir 0,315 vs legenda
0,324 pada grafik 5 Sep 2026 — selisih 0,009, kurang dari satu piksel.

APA INDIKATOR INI, DAN APA YANG BUKAN:
  - Ekspektasi investor untuk SATU BULAN ke depan, disurvei MINGGUAN. Rentangnya kira-kira
    -0,4 sampai +0,6 pada grafik ini.
  - Menurut Sentix sendiri ia KONTRARIAN: ekstrem negatif biasanya mendahului kenaikan,
    optimisme tinggi adalah peringatan konsolidasi, dan divergensi menandai titik balik.
  - Ini SENTIMEN, bukan VALUASI. Ia mengukur emosi pasar (serakah vs takut), bukan apakah
    harga Bitcoin mahal atau murah secara fundamental. Menyebutnya pengukur valuasi akan
    membuat pembaca mengira ada dasar nilai wajar di baliknya — padahal tidak ada.
  - "H1" di legendanya adalah HORIZON 1 bulan, BUKAN timeframe 1 jam. Jangan
    diperlakukan seperti label candle.

Pemakaian:
    python cloud/sentix.py              # bacaan terkini
    python cloud/sentix.py --json
    python cloud/sentix.py --uji        # ukur apakah sinyal kontrariannya bekerja
"""

import argparse
import bisect
import csv
import io
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "data", "sentix_cache.json")
URL_GAMBAR = "https://www.crypto-sentiment.com/images/sntm_bitcoins.png"
URL_HALAMAN = "https://www.crypto-sentiment.com/bitcoin-sentiment"
UA = "Mozilla/5.0 (riset-koin)"

WARNA_GARIS = (40, 104, 139)       # garis sentimen biru
WARNA_ZONA_MERAH = (229, 195, 196)
WARNA_ZONA_KREM = (232, 233, 203)
TOLERANSI_WARNA = 18
# Survei mingguan: bacaan lebih tua dari ini sudah melewati satu siklus survei.
UMUR_BASI_HARI = 9
# Ambang zona ekstrem, dibaca dari arsiran zona pada grafik resminya.
AMBANG_OPTIMIS = 0.30
AMBANG_PESIMIS = -0.30


class GagalKalibrasi(Exception):
    """Tata letak grafik tidak lagi seperti yang diharapkan. Lebih baik berhenti daripada
    mengeluarkan angka dari skala yang salah — angka yang salah tapi terlihat presisi jauh
    lebih berbahaya daripada 'tidak tersedia'."""


def _pillow():
    """Muat Pillow, pasang sekali kalau belum ada. None kalau tetap tidak bisa."""
    try:
        from PIL import Image
        return Image
    except ImportError:
        pass
    # Jangan memasang dari dalam tes: pip jalan di subprocess sehingga blokir jaringan
    # suite tidak berlaku, dan yang terjadi adalah menggantung sampai timeout.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "pillow"],
                       check=True, timeout=180, capture_output=True)
        from PIL import Image
        return Image
    except Exception:
        return None


def unduh(tujuan):
    """Unduh PNG lewat curl. Return (ok, last_modified_utc: date|None, err)."""
    header = tujuan + ".hdr"
    try:
        p = subprocess.run(["curl", "-s", "-L", "--max-time", "45", "-A", UA,
                            "-D", header, "-o", tujuan, URL_GAMBAR],
                           capture_output=True, text=True, timeout=60)
        if p.returncode != 0 or not os.path.exists(tujuan) or os.path.getsize(tujuan) < 1000:
            return False, None, "gambar sentix gagal diunduh"
        with open(tujuan, "rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                return False, None, "berkas yang diunduh bukan PNG"
        tgl = None
        try:
            with open(header, encoding="latin-1") as f:
                for baris in f:
                    if baris.lower().startswith("last-modified:"):
                        tgl = parsedate_to_datetime(baris.split(":", 1)[1].strip()).date()
        except Exception:
            pass
        return True, tgl, None
    finally:
        try:
            os.remove(header)
        except OSError:
            pass


def _dekat(c, t, tol=TOLERANSI_WARNA):
    return all(abs(a - b) <= tol for a, b in zip(c, t))


def _kelompok(nilai, jarak_maks=1):
    kel, cur = [], []
    for v in nilai:
        if cur and v - cur[-1] > jarak_maks:
            kel.append(cur)
            cur = []
        cur.append(v)
    if cur:
        kel.append(cur)
    return kel


def kalibrasi(px, W, H):
    """Turunkan skala dari geometri grafik. Raise GagalKalibrasi kalau tak meyakinkan."""
    # Area plot: rentang kolom yang berarsir zona merah pada satu baris di bagian atas.
    baris_zona = next((y for y in range(20, H // 2)
                       if sum(1 for x in range(W) if px[x, y] == WARNA_ZONA_MERAH) > W // 2),
                      None)
    if baris_zona is None:
        raise GagalKalibrasi("zona merah tidak ditemukan — tata letak berubah")
    merah = [x for x in range(W) if px[x, baris_zona] == WARNA_ZONA_MERAH]
    kiri, kanan = min(merah), max(merah)

    # Garis nol: baris dengan piksel hitam terbanyak di area plot.
    skor = [(sum(1 for x in range(kiri, kanan) if sum(px[x, y]) < 60), y)
            for y in range(20, H - 20)]
    skor.sort(reverse=True)
    if skor[0][0] < (kanan - kiri) * 0.8:
        raise GagalKalibrasi("garis nol tidak utuh")
    baris_nol = [y for n, y in skor if n >= skor[0][0] * 0.9]
    nol = sum(baris_nol) / len(baris_nol)

    # Label sumbu kanan: blok glif gelap di kolom tepat di kanan area plot. Jaraknya
    # rata = 0,1 per blok. Dicari di beberapa kolom dan dipilih yang paling banyak blok.
    # Label yang sah membentuk DERET HITUNG yang berjangkar di garis nol. Blok lain di kolom
    # yang sama — judul, legenda, sudut bingkai — tidak jatuh di kelipatan jarak itu, jadi
    # disaring di sini. Versi pertama memilih kolom dengan blok TERBANYAK, dan satu kolom
    # menangkap glif ekstra di atas label 0,6: jarak pertamanya 40, bukan 27, dan
    # kalibrasinya (dengan benar) ditolak.
    terbaik = []
    for x0 in range(kanan + 2, min(kanan + 14, W)):
        ys = [y for y in range(15, H - 15) if sum(px[x0, y]) < 300]
        diatas = sorted(p for p in (sum(k) / len(k) for k in _kelompok(ys) if len(k) >= 3)
                        if p < nol - 5)
        if len(diatas) < 4:
            continue
        gaps = sorted(b - a for a, b in zip(diatas, diatas[1:]))
        jarak = gaps[len(gaps) // 2]                  # median: kebal satu-dua pencilan
        if jarak < 5:
            continue
        sah = [p for p in diatas
               if abs((nol - p) / jarak - round((nol - p) / jarak)) < 0.15
               and round((nol - p) / jarak) >= 1]
        if len(sah) > len(terbaik):
            terbaik = sah
    if len(terbaik) < 4:
        raise GagalKalibrasi(f"label sumbu kanan cuma {len(terbaik)}, butuh minimal 4")
    terbaik.sort()
    selang = [b - a for a, b in zip(terbaik, terbaik[1:])]
    rata = sum(selang) / len(selang)
    # Jarak antar-label harus rata. Kalau tidak, yang terdeteksi bukan label sumbu.
    if max(abs(s - rata) for s in selang) > 2.0:
        raise GagalKalibrasi(f"jarak label tidak rata: {[round(s, 1) for s in selang]}")
    # Label "0.0" harus segaris dengan garis nol — pemeriksa silang dua temuan terpisah.
    if abs((terbaik[-1] + rata) - nol) > 3.0:
        raise GagalKalibrasi("label nol tidak segaris dengan garis nol")

    # Tanda sumbu bawah (kuartal): segmen gelap pendek tepat di bawah tepi plot.
    bawah = max((y for y in range(H) if px[(kiri + kanan) // 2, y] == WARNA_ZONA_KREM),
                default=None)
    if bawah is None:
        raise GagalKalibrasi("tepi bawah plot tidak ditemukan")
    tanda = []
    for y0 in range(bawah + 1, min(bawah + 6, H)):
        xs = [x for x in range(kiri - 3, kanan + 3) if sum(px[x, y0]) < 400]
        cand = [sum(k) / len(k) for k in _kelompok(xs) if len(k) <= 3]
        if len(cand) > len(tanda):
            tanda = cand
    tanda = [t for t in tanda if kiri - 3 <= t <= kanan + 1]
    if len(tanda) < 4:
        raise GagalKalibrasi(f"tanda sumbu waktu cuma {len(tanda)}")
    selang_x = [b - a for a, b in zip(tanda, tanda[1:])]
    rata_x = sum(selang_x) / len(selang_x)
    if max(abs(s - rata_x) for s in selang_x) > 2.5:
        raise GagalKalibrasi("jarak tanda kuartal tidak rata")

    # Tepi ATAS area plot: baris pertama berarsir zona merah. Pemindaian garis WAJIB
    # dibatasi di antara tepi atas dan bawah ini — lihat digitasi().
    atas = next(y for y in range(H) if px[(kiri + kanan) // 2, y] == WARNA_ZONA_MERAH)
    return {"kiri": kiri, "kanan": kanan, "atas": atas, "bawah": bawah, "nol": nol,
            "px_per_satuan": rata * 10, "tanda_kuartal": tanda}


def _awal_kuartal(d):
    return date(d.year, ((d.month - 1) // 3) * 3 + 1, 1)


def _geser_kuartal(d, n):
    bulan = d.month - 1 + 3 * n
    return date(d.year + bulan // 12, bulan % 12 + 1, 1)


def pasang_tanggal(kal, x_terakhir, tgl_grafik):
    """Beri tanggal tiap kolom. Tanda kuartal terakhir = awal kuartal terakhir sebelum
    tanggal grafik; dicek silang dengan memastikan titik terakhir jatuh dekat tanggal itu.
    """
    tanda = kal["tanda_kuartal"]
    for geser in (0, -1, 1):
        akhir = _geser_kuartal(_awal_kuartal(tgl_grafik), geser)
        tgl_tanda = [_geser_kuartal(akhir, i - (len(tanda) - 1)) for i in range(len(tanda))]
        rata = (tanda[-1] - tanda[0]) / (len(tanda) - 1)
        hari_per_px = ((tgl_tanda[-1] - tgl_tanda[-2]).days) / rata
        perkiraan = tgl_tanda[-1] + timedelta(days=(x_terakhir - tanda[-1]) * hari_per_px)
        if abs((perkiraan - tgl_grafik).days) <= 21:
            return tanda, tgl_tanda
    raise GagalKalibrasi("titik terakhir tidak jatuh dekat tanggal grafik")


def x_ke_tanggal(x, tanda, tgl_tanda):
    """Interpolasi linier per kuartal — kuartal tidak sama panjang dalam hari."""
    i = max(1, min(bisect.bisect_left(tanda, x), len(tanda) - 1))
    x0, x1 = tanda[i - 1], tanda[i]
    d0, d1 = tgl_tanda[i - 1], tgl_tanda[i]
    return d0 + timedelta(days=(x - x0) / (x1 - x0) * (d1 - d0).days)


def digitasi(path, tgl_grafik):
    """Urai grafik jadi deret mingguan [(tanggal, nilai)]. Raise GagalKalibrasi."""
    Image = _pillow()
    if Image is None:
        raise GagalKalibrasi("Pillow tidak tersedia")
    img = Image.open(path).convert("RGB")
    W, H = img.size
    px = img.load()
    kal = kalibrasi(px, W, H)

    kolom = []
    for x in range(kal["kiri"] + 1, kal["kanan"]):
        # HANYA di dalam area plot. Versi pertama memindai dari baris 15, dan bilah judul
        # grafik berwarna biru tua yang mirip warna garis sentimen: rata-rata tiap kolom
        # tertarik ke atas. Hasilnya bacaan terkini 0,55 padahal legenda resmi 0,324, dan
        # 69 dari 137 minggu terbaca "optimis ekstrem" dengan NOL minggu pesimis — padahal
        # garisnya jelas turun ke -0,33 beberapa kali. Kalibrasi skalanya benar; yang
        # tercemar adalah piksel yang dianggap garis.
        ys = [y for y in range(kal["atas"], kal["bawah"] + 1) if _dekat(px[x, y], WARNA_GARIS)]
        if ys:
            kolom.append((x, (kal["nol"] - sum(ys) / len(ys)) / kal["px_per_satuan"]))
    if len(kolom) < 100:
        raise GagalKalibrasi(f"garis sentimen cuma {len(kolom)} kolom")
    # Sentimen sentix adalah selisih proporsi, jadi secara definisi berada di [-1, 1].
    # Nilai di luar itu berarti skala yang dipakai salah, bukan pasar yang ekstrem.
    if any(abs(v) > 1.0 for _, v in kolom):
        raise GagalKalibrasi("nilai di luar [-1, 1] — skala salah")

    tanda, tgl_tanda = pasang_tanggal(kal, kolom[-1][0], tgl_grafik)
    per_tgl = [(x_ke_tanggal(x, tanda, tgl_tanda), v) for x, v in kolom]
    # Satu nilai per minggu: kolom terdekat ke tiap tanggal mingguan, mundur dari akhir.
    mingguan, tgl = [], per_tgl[-1][0]
    semua_tgl = [t for t, _ in per_tgl]
    while tgl >= per_tgl[0][0]:
        i = min(range(len(semua_tgl)), key=lambda k: abs((semua_tgl[k] - tgl).days))
        mingguan.append((tgl, round(per_tgl[i][1], 3)))
        tgl -= timedelta(days=7)
    mingguan.reverse()
    return mingguan, kal


def zona(v):
    if v >= AMBANG_OPTIMIS:
        return "OPTIMIS EKSTREM (kontrarian: waspada konsolidasi)"
    if v <= AMBANG_PESIMIS:
        return "PESIMIS EKSTREM (kontrarian: biasanya mendahului kenaikan)"
    if v >= 0:
        return "netral condong optimis"
    return "netral condong pesimis"


def ambil(paksa=False):
    """Bacaan terkini + riwayat. Return dict; kunci 'tidak_tersedia' kalau gagal."""
    import tempfile
    d = tempfile.mkdtemp(prefix="sentix_")
    png = os.path.join(d, "sntm.png")
    ok, tgl_grafik, err = unduh(png)
    if not ok:
        return {"tidak_tersedia": err, "sumber": URL_HALAMAN}
    tgl_grafik = tgl_grafik or datetime.now(timezone.utc).date()
    try:
        deret, kal = digitasi(png, tgl_grafik)
    except GagalKalibrasi as e:
        return {"tidak_tersedia": f"grafik tidak bisa diurai dengan yakin: {e}",
                "sumber": URL_HALAMAN}
    finally:
        try:
            os.remove(png)
            os.rmdir(d)
        except OSError:
            pass

    hari_ini = datetime.now(timezone.utc).date()
    t_akhir, v_akhir = deret[-1]
    umur = (hari_ini - tgl_grafik).days
    ringkas = lambda n: [v for _, v in deret[-n:]]
    hasil = {
        "indikator": "sentix Bitcoin Sentiment (ekspektasi investor 1 bulan, survei mingguan)",
        "sumber": URL_HALAMAN,
        "tanggal_grafik": tgl_grafik.isoformat(),
        "umur_hari": umur,
        "bacaan_terkini": v_akhir,
        "zona": zona(v_akhir),
        "empat_minggu_terakhir": ringkas(4),
        "perubahan_4_minggu": round(v_akhir - deret[-5][1], 3) if len(deret) >= 5 else None,
        "rentang_riwayat": f"{deret[0][0].isoformat()} s/d {t_akhir.isoformat()}",
        "jumlah_minggu": len(deret),
        "wajib_dibaca": (
            "Angka ini DIDIGITALKAN KODE dari grafik resmi sentix — sentix tidak menerbitkan "
            "angkanya. Presisinya sekitar +/-0,01 (divalidasi: 0,315 hasil digitasi vs "
            "0,324 di legenda). Sebut sebagai perkiraan dua desimal, bukan tiga. "
            "Ini SENTIMEN, bukan VALUASI: ia mengukur ekspektasi dan emosi investor, bukan "
            "apakah harga mahal atau murah. Sentix sendiri membacanya secara KONTRARIAN — "
            "ekstrem negatif biasanya mendahului kenaikan, optimisme tinggi adalah "
            "peringatan. 'H1' di legendanya berarti horizon 1 bulan, BUKAN timeframe 1 jam. "
            "Survei mingguan: sebut umurnya."),
    }
    if umur > UMUR_BASI_HARI:
        hasil["peringatan_basi"] = (f"Grafik berumur {umur} hari — melewati satu siklus "
                                    f"survei mingguan. Sebutkan bahwa bacaannya lama.")
    hasil["_deret"] = [(t.isoformat(), v) for t, v in deret]
    return hasil


def _harga_btc():
    """Harga BTC harian dari FRED (CBBTCUSD). Return {date: close}."""
    try:
        p = subprocess.run(["curl", "-s", "--max-time", "45", "-A", "riset-koin/1.0",
                            "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CBBTCUSD"],
                           capture_output=True, text=True, timeout=60)
        keluar = {}
        for r in list(csv.reader(io.StringIO(p.stdout)))[1:]:
            if len(r) >= 2 and r[1] not in (".", ""):
                try:
                    keluar[date.fromisoformat(r[0])] = float(r[1])
                except ValueError:
                    continue
        return keluar
    except Exception:
        return {}


def uji_kontrarian(deret, harga, maju_hari=28):
    """Apakah sentimen EKSTREM mendahului arah harga yang berlawanan?

    Klaim sentix adalah klaim kontrarian yang bisa diperiksa: kalau benar, return 4 minggu
    sesudah zona pesimis ekstrem harus lebih baik daripada sesudah zona optimis ekstrem.
    Dibandingkan juga dengan SELURUH minggu, supaya "naik sesudah pesimis" tidak dikira
    sinyal padahal BTC memang cenderung naik di periode itu.
    """
    tgl_harga = sorted(harga)

    def harga_pada(d):
        i = bisect.bisect_right(tgl_harga, d) - 1
        return harga[tgl_harga[i]] if i >= 0 else None

    def ret(d):
        a, b = harga_pada(d), harga_pada(d + timedelta(days=maju_hari))
        if not a or not b or d + timedelta(days=maju_hari) > tgl_harga[-1]:
            return None
        return (b - a) / a * 100

    grup = {"semua": [], "pesimis_ekstrem": [], "optimis_ekstrem": [], "netral": []}
    for t, v in deret:
        r = ret(date.fromisoformat(t) if isinstance(t, str) else t)
        if r is None:
            continue
        grup["semua"].append(r)
        if v <= AMBANG_PESIMIS:
            grup["pesimis_ekstrem"].append(r)
        elif v >= AMBANG_OPTIMIS:
            grup["optimis_ekstrem"].append(r)
        else:
            grup["netral"].append(r)

    def ringkas(xs):
        if not xs:
            return {"n": 0}
        s = sorted(xs)
        return {"n": len(xs), "median_persen": round(s[len(s) // 2], 2),
                "rata_persen": round(sum(xs) / len(xs), 2),
                "naik_persen": round(sum(1 for x in xs if x > 0) / len(xs) * 100, 1)}

    hasil = {k: ringkas(v) for k, v in grup.items()}
    hasil["horizon_hari"] = maju_hari
    semua = hasil["semua"]
    # Tiap sisi dinilai TERPISAH terhadap seluruh minggu. Menuntut kedua sisi cukup sampel
    # sebelum mengatakan apa pun (versi pertama) mengubur temuan yang justru relevan untuk
    # keputusan: pada grafik 5 Sep 2026 sisi pesimis cuma n=1, tapi sisi optimis n=15
    # memperlihatkan BTC naik LEBIH dari rata-rata sesudah zona "peringatan" — kebalikan
    # klaim kontrarian. User yang menjual di zona merah perlu tahu itu.
    catatan = []
    for nama, label, harap_lebih_baik in (("pesimis_ekstrem", "pesimis ekstrem", True),
                                          ("optimis_ekstrem", "optimis ekstrem", False)):
        g = hasil[nama]
        if g.get("n", 0) < 5:
            catatan.append(f"{label}: n={g.get('n', 0)}, terlalu sedikit untuk dinilai")
            continue
        lebih_baik = g["median_persen"] > semua["median_persen"]
        cocok = lebih_baik == harap_lebih_baik
        catatan.append(
            f"{label} (n={g['n']}): median {maju_hari} hari sesudahnya {g['median_persen']}% "
            f"vs seluruh minggu {semua['median_persen']}% -> "
            + ("SEARAH klaim kontrarian" if cocok else "BERLAWANAN dengan klaim kontrarian"))
    hasil["vonis"] = (
        "; ".join(catatan)
        + ". Minggu-minggu yang berdekatan saling tumpang tindih, jadi jumlah KEJADIAN "
          "independennya jauh lebih kecil dari n — anggap ini petunjuk, bukan bukti. Riwayat "
          "grafiknya pun hanya sejak Jan 2024.")
    return hasil


def main():
    ap = argparse.ArgumentParser(description="sentix Bitcoin Sentiment, didigitalkan kode")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--uji", action="store_true", help="ukur sinyal kontrarian vs harga BTC")
    args = ap.parse_args()
    hasil = ambil()
    if hasil.get("tidak_tersedia"):
        print(json.dumps(hasil, indent=2, ensure_ascii=False) if args.json
              else "TIDAK TERSEDIA: " + hasil["tidak_tersedia"])
        return 1
    if args.uji:
        harga = _harga_btc()
        if not harga:
            hasil["uji_kontrarian"] = {"tidak_tersedia": "harga BTC FRED gagal diambil"}
        else:
            hasil["uji_kontrarian"] = uji_kontrarian(hasil["_deret"], harga)
    hasil.pop("_deret", None)
    if args.json:
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return 0
    for k, v in hasil.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

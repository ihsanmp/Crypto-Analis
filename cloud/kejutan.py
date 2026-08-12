"""Studi peristiwa: bagaimana harga BEREAKSI pada rilis data, dipisah menurut arah KEJUTAN.

Pertanyaan "prediksi CPI nanti bullish untuk emas?" selama ini tidak bisa dijawab dari data.
Yang ada cuma backtest.py::uji_makro, dan itu sengaja hanya mengukur BESAR gerakan pada
jendela tanggal tebakan (tgl 10-15), bukan arahnya, bukan pada tanggal rilis sebenarnya.
Jadi bot cuma bisa bilang "hari CPI biasanya lebih bergejolak" — benar, tapi bukan jawaban.

Yang membuat studi ini mungkin: berkas nowcast Cleveland Fed memuat SATU CHART PER BULAN
TARGET sejak 2013, masing-masing berisi lintasan nowcast harian DAN garis "Actual" yang baru
muncul pada hari rilis. Dari situ tiga hal bisa diperas sekaligus:

  - tanggal rilis SEBENARNYA (hari pertama garis "Actual" terisi),
  - ramalan terakhir sebelum rilis (nowcast di hari sebelum "Actual" muncul),
  - angka aktualnya.

kejutan = aktual - nowcast_terakhir. Itulah yang menggerakkan harga; angka mentahnya tidak.

BATAS YANG WAJIB DISEBUT SAAT MENGUTIP — ini model Cleveland Fed, BUKAN median survei ekonom
Wall Street. Konsensus pasar bisa berbeda, jadi "kejutan" di sini adalah kejutan terhadap
model, bukan terhadap posisi pasar. Perlakukan sebagai perkiraan arah, jangan sebagai
pengukuran kejutan pasar yang presisi.

Pemakaian:
    python cloud/kejutan.py --indikator CPI --simbol GOLD --pasar
    python cloud/kejutan.py --indikator "Core CPI" --simbol BTC
    python cloud/kejutan.py --indikator CPI            # sejarah kejutan saja, tanpa harga
"""

import argparse
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from statistics import median

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "data", "kejutan_cache.json")
CACHE_UMUR = 12 * 3600          # rilis bulanan; tidak berubah tiap jam

CF_URL = ("https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/"
          "nowcast_month.json?sc_lang=en")
UA = {"User-Agent": "Crypto-Analis Research bot"}
TIMEOUT = 60

# Nama seri di berkas Cleveland Fed. Kunci = yang boleh diketik user.
INDIKATOR = {
    "CPI": "CPI Inflation",
    "CORE CPI": "Core CPI Inflation",
    "PCE": "PCE Inflation",
    "CORE PCE": "Core PCE Inflation",
}

# Kejutan kebijakan moneter FOMC dari Federal Reserve Bank of San Francisco (Bauer &
# Swanson): perubahan harga futures suku bunga dalam jendela 30 menit di sekitar pengumuman,
# dalam BASIS POIN. Ini bukan tebakan tentang keputusannya, melainkan repricing pasar yang
# BENAR-BENAR terjadi — sudah mencakup nada statement dan dot plot sekaligus.
#
# DUA BATAS YANG MENENTUKAN CARA PAKAI:
#  1. Serinya berakhir 2023-12-13 dan tidak diperbarui sejak itu. Rezim 2024-2026 TIDAK ada
#     di dalamnya — padahal uji rezim pada CPI menunjukkan periode terakhir justru paling
#     menyimpang. Jangan pernah menyajikannya seolah mencakup keadaan sekarang.
#  2. Kejutannya diukur SETELAH pengumuman. Jadi seri ini menjawab "kalau kejutannya hawkish
#     sekian bp, emas historisnya bergerak berapa" — BUKAN "FOMC nanti bullish atau tidak".
#     Angkanya mustahil diketahui sebelum rapat; itu definisinya, bukan kekurangan data.
#
# Berkas xlsx-nya memuat 361 rapat sejak 1988, tapi candle harian gratis hanya sampai 2011
# (rentang "max" Yahoo turun jadi bulanan), jadi CSV 2012-2023 sudah mencakup seluruh bagian
# yang bisa dipasangkan dengan harga. Tidak ada yang hilang dengan memakai yang sederhana.
FOMC_URL = "https://www.frbsf.org/wp-content/uploads/chart1-monetary-policy-surprises.csv"
FOMC_AKHIR = "2023-12-13"

# Riwayat konsensus SoSoValue yang sudah ditarik dan disimpan (lihat sosovalue.py
# --tarik-riwayat). Ini yang membuat studi kejutan NFP dan PPI mungkin: konsensusnya ada
# sampai 2010, sesuatu yang tidak disimpan sumber gratis lain mana pun.
#
# BATAS YANG WAJIB DISEBUT: konsensus ini TIDAK punya jejak vintage. Tidak ada cara
# memastikan angka forecast-nya sama dengan yang tampil di layar sebelum rilis — kalau
# pernah di-backfill, kejutannya ikut salah. Perlakukan sebagai perkiraan, dan sebutkan
# sumbernya. Bandingkan dengan arsip.py kalau arsip kita sendiri sudah cukup tebal.
SOSO_PATH = os.path.join(BASE_DIR, "data", "sosovalue_riwayat.json")

# Label sisi kejutan berbeda maknanya per sumber: pada CPI "panas" berarti inflasi di atas
# ramalan; pada FOMC positif berarti pasar mereprice ke arah HAWKISH; pada NFP positif
# berarti lapangan kerja lebih KUAT dari perkiraan.
LABEL_SISI = {
    "inflasi": ("kejutan_lebih_panas", "kejutan_lebih_dingin"),
    "fomc": ("kejutan_hawkish", "kejutan_dovish"),
    "tenaga_kerja": ("kejutan_lebih_kuat", "kejutan_lebih_lemah"),
}

# Acara SoSoValue -> label sisi yang benar.
SOSO_SISI = {"NFP": "tenaga_kerja", "PPI": "inflasi",
             "CPI": "inflasi", "CORE CPI": "inflasi"}

# Berapa hari perdagangan ke depan yang diukur. H = hari rilis itu sendiri.
HORIZON = (0, 1, 5)


def _muat_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _simpan_cache(c):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False)
    except Exception as e:
        print(f"[kejutan] gagal menyimpan cache: {e}")


def _angka(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bedah_bulan(entri, seri_nowcast, seri_aktual):
    """Peras (tanggal rilis, nowcast terakhir, aktual) dari satu chart bulan target."""
    bulan = (entri.get("chart") or {}).get("subcaption")
    kategori = (entri.get("categories") or [{}])[0].get("category") or []
    label = [c.get("label") for c in kategori]

    seri = {}
    for s in entri.get("dataset") or []:
        seri[s.get("seriesname")] = [x.get("value") for x in (s.get("data") or [])]

    nowcast, aktual = seri.get(seri_nowcast) or [], seri.get(seri_aktual) or []
    terisi = [i for i, v in enumerate(aktual) if _angka(v) is not None]
    if not terisi or not bulan:
        return None                      # aktual belum rilis

    i0 = terisi[0]
    # Ramalan yang dipakai adalah yang BERLAKU sebelum rilis. Memakai nowcast setelah
    # tanggal rilis akan mencampur informasi yang belum ada saat itu — look-ahead bias.
    sebelum = [_angka(v) for v in nowcast[:i0] if _angka(v) is not None]
    if not sebelum:
        return None

    a = _angka(aktual[i0])
    f = sebelum[-1]
    tanggal = label[i0] if i0 < len(label) else None
    if not tanggal or a is None:
        return None

    # Label sumbu-x cuma "MM/DD"; tahunnya diambil dari bulan target. Rilis selalu jatuh
    # SETELAH bulan targetnya, jadi bulan rilis yang lebih kecil berarti sudah ganti tahun.
    try:
        thn_target, bln_target = (int(x) for x in bulan.split("-")[:2])
        bln_rilis, hari_rilis = (int(x) for x in tanggal.split("/")[:2])
    except (ValueError, IndexError):
        return None
    thn_rilis = thn_target + 1 if bln_rilis < bln_target else thn_target
    try:
        iso = datetime(thn_rilis, bln_rilis, hari_rilis, tzinfo=timezone.utc).date().isoformat()
    except ValueError:
        return None

    return {"bulan_target": bulan, "tanggal_rilis": iso,
            "nowcast_mom_persen": round(f, 3), "aktual_mom_persen": round(a, 3),
            "kejutan_pp": round(a - f, 3)}


def deret_kejutan(indikator, paksa=False):
    """Riwayat (tanggal rilis, nowcast, aktual, kejutan) + rilis yang BELUM keluar."""
    nama = INDIKATOR[indikator]
    nama_aktual = f"Actual {nama}"
    kunci = f"kejutan_{indikator}"

    cache = _muat_cache()
    simpan = cache.get(kunci) or {}
    if simpan.get("data") and time.time() - simpan.get("waktu", 0) < CACHE_UMUR:
        return simpan["data"], True, None

    try:
        with urllib.request.urlopen(urllib.request.Request(CF_URL, headers=UA),
                                    timeout=TIMEOUT) as r:
            mentah = json.loads(r.read().decode(errors="replace"))
    except Exception as e:
        if simpan.get("data"):
            return simpan["data"], True, f"{type(e).__name__} (pakai cache lama)"
        return None, False, f"{type(e).__name__}: {e}"

    riwayat, menunggu = [], []
    for entri in mentah if isinstance(mentah, list) else []:
        hasil = _bedah_bulan(entri, nama, nama_aktual)
        if hasil:
            riwayat.append(hasil)
            continue
        # Belum rilis: nowcast terakhirnya tetap berguna sebagai ramalan yang berlaku.
        bulan = (entri.get("chart") or {}).get("subcaption")
        seri = {s.get("seriesname"): [x.get("value") for x in (s.get("data") or [])]
                for s in entri.get("dataset") or []}
        nilai = [_angka(v) for v in (seri.get(nama) or []) if _angka(v) is not None]
        if bulan and nilai:
            menunggu.append({"bulan_target": bulan, "nowcast_mom_persen": round(nilai[-1], 3)})

    riwayat.sort(key=lambda x: x["tanggal_rilis"])
    data = {"riwayat": riwayat, "belum_rilis": menunggu[-2:]}

    # Payload aslinya 7,5 MB. Yang disimpan HANYA hasil perasan — pernah ada bug cache
    # 13,9 MB di kalender.py karena menyimpan payload mentah.
    cache[kunci] = {"data": data, "waktu": time.time()}
    _simpan_cache(cache)
    return data, False, None


def deret_fomc(paksa=False, ortogonal=False):
    """Kejutan kebijakan FOMC dalam basis poin. Bentuknya disamakan dengan deret_kejutan."""
    kunci = "fomc_sffed"
    cache = _muat_cache()
    simpan = cache.get(kunci) or {}
    mentah, dari_cache, err = None, False, None

    if simpan.get("baris") and not paksa and time.time() - simpan.get("waktu", 0) < CACHE_UMUR:
        mentah, dari_cache = simpan["baris"], True
    else:
        try:
            with urllib.request.urlopen(urllib.request.Request(FOMC_URL, headers=UA),
                                        timeout=TIMEOUT) as r:
                teks = r.read().decode("utf-8-sig", errors="replace")
            mentah = [b for b in teks.splitlines() if b.strip()]
            cache[kunci] = {"baris": mentah, "waktu": time.time()}
            _simpan_cache(cache)
        except Exception as e:
            if simpan.get("baris"):
                mentah, dari_cache = simpan["baris"], True
                err = f"{type(e).__name__} (pakai cache lama)"
            else:
                return None, False, f"{type(e).__name__}: {e}"

    riwayat = []
    for baris in mentah[1:]:                       # baris pertama header
        bagian = [x.strip() for x in baris.split(",")]
        if len(bagian) < 3:
            continue
        tgl, kasar, ortho = bagian[0], _angka(bagian[1]), _angka(bagian[2])
        dipakai = ortho if ortogonal else kasar
        if dipakai is None or not re.match(r"^\d{4}-\d{2}-\d{2}$", tgl):
            continue
        riwayat.append({"tanggal_rilis": tgl,
                        "kejutan_pp": dipakai,          # satuan: basis poin
                        "kejutan_kasar_bp": kasar,
                        "kejutan_ortogonal_bp": ortho,
                        # Tidak ada padanan "aktual" pada FOMC; pemotongan per tingkat
                        # inflasi otomatis dilewati karena kolom ini kosong.
                        "aktual_mom_persen": None})
    riwayat.sort(key=lambda x: x["tanggal_rilis"])
    return {"riwayat": riwayat, "belum_rilis": []}, dari_cache, err


def _nilai_soso(v):
    """'85' -> (85.0, '') · '0.1%' -> (0.1, '%') · '' -> (None, None)."""
    t = (v or "").strip()
    if not t:
        return None, None
    satuan = "%" if t.endswith("%") else ""
    try:
        return float(t.rstrip("%").replace(",", "")), satuan
    except ValueError:
        return None, None


def deret_soso(label):
    """Riwayat kejutan dari berkas SoSoValue. Bentuknya disamakan dengan deret_kejutan."""
    try:
        with open(SOSO_PATH, encoding="utf-8") as f:
            berkas = json.load(f)
    except OSError:
        return None, False, ("berkas riwayat SoSoValue belum ada — jalankan workflow "
                             "'Periksa SoSoValue' sekali untuk menariknya")
    except ValueError:
        return None, False, "berkas riwayat SoSoValue rusak"

    acara = (berkas.get("acara") or {}).get(label)
    if not acara or "data" not in acara:
        return None, False, f"acara '{label}' tidak ada di berkas riwayat"

    riwayat = []
    for baris in acara["data"]:
        tgl = (baris.get("date") or "").strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", tgl):
            continue
        a, sa = _nilai_soso(baris.get("actual"))
        f_, sf = _nilai_soso(baris.get("forecast"))
        # Satuan harus sama; aktual kosong berarti belum rilis.
        if a is None or f_ is None or sa != sf:
            continue
        riwayat.append({"tanggal_rilis": tgl, "kejutan_pp": round(a - f_, 4),
                        "aktual_mom_persen": a if sa == "%" else None,
                        "aktual": a, "konsensus": f_})
    # Baris dengan aktual KOSONG adalah rilis yang belum keluar — di situlah konsensus untuk
    # rilis BERIKUTNYA berada. Ini yang menggantikan peran kalender.py di brief.
    menunggu = []
    for baris in acara["data"]:
        tgl = (baris.get("date") or "").strip()
        a2, _ = _nilai_soso(baris.get("actual"))
        f2, _ = _nilai_soso(baris.get("forecast"))
        if a2 is None and f2 is not None and tgl:
            menunggu.append({"tanggal": tgl, "konsensus": baris.get("forecast"),
                             "sebelumnya": baris.get("previous")})
    menunggu.sort(key=lambda x: x["tanggal"])

    riwayat.sort(key=lambda x: x["tanggal_rilis"])
    return ({"riwayat": riwayat, "belum_rilis": menunggu[:2],
             "ditarik_utc": berkas.get("ditarik_utc"),
             "nama_acara": acara.get("nama")}, True, None)


def _sebaran(nilai):
    """Ringkasan sebaran yang jujur: arah, besar, dan seberapa menyebar."""
    if not nilai:
        return None
    naik = [x for x in nilai if x > 0]
    n = len(nilai)
    r = {"n": n,
         "persen_naik": round(len(naik) / n * 100, 1),
         "median_persen": round(median(nilai), 2),
         "rata2_persen": round(sum(nilai) / n, 2),
         "terbaik_persen": round(max(nilai), 2),
         "terburuk_persen": round(min(nilai), 2)}
    if n < 10:
        r["peringatan"] = (f"SAMPEL KECIL ({n} rilis) — tidak bermakna secara statistik. "
                           "Sebut sebagai catatan, jangan sebagai bukti.")
    return r


def reaksi_harga(simbol, riwayat, pasar, rentang="15y", catatan=None, meta=None,
                 sisi="inflasi"):
    """Reaksi gabungan menurut arah kejutan. Angka POOLED — wajib dibaca bersama uji rezim.

    `catatan`/`meta` boleh dioper supaya pemanggil yang juga menghitung per rezim tidak
    menarik harga dua kali.
    """
    if catatan is None:
        catatan, meta = _per_rilis(simbol, riwayat, pasar, rentang)
        if catatan is None:
            return meta

    panas = {h: [] for h in HORIZON}
    dingin = {h: [] for h in HORIZON}
    semua = {h: [] for h in HORIZON}
    for c in catatan:
        # Bukan bernama `sisi`: itu nama parameter pemilih label, dan menimpanya membuat
        # LABEL_SISI[sisi] menerima dict.
        kelompok = panas if c["kejutan_pp"] > 0 else dingin
        for h, v in c["ret"].items():
            semua[h].append(v)
            kelompok[h].append(v)

    def bungkus(d):
        return {f"H+{h}" if h else "H (hari rilis)": _sebaran(v) for h, v in d.items()}

    hasil = {
        "simbol": meta["simbol"],
        "rilis_terpakai": len(catatan),
        "jendela_harga": meta["jendela_harga"],
        "diukur": ("H = open->close hari rilis; H+1 dan H+5 = close hari rilis -> close "
                   "n hari perdagangan berikutnya. Semua dalam persen."),
        "semua_rilis": bungkus(semua),
        LABEL_SISI[sisi][0]: bungkus(panas),
        LABEL_SISI[sisi][1]: bungkus(dingin),
    }
    for k in ("di_luar_jangkauan_harga", "tanpa_hari_perdagangan"):
        if meta.get(k):
            hasil[k] = meta[k]

    # Riwayat harga crypto gratis cuma ~1 tahun, jadi tumpang tindihnya dengan seri rilis
    # bisa tinggal belasan kejadian — atau nol untuk FOMC yang berakhir 2023. Angka yang
    # keluar tetap terlihat rapi, dan itu bahayanya. Batasi pembacaannya di sini.
    if len(catatan) < 24:
        hasil["peringatan_cakupan"] = (
            f"Hanya {len(catatan)} rilis yang beririsan dengan riwayat harga "
            f"({meta['jendela_harga']}). Itu TERLALU PENDEK untuk membaca arah — sampaikan "
            "sebagai catatan cakupan, jangan sebagai temuan. Untuk aset dengan riwayat "
            "harian pendek, pakai bagian ini hanya untuk menunjukkan bahwa rilisnya "
            "menaikkan volatilitas.")

    # Label panjang dipertahankan di sini supaya bentuk keluaran tidak berubah; uji rezim
    # memakai label pendek karena tampil sebagai tabel banyak baris.
    selisih = {("H (hari rilis)" if k == "H" else k): v
               for k, v in _selisih_median(catatan)["selisih"].items()}
    if selisih:
        hasil["selisih_median_panas_dikurangi_dingin_persen"] = selisih
        # BUKAN "cara_baca": nama itu ada di _PANDUAN_STATIS dan dibuang oleh --ringkas,
        # padahal --ringkas justru yang dipakai produksi. Aturan yang menentukan boleh
        # tidaknya angka ini dikutip TIDAK BOLEH ikut terbuang.
        # Atribusi sumber SENGAJA tidak diulang di sini. Kalimat ini dipakai ketiga sumber
        # (nowcast Cleveland Fed, konsensus pasar SoSoValue, seri SF Fed), jadi menyebut
        # satu sumber di dalamnya membuatnya SALAH pada dua sumber lainnya — dan itu pernah
        # terjadi. Sumber yang benar sudah tercetak di field "sumber" tiap keluaran.
        hasil["wajib_dibaca"] = (
            "Angka ini GABUNGAN seluruh riwayat dan TIDAK BOLEH dikutip sendirian. Contoh "
            "nyata pada emas: selisih H+5 gabungan ternyata artefak — tandanya berbalik "
            "saat data dipotong per periode (2013-2017 dan 2017-2022 POSITIF, hanya "
            "2022-2026 sangat negatif). Baca 'uji_ketahanan_per_rezim' LEBIH DULU dan "
            "pakai vonisnya. Selisih di bawah ~0,3% pada emas tidak bisa dibedakan dari "
            "derau harian — sebut TIDAK ADA EDGE ARAH. Sebutkan juga terhadap APA kejutan "
            "diukur; lihat field 'sumber', karena arah efeknya bisa berbeda antar sumber.")
    return hasil


def _per_rilis(simbol, riwayat, pasar, rentang="15y"):
    """Satu catatan per rilis: kejutan + return H/H+1/H+5. Dasar semua pengelompokan.

    Dipisah dari agregasinya supaya data yang sama bisa dipotong menurut rezim tanpa
    menarik ulang harga — dan supaya angka di pemotongan mana pun dijamin berasal dari
    perhitungan yang persis sama.
    """
    if pasar:
        from market import tarik
        KOM = {"GOLD": "GC=F", "EMAS": "GC=F", "XAUUSD": "GC=F", "SILVER": "SI=F",
               "PERAK": "SI=F", "XAGUSD": "SI=F", "OIL": "CL=F", "WTI": "CL=F",
               "DXY": "DX-Y.NYB", "SPX": "^GSPC"}
        s = KOM.get(simbol.upper(), simbol.upper())
        candles, _, err = tarik(s, rentang, "1d")
    else:
        from indicators import fetch_base, resolve_cg_id
        s = simbol.upper()
        candles, _, _, err = fetch_base(s, resolve_cg_id(s), "1d")
    if err or not candles:
        return None, {"tidak_tersedia": err or "candle kosong"}

    baris, urut = {}, []
    for i, c in enumerate(candles):
        tgl = datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc).date().isoformat()
        baris[tgl] = i
        urut.append(tgl)
    if not urut:
        return None, {"tidak_tersedia": "candle kosong"}

    awal, akhir = urut[0], urut[-1]
    catatan, di_luar, tanpa_padanan = [], 0, 0
    for r in riwayat:
        tgl = r["tanggal_rilis"]
        if tgl < awal or tgl > akhir:
            di_luar += 1
            continue
        i = baris.get(tgl)
        if i is None:
            berikut = [t for t in urut if t > tgl]
            if not berikut:
                tanpa_padanan += 1
                continue
            i = baris[berikut[0]]
        ret = {}
        for h in HORIZON:
            j = i + h
            if j >= len(candles):
                continue
            buka = candles[i][1] if h == 0 else candles[i][4]
            tutup = candles[j][4]
            if buka and tutup:
                ret[h] = (tutup - buka) / buka * 100
        if ret:
            catatan.append({"tanggal": tgl, "kejutan_pp": r["kejutan_pp"],
                            "aktual": r.get("aktual_mom_persen"), "ret": ret})
    meta = {"simbol": s, "jendela_harga": f"{awal} s/d {akhir}",
            "di_luar_jangkauan_harga": di_luar, "tanpa_hari_perdagangan": tanpa_padanan}
    return catatan, meta


def _selisih_median(catatan):
    """median(panas) - median(dingin) per horizon, plus jumlah sampel tiap sisi."""
    panas = {h: [] for h in HORIZON}
    dingin = {h: [] for h in HORIZON}
    for c in catatan:
        sisi = panas if c["kejutan_pp"] > 0 else dingin
        for h, v in c["ret"].items():
            sisi[h].append(v)
    keluar = {"n_panas": len(panas[1]), "n_dingin": len(dingin[1]), "selisih": {}}
    for h in HORIZON:
        if panas[h] and dingin[h]:
            nama = f"H+{h}" if h else "H"
            keluar["selisih"][nama] = round(median(panas[h]) - median(dingin[h]), 2)
    # Median dari sisi yang cuma 8 kejadian mudah bergeser oleh satu-dua rapat. Vonis
    # "tanda bertahan" yang bersandar pada potongan setipis itu harus terlihat tipisnya.
    tertipis = min(keluar["n_panas"], keluar["n_dingin"])
    if tertipis < 10:
        keluar["peringatan"] = (f"SISI TERTIPIS HANYA {tertipis} KEJADIAN — median di "
                                "potongan ini rapuh. Jangan diperlakukan setara potongan "
                                "yang tebal.")
    return keluar


def reaksi_per_rezim(simbol, riwayat, pasar, rentang="15y", catatan=None, meta=None):
    """Apakah tandanya BERTAHAN kalau datanya dipotong? Ini uji ketahanan, bukan hiasan.

    Satu temuan dari 154 rilis yang membentang 13 tahun bisa sepenuhnya digerakkan oleh
    satu rezim — mis. guncangan inflasi 2021-2023 — lalu tampil seolah berlaku umum.
    Kalau tandanya berbalik antar-potongan, temuan itu TIDAK bisa dipakai meramal.
    """
    if catatan is None:
        catatan, meta = _per_rilis(simbol, riwayat, pasar, rentang)
        if catatan is None:
            return meta
    if len(catatan) < 30:
        return {"tidak_tersedia": f"hanya {len(catatan)} rilis cocok dengan riwayat harga — "
                                  "terlalu sedikit untuk dipotong per rezim"}

    urut = sorted(catatan, key=lambda c: c["tanggal"])
    n = len(urut)
    potongan = {}

    # 1. Kronologis: sepertiga awal / tengah / akhir.
    for nama, bagian in (("periode_awal", urut[:n // 3]),
                         ("periode_tengah", urut[n // 3:2 * n // 3]),
                         ("periode_akhir", urut[2 * n // 3:])):
        potongan[f"{nama} ({bagian[0]['tanggal'][:7]}..{bagian[-1]['tanggal'][:7]})"] = bagian

    # 2. Tingkat inflasi: aktual MoM di atas / di bawah median. Rezim inflasi tinggi dan
    #    rendah adalah dua dunia berbeda bagi emas.
    dengan_aktual = [c for c in urut if c.get("aktual") is not None]
    if len(dengan_aktual) >= 30:
        batas = median(c["aktual"] for c in dengan_aktual)
        potongan[f"inflasi_tinggi (MoM > {batas:.2f}%)"] = [
            c for c in dengan_aktual if c["aktual"] > batas]
        potongan[f"inflasi_rendah (MoM <= {batas:.2f}%)"] = [
            c for c in dengan_aktual if c["aktual"] <= batas]

    # 3. Besar kejutan: kejutan kecil sebagian besar derau. Kalau ada sinyal, mestinya
    #    paling terlihat pada kejutan besar.
    batas_k = median(abs(c["kejutan_pp"]) for c in urut)
    potongan[f"kejutan_besar (|kejutan| > {batas_k:.3f}pp)"] = [
        c for c in urut if abs(c["kejutan_pp"]) > batas_k]
    potongan[f"kejutan_kecil (|kejutan| <= {batas_k:.3f}pp)"] = [
        c for c in urut if abs(c["kejutan_pp"]) <= batas_k]

    hasil = {"simbol": meta["simbol"], "total_rilis": n,
             "potongan": {nama: _selisih_median(b) for nama, b in potongan.items()
                          if len(b) >= 8},
             "batas_metode": (
                 "Ketiga cara memotong memakai RILIS YANG SAMA, jadi potongannya tumpang "
                 "tindih dan bukan tujuh uji independen. Ini uji ketahanan sederhana: "
                 "kalau tanda saja sudah berbalik antar potongan, temuannya jelas rapuh. "
                 "Tanda yang bertahan TIDAK otomatis berarti efeknya nyata — besarannya "
                 "tetap harus di atas derau.")}

    tipis = [n for n, p in hasil["potongan"].items() if p.get("peringatan")]
    if tipis:
        hasil["potongan_bersampel_tipis"] = tipis

    # Vonis ketahanan. H (hari rilis) DULU dikecualikan karena dianggap terlalu berisik —
    # itu keliru dan sempat menyembunyikan temuan. Pada NFP, H adalah satu-satunya horizon
    # yang tandanya konsisten (negatif di kelima potongan, -0,24% s/d -1,30%), sementara
    # H+1 dan H+5 berbalik-balik. Ceritanya justru masuk akal: rilis menggerakkan harga
    # SEKETIKA, lalu derau harian mengambil alih. Menghakimi hanya H+1/H+5 berarti
    # menyimpulkan "tidak ada apa-apa" pada kejadian yang jelas ada apa-apanya.
    for horizon in ("H", "H+1", "H+5"):
        tanda = [p["selisih"].get(horizon) for p in hasil["potongan"].values()
                 if p["selisih"].get(horizon) is not None]
        if len(tanda) < 3:
            continue
        positif = sum(1 for t in tanda if t > 0)
        negatif = sum(1 for t in tanda if t < 0)
        konsisten = positif == 0 or negatif == 0
        hasil[f"vonis_{horizon}"] = {
            "potongan_diuji": len(tanda),
            "tanda_positif": positif, "tanda_negatif": negatif,
            "nilai": tanda,
            "tanda_bertahan": konsisten,
            # "arti" juga dibuang --ringkas. Tanpa kalimat ini model cuma menerima boolean
            # telanjang dan harus menebak sendiri apa yang mesti dilakukan.
            "tindakan": ("Tanda BERTAHAN di semua potongan — temuannya lebih bisa dipercaya, "
                     "walau besarannya tetap kecil."
                     if konsisten else
                     "Tanda BERBALIK antar potongan. Temuan gabungan itu artefak "
                     "pengelompokan, BUKAN sifat yang bisa dipakai meramal. Perlakukan "
                     "seperti NFP/PPI/FOMC: sampaikan jadwal dan volatilitas saja, dan "
                     "katakan arahnya tidak bisa diprediksi."),
        }
    return hasil


def main_soso(args, label):
    """Jalur konsensus pasar tersimpan. Menutup NFP dan PPI yang tak punya nowcast model."""
    data, _, err = deret_soso(label)
    keluar = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "indikator": label,
        "sumber": ("konsensus pasar SoSoValue (tersimpan), BUKAN nowcast model. Tidak ada "
                   "jejak vintage: tak bisa dipastikan angka forecast-nya sama dengan yang "
                   "tampil sebelum rilis. Sebutkan sumbernya saat mengutip."),
    }
    if err or not data:
        keluar["tidak_tersedia"] = err or "gagal membaca riwayat"
        print(json.dumps(keluar, indent=2, ensure_ascii=False))
        return

    riwayat = data["riwayat"]
    keluar["nama_acara"] = data.get("nama_acara")
    if data.get("belum_rilis"):
        keluar["rilis_berikutnya"] = data["belum_rilis"]
    keluar["data_ditarik_utc"] = data.get("ditarik_utc")
    keluar["jumlah_rilis"] = len(riwayat)
    keluar["jendela"] = (f"{riwayat[0]['tanggal_rilis']} s/d {riwayat[-1]['tanggal_rilis']}"
                         if riwayat else None)
    if args.simbol and riwayat:
        catatan, meta = _per_rilis(args.simbol, riwayat, args.pasar)
        if catatan is None:
            keluar["reaksi_harga"] = meta
        else:
            keluar["reaksi_harga"] = reaksi_harga(
                args.simbol, riwayat, args.pasar, catatan=catatan, meta=meta,
                sisi=SOSO_SISI[label])
            if args.rezim:
                keluar["uji_ketahanan_per_rezim"] = reaksi_per_rezim(
                    args.simbol, riwayat, args.pasar, catatan=catatan, meta=meta)
    if args.ringkas:
        from backtest import buang_panduan
        keluar = buang_panduan(keluar)
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


def main_fomc(args):
    """Jalur FOMC. Dipisah dari jalur inflasi karena sumber, satuan, dan batasnya berbeda."""
    data, dari_cache, err = deret_fomc(args.paksa if hasattr(args, "paksa") else False,
                                       args.ortogonal)
    keluar = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "indikator": "FOMC",
        "ukuran": ("kejutan ORTOGONAL (bersih dari informasi publik sebelum pengumuman)"
                   if args.ortogonal else "kejutan KASAR"),
        "satuan": "basis poin",
        "sumber": ("Federal Reserve Bank of San Francisco — Monetary Policy Surprises "
                   "(Bauer & Swanson 2023): perubahan futures suku bunga dalam jendela "
                   "30 menit di sekitar pengumuman FOMC."),
        "dari_cache": dari_cache,
    }
    if err or not data:
        keluar["tidak_tersedia"] = err or "gagal mengurai CSV kejutan FOMC"
        print(json.dumps(keluar, indent=2, ensure_ascii=False))
        return

    riwayat = data["riwayat"]
    keluar["jumlah_rapat"] = len(riwayat)
    keluar["jendela"] = (f"{riwayat[0]['tanggal_rilis']} s/d {riwayat[-1]['tanggal_rilis']}"
                         if riwayat else None)
    keluar["batas_wajib_disebut"] = (
        f"Seri ini BERAKHIR {FOMC_AKHIR} dan tidak diperbarui sejak itu — rezim 2024-2026 "
        "tidak terwakili sama sekali. Dan kejutannya diukur SETELAH pengumuman, jadi angka "
        "ini TIDAK BISA dipakai memperkirakan hasil rapat yang akan datang. Yang bisa "
        "dijawab hanyalah SENSITIVITAS: kalau kejutannya hawkish sekian basis poin, "
        "historisnya harga bergerak berapa.")

    if args.simbol:
        catatan, meta = _per_rilis(args.simbol, riwayat, args.pasar)
        if catatan is None:
            keluar["reaksi_harga"] = meta
        else:
            keluar["reaksi_harga"] = reaksi_harga(args.simbol, riwayat, args.pasar,
                                                  catatan=catatan, meta=meta, sisi="fomc")
            if args.rezim:
                keluar["uji_ketahanan_per_rezim"] = reaksi_per_rezim(
                    args.simbol, riwayat, args.pasar, catatan=catatan, meta=meta)
    if args.ringkas:
        from backtest import buang_panduan
        keluar = buang_panduan(keluar)
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indikator", default="CPI",
                    help="CPI | Core CPI | PCE | Core PCE | FOMC")
    ap.add_argument("--ortogonal", action="store_true",
                    help="FOMC: pakai kejutan yang diortogonalisasi terhadap informasi "
                         "publik sebelum pengumuman (Bauer-Swanson)")
    ap.add_argument("--simbol", help="aset yang diukur reaksinya, mis. GOLD / BTC / SPX")
    ap.add_argument("--pasar", action="store_true",
                    help="simbol berupa komoditas/saham/forex (via market.py)")
    ap.add_argument("--sumber", default="nowcast", choices=("nowcast", "sosovalue"),
                    help="nowcast = Cleveland Fed (CPI/PCE saja); sosovalue = konsensus "
                         "pasar tersimpan (NFP/PPI/CPI/Core CPI)")
    ap.add_argument("--rezim", action="store_true",
                    help="uji apakah tanda selisih bertahan saat data dipotong per rezim")
    ap.add_argument("--ringkas", action="store_true",
                    help="buang panduan statis (dipakai saat dikirim ke model)")
    args = ap.parse_args()

    ind = args.indikator.strip().upper()
    if ind == "FOMC":
        main_fomc(args)
        return
    if ind in SOSO_SISI and args.sumber == "sosovalue":
        main_soso(args, ind)
        return
    if ind not in INDIKATOR:
        print(json.dumps({"tidak_tersedia": f"indikator '{args.indikator}' tidak dikenal",
                          "pilihan": list(INDIKATOR)}, indent=2, ensure_ascii=False))
        return

    data, dari_cache, err = deret_kejutan(ind)
    keluar = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "indikator": ind,
        "sumber": ("Cleveland Fed inflation nowcasting — RAMALAN MODEL, bukan median survei "
                   "ekonom Wall Street. Sebut demikian saat mengutip."),
        "dari_cache": dari_cache,
    }
    if err or not data:
        keluar["tidak_tersedia"] = err or "gagal mengurai berkas nowcast"
        print(json.dumps(keluar, indent=2, ensure_ascii=False))
        return

    riwayat = data["riwayat"]
    kejut = [r["kejutan_pp"] for r in riwayat]
    keluar["belum_rilis"] = data["belum_rilis"]
    keluar["sejarah_kejutan"] = {
        "jumlah_rilis": len(riwayat),
        "jendela": f"{riwayat[0]['tanggal_rilis']} s/d {riwayat[-1]['tanggal_rilis']}"
                   if riwayat else None,
        "kejutan_median_pp": round(median(kejut), 3) if kejut else None,
        "persen_lebih_panas": round(sum(1 for k in kejut if k > 0) / len(kejut) * 100, 1)
                              if kejut else None,
        "kejutan_12_terakhir": riwayat[-12:],
    }
    if args.simbol:
        # Harga ditarik SEKALI lalu dipakai kedua analisis, supaya angka gabungan dan angka
        # per rezim dijamin berasal dari deret yang persis sama.
        catatan, meta = _per_rilis(args.simbol, riwayat, args.pasar)
        if catatan is None:
            keluar["reaksi_harga"] = meta
        else:
            keluar["reaksi_harga"] = reaksi_harga(args.simbol, riwayat, args.pasar,
                                                  catatan=catatan, meta=meta)
            if args.rezim:
                keluar["uji_ketahanan_per_rezim"] = reaksi_per_rezim(
                    args.simbol, riwayat, args.pasar, catatan=catatan, meta=meta)

    if args.ringkas:
        from backtest import buang_panduan
        keluar = buang_panduan(keluar)
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

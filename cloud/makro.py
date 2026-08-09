"""Data makro ekonomi AS dari FRED (Federal Reserve) — RESMI, gratis, TANPA API key.

Mengisi lubang nyata: cloud/data/gold_drivers.md mendaftar CPI, NFP, pengangguran, Fed
Funds, dan yield sebagai penggerak utama emas & forex — tapi bot tidak punya sumber
angkanya sama sekali dan bersandar pada WebSearch, yang rapuh untuk angka.

Dipakai endpoint CSV publik FRED (fredgraph.csv) yang tidak memerlukan kunci sama sekali.

YANG DIBERIKAN vs TIDAK:
  DAPAT  : angka AKTUAL yang sudah dirilis + perubahan MoM/YoY + umur datanya.
  TIDAK  : angka KONSENSUS/forecast sebelum rilis. Itu tidak tersedia gratis di mana pun,
           jadi tetap harus diminta ke user. Yang menggerakkan pasar adalah SELISIH
           actual vs forecast — dengan script ini separuhnya (actual) sudah otomatis.

BATASAN YANG WAJIB DISAMPAIKAN:
  - Data bulanan TERTINGGAL. CPI bulan Juni baru terbit pertengahan Juli, jadi "terbaru"
    bisa berumur 1-2 bulan. Umur selalu dihitung dan ditampilkan.
  - Ini data AS saja. Untuk bank sentral lain (ECB, BoJ) tidak tercakup.
  - Angka bisa DIREVISI di rilis berikutnya (lazim untuk NFP).

Pemakaian:
    python cloud/makro.py
    python cloud/makro.py --ringkas
"""

import argparse
import json
import concurrent.futures
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-pasar/1.0)"}
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
TIMEOUT = 20
PARALEL = 6      # FRED dari runner GitHub jauh lebih lambat daripada dari rumah:
                 # sepuluh permintaan berurutan pernah menembus 240 detik (run 31165241681)

# (kode FRED, nama, satuan, jenis) — jenis "bulanan" dihitung MoM/YoY, "harian" dihitung
# perubahan 30 hari.
SERI = [
    ("CPIAUCSL", "CPI (harga konsumen)", "indeks", "bulanan"),
    ("CPILFESL", "Core CPI (tanpa pangan & energi)", "indeks", "bulanan"),
    ("PCEPILFE", "Core PCE (ukuran resmi target Fed)", "indeks", "bulanan"),
    ("PAYEMS", "NFP (pekerja nonpertanian)", "ribu orang", "bulanan"),
    ("UNRATE", "Tingkat pengangguran", "persen", "bulanan"),
    ("ICSA", "Klaim pengangguran awal (mingguan)", "orang", "harian"),
    ("DFF", "Fed Funds Rate (efektif)", "persen", "harian"),
    ("DGS2", "Yield US 2 tahun", "persen", "harian"),
    ("DGS10", "Yield US 10 tahun", "persen", "harian"),
    ("DTWEXBGS", "Indeks dolar AS (broad)", "indeks", "harian"),
    # Kredit & kondisi finansial. Spread kredit bereaksi LEBIH CEPAT daripada saham
    # terhadap guncangan — pelebarannya biasanya mendahului tekanan equity.
    ("BAMLH0A0HYM2", "Spread High Yield (HY OAS)", "persen", "harian"),
    ("BAMLC0A0CM", "Spread Investment Grade (IG OAS)", "persen", "harian"),
    ("NFCI", "Indeks kondisi finansial Chicago Fed", "indeks", "harian"),
    ("DFII10", "Yield RIIL 10 tahun (TIPS)", "persen", "harian"),
    ("DGS3MO", "Yield US 3 bulan", "persen", "harian"),
]

# Seri yang persentilnya dihitung. Nilai mentah spread kredit tidak berarti tanpa tahu
# posisinya terhadap sejarah: HY OAS 2,7% terdengar kecil, tapi apakah itu zona euforia
# atau normal hanya terlihat dari peringkat persentilnya.
_PERSENTIL = {"BAMLH0A0HYM2", "BAMLC0A0CM", "NFCI", "DFII10"}
_TAHUN_PERSENTIL = 3

# Arah dampak ke EMAS bila angkanya NAIK. Sesuai cloud/data/gold_drivers.md, termasuk
# DUA PENGECUALIAN yang arahnya terbalik (pengangguran & klaim: naik = ekonomi lemah =
# Fed dovish = emas NAIK).
ARAH_EMAS = {
    "CPIAUCSL": "turun", "CPILFESL": "turun", "PCEPILFE": "turun",
    "PAYEMS": "turun", "DFF": "turun", "DGS2": "turun", "DGS10": "turun",
    "DTWEXBGS": "turun",
    "UNRATE": "NAIK (pengecualian arah)", "ICSA": "NAIK (pengecualian arah)",
    # Yield RIIL adalah discount rate untuk semua aset berdurasi panjang — naik menekan
    # emas paling langsung. Spread kredit melebar = stres, biasanya menopang emas.
    "DFII10": "turun", "DGS3MO": "turun",
    "BAMLH0A0HYM2": "NAIK (stres kredit menopang emas)",
    "BAMLC0A0CM": "NAIK (stres kredit menopang emas)",
    "NFCI": "NAIK (kondisi finansial mengetat = stres)",
}


def ambil(kode):
    """Return list (tanggal, nilai) terurut lama->baru, atau (None, error)."""
    try:
        req = urllib.request.Request(FRED + kode, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            baris = r.read().decode().strip().split("\n")
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, type(e).__name__

    keluar = []
    for b in baris[1:]:
        bagian = b.split(",")
        if len(bagian) < 2 or bagian[1].strip() in (".", ""):
            continue        # FRED menandai data kosong dengan titik — jangan ditambal
        try:
            keluar.append((bagian[0].strip(), float(bagian[1])))
        except ValueError:
            continue
    return (keluar, None) if keluar else (None, "tidak ada data terbaca")


def tumbuh(baru, lama):
    if baru is None or not lama:
        return None
    return round((baru - lama) / abs(lama) * 100, 2)


def olah(kode, nama, satuan, jenis, data):
    tgl, nilai = data[-1]
    try:
        umur = (datetime.now(timezone.utc).date() - datetime.strptime(tgl, "%Y-%m-%d").date()).days
    except Exception:
        umur = None

    item = {"nama": nama, "kode_fred": kode, "satuan": satuan,
            "terbaru": nilai, "tanggal_data": tgl, "umur_hari": umur,
            "arah_emas_bila_naik": ARAH_EMAS.get(kode)}

    if jenis == "bulanan":
        if len(data) >= 2:
            item["mom_persen"] = tumbuh(nilai, data[-2][1])
        if len(data) >= 13:
            item["yoy_persen"] = tumbuh(nilai, data[-13][1])
        # NFP lebih bermakna sebagai SELISIH orang, bukan persen.
        if kode == "PAYEMS" and len(data) >= 2:
            item["tambahan_pekerjaan_ribu"] = round(nilai - data[-2][1], 1)
    else:
        acuan = data[-22] if len(data) >= 22 else data[0]
        item["perubahan_30h_persen"] = tumbuh(nilai, acuan[1])
        item["nilai_30h_lalu"] = acuan[1]

    if kode in _PERSENTIL and len(data) > 60:
        # Jendela dihitung dari TANGGAL, bukan jumlah titik. Memakai 252*3 titik hanya
        # benar untuk seri harian: NFCI itu MINGGUAN, sehingga 756 titik = 14,5 tahun
        # padahal fieldnya bernama persentil_3thn. Labelnya keliru secara faktual, dan
        # persentil terhadap 14 tahun berarti hal yang sangat berbeda.
        batas = datetime.strptime(tgl, "%Y-%m-%d") - timedelta(days=365 * _TAHUN_PERSENTIL)
        jendela = []
        for t, v in data:
            try:
                if datetime.strptime(t, "%Y-%m-%d") >= batas:
                    jendela.append((t, v))
            except ValueError:
                continue
        if len(jendela) < 30:
            jendela = data[-60:]      # riwayat terlalu pendek: pakai apa adanya
        nilai_saja = sorted(x[1] for x in jendela)
        posisi = sum(1 for x in nilai_saja if x <= nilai)
        item["persentil"] = round(posisi / len(nilai_saja) * 100, 1)
        item["rentang_jendela"] = [round(nilai_saja[0], 3), round(nilai_saja[-1], 3)]
        item["jendela_persentil"] = f"{jendela[0][0]} s/d {jendela[-1][0]} ({len(jendela)} titik)"
        item["arti_persentil"] = ("0 = terendah dalam jendela di atas, 100 = tertinggi. "
                                  "Untuk spread kredit: persentil RENDAH berarti kompresi/"
                                  "euforia (risiko dihargai murah), TINGGI berarti stres.")

    # FRED memberi tanggal di AWAL periode: data bulan Juni bertanggal 2026-06-01 padahal
    # baru terbit pertengahan Juli. Jadi "umur" terlihat besar walau itu rilis TERBARU.
    # Tanpa penjelasan ini, bot bisa salah menyebutnya data basi.
    if jenis == "bulanan":
        item["arti_tanggal"] = (f"periode data = {tgl[:7]}; FRED menandai dengan tanggal awal "
                                "bulan. Ini rilis TERBARU yang tersedia, bukan data basi — "
                                "laporan bulanan memang terbit sebulan setelah periodenya.")
    elif umur is not None and umur > 10:
        item["catatan_umur"] = (f"data harian terakhir berumur {umur} hari — periksa apakah "
                                "pasar sedang libur atau rilisnya tertunda")
    return item



# Sumber TAMBAHAN di luar FRED. Daftar endpoint publiknya ditemukan lewat penelusuran
# konektor FinceptTerminal; implementasinya ditulis sendiri (kode mereka AGPL — daftar API
# publik itu sendiri bukan objek hak cipta). Semua tanpa API key, diuji hidup.
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/"
ECB_DFR = ("https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV"
           "?lastNObservations=1&format=csvdata")


def _yahoo_terakhir(simbol):
    try:
        req = urllib.request.Request(YAHOO + simbol + "?range=1mo&interval=1d", headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            hasil = json.loads(r.read().decode())["chart"]["result"][0]
        meta = hasil.get("meta") or {}
        # previousClose tidak selalu ada di meta indeks; ambil dari deret penutupan.
        sebelum = meta.get("previousClose") or meta.get("chartPreviousClose")
        if sebelum is None:
            tutup = [x for x in (((hasil.get("indicators") or {}).get("quote") or [{}])[0]
                                 .get("close") or []) if x is not None]
            sebelum = tutup[-2] if len(tutup) >= 2 else None
        return meta.get("regularMarketPrice"), sebelum, None
    except Exception as e:
        return None, None, type(e).__name__


def ecb_suku_bunga():
    """Suku bunga kebijakan ECB (deposit facility) — SDMX resmi ECB, tanpa API key.

    Penting karena metodologi forex menuntut perbandingan arah kebijakan KEDUA bank
    sentral. Dengan FRED saja hanya sisi AS yang terlihat, sehingga EURUSD cuma bisa
    dinilai setengah.
    """
    try:
        req = urllib.request.Request(ECB_DFR, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            baris = r.read().decode().strip().split("\n")
        kepala = baris[0].split(",")
        isi = baris[-1].split(",")
        rekam = dict(zip(kepala, isi))
        return {"nama": "Suku bunga kebijakan ECB (deposit facility)",
                "terbaru": float(rekam.get("OBS_VALUE")),
                "tanggal_data": rekam.get("TIME_PERIOD"),
                "sumber": "ECB SDMX (resmi, tanpa API key)"}
    except Exception as e:
        return {"gagal": f"{type(e).__name__}"}


def rezim_pasar():
    """Penanda rezim risiko lintas pasar — pilar Volatilitas, Breadth, dan Selera Risiko.

    Semua dari Yahoo, tanpa API key. Yang dikejar bukan level mentahnya melainkan
    RASIO dan DIVERGENSInya: harga bisa naik sementara kesehatannya memburuk, dan justru
    divergensi itu sinyal paling berharga.
    """
    keluar = {}
    for kode, simbol, nama, arti in (
        ("vix", "%5EVIX", "VIX (indeks volatilitas S&P 500)",
         "di bawah 15 = pasar tenang/risk-on; di atas 25 = tegang/risk-off; "
         "di atas 30 = panik. Naik tajam biasanya menekan aset berisiko dan menopang emas."),
        ("dxy", "DX-Y.NYB", "Indeks dolar DXY",
         "dolar menguat menekan emas dan komoditas; melemah menopang keduanya. "
         "Dolar adalah harga likuiditas global — menguat = pengetatan untuk semua aset berisiko."),
        ("vix3m", "%5EVIX3M", "VIX 3 bulan",
         "dipakai bersama VIX untuk term structure; lihat vix_term_structure."),
        ("move", "%5EMOVE", "MOVE (volatilitas obligasi)",
         "volatilitas obligasi sering MEMIMPIN VIX — naik lebih dulu sebelum stres "
         "merambat ke saham."),
        ("audjpy", "AUDJPY=X", "AUD/JPY",
         "proksi risk-on/risk-off paling murni. Turun tajam = carry trade di-unwind, "
         "biasanya bersamaan dengan VIX naik."),
    ):
        nilai, sebelum, err = _yahoo_terakhir(simbol)
        if err or nilai is None:
            keluar[kode] = {"gagal": err or "kosong"}
            continue
        item = {"nama": nama, "terbaru": round(nilai, 2), "arti": arti,
                "sumber": "Yahoo Finance (tanpa API key, API tidak resmi)"}
        if sebelum:
            item["perubahan_persen"] = round((nilai - sebelum) / sebelum * 100, 2)
        keluar[kode] = item

    # --- Rasio: inilah yang mengungkap kesehatan, bukan level tunggal ---
    def rasio(a, b):
        na, _, ea = _yahoo_terakhir(a)
        nb, _, eb = _yahoo_terakhir(b)
        return (round(na / nb, 4) if (na and nb) else None), (ea or eb)

    turunan = {}
    vix = (keluar.get("vix") or {}).get("terbaru")
    v3m = (keluar.get("vix3m") or {}).get("terbaru")
    if vix and v3m:
        ts = round(vix / v3m, 3)
        turunan["vix_term_structure"] = {
            "nilai": ts,
            "status": "BACKWARDATION — stres akut" if ts > 1.0 else "contango (normal)",
            "arti": ("VIX dibagi VIX3M. Di atas 1,0 berarti pasar membayar lebih mahal untuk "
                     "perlindungan JANGKA PENDEK daripada jangka panjang — tanda stres akut, "
                     "bukan sekadar volatilitas tinggi."),
        }
    rsp_spy, e1 = rasio("RSP", "SPY")
    if rsp_spy:
        turunan["breadth_equal_vs_cap"] = {
            "nilai": rsp_spy,
            "arti": ("S&P equal-weight dibagi cap-weight. Rasio TURUN berarti kenaikan indeks "
                     "makin ditopang segelintir raksasa — partisipasi menyempit dan rapuh. "
                     "Bandingkan arahnya dengan arah indeks: indeks naik sementara rasio ini "
                     "turun adalah pola DISTRIBUSI klasik."),
        }
    xly_xlp, e2 = rasio("XLY", "XLP")
    if xly_xlp:
        turunan["selera_risiko_siklikal_vs_defensif"] = {
            "nilai": xly_xlp,
            "arti": ("Consumer discretionary dibagi consumer staples. Turun = rotasi diam-diam "
                     "ke defensif, sering mendahului pelemahan indeks."),
        }
    if turunan:
        keluar["turunan"] = turunan
    return keluar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ringkas", action="store_true",
                    help="buang panduan statis (hemat token saat dipakai bot)")
    args = ap.parse_args()

    hasil = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": "FRED / Federal Reserve Bank of St. Louis (resmi, gratis, tanpa API key)",
        "peringatan": [
            "Ini angka AKTUAL yang sudah dirilis — BUKAN konsensus/forecast. Yang "
            "menggerakkan pasar adalah SELISIH actual vs forecast, jadi angka konsensus "
            "tetap harus diminta ke user.",
            "Data bulanan memang tertinggal SATU PERIODE: laporan bulan Juni terbit "
            "pertengahan Juli. Tanggal dari FRED menunjuk AWAL periode, jadi umur_hari "
            "terlihat besar padahal itu rilis terbaru. Sebut periodenya (mis. 'CPI Juni'), "
            "jangan menyebutnya data basi dan jangan disajikan seolah kondisi hari ini.",
            "Angka bisa DIREVISI di rilis berikutnya (lazim untuk NFP).",
            "Hanya data Amerika Serikat.",
        ],
    }

    # Ditarik PARALEL. Berurutan, sepuluh seri x timeout 25 detik bisa menembus 240 detik
    # dan seluruh langkah makro gagal — persis yang terjadi di run 31165241681, padahal
    # dari mesin lokal hanya 5 detik. Satu seri lambat kini tidak lagi menjatuhkan sisanya.
    data, gagal = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=PARALEL) as pool:
        tugas = {pool.submit(ambil, k): (k, n, sa, j) for k, n, sa, j in SERI}
        for fut in concurrent.futures.as_completed(tugas):
            kode, nama, satuan, jenis = tugas[fut]
            try:
                isi, err = fut.result()
            except Exception as e:
                isi, err = None, type(e).__name__
            if err:
                gagal[nama] = err
                continue
            data[kode] = olah(kode, nama, satuan, jenis, isi)
    data = {k: data[k] for k, *_ in SERI if k in data}   # urutan tetap seperti daftar SERI

    hasil["indikator"] = data

    # Ditarik paralel bersama FRED supaya tidak menambah waktu tunggu.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f_ecb, f_rez = pool.submit(ecb_suku_bunga), pool.submit(rezim_pasar)
        hasil["bank_sentral_lain"] = {"ecb": f_ecb.result()}
        hasil["rezim_pasar"] = f_rez.result()
    if gagal:
        hasil["gagal_diambil"] = gagal

    # Kurva imbal hasil: 10 tahun dikurangi 2 tahun. Negatif = inversi, secara historis
    # mendahului resesi dan biasanya mendukung emas.
    y2 = (data.get("DGS2") or {}).get("terbaru")
    y10 = (data.get("DGS10") or {}).get("terbaru")
    if y2 is not None and y10 is not None:
        selisih = round(y10 - y2, 2)
        hasil["kurva_imbal_hasil"] = {
            "spread_10y_2y": selisih,
            "status": ("INVERSI (10 tahun di bawah 2 tahun)" if selisih < 0
                       else "datar" if selisih < 0.3 else "normal"),
            "arti": ("Inversi historisnya mendahului resesi dan cenderung mendukung emas. "
                     "Ini konteks jangka panjang, BUKAN sinyal masuk."),
        }
        y3m = (data.get("DGS3MO") or {}).get("terbaru")
        if y3m is not None:
            # 10y-3m dipakai riset Fed sendiri dan historisnya lebih akurat daripada 10y-2y.
            s3 = round(y10 - y3m, 2)
            hasil["kurva_imbal_hasil"]["spread_10y_3m"] = s3
            hasil["kurva_imbal_hasil"]["status_10y_3m"] = (
                "INVERSI" if s3 < 0 else "datar" if s3 < 0.3 else "normal")
            hasil["kurva_imbal_hasil"]["catatan_10y_3m"] = (
                "Versi 10y-3m ini yang dipakai riset Fed sendiri dan historisnya lebih "
                "akurat memprediksi resesi daripada 10y-2y. Kalau keduanya berbeda vonis, "
                "sebutkan keduanya.")

    hasil["cara_pakai"] = [
        "Bandingkan angka AKTUAL di sini dengan KONSENSUS dari user untuk menilai arah reaksi.",
        "arah_emas_bila_naik sudah mengikuti gold_drivers.md — perhatikan DUA pengecualian "
        "(pengangguran & klaim: naik = emas NAIK).",
        "Selalu sebut tanggal_data dan umur_hari saat mengutip angka.",
        "Yield 2 tahun adalah validasi silang yang disarankan acuan gold: kalau yield naik "
        "bersamaan dengan dugaan hawkish, reaksi emas biasanya bertahan.",
    ]

    if args.ringkas:
        buang = ("cara_pakai", "arti", "acuan")
        hasil = {k: v for k, v in hasil.items() if k not in buang}
        for v in hasil.get("indikator", {}).values():
            v.pop("kode_fred", None)
        if "kurva_imbal_hasil" in hasil:
            hasil["kurva_imbal_hasil"].pop("arti", None)

    print(json.dumps(hasil, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

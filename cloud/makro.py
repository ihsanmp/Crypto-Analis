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
from datetime import datetime, timezone

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
]

# Arah dampak ke EMAS bila angkanya NAIK. Sesuai cloud/data/gold_drivers.md, termasuk
# DUA PENGECUALIAN yang arahnya terbalik (pengangguran & klaim: naik = ekonomi lemah =
# Fed dovish = emas NAIK).
ARAH_EMAS = {
    "CPIAUCSL": "turun", "CPILFESL": "turun", "PCEPILFE": "turun",
    "PAYEMS": "turun", "DFF": "turun", "DGS2": "turun", "DGS10": "turun",
    "DTWEXBGS": "turun",
    "UNRATE": "NAIK (pengecualian arah)", "ICSA": "NAIK (pengecualian arah)",
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
    """VIX & DXY — penanda rezim risiko yang diminta aturan 'kenali rezim dulu'."""
    keluar = {}
    for kode, simbol, nama, arti in (
        ("vix", "%5EVIX", "VIX (indeks volatilitas S&P 500)",
         "di bawah 15 = pasar tenang/risk-on; di atas 25 = tegang/risk-off; "
         "di atas 30 = panik. Naik tajam biasanya menekan aset berisiko dan menopang emas."),
        ("dxy", "DX-Y.NYB", "Indeks dolar DXY",
         "dolar menguat menekan emas dan komoditas; melemah menopang keduanya."),
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

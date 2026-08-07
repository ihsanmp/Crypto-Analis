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
import urllib.error
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-pasar/1.0)"}
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
TIMEOUT = 25

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

    data, gagal = {}, {}
    for kode, nama, satuan, jenis in SERI:
        isi, err = ambil(kode)
        if err:
            gagal[nama] = err
            continue
        data[kode] = olah(kode, nama, satuan, jenis, isi)

    hasil["indikator"] = data
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

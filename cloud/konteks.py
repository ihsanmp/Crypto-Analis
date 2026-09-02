"""Konteks PASAR & SEKTOR untuk analisa saham.

Sebagian besar gerak saham individual berasal dari pasar dan sektornya, bukan dari emiten
itu sendiri. Tanpa ini bot menganalisa emiten seolah berdiri sendiri — lalu memuji setup
teknikal yang sebenarnya cuma ikut arus indeks, atau menyalahkan emiten atas pelemahan yang
sebenarnya sektoral.

Semua dari Yahoo lewat market.py yang sudah ada — TANPA API key dan tanpa penarik baru.
Kode SIC emiten diambil dari SEC submissions (juga tanpa key) lalu dipetakan ke ETF sektor.

BATASAN YANG WAJIB DISAMPAIKAN:
  - Yahoo API tidak resmi; kegagalan dilaporkan apa adanya, tidak ditambal.
  - Pemetaan SIC -> ETF ditulis eksplisit dan TIDAK menebak. Kode yang tidak ada di peta
    dilaporkan sebagai tidak terpetakan, bukan dicocokkan ke sektor terdekat.
  - Kinerja relatif dihitung dari TANGGAL, bukan jumlah candle — hari bursa tidak sama
    dengan hari kalender, dan libur membuat jumlah candle berbeda antar simbol.

Pemakaian:
    python cloud/konteks.py --pasar
    python cloud/konteks.py --sektor
    python cloud/konteks.py --untuk NVDA
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from market import tarik  # noqa: E402

# SEC mewajibkan User-Agent berisi identitas + kontak (kebijakan fair access).
# Tanpa format yang benar, seluruh permintaan dibalas HTTP 403 — bukan error yang
# menjelaskan dirinya, jadi mudah disalahartikan sebagai emiten tidak ditemukan.
# Dipakai identitas yang sama dengan stockfund.py yang memang sudah berhasil.
# Kontak SEC bisa dipindah ke secret SEC_CONTACT (repo ini publik); tanpa
# variabel itu, nilainya sama seperti sebelumnya.
UA = {"User-Agent": "Crypto-Analis Research bot "
                    + os.environ.get("SEC_CONTACT", "ihsanmaulanand@gmail.com")}
SEC_SUB = "https://data.sec.gov/submissions/CIK{}.json"

INDEKS = {
    "^GSPC": "S&P 500",
    "^NDX": "Nasdaq 100",
    "^RUT": "Russell 2000 (emiten kecil)",
    "^VIX": "VIX (volatilitas)",
}
ACUAN = "^GSPC"

SEKTOR = {
    "XLK": "Teknologi", "XLF": "Keuangan", "XLE": "Energi", "XLV": "Kesehatan",
    "XLY": "Konsumsi siklikal", "XLP": "Konsumsi pokok", "XLI": "Industri",
    "XLU": "Utilitas", "XLRE": "Properti", "XLB": "Bahan baku", "XLC": "Komunikasi",
}

# Pemetaan kode SIC -> ETF sektor, ditulis EKSPLISIT. Rentang diambil dari pembagian
# resmi SEC. Yang tidak tercakup DILAPORKAN tidak terpetakan — menebak sektor lebih
# berbahaya daripada mengaku tidak tahu, karena pembanding yang salah menyesatkan.
SIC_KE_SEKTOR = [
    ((100, 999), "XLP", "pertanian"),
    ((1000, 1099), "XLB", "pertambangan logam"),
    ((1200, 1399), "XLE", "batubara & migas"),
    ((1400, 1499), "XLB", "tambang nonlogam"),
    ((1500, 1799), "XLI", "konstruksi"),
    ((2000, 2199), "XLP", "makanan & tembakau"),
    ((2200, 2399), "XLY", "tekstil & pakaian"),
    ((2400, 2599), "XLI", "kayu & furnitur"),
    ((2600, 2699), "XLB", "kertas"),
    ((2700, 2799), "XLC", "penerbitan & percetakan"),
    ((2800, 2829), "XLB", "kimia"),
    ((2830, 2836), "XLV", "farmasi & bioteknologi"),
    ((2840, 2899), "XLP", "sabun & kosmetik"),
    ((2900, 2999), "XLE", "pengilangan minyak"),
    ((3000, 3299), "XLB", "karet, kaca, semen"),
    ((3300, 3499), "XLB", "logam dasar"),
    ((3500, 3569), "XLI", "mesin industri"),
    ((3570, 3579), "XLK", "perangkat keras komputer"),
    ((3600, 3651), "XLK", "elektronik"),
    ((3652, 3652), "XLC", "rekaman & media"),
    ((3660, 3669), "XLK", "peralatan komunikasi"),
    ((3670, 3679), "XLK", "semikonduktor"),
    ((3680, 3699), "XLK", "komputer & elektronik"),
    ((3700, 3799), "XLY", "otomotif & transportasi"),
    ((3800, 3851), "XLV", "alat kesehatan & instrumen"),
    ((3900, 3999), "XLY", "manufaktur lain-lain"),
    ((4000, 4299), "XLI", "transportasi & pergudangan"),
    ((4400, 4700), "XLI", "pelayaran & transportasi udara"),
    ((4800, 4813), "XLC", "telekomunikasi"),
    ((4820, 4899), "XLC", "penyiaran & media"),
    ((4900, 4991), "XLU", "utilitas"),
    ((5000, 5199), "XLI", "perdagangan grosir"),
    ((5200, 5599), "XLY", "ritel"),
    ((5600, 5799), "XLY", "ritel pakaian & furnitur"),
    ((5800, 5899), "XLY", "restoran"),
    ((5900, 5999), "XLY", "ritel lain-lain"),
    ((6000, 6199), "XLF", "perbankan & kredit"),
    ((6200, 6299), "XLF", "sekuritas & bursa"),
    ((6300, 6499), "XLF", "asuransi"),
    ((6500, 6599), "XLRE", "properti"),
    ((6700, 6799), "XLF", "holding & investasi"),
    ((7000, 7099), "XLY", "hotel & penginapan"),
    ((7370, 7379), "XLK", "layanan perangkat lunak & data"),
    ((7800, 7999), "XLC", "hiburan & rekreasi"),
    ((8000, 8099), "XLV", "layanan kesehatan"),
    ((8200, 8299), "XLY", "pendidikan"),
    ((8700, 8799), "XLI", "jasa profesional"),
]


def _tutup_pada(candles, hari_lalu):
    """Harga penutupan terdekat SEBELUM `hari_lalu` dari candle terakhir.

    Dicari lewat TANGGAL, bukan mundur sekian candle: jumlah hari bursa berbeda antar
    simbol karena libur, sehingga mundur 21 candle bisa berarti rentang berbeda-beda dan
    perbandingan antar sektor jadi tidak setara.
    """
    if not candles:
        return None, None
    akhir_ts = candles[-1][0] / 1000
    batas = akhir_ts - hari_lalu * 86400
    kandidat = [c for c in candles if c[0] / 1000 <= batas]
    if not kandidat:
        return None, None
    c = kandidat[-1]
    return c[4], datetime.fromtimestamp(c[0] / 1000, timezone.utc).strftime("%Y-%m-%d")


def kinerja(simbol, hari=(30, 90)):
    """Return (dict kinerja, error). Perubahan persen untuk tiap horizon."""
    candles, _, err = tarik(simbol, "1y", "1d")
    if err or not candles:
        return None, err or "kosong"
    akhir = candles[-1][4]
    hasil = {"terakhir": round(akhir, 2),
             "tanggal": datetime.fromtimestamp(candles[-1][0] / 1000,
                                               timezone.utc).strftime("%Y-%m-%d")}
    for h in hari:
        awal, tgl = _tutup_pada(candles, h)
        if awal:
            hasil[f"perubahan_{h}h_persen"] = round((akhir - awal) / awal * 100, 2)
            hasil[f"dibanding_tanggal_{h}h"] = tgl
    return hasil, None


def konteks_pasar():
    keluar, gagal = {}, {}
    for sim, nama in INDEKS.items():
        k, err = kinerja(sim)
        if err:
            gagal[nama] = err
            continue
        k["nama"] = nama
        keluar[sim] = k
    hasil = {"indeks": keluar}
    if gagal:
        hasil["gagal_diambil"] = gagal
    vix = (keluar.get("^VIX") or {}).get("terakhir")
    if vix is not None:
        hasil["arti_vix"] = (
            f"VIX {vix}: di bawah 15 pasar tenang · 15-25 normal · di atas 25 tegang · "
            "di atas 30 panik. Naik tajam biasanya menekan saham berisiko lebih dulu.")
    return hasil


def peringkat_sektor():
    """Kinerja RELATIF tiap sektor terhadap S&P 500."""
    acuan, err = kinerja(ACUAN)
    if err:
        return {"tidak_tersedia": f"acuan {ACUAN} gagal diambil: {err}"}
    baris, gagal = [], {}
    for sim, nama in SEKTOR.items():
        k, e = kinerja(sim)
        if e:
            gagal[nama] = e
            continue
        item = {"etf": sim, "sektor": nama}
        for h in (30, 90):
            a = acuan.get(f"perubahan_{h}h_persen")
            s = k.get(f"perubahan_{h}h_persen")
            if a is not None and s is not None:
                item[f"relatif_{h}h_persen"] = round(s - a, 2)
                item[f"absolut_{h}h_persen"] = s
        baris.append(item)
    baris.sort(key=lambda x: x.get("relatif_30h_persen", -999), reverse=True)
    hasil = {
        "acuan": {"simbol": ACUAN, "nama": INDEKS[ACUAN],
                  "perubahan_30h_persen": acuan.get("perubahan_30h_persen"),
                  "perubahan_90h_persen": acuan.get("perubahan_90h_persen")},
        "peringkat": baris,
        "arti": ("relatif = kinerja sektor DIKURANGI kinerja S&P 500. Positif berarti "
                 "sektor itu mengungguli pasar. Rotasi ke sektor defensif (XLP, XLU, XLV) "
                 "sering mendahului pelemahan indeks."),
    }
    if gagal:
        hasil["gagal_diambil"] = gagal
    return hasil


def _cik_dan_sic(ticker):
    """Ambil CIK & kode SIC emiten dari SEC. Return (cik, sic, nama, error)."""
    from sec_tickers import peta_ticker
    peta, _, err_peta = peta_ticker()
    if err_peta and not peta:
        return None, None, None, f"daftar emiten gagal: {err_peta}"
    rekam = peta.get(ticker.upper())
    cik = rekam["cik"] if rekam else None
    if not cik:
        return None, None, None, f"{ticker} tidak ditemukan di daftar emiten SEC (non-AS?)"
    try:
        req = urllib.request.Request(SEC_SUB.format(cik), headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            sub = json.loads(r.read().decode())
    except Exception as e:
        return cik, None, None, f"submissions gagal: {type(e).__name__}"
    sic = sub.get("sic")
    try:
        sic = int(sic)
    except (TypeError, ValueError):
        sic = None
    return cik, sic, sub.get("name"), None


def sektor_emiten(ticker):
    cik, sic, nama, err = _cik_dan_sic(ticker)
    hasil = {"ticker": ticker.upper(), "cik": cik, "sic": sic, "nama_emiten": nama}
    if err:
        hasil["catatan"] = err
    if sic is None:
        hasil["etf_sektor"] = None
        hasil["tidak_terpetakan"] = ("kode SIC tidak tersedia — sektor TIDAK ditebak. "
                                     "Sampaikan bahwa pembanding sektornya tidak ada.")
        return hasil
    for (a, b), etf, label in SIC_KE_SEKTOR:
        if a <= sic <= b:
            hasil["etf_sektor"] = etf
            hasil["sektor"] = SEKTOR.get(etf)
            hasil["sic_kelompok"] = label
            return hasil
    hasil["etf_sektor"] = None
    hasil["tidak_terpetakan"] = (f"kode SIC {sic} tidak ada di peta — sektor TIDAK ditebak. "
                                 "Menebak sektor menghasilkan pembanding yang menyesatkan.")
    return hasil


def konteks_untuk(ticker):
    hasil = {"pasar": konteks_pasar(), "emiten": sektor_emiten(ticker)}
    etf = hasil["emiten"].get("etf_sektor")
    if etf:
        acuan, e1 = kinerja(ACUAN)
        sek, e2 = kinerja(etf)
        if not e1 and not e2:
            banding = {"etf": etf, "sektor": SEKTOR.get(etf)}
            for h in (30, 90):
                a = acuan.get(f"perubahan_{h}h_persen")
                s = sek.get(f"perubahan_{h}h_persen")
                if a is not None and s is not None:
                    banding[f"sektor_{h}h_persen"] = s
                    banding[f"pasar_{h}h_persen"] = a
                    banding[f"relatif_{h}h_persen"] = round(s - a, 2)
            hasil["sektor_vs_pasar"] = banding
        else:
            hasil["sektor_vs_pasar"] = {"gagal": e1 or e2}
    return hasil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pasar", action="store_true", help="indeks + VIX")
    ap.add_argument("--sektor", action="store_true", help="peringkat sektor vs S&P 500")
    ap.add_argument("--untuk", help="konteks pasar + sektor untuk satu emiten, mis. NVDA")
    args = ap.parse_args()

    keluar = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
              "sumber": "Yahoo Finance lewat market.py (tanpa API key, API tidak resmi) "
                        "+ SEC submissions untuk kode SIC"}
    if args.untuk:
        keluar.update(konteks_untuk(args.untuk))
    elif args.sektor:
        keluar["sektor"] = peringkat_sektor()
    else:
        keluar["pasar"] = konteks_pasar()
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

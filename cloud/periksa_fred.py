"""Diagnostik FRED dari runner GitHub — kenapa jam_likuiditas.py kena TimeoutError.

Run 38746731651 & 38757921517: ketujuh seri FRED TimeoutError dari runner, padahal dari
jaringan pengembang lancar. Skrip ini mengukur tiap kemungkinan penyebab secara terpisah:
ukuran riwayat (sejak 2012 vs 4 tahun), paralel vs berurutan, dan host alternatif
(api.stlouisfed.org bila secret FRED_API_KEY ada). Kunci TIDAK pernah dicetak.

    python cloud/periksa_fred.py
"""
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

KODE = ("WALCL", "WDTGAL", "RRPONTSYD", "DGS2", "DTWEXBGS", "NFCI", "SAHMREALTIME")
GRAPH = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}&cosd={}"
API = ("https://api.stlouisfed.org/fred/series/observations?series_id={}&api_key={}"
       "&file_type=json&observation_start={}")
UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-pasar/1.0)"}


def satu(url, batas=60):
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=batas) as r:
            n = len(r.read())
        return f"OK {n // 1024} KB {time.time() - t0:.1f}s"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} {time.time() - t0:.1f}s (host TERJANGKAU)"
    except Exception as e:
        return f"{type(e).__name__} {time.time() - t0:.1f}s"


ALTERNATIF = (
    # api.stlouisfed.org TANPA kunci: balasan 400 cepat = host terjangkau, timeout = diblokir.
    ("FRED API (tanpa kunci)", "https://api.stlouisfed.org/fred/series/observations?series_id=DGS2&file_type=json"),
    ("ALFRED", "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=DGS2"),
    ("Fed H.4.1 halaman", "https://www.federalreserve.gov/releases/h41/current/h41.htm"),
    ("Fed DDP", "https://www.federalreserve.gov/datadownload/Choose.aspx?rel=H41"),
    ("Chicago Fed NFCI", "https://www.chicagofed.org/-/media/publications/nfci/nfci-data-series-csv.csv"),
    ("Treasury yield", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve&field_tdr_date_value=2026&page&_format=csv"),
    ("NY Fed RRP", "https://markets.newyorkfed.org/api/rp/reverserepo/propositions/search.json?startDate=2026-09-01&endDate=2026-10-15"),
    ("Fiscal Data TGA", "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance?sort=-record_date&page[size]=3"),
    ("BLS v1", "https://api.bls.gov/publicAPI/v1/timeseries/data/LNS14000000"),
)


def main():
    if "--kunci" in sys.argv:
        kunci = os.environ.get("FRED_API_KEY", "").strip()
        print("== api.stlouisfed.org dengan FRED_API_KEY ==", flush=True)
        if not kunci:
            print("  FRED_API_KEY kosong — secret belum terbaca oleh workflow")
            return
        for k in KODE:
            print(f"  {k:<13} {satu(API.format(k, kunci, '2012-01-01'))}", flush=True)
        return
    print("== host alternatif ==", flush=True)
    for nama, url in ALTERNATIF:
        print(f"  {nama:<24} {satu(url, 20)}", flush=True)
    if "--alternatif" in sys.argv:
        return
    for nama, mulai, paralel in (("2012, berurutan", "2012-01-01", 1),
                                 ("4 tahun, berurutan", "2022-10-01", 1),
                                 ("4 tahun, paralel 7", "2022-10-01", 7)):
        print(f"\n== fredgraph.csv {nama} ==", flush=True)
        urls = [GRAPH.format(k, mulai) for k in KODE]
        with ThreadPoolExecutor(paralel) as ex:
            for k, hasil in zip(KODE, ex.map(satu, urls)):
                print(f"  {k:<13} {hasil}", flush=True)
    kunci = os.environ.get("FRED_API_KEY", "").strip()
    print("\n== api.stlouisfed.org ==", flush=True)
    if not kunci:
        print("  FRED_API_KEY kosong — dilewati")
        return
    for k in KODE:
        print(f"  {k:<13} {satu(API.format(k, kunci, '2012-01-01'))}", flush=True)


if __name__ == "__main__":
    sys.exit(main())

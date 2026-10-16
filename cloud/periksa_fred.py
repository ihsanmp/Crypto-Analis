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
    except Exception as e:
        return f"{type(e).__name__} {time.time() - t0:.1f}s"


def main():
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

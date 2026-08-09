"""Cache peta ticker -> CIK dari SEC, dipakai bersama.

Berkas company_tickers.json berukuran ~777 KB dan diunduh ULANG setiap kali sebuah emiten
dianalisa — dua kali malah, karena stockfund.py dan konteks.py memintanya sendiri-sendiri.
Di runner GitHub, SEC bisa memakan puluhan detik untuk berkas sebesar itu (terukur 42,9
detik), dan itu langsung memotong jatah waktu tahap analisa.

Isinya nyaris tidak berubah — emiten baru terdaftar hitungan hari, bukan menit — jadi
di-cache 7 hari. Cache ikut di-commit supaya berguna di runner yang selalu bersih.
"""

import json
import os
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "data", "sec_tickers_cache.json")
CACHE_UMUR = 7 * 24 * 3600
URL = "https://www.sec.gov/files/company_tickers.json"
# SEC mewajibkan User-Agent berisi identitas + kontak (kebijakan fair access).
UA = {"User-Agent": "Crypto-Analis Research bot ihsanmaulanand@gmail.com"}


def peta_ticker(paksa=False):
    """Return (dict TICKER -> {"cik", "nama"}, dari_cache, error).

    Nama emiten ikut disimpan: pemanggil lama mengambilnya dari respons yang sama, jadi
    kalau cache hanya menyimpan CIK, nama emiten hilang diam-diam dari keluaran.
    """
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            simpan = json.load(f)
        if not paksa and time.time() - simpan.get("waktu", 0) < CACHE_UMUR:
            return simpan.get("peta") or {}, True, None
    except Exception:
        simpan = {}

    try:
        with urllib.request.urlopen(urllib.request.Request(URL, headers=UA),
                                    timeout=60) as r:
            mentah = json.loads(r.read().decode())
    except Exception as e:
        kode = getattr(e, "code", "")
        pesan = f"{type(e).__name__} {kode}".strip()
        if simpan.get("peta"):
            return simpan["peta"], True, f"{pesan} (pakai cache lama)"
        return {}, False, pesan

    peta = {}
    for v in (mentah or {}).values():
        t = (v.get("ticker") or "").upper()
        if t:
            peta[t] = {"cik": str(v.get("cik_str", "")).zfill(10),
                       "nama": v.get("title")}
    if not peta:
        if simpan.get("peta"):
            return simpan["peta"], True, "peta kosong (pakai cache lama)"
        return {}, False, "peta kosong"

    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"peta": peta, "waktu": time.time()}, f)
    except Exception as e:
        print(f"[sec_tickers] gagal menyimpan cache: {e}")
    return peta, False, None

"""Cache peta ticker -> CIK dari SEC, dipakai bersama.

Berkas company_tickers.json berukuran ~777 KB dan diunduh ULANG setiap kali sebuah emiten
dianalisa — dua kali malah, karena stockfund.py dan konteks.py memintanya sendiri-sendiri.
Di runner GitHub, SEC bisa memakan puluhan detik untuk berkas sebesar itu (terukur 42,9
detik), dan itu langsung memotong jatah waktu tahap analisa.

Isinya nyaris tidak berubah — emiten baru terdaftar hitungan hari, bukan menit — jadi
di-cache 7 hari. Cache ikut di-commit supaya berguna di runner yang selalu bersih.
"""

import gzip
import json
import os
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "data", "sec_tickers_cache.json")
CACHE_UMUR = 7 * 24 * 3600
URL = "https://www.sec.gov/files/company_tickers.json"
# SEC mewajibkan User-Agent berisi identitas + kontak (kebijakan fair access), jadi
# alamat email di sini FUNGSIONAL — tanpa kontak yang jelas, permintaan bisa diblokir.
# Tapi repo ini PUBLIK, dan alamat pribadi yang ditulis di sini terbuka untuk pemanen
# alamat. Bisa dipindah ke secret SEC_CONTACT tanpa mengubah apa pun hari ini: kalau
# variabelnya diset, nilainya yang dipakai; kalau tidak, jatuh ke nilai lama.
UA = {"User-Agent": "Crypto-Analis Research bot "
                    + os.environ.get("SEC_CONTACT", "ihsanmaulanand@gmail.com")}


def peta_ticker(paksa=False):
    """Return (dict TICKER -> {"cik", "nama"}, dari_cache, error).

    Nama emiten ikut disimpan: pemanggil lama mengambilnya dari respons yang sama, jadi
    kalau cache hanya menyimpan CIK, nama emiten hilang diam-diam dari keluaran.
    """
    # Dibaca dari versi TERKOMPRESI. Petanya ~684 KB mentah dan ikut ditarik setiap
    # checkout — termasuk pada run crypto/forex yang tidak membutuhkannya sama sekali.
    simpan = {}
    for jalur, buka in ((CACHE_PATH + ".gz", lambda p: gzip.open(p, "rt", encoding="utf-8")),
                        (CACHE_PATH, lambda p: open(p, encoding="utf-8"))):
        try:
            with buka(jalur) as f:
                simpan = json.load(f)
            break
        except OSError:
            continue
        except Exception:
            simpan = {}
            break
    if not paksa and simpan.get("peta") and time.time() - simpan.get("waktu", 0) < CACHE_UMUR:
        return simpan["peta"], True, None

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
        with gzip.open(CACHE_PATH + ".gz", "wt", encoding="utf-8", compresslevel=9) as f:
            json.dump({"peta": peta, "waktu": time.time()}, f, separators=(",", ":"))
    except Exception as e:
        print(f"[sec_tickers] gagal menyimpan cache: {e}")
    return peta, False, None

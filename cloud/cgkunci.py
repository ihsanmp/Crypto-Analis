"""Kunci Demo CoinGecko — opsional, dikirim lewat HEADER, tidak pernah lewat URL.

KENAPA ADA. API publik CoinGecko tanpa kunci dibatasi per alamat IP, dan IP GitHub Actions
dipakai bersama banyak pengguna lain. Bukti produksi 17 Sep 2026, run 35178956460:
musim.py mendapat data segar pukul 03:39 UTC, lalu naratif.py yang jalan puluhan detik
kemudian ditolak (429) tiga kali berturut-turut walau sudah menunggu 28 detik. Kunci Demo
(paket gratis CoinGecko) memberi kuota milik sendiri, tidak berbagi dengan IP runner.

KENAPA HEADER, BUKAN PARAMETER URL. Repo ini PUBLIK. URL ikut tercetak di pesan galat,
dan kategori.py memakai URL sebagai kunci cache di kategori_cache.json — berkas yang
ikut ter-commit. Kunci yang ditempel di URL akan bocor ke sana tanpa ada yang sadar.
Header tidak pernah menyentuh keduanya.

TANPA KUNCI, SEMUANYA TETAP JALAN seperti sebelumnya (API publik). Modul ini tidak
pernah mencetak kuncinya — hanya ada/tidaknya.

Pemakaian:
    python cloud/cgkunci.py              # ada/tidaknya kunci, dan uji /ping
"""

import json
import os
import subprocess
import sys

NAMA_ENV = "COINGECKO_DEMO_KEY"
NAMA_HEADER = "x-cg-demo-api-key"
HOST = "api.coingecko.com"


def kunci():
    return (os.environ.get(NAMA_ENV) or "").strip()


def header_untuk(url):
    """dict header tambahan untuk `url`. Kosong kalau bukan CoinGecko atau tanpa kunci —
    jadi aman dipanggil untuk URL apa pun, termasuk sumber lain."""
    k = kunci()
    if k and HOST in (url or ""):
        return {NAMA_HEADER: k}
    return {}


def argumen_curl(url):
    """Argumen `-H` untuk curl. Daftar kosong kalau header_untuk kosong."""
    keluar = []
    for nama, nilai in header_untuk(url).items():
        keluar += ["-H", f"{nama}: {nilai}"]
    return keluar


def main():
    ada = bool(kunci())
    print(f"kunci {NAMA_ENV}: {'ADA' if ada else 'TIDAK ADA'} (isinya tidak dicetak)")
    url = f"https://{HOST}/api/v3/ping"
    try:
        p = subprocess.run(["curl", "-s", "--max-time", "20", *argumen_curl(url), url],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        d = json.loads(p.stdout or "{}")
    except Exception as e:
        print(f"/ping gagal dihubungi: {type(e).__name__}")
        return 1
    if "gecko_says" in d:
        print(f"/ping OK{' — kunci diterima' if ada else ' (API publik)'}")
        return 0
    print(f"/ping DITOLAK: {json.dumps(d.get('status') or d, ensure_ascii=False)[:200]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

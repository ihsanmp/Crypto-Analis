"""Satu pintu ke Yahoo chart API, dengan cadangan host & coba ulang untuk galat sementara.

Saham, forex, komoditas, indeks, dan riwayat panjang BTC/ETH untuk model kuant semuanya
bergantung pada Yahoo — satu-satunya sumber gratis tanpa kunci yang dipakai untuk itu.
Cadangan di sini terbatas pada yang SAH: host kedua Yahoo (query2) dan jeda singkat saat
dibatasi (429/5xx/timeout). Stooq dicoba 18 Okt 2026 dan menolak dengan verifikasi
anti-bot (proof-of-work) — tidak dipakai, karena menembusnya = melewati proteksi bot.

404 tidak diulang: simbolnya memang tidak ada, mengulang hanya membuang waktu.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

HOST = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")
UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-pasar/1.0)"}
_SEMENTARA = {429, 500, 502, 503, 504}


def chart(simbol, query, timeout=20, jeda=1.5):
    """GET /v8/finance/chart/<simbol>?<query> -> dict JSON. Mencoba query1, lalu query2,
    lalu query1 sekali lagi sesudah jeda. Galat terakhir dilempar ulang (HTTPError dengan
    kode aslinya), supaya pemanggil tetap bisa membedakan 404 dari gangguan."""
    # safe="%": makro.py menulis simbol yang SUDAH ter-encode ("%5EVIX"); meng-encode ulang
    # jadi "%255EVIX" -> 404 (diagnostik runner 18 Okt 2026: VIX, VIX3M, MOVE hilang).
    jalur = f"/v8/finance/chart/{urllib.parse.quote(simbol, safe='%')}?{query}"
    galat = None
    for i, host in enumerate(HOST + HOST[:1]):
        if i == len(HOST):
            time.sleep(jeda)
        try:
            req = urllib.request.Request(host + jalur, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code not in _SEMENTARA:
                raise
            galat = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            galat = e
    raise galat

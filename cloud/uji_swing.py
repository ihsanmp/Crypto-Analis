"""Uji balik MINOR SWING STRATEGY (Astronacci) pada BTC H1 — aturan yang sama dengan swing.py.

Data: candle 1 jam Bitstamp BTC/USD, publik dan gratis tanpa kunci, ditarik mundur 1.000
candle per permintaan. Tidak bisa dari jaringan lokal (bursa diblokir), jadi dijalankan
di runner GitHub lewat workflow "Uji minor swing".

Yang dilaporkan: jumlah transaksi, persentase menang, dan EKSPEKTANSI dalam R setelah
biaya — satuan yang menentukan untung-rugi. Dengan RR 1:1 dan biaya ~0,1R per transaksi,
win rate 50% berarti RUGI; ambang impasnya sekitar 55%.

Pembanding: uji binomial terhadap 50% (jalan acak dengan penghalang simetris 1:1 memberi
~50% menang), dan pemecahan per tahun & per arah — supaya satu periode tren kuat tidak
menyamar jadi keunggulan strategi.

Pemakaian (runner):
    python cloud/uji_swing.py --tahun 3
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swing  # noqa: E402

URL = "https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=3600&limit=1000&end={end}"


def tarik(tahun):
    akhir = int(time.time())
    batas = akhir - int(tahun * 365.25 * 86400)
    semua = {}
    while akhir > batas:
        req = urllib.request.Request(URL.format(end=akhir),
                                     headers={"User-Agent": "Mozilla/5.0 riset-koin"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())["data"]["ohlc"]
        if not data:
            break
        for b in data:
            ts = int(b["timestamp"])
            semua[ts] = [ts * 1000, float(b["open"]), float(b["high"]), float(b["low"]),
                         float(b["close"]), float(b["volume"])]
        akhir = min(int(b["timestamp"]) for b in data) - 3600
        time.sleep(0.3)
    return [semua[k] for k in sorted(semua) if k >= batas]


def _p_binom(k, n):
    if n == 0:
        return None
    z = (k - n / 2) / math.sqrt(n / 4)
    return round(math.erfc(abs(z) / math.sqrt(2)), 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tahun", type=float, default=3)
    a = ap.parse_args()
    candle = tarik(a.tahun)
    awal = datetime.fromtimestamp(candle[0][0] / 1000, timezone.utc).date()
    akhir = datetime.fromtimestamp(candle[-1][0] / 1000, timezone.utc).date()
    out = {"data": {"candle": len(candle), "awal": str(awal), "akhir": str(akhir),
                    "sumber": "Bitstamp BTC/USD 1h"}}
    for label, biaya in (("biaya_0_1", 0.001), ("biaya_0_2", 0.002), ("tanpa_biaya", 0.0)):
        tr = swing.backtest(candle, biaya)
        r = swing.ringkas_uji(tr)
        if tr:
            menang = sum(1 for x in tr if x["hasil_R"] > 0)
            r["p_vs_50"] = _p_binom(menang, len(tr))
            per_tahun, per_arah = {}, {}
            for x in tr:
                th = datetime.fromtimestamp(x["ts_isi"] / 1000, timezone.utc).year
                per_tahun.setdefault(th, []).append(x)
                per_arah.setdefault(x["arah"], []).append(x)
            r["per_tahun"] = {th: swing.ringkas_uji(v) for th, v in sorted(per_tahun.items())}
            r["per_arah"] = {k: swing.ringkas_uji(v) for k, v in per_arah.items()}
            # Biaya per transaksi dalam R: menang = RR − hasil, kalah = −1 − hasil.
            # Impas: p·(1−f) − (1−p)·(1+f) = 0  →  p = (1+f)/2.
            f = sum((swing.RR - x["hasil_R"]) if x["hasil_R"] > 0 else (-1 - x["hasil_R"])
                    for x in tr) / len(tr)
            r["biaya_rata_R"] = round(f, 3)
            r["win_rate_impas_persen"] = round(100 * (1 + f) / 2, 1)
        out[label] = r
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

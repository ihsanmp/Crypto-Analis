"""
uji_gaya.py
===========
Menguji dua kaki sinyal gaya "#Kalimasada" (lihat cloud/data/gaya_kalimasada.md) terhadap
riwayat BTC 14 tahun dengan OHLC SUNGGUHAN — bukan candle close-only.

KENAPA BERKAS INI ADA. backtest.py memakai CoinGecko, dan candle harian crypto di sana
tidak punya high/low sama sekali (open=high=low=close di 366/366). Sinyal yang menuntut
sentuhan level karena itu tidak pernah bisa diukur apa adanya. Candle 4 jam punya high/low
asli tapi hanya menyimpan ~30 hari — dan 30 hari terakhir kebetulan pasar naik seluruhnya,
jadi tidak bisa menjawab "bagaimana kalau pasar turun?".

Bitstamp BTC harian (5.356 candle, 2012-2026) menjawab keduanya: OHLC asli DAN memuat tiga
pasar beruang. Berkasnya sudah ada di repo untuk uji fase bulan.

YANG DIUKUR. Untuk tiap sinyal: peluang menang pada horizon N candle, DIBANDINGKAN dengan
lantai acak di rezim yang sama. Lantai acak = peluang menang kalau masuk di hari ACAK dalam
rezim itu. Tanpa pembanding ini, "menang 59%" tidak berarti apa-apa: di pasar naik, masuk
acak pun menang 58%.

Rezim ditentukan harga vs SMA200 — definisi bull/bear paling lazim dan tidak melihat
ke depan.

Jalankan: python cloud/uji_gaya.py            (opsi: --horizon 20 --era)
"""
import argparse
import csv
import gzip
import importlib.util
import math
import os
import sys

AKAR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(AKAR, "data", "btc_daily_bitstamp.csv.gz")


def muat():
    with gzip.open(DATA, "rt", encoding="utf-8") as f:
        baris = list(csv.DictReader(f))
    c = [[i * 86400000, float(b["open"]), float(b["high"]), float(b["low"]),
          float(b["close"]), float(b["volume"] or 0)] for i, b in enumerate(baris)]
    return c, [b["dt"][:10] for b in baris]


def pemicu(candles):
    sys.path.insert(0, AKAR)
    spec = importlib.util.spec_from_file_location("bt", os.path.join(AKAR, "backtest.py"))
    bt = importlib.util.module_from_spec(spec)
    sys.modules["bt"] = bt
    spec.loader.exec_module(bt)
    return bt.cari_pemicu(candles)


def sma200(close):
    keluar, s = [None] * len(close), 0.0
    for i, v in enumerate(close):
        s += v
        if i >= 200:
            s -= close[i - 200]
        if i >= 199:
            keluar[i] = s / 200
    return keluar


def _se(p, n):
    """Galat baku proporsi. Tanpa ini, selisih 7 poin pada n=22 terbaca seperti temuan."""
    return 100 * math.sqrt((p / 100) * (1 - p / 100) / n) if n else float("inf")


def ukur(idx, close, rez, n_depan, lo, hi, r):
    """(n, menang%, lantai%, selisih, SE) untuk satu sinyal di satu potongan & rezim."""
    def ret(i):
        return (close[i + n_depan] / close[i] - 1) * 100 if i + n_depan < len(close) else None

    v = [ret(i) for i in idx if lo <= i < hi and rez[i] == r and ret(i) is not None]
    lantai = [ret(i) for i in range(lo, min(hi, len(close)))
              if rez[i] == r and ret(i) is not None]
    if len(v) < 5 or not lantai:
        return None
    w = 100 * sum(1 for x in v if x > 0) / len(v)
    fl = 100 * sum(1 for x in lantai if x > 0) / len(lantai)
    return len(v), w, fl, w - fl, _se(w, len(v))


def main():
    ap = argparse.ArgumentParser(description="Uji sinyal gaya Kalimasada pada BTC OHLC asli")
    ap.add_argument("--horizon", type=int, default=20, help="candle ke depan yang diukur")
    ap.add_argument("--era", action="store_true", help="pecah per era, uji ketahanan tanda")
    a = ap.parse_args()

    candles, tgl = muat()
    close = [x[4] for x in candles]
    sma = sma200(close)
    rez = [None if s is None else ("NAIK" if c > s else "TURUN") for c, s in zip(close, sma)]
    palsu = sum(1 for x in candles if abs(x[3] - x[4]) < 1e-12)
    pem = pemicu(candles)

    print(f"BTC harian Bitstamp, {len(candles)} candle, {tgl[0]} .. {tgl[-1]}")
    print(f"high/low asli: {len(candles) - palsu}/{len(candles)} candle · "
          f"horizon {a.horizon} candle\n")

    era = [("SELURUH", 0, len(close))]
    if a.era:
        era += [("2012-2016", 0, 1826), ("2016-2021", 1826, 3652),
                ("2021-2026", 3652, len(close))]

    for nama in ("golden_cross_13x21", "pullback_ke_ema21_saat_uptrend"):
        if nama not in pem:
            print(f"=== {nama}: TIDAK ADA (data tanpa high/low?) ===\n")
            continue
        print(f"=== {nama} ===")
        print(f"{'potongan':<12} {'rezim':<6} {'n':>4} {'menang%':>8} {'lantai%':>8} "
              f"{'selisih':>8} {'1SE':>6}  vonis")
        for lbl, lo, hi in era:
            for r in ("NAIK", "TURUN"):
                h = ukur(pem[nama], close, rez, a.horizon, lo, hi, r)
                if not h:
                    continue
                n, w, fl, d, e = h
                vonis = ""
                if lbl == "SELURUH":
                    vonis = "  DI LUAR 2SE" if abs(d) > 2 * e else "  dalam derau"
                print(f"{lbl:<12} {r:<6} {n:>4} {w:>8.1f} {fl:>8.1f} {d:>+8.1f} "
                      f"{e:>6.1f}{vonis}")
        print()

    print("CARA MEMBACANYA. Selisih di dalam 2x galat baku TIDAK bisa dibedakan dari derau —"
          "\nsebut tidak ada edge, bukan 'lemah'. Tanda yang berbalik antar era juga rapuh"
          "\nwalau selisihnya besar. Dan semua ini mengukur PELUANG MENANG pada horizon"
          "\ntetap tanpa stop maupun target; sinyal dengan peluang menang rendah masih bisa"
          "\nberharapan positif kalau imbalan:risikonya bagus. BTC saja, bukan altcoin.")


if __name__ == "__main__":
    main()

"""Uji: apakah bulan baru / purnama memicu REVERSAL (pembalikan arah) BTC?

Kenapa uji ini perlu ada: moon_phase_btc.md menguji RATA-RATA return dan volatilitas di
sekitar fase bulan — keduanya null. Tapi klaim "bulan baru memicu reversal" tidak bisa
dibantah oleh uji rata-rata: tren naik yang berbalik turun dan tren turun yang berbalik
naik saling meniadakan, sehingga rata-ratanya tetap nol walau efeknya ada. Yang diuji di
sini adalah PERUBAHAN TANDA arah, bukan arahnya.

DITETAPKAN SEBELUM MELIHAT HASIL (11 Okt 2026):
  Data      : cloud/data/btc_daily_bitstamp.csv.gz (Bitstamp harian, sama dengan uji lain)
  Hari event: satu hari per siklus — hari yang elongasi tengah harinya paling dekat ke
              0° (bulan baru) atau 180° (purnama), yaitu jarak < 6,1° (setengah gerak
              harian Bulan, ~12,2°/hari).
  Reversal  : tanda return N hari SEBELUM hari t berbeda dengan tanda return N hari
              SESUDAHNYA. Horizon utama N = 7; N = 3 dan 14 sebagai pelengkap.
  Statistik : tingkat reversal di hari event dikurangi tingkat di semua hari.
  Placebo   : 2.000 geseran melingkar — hari-hari event digeser acak 30 s/d (panjang
              era - 30) hari dengan pembungkusan, sehingga jarak antar-event dan
              pengelompokan tren tetap, hanya kaitannya dengan fase bulan yang putus.
              p = porsi placebo yang selisihnya (mutlak) >= selisih asli (dua sisi).
              (Rancangan awal memakai "siklus palsu 29,53 hari dengan offset acak". Pada
              data HARIAN itu hanya menghasilkan ~30 himpunan berbeda — 2.000 placebo
              semu — dan memberi p=0,000 yang palsu. Diganti sebelum hasil dipakai.)
  Pemisahan : 2012–2018 vs 2019–2026, supaya efek satu era tidak dibaca sebagai umum.

    python cloud/uji_reversal_bulan.py
    python cloud/uji_reversal_bulan.py --placebo 500    # lebih cepat
"""
import argparse
import csv
import datetime as dt
import gzip
import math
import os
import random
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

AMBANG = 6.1
HORIZON = (7, 3, 14)          # urutan: utama dulu
BENIH = 20261011


def muat():
    hari, tutup = [], []
    with gzip.open(os.path.join(BASE_DIR, "data", "btc_daily_bitstamp.csv.gz"), "rt",
                   encoding="utf-8") as f:
        for b in csv.DictReader(f):
            try:
                c = float(b["close"])
            except (TypeError, ValueError):
                continue
            if c > 0:
                hari.append(dt.date.fromisoformat(b["dt"][:10]))
                tutup.append(c)
    return hari, tutup


def jarak_sudut(a, b):
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def hari_fase(hari):
    """Indeks hari bulan baru & purnama, dari ephemeris astro.py (tengah hari UTC)."""
    from astro import fase_bulan
    baru, purnama = [], []
    for i, d in enumerate(hari):
        e = fase_bulan(dt.datetime(d.year, d.month, d.day, 12, tzinfo=dt.timezone.utc))
        if jarak_sudut(e, 0.0) < AMBANG:
            baru.append(i)
        elif jarak_sudut(e, 180.0) < AMBANG:
            purnama.append(i)
    return baru, purnama


def tanda_reversal(tutup, n):
    """{indeks: True/False} untuk setiap hari yang punya n hari sebelum & sesudah."""
    hasil = {}
    for t in range(n, len(tutup) - n):
        a = math.log(tutup[t] / tutup[t - n])
        b = math.log(tutup[t + n] / tutup[t])
        if a != 0 and b != 0:
            hasil[t] = (a > 0) != (b > 0)
    return hasil


def tingkat(rev, indeks):
    v = [rev[i] for i in indeks if i in rev]
    return (sum(v) / len(v), len(v)) if v else (float("nan"), 0)


def uji(tutup, event, indeks_era, n, placebo, rng):
    rev = tanda_reversal(tutup, n)
    era = set(indeks_era)
    dasar, _ = tingkat(rev, [i for i in rev if i in era])
    asli, jml = tingkat(rev, [i for i in event if i in era])
    selisih = asli - dasar
    lebih = 0
    lo, hi = min(era), max(era)
    panjang = hi - lo + 1
    ev = [i - lo for i in event if i in era]
    for _ in range(placebo):
        geser = rng.randint(30, panjang - 30)
        palsu = [lo + (i + geser) % panjang for i in ev]
        p_t, _ = tingkat(rev, palsu)
        if abs(p_t - dasar) >= abs(selisih):
            lebih += 1
    return {"n": n, "event": jml, "tingkat_event": asli, "tingkat_dasar": dasar,
            "selisih_pp": 100 * selisih, "p": (lebih + 1) / (placebo + 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placebo", type=int, default=2000)
    a = ap.parse_args()
    hari, tutup = muat()
    baru, purnama = hari_fase(hari)
    semua = list(range(len(hari)))
    batas = next(i for i, d in enumerate(hari) if d.year >= 2019)
    era = [("Semua", semua), ("2012–2018", semua[:batas]), ("2019–2026", semua[batas:])]
    print(f"Data: {hari[0]} s/d {hari[-1]}, {len(hari)} hari · bulan baru {len(baru)} · "
          f"purnama {len(purnama)} · placebo {a.placebo} geseran melingkar")
    for nama_fase, event in (("Bulan baru", baru), ("Purnama", purnama)):
        for n in HORIZON:
            for nama_era, idx in era:
                rng = random.Random(BENIH + n)
                h = uji(tutup, event, idx, n, a.placebo, rng)
                print(f"{nama_fase:10} N={n:<2} {nama_era:9} event={h['event']:3} "
                      f"reversal {100 * h['tingkat_event']:.1f}% vs dasar "
                      f"{100 * h['tingkat_dasar']:.1f}% ({h['selisih_pp']:+.1f} pp) "
                      f"p={h['p']:.3f}" + ("   <- horizon UTAMA" if n == HORIZON[0]
                                           and nama_era == "Semua" else ""))


if __name__ == "__main__":
    main()

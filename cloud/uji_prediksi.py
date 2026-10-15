"""Kalibrasi PREDIKSI HARGA PENUTUPAN per horizon (1 hari, 7 hari, 30 hari).

Kenapa ada: user meminta "prediksi harga daily/weekly". Yang bisa dipertanggungjawabkan
bukan satu angka, melainkan KISARAN beserta seberapa sering kisaran itu benar. Metodenya
jalan acak (median = harga terakhir, lebar = sigma * akar(h)) — pemenang uji sebelumnya
untuk harga PENUTUP (uji_timesfm.py: TimesFM dan sebaran empiris kalah darinya). Yang
belum pernah diukur: cakupannya di horizon PENDEK. Itu yang diuji di sini.

DITETAPKAN SEBELUM MELIHAT HASIL (15 Okt 2026):
  Data     : cloud/data/btc_daily_bitstamp.csv.gz (BTC harian 2012–2026)
  Sigma    : simpangan baku imbal hasil log harian 90 hari terakhir SEBELUM titik asal
  Kuantil  : z(0,10) = -1,2816 · z(0,25) = -0,6745 · median = harga terakhir (tanpa drift)
  Horizon  : 1, 7, 30 hari
  Asal     : setiap hari (horizon 1) / tiap 7 hari (7, 30) supaya titik tidak terlalu rapat
  Ukuran   : cakupan p10–p90 (target 80%) dan p25–p75 (target 50%), per era 2012–2018 vs
             2019–2026; plus porsi penutupan > harga asal (apakah "median = harga sekarang"
             bias arah).

    python cloud/uji_prediksi.py
"""
import csv
import gzip
import math
import os
import statistics

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JENDELA_SIGMA = 90
Z10, Z25 = 1.2816, 0.6745
HORIZON = (1, 7, 30)


def muat():
    tgl, tutup = [], []
    with gzip.open(os.path.join(BASE_DIR, "data", "btc_daily_bitstamp.csv.gz"), "rt",
                   encoding="utf-8") as f:
        for b in csv.DictReader(f):
            try:
                c = float(b["close"])
            except (TypeError, ValueError):
                continue
            if c > 0:
                tgl.append(b["dt"][:10])
                tutup.append(c)
    return tgl, tutup


def rentang(tutup, i, h):
    """(p10, p25, p75, p90) harga penutupan h hari setelah indeks i."""
    r = [math.log(tutup[j] / tutup[j - 1]) for j in range(i - JENDELA_SIGMA + 1, i + 1)]
    s = statistics.pstdev(r) * math.sqrt(h)
    p = tutup[i]
    return (p * math.exp(-Z10 * s), p * math.exp(-Z25 * s),
            p * math.exp(Z25 * s), p * math.exp(Z10 * s))


def uji(tgl, tutup, h, dari=None, sampai=None):
    langkah = 1 if h == 1 else 7
    n80 = n50 = naik = total = 0
    for i in range(JENDELA_SIGMA, len(tutup) - h, langkah):
        if dari and tgl[i] < dari or sampai and tgl[i] > sampai:
            continue
        p10, p25, p75, p90 = rentang(tutup, i, h)
        a = tutup[i + h]
        total += 1
        n80 += p10 <= a <= p90
        n50 += p25 <= a <= p75
        naik += a > tutup[i]
    if not total:
        return None
    return {"titik": total, "cakupan_80": round(100 * n80 / total, 1),
            "cakupan_50": round(100 * n50 / total, 1),
            "ditutup_lebih_tinggi": round(100 * naik / total, 1)}


def main():
    tgl, tutup = muat()
    print(f"BTC {tgl[0]} s/d {tgl[-1]} · sigma {JENDELA_SIGMA} hari · target cakupan 80% & 50%")
    for h in HORIZON:
        for nama, dari, sampai in (("Semua", None, None), ("2012–2018", None, "2018-12-31"),
                                   ("2019–2026", "2019-01-01", None)):
            r = uji(tgl, tutup, h, dari, sampai)
            print(f"h={h:<2} {nama:9} titik={r['titik']:5} cakupan p10–p90 {r['cakupan_80']:5.1f}% "
                  f"· p25–p75 {r['cakupan_50']:5.1f}% · ditutup lebih tinggi "
                  f"{r['ditutup_lebih_tinggi']:5.1f}%")


if __name__ == "__main__":
    main()

"""Uji astro-trading pada BTC — dua repo user dan dokumen risetnya, diuji dengan cara yang benar.

Asalnya permintaan user 24 Sep 2026: memakai ilmu jesse-astrology-trading-strategy dan
pyAstroTrader di setiap analisa. Sebelum dipakai, keduanya DIUJI — seperti setiap
temuan lain di repo ini (lihat README, prinsip 3: temuan wajib lolos uji ketahanan).

UJI 1 — SINYAL jesse-astrology (ml-BTC-USD-daily-index.csv).
    Sinyal buy/sell harian 2010–2022; file-nya terakhir diterbitkan 6 Sep 2021. Jadi
    7 Sep 2021 – 31 Des 2022 (481 hari) adalah RAMALAN SUNGGUHAN. Diukur pada target
    yang mereka latih sendiri (arah harga tengah OHLC/4) dan pada arah close, lalu
    dibandingkan dengan pilihan hari ACAK berjumlah sama (plasebo).
    Datanya diunduh saat uji dijalankan dan TIDAK disimpan di repo: berlisensi AGPL-3.0.

UJI 2 — METODE pyAstroTrader, diulang dua kali.
    pyAstroTrader melatih model pada posisi planet harian untuk meramal arah 5 hari
    (SWING_TRADE_DURATION = 5). Cara ia menilai modelnya bocor tiga lapis:
      (a) train_test_split(shuffle=True) pada deret waktu — hari uji adalah tetangga hari
          latih, dan posisi planet nyaris identik antar hari berurutan;
      (b) skor dihitung pada `total_test` = SELURUH data, termasuk data latih;
      (c) diulang hingga MAX_INTERACTIONS kali dan yang disimpan skor terbaik.
    Di sini metodenya diulang dengan fitur yang sama jenisnya (sin/cos bujur, dokumen riset
    user Bagian C.1) dan k-NN, sekali dengan pemecahan ACAK seperti aslinya, sekali secara
    KRONOLOGIS (latih masa lalu, nilai masa depan). Selisih keduanya = besar kebocorannya.

UJI 3 — PERISTIWA (aspek mayor & retrograde) vs VOLATILITAS dan ARAH 5 hari.
    Dokumen riset user (Bagian C.3) menyarankan target VOLATILITAS, bukan arah — "siklus
    waktu tidak menentukan arah". Keduanya diuji. Tiap fitur dibandingkan dengan dirinya
    sendiri yang DIGESER waktunya (plasebo geser-melingkar, ≥ 90 hari): pergeseran
    mempertahankan lamanya aspek & pengelompokan volatilitas, hanya memutus kaitannya
    dengan tanggal sebenarnya. Banyak fitur diuji sekaligus, jadi dikoreksi FDR
    (Benjamini–Hochberg, q = 0,10).

SEMUA PARAMETER DITETAPKAN SEBELUM MELIHAT HASIL (di bawah). Mengubahnya sesudah melihat
hasil lalu melaporkan yang terbaik adalah cara termudah membuat astrologi "terbukti".

Skrip ini untuk RISET, bukan untuk runner bot: memakai numpy (tidak terpasang di runner).
Hasilnya dicatat di cloud/data/astro_trading.md dan dipaku di tests/test_uji_astro_hasil.py.

Pemakaian:
    python cloud/uji_astro.py            # ketiga uji
    python cloud/uji_astro.py --json
"""

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import math
import os
import random
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import astro  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_BTC = os.path.join(BASE_DIR, "data", "btc_daily_bitstamp.csv.gz")
URL_JESSE = ("https://raw.githubusercontent.com/financial-astrology-research/"
             "jesse-astrology-trading-strategy/master/strategies/AstroStrategyMA/"
             "ml-BTC-USD-daily-index.csv")

# --- Parameter a priori -------------------------------------------------------------------
TERBIT_JESSE = dt.date(2021, 9, 6)     # commit terakhir file sinyal BTC (git log)
AKHIR_JESSE = dt.date(2022, 12, 31)
N_PLASEBO = 5000
SEED = 42
HORIZON_ARAH = 5                       # = SWING_TRADE_DURATION pyAstroTrader
PORSI_LATIH = 0.7                      # = test_size 0.3 pyAstroTrader
K_NN = 15
GESER_MIN = 90                         # hari; plasebo geser-melingkar
N_GESER = 400
Q_FDR = 0.10
MIN_HARI_FITUR = 60                    # fitur yang aktif < 60 hari tidak diuji


def muat_btc():
    k = {}
    with gzip.open(CSV_BTC, "rt", encoding="utf-8") as f:
        for b in csv.DictReader(f):
            try:
                o, h, l, c = (float(b[x]) for x in ("open", "high", "low", "close"))
            except (TypeError, ValueError):
                continue
            if c > 0:
                k[dt.date.fromisoformat(b["dt"][:10])] = (o, h, l, c)
    return k


def _p_binom(k, n):
    z = (k - n / 2) / math.sqrt(n / 4)
    return math.erfc(abs(z) / math.sqrt(2))


# --- UJI 1 --------------------------------------------------------------------------------

def uji_jesse(btc, sinyal=None):
    if sinyal is None:
        with urllib.request.urlopen(URL_JESSE, timeout=30) as r:
            sinyal = {dt.date.fromisoformat(b["Date"]): b["Action"]
                      for b in csv.DictReader(io.StringIO(r.read().decode()))}
    hasil = {}
    for label, mulai, akhir in (("in_sample", dt.date(2014, 1, 1), TERBIT_JESSE),
                                ("luar_sampel", TERBIT_JESSE + dt.timedelta(days=1),
                                 AKHIR_JESSE)):
        hari = sorted(d for d in sinyal if mulai <= d <= akhir and d in btc
                      and d - dt.timedelta(days=1) in btc)
        n = len(hari)
        r = {}
        for target in ("mid", "close"):
            benar = naik = 0
            for d in hari:
                k0, k1 = btc[d - dt.timedelta(days=1)], btc[d]
                up = (sum(k1) > sum(k0)) if target == "mid" else (k1[3] > k0[3])
                naik += up
                benar += (sinyal[d] == "buy") == up
            r[target] = {"akurasi": round(100 * benar / n, 1),
                         "baseline_mayoritas": round(100 * max(naik, n - naik) / n, 1),
                         "p_vs_50": round(_p_binom(benar, n), 3)}
        ret = [btc[d][3] / btc[d - dt.timedelta(days=1)][3] for d in hari]
        beli = [sinyal[d] == "buy" for d in hari]

        def gabung(mask):
            x = 1.0
            for ri, m in zip(ret, mask):
                if m:
                    x *= ri
            return x - 1

        nyata = gabung(beli)
        bh = gabung([True] * n)
        rng = random.Random(SEED)
        k = sum(beli)
        acak = sorted(gabung([i in s for i in range(n)])
                      for s in (set(rng.sample(range(n), k)) for _ in range(N_PLASEBO)))
        hasil[label] = {
            "n_hari": n, "hari_buy": k, **{f"target_{t}": v for t, v in r.items()},
            "long_hari_buy_persen": round(100 * nyata, 1),
            "beli_tahan_persen": round(100 * bh, 1),
            "plasebo_median_persen": round(100 * acak[len(acak) // 2], 1),
            "plasebo_p": round(sum(1 for x in acak if x >= nyata) / len(acak), 3)}
    return hasil


# --- fitur astro harian (dipakai uji 2 & 3) ------------------------------------------------

def fitur_semua(hari):
    return {d: astro.fitur_harian(d) for d in hari}


# --- UJI 2 --------------------------------------------------------------------------------

def uji_bocor(btc, fitur):
    import numpy as np

    hari = sorted(d for d in fitur if d + dt.timedelta(days=HORIZON_ARAH) in btc)
    kolom = sorted(k for k in fitur[hari[0]] if k.endswith(("_sin", "_cos")))
    X = np.array([[fitur[d][k] for k in kolom] for d in hari])
    y = np.array([btc[d + dt.timedelta(days=HORIZON_ARAH)][3] > btc[d][3] for d in hari])

    def knn(latih, uji):
        Xa, ya, Xb = X[latih], y[latih], X[uji]
        benar = 0
        for i in range(0, len(Xb), 256):
            blok = Xb[i:i + 256]
            jarak = ((blok[:, None, :] - Xa[None, :, :]) ** 2).sum(axis=2)
            dekat = np.argpartition(jarak, K_NN, axis=1)[:, :K_NN]
            tebak = ya[dekat].mean(axis=1) > 0.5
            benar += int((tebak == y[uji][i:i + 256]).sum())
        return benar / len(Xb)

    n = len(hari)
    potong = int(n * PORSI_LATIH)
    rng = np.random.default_rng(SEED)
    acak = rng.permutation(n)
    latih_a, uji_a = acak[:potong], acak[potong:]
    latih_k, uji_k = np.arange(potong), np.arange(potong, n)
    return {
        "n_hari": n, "fitur": len(kolom), "horizon_hari": HORIZON_ARAH, "k": K_NN,
        "akurasi_pecah_acak": round(100 * knn(latih_a, uji_a), 1),
        "akurasi_kronologis": round(100 * knn(latih_k, uji_k), 1),
        "baseline_kronologis": round(100 * max(y[uji_k].mean(), 1 - y[uji_k].mean()), 1),
        "periode_uji_kronologis": f"{hari[potong].isoformat()} .. {hari[-1].isoformat()}",
    }


# --- UJI 3 --------------------------------------------------------------------------------

def uji_peristiwa(btc, fitur):
    import numpy as np

    hari = sorted(d for d in fitur if d - dt.timedelta(days=1) in btc
                  and d + dt.timedelta(days=HORIZON_ARAH) in btc)
    vol = np.array([abs(math.log(btc[d][3] / btc[d - dt.timedelta(days=1)][3]))
                    for d in hari])
    arah = np.array([btc[d + dt.timedelta(days=HORIZON_ARAH)][3] > btc[d][3]
                     for d in hari], dtype=float)
    nama = sorted({k for f in fitur.values() for k in f if not k.endswith(("_sin", "_cos"))})
    rng = np.random.default_rng(SEED)
    geser = rng.integers(GESER_MIN, len(hari) - GESER_MIN, N_GESER)

    hasil = []
    for k in nama:
        m = np.array([fitur[d].get(k, 0) for d in hari], dtype=bool)
        if m.sum() < MIN_HARI_FITUR or (~m).sum() < MIN_HARI_FITUR:
            continue
        for target, seri in (("volatilitas", vol), ("arah_5h", arah)):
            efek = seri[m].mean() - seri[~m].mean()
            palsu = np.array([seri[np.roll(m, s)].mean() - seri[~np.roll(m, s)].mean()
                              for s in geser])
            p = (np.sum(np.abs(palsu) >= abs(efek)) + 1) / (len(palsu) + 1)
            hasil.append({"fitur": k, "target": target, "hari_aktif": int(m.sum()),
                          "efek": float(efek), "p": float(p)})

    # Benjamini–Hochberg per target.
    for target in ("volatilitas", "arah_5h"):
        baris = sorted((h for h in hasil if h["target"] == target), key=lambda h: h["p"])
        m_uji = len(baris)
        lolos_sampai = 0
        for i, h in enumerate(baris, 1):
            if h["p"] <= Q_FDR * i / m_uji:
                lolos_sampai = i
        for i, h in enumerate(baris, 1):
            h["lolos_fdr"] = i <= lolos_sampai

    ringkas = {}
    for target in ("volatilitas", "arah_5h"):
        baris = [h for h in hasil if h["target"] == target]
        ringkas[target] = {
            "diuji": len(baris),
            "p_di_bawah_0_05": sum(1 for h in baris if h["p"] < 0.05),
            "diharapkan_kebetulan": round(0.05 * len(baris), 1),
            "lolos_fdr": [h["fitur"] for h in baris if h["lolos_fdr"]],
        }
    # Klaim paling populer, dilaporkan terpisah apa pun hasilnya.
    populer = {h["target"]: {"efek": round(h["efek"], 5), "p": round(h["p"], 3),
                             "hari_aktif": h["hari_aktif"]}
               for h in hasil if h["fitur"] == "Merkurius_retrograde"}
    return {"n_hari": len(hari), "ringkas": ringkas, "merkurius_retrograde": populer,
            "vol_rata_harian_persen": round(100 * float(vol.mean()), 2),
            "detail": sorted(hasil, key=lambda h: h["p"])[:12]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--tanpa-jesse", action="store_true", help="lewati unduhan GitHub")
    a = ap.parse_args()

    btc = muat_btc()
    hari = sorted(d for d in btc if d >= dt.date(2012, 1, 2))
    fitur = fitur_semua(hari)
    out = {}
    if not a.tanpa_jesse:
        out["uji1_jesse"] = uji_jesse(btc)
    out["uji2_pyastrotrader"] = uji_bocor(btc, fitur)
    out["uji3_peristiwa"] = uji_peristiwa(btc, fitur)
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

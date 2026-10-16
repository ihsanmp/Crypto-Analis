"""Uji Liquidity Clock (jam_likuiditas.py) pada BTC 2015-2026 — DIDAFTARKAN SEBELUM DIJALANKAN.

Hipotesis (rancangan user 15 Okt 2026): skor Liquidity Jumat t memprediksi return BTC
4, 8, dan 12 minggu ke depan secara POSITIF.

  Sinyal    : skor Liquidity Jumat t, hanya data yang sudah TERSEDIA hari itu (JEDA_RILIS).
  Masuk     : penutupan candle harian Sabtu (t+1) — sesudah sinyal, bukan pada harga sinyal.
  Ukuran    : IC = korelasi peringkat Spearman skor vs log-return t+1 -> t+1+7h hari.
  p-value   : placebo GESER MELINGKAR 2.000x (geser >= 26 minggu). Mempertahankan
              autokorelasi skor DAN tumpang-tindih return — uji t biasa pada return 12
              minggu yang dihitung tiap minggu terlalu optimis.
  Lolos     : IC > 0 dengan p < 0,05/3 (Bonferroni, 3 horizon) DAN tanda IC sama di kedua
              era 2015-2020 & 2021-2026. Selain itu: TIDAK TERBUKTI.
  Deskriptif (tidak ikut vonis): IC per komponen, return per kuadran jam, strategi eksposur
              vs beli-tahan, grid ketahanan lookback x k.

Data BTC: cloud/data/btc_daily_bitstamp.csv.gz (sama dengan uji lain). FRED via makro.ambil.

    python cloud/uji_jam_likuiditas.py
    python cloud/uji_jam_likuiditas.py --placebo 500
"""
import argparse
import csv
import gzip
import math
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jam_likuiditas as jl  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MULAI_UJI = date(2015, 1, 2)
HORIZON = (4, 8, 12)
ERA = ((date(2015, 1, 1), date(2020, 12, 31)), (date(2021, 1, 1), date(2026, 12, 31)))
BENIH = 20261015


def muat_btc():
    tutup = {}
    with gzip.open(os.path.join(BASE_DIR, "data", "btc_daily_bitstamp.csv.gz"), "rt",
                   encoding="utf-8") as f:
        for b in csv.DictReader(f):
            try:
                c = float(b["close"])
            except (TypeError, ValueError):
                continue
            if c > 0:
                tutup[date.fromisoformat(b["dt"][:10])] = c
    return tutup


def peringkat(x):
    urut = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(urut):
        j = i
        while j + 1 < len(urut) and x[urut[j + 1]] == x[urut[i]]:
            j += 1
        for k in range(i, j + 1):
            r[urut[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a, b):
    pas = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pas) < 20:
        return None
    ra, rb = peringkat([p[0] for p in pas]), peringkat([p[1] for p in pas])
    n = len(pas)
    ma, mb = sum(ra) / n, sum(rb) / n
    kov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return kov / (va * vb) if va and vb else None


def return_maju(jumat, tutup, h):
    keluar = []
    for f in jumat:
        a, b = tutup.get(f + timedelta(days=1)), tutup.get(f + timedelta(days=1 + 7 * h))
        keluar.append(math.log(b / a) if a and b else None)
    return keluar


def placebo_p(skor, ret, ic, n, rng, geser_min=26):
    """Fraksi geser melingkar yang IC-nya >= IC asli (satu sisi)."""
    idx = [i for i, (s, r) in enumerate(zip(skor, ret)) if s is not None and r is not None]
    s = [skor[i] for i in idx]
    r = [ret[i] for i in idx]
    m = len(s)
    lebih = 0
    for _ in range(n):
        g = rng.randint(geser_min, m - geser_min)
        if spearman(s[g:] + s[:g], r) >= ic:
            lebih += 1
    return (lebih + 1) / (n + 1)


def potong(jumat, deret, awal, akhir):
    return [v if awal <= f <= akhir else None for f, v in zip(jumat, deret)]


BIAYA_SATU_ARAH = 0.0015      # 0,15% per sisi = separuh biaya pulang-pergi BTC backtest.py


def strategi(jumat, liq, resesi, tutup, biaya=BIAYA_SATU_ARAH):
    """Eksposur Jumat t diterapkan ke minggu t+1 -> t+8 hari; ubah hanya bila >= 10 pp.

    BIAYA (langkah 3, 16 Okt 2026): tiap perubahan eksposur membayar |delta| x biaya;
    beli-tahan membayar satu kali masuk. Versi awal tanpa biaya (CAGR 40,1% vs 61,8%)."""
    e_now, nilai, bh, puncak, puncak_bh, dd, dd_bh, ubah, ret = None, 1.0, 1.0, 1.0, 1.0, 0, 0, 0, []
    ret_bh, per_tahun, total_biaya = [], {}, 0.0
    for f, s, rs in zip(jumat, liq, resesi):
        a, b = tutup.get(f + timedelta(days=1)), tutup.get(f + timedelta(days=8))
        if s is None or not a or not b or f < MULAI_UJI:
            continue
        target = jl.eksposur(s, None, rs)
        if e_now is None:
            bh *= 1 - biaya
        if e_now is None or abs(target - e_now) >= jl.AMBANG_UBAH:
            potong = abs(target - (e_now or 0.0)) * biaya
            nilai *= 1 - potong
            total_biaya += potong
            ubah += e_now is not None
            e_now = target
        r = b / a - 1
        nilai *= 1 + e_now * r
        bh *= 1 + r
        ret.append(e_now * r)
        ret_bh.append(r)
        th_ = per_tahun.setdefault(f.year, [1.0, 1.0, []])
        th_[0] *= 1 + e_now * r
        th_[1] *= 1 + r
        th_[2].append(e_now)
        puncak, puncak_bh = max(puncak, nilai), max(puncak_bh, bh)
        dd, dd_bh = min(dd, nilai / puncak - 1), min(dd_bh, bh / puncak_bh - 1)
    th = len(ret) / 52
    mu = sum(ret) / len(ret)
    sd = math.sqrt(sum((x - mu) ** 2 for x in ret) / (len(ret) - 1))
    mb = sum(ret_bh) / len(ret_bh)
    sb = math.sqrt(sum((x - mb) ** 2 for x in ret_bh) / (len(ret_bh) - 1))
    return {"tahun": round(th, 1), "cagr_strategi": nilai ** (1 / th) - 1,
            "cagr_beli_tahan": bh ** (1 / th) - 1, "maxdd_strategi": dd,
            "maxdd_beli_tahan": dd_bh, "sharpe_strategi": mu / sd * math.sqrt(52),
            "sharpe_beli_tahan": mb / sb * math.sqrt(52),
            "perubahan_eksposur": ubah, "biaya_total_persen": total_biaya * 100,
            "per_tahun": {y: (v[0] - 1, v[1] - 1, sum(v[2]) / len(v[2]))
                          for y, v in sorted(per_tahun.items())}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placebo", type=int, default=2000)
    a = ap.parse_args()
    rng = random.Random(BENIH)
    tutup = muat_btc()
    akhir = max(tutup)
    fred, gagal = jl.ambil_fred()
    if gagal:
        sys.exit(f"FRED gagal: {gagal}")
    jumat = jl.jumat_dari(date.fromisoformat(jl.MULAI), akhir)
    L = jl.deret_likuiditas(fred, jumat)
    liq = potong(jumat, L["likuiditas"], MULAI_UJI, akhir)
    print(f"BTC {min(tutup)}..{akhir} · sinyal Jumat {MULAI_UJI}..{akhir} · "
          f"{sum(v is not None for v in liq)} minggu berskor")

    print("\n== UTAMA: IC skor Liquidity vs return BTC ke depan ==")
    alpha = 0.05 / len(HORIZON)
    lolos_semua = []
    for h in HORIZON:
        ret = return_maju(jumat, tutup, h)
        ic = spearman(liq, ret)
        p = placebo_p(liq, ret, ic, a.placebo, rng)
        era = [spearman(potong(jumat, liq, *e), ret) for e in ERA]
        lolos = ic > 0 and p < alpha and all(x is not None and x > 0 for x in era)
        lolos_semua.append(lolos)
        print(f"h={h:>2} mg  IC={ic:+.3f}  p_placebo={p:.3f}  era15-20={era[0]:+.3f}  "
              f"era21-26={era[1]:+.3f}  -> {'LOLOS' if lolos else 'tidak lolos'}")
    print("VONIS:", "TERBUKTI pada horizon " + ",".join(
        str(h) for h, x in zip(HORIZON, lolos_semua) if x) if any(lolos_semua)
        else "TIDAK TERBUKTI (pra-registrasi: Bonferroni 3 horizon + konsisten 2 era)")

    # NFCI direvisi tiap minggu dan ALFRED (vintage) tidak terjangkau, jadi L4 memakai
    # versi TERKINI — satu-satunya jalur bocor masa depan yang tersisa. Vonis yang hanya
    # hidup karena L4 tidak bisa dipercaya.
    print("\n== Pemeriksaan bocor: tanpa L4 (NFCI direvisi), h=12 ==")
    r12 = return_maju(jumat, tutup, 12)
    tanpa = [jl._rata(*v) for v in zip(*(L["komponen"][k] for k in L["komponen"]
                                          if not k.startswith("L4")))]
    tanpa = potong(jumat, tanpa, MULAI_UJI, akhir)
    ic_t = spearman(tanpa, r12)
    print(f"IC={ic_t:+.3f}  p_placebo={placebo_p(tanpa, r12, ic_t, a.placebo, rng):.4f}  "
          f"era={[round(spearman(potong(jumat, tanpa, *e), r12), 3) for e in ERA]}")

    print("\n== Deskriptif: IC per komponen (h=8) ==")
    r8 = return_maju(jumat, tutup, 8)
    for k, v in L["komponen"].items():
        print(f"{k:<22} IC={spearman(potong(jumat, v, MULAI_UJI, akhir), r8):+.3f}")

    for h in (4, 12):
        print(f"\n== Deskriptif: return BTC {h} minggu per kuadran jam ==")
        rh = return_maju(jumat, tutup, h)
        kel = {}
        for i in range(jl.K_MINGGU, len(jumat)):
            s, s0 = liq[i], L["likuiditas"][i - jl.K_MINGGU]
            if s is None or s0 is None or rh[i] is None:
                continue
            kel.setdefault(jl.KUADRAN[(s >= 0, s - s0 >= 0)][0], []).append(rh[i])
        for nama, xs in sorted(kel.items(), key=lambda t: -sum(t[1]) / len(t[1])):
            naik = sum(x > 0 for x in xs) / len(xs)
            print(f"{nama:<26} N={len(xs):>3}  median={(math.exp(sorted(xs)[len(xs) // 2]) - 1) * 100:+.1f}%"
                  f"  naik={naik * 100:.0f}%")

    # Yang diuji IC adalah POSISI skor, bukan kuadran — jadi tampilkan juga per tersil skor.
    print("\n== Deskriptif: return BTC 12 minggu per tersil skor Liquidity ==")
    pas = sorted((s, r) for s, r in zip(liq, r12) if s is not None and r is not None)
    n3 = len(pas) // 3
    for nama, xs in (("RENDAH", pas[:n3]), ("TENGAH", pas[n3:2 * n3]), ("TINGGI", pas[2 * n3:])):
        rs = sorted(r for _, r in xs)
        print(f"{nama:<7} skor {xs[0][0]:+.2f}..{xs[-1][0]:+.2f}  N={len(xs)}  "
              f"median={(math.exp(rs[len(rs) // 2]) - 1) * 100:+.1f}%  "
              f"naik={sum(r > 0 for r in rs) / len(rs) * 100:.0f}%")

    print("\n== Deskriptif: strategi eksposur (Liquidity saja) vs beli-tahan ==")
    kotor = strategi(jumat, L["likuiditas"], L["resesi"], tutup, biaya=0.0)
    print(f"TANPA biaya: CAGR {kotor['cagr_strategi'] * 100:.1f}% vs "
          f"{kotor['cagr_beli_tahan'] * 100:.1f}%")
    st = strategi(jumat, L["likuiditas"], L["resesi"], tutup)
    print(f"SETELAH biaya {BIAYA_SATU_ARAH * 100:.2f}%/sisi (total "
          f"{st['biaya_total_persen']:.1f}% dari modal sepanjang periode):")
    print(f"{st['tahun']} th · CAGR {st['cagr_strategi'] * 100:.1f}% vs "
          f"{st['cagr_beli_tahan'] * 100:.1f}% · maxDD {st['maxdd_strategi'] * 100:.0f}% vs "
          f"{st['maxdd_beli_tahan'] * 100:.0f}% · Sharpe {st['sharpe_strategi']:.2f} vs "
          f"{st['sharpe_beli_tahan']:.2f} · "
          f"{st['perubahan_eksposur']} kali ubah")
    # PEMBANDING YANG ADIL: eksposur TETAP sebesar rata-rata eksposur strategi. Strategi yang
    # rata-rata ±50% tentu lebih dangkal drawdown-nya dari beli-tahan 100%; pertanyaannya
    # apakah TIMING-nya menambah nilai di atas sekadar setengah investasi.
    e_rata = sum(v[2] for v in st["per_tahun"].values()) / len(st["per_tahun"])
    tetap = strategi(jumat, [None if s is None else 2 * e_rata - 1 for s in L["likuiditas"]],
                     [False] * len(jumat), tutup)
    print(f"  pembanding eksposur TETAP {e_rata * 100:.0f}%: CAGR "
          f"{tetap['cagr_strategi'] * 100:.1f}% · maxDD {tetap['maxdd_strategi'] * 100:.0f}% · "
          f"Sharpe {tetap['sharpe_strategi']:.2f}  -> timing Liquidity "
          + ("MENAMBAH nilai" if st["sharpe_strategi"] > tetap["sharpe_strategi"]
             and st["cagr_strategi"] > tetap["cagr_strategi"] else
             "TIDAK jelas menambah nilai"))
    print("  per tahun (strategi | beli-tahan | eksposur rata2):")
    for y, (rs_, rb_, e_) in st["per_tahun"].items():
        print(f"   {y}: {rs_ * 100:+7.1f}% | {rb_ * 100:+7.1f}% | {e_ * 100:3.0f}%"
              + ("   <- strategi lebih baik" if rs_ > rb_ else ""))

    print("\n== Ketahanan: IC h=8 untuk lookback x k ==")
    asli = (jl.LOOKBACK, jl.K_MINGGU)
    for lb in (52, 104, 156):
        baris = []
        for k in (2, 4, 8):
            jl.LOOKBACK, jl.K_MINGGU = lb, k
            jl_skor = jl.skor

            def sk(x, tanda=1, _lb=lb, _k=k):
                return jl_skor(x, k=_k, lookback=_lb, min_riwayat=min(52, _lb), tanda=tanda)
            jl.skor = sk
            try:
                v = jl.deret_likuiditas(fred, jumat)["likuiditas"]
            finally:
                jl.skor = jl_skor
            baris.append(f"k={k}:{spearman(potong(jumat, v, MULAI_UJI, akhir), r8):+.3f}")
        print(f"lookback {lb:>3}  " + "  ".join(baris))
    jl.LOOKBACK, jl.K_MINGGU = asli


if __name__ == "__main__":
    main()

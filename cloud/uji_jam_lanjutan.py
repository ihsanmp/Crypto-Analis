"""Uji lanjutan Liquidity & Adoption Clock — DIDAFTARKAN SEBELUM DIJALANKAN (15 Okt 2026).

Melengkapi uji_jam_likuiditas.py (yang hanya menguji skor Liquidity pada BTC).

  1. ALTCOIN  Skor Liquidity vs return 12 minggu ETH (sejak 2017-11) dan SOL (sejak 2020-04),
              harga harian Yahoo. Hanya horizon 12 minggu — satu-satunya yang lolos di BTC;
              menguji horizon lain di sini berarti memancing. Lolos: IC > 0, p placebo
              < 0,05/2 (Bonferroni 2 aset), dan positif di KEDUA paruh sampel aset itu.
  2. GELOMBANG Skor Gelombang (funding + Fear & Greed) vs return BTC 4/8/12 minggu.
              Hipotesis rancangan: Gelombang tinggi = rawan koreksi -> IC NEGATIF. Lolos:
              IC < 0, p placebo (ekor bawah) < 0,05/3, negatif di 2021-23 DAN 2024-26.
              Aturan "Gelombang > 0,5 potong 25 pp" dinilai deskriptif: median return
              sesudah minggu > 0,5 vs sisanya.
  3. ADOPSI   Skor Struktural (A1+A2 dari arus ETF Farside) vs return BTC 4/12 minggu.
              Rancangan: "tidak dioptimasi, hanya dicek arahnya". Sampel ~85 minggu =
              ~7 jendela 12 minggu independen -> TIDAK ada vonis; yang dilaporkan hanya
              tanda IC dan apakah sesuai teori (positif).
  4. STRATEGI Eksposur Liquidity saja vs Liquidity+Struktural+Gelombang pada periode yang
              sama (sejak skor adopsi ada). Deskriptif.

    python cloud/uji_jam_lanjutan.py [--placebo 2000]
"""
import argparse
import math
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jam_likuiditas as jl  # noqa: E402
import uji_jam_likuiditas as uj  # noqa: E402

BENIH = 20261016
ALTCOIN = (("ETH-USD", date(2017, 11, 10)), ("SOL-USD", date(2020, 4, 11)))
ERA_GEL = ((date(2021, 1, 1), date(2023, 12, 31)), (date(2024, 1, 1), date(2026, 12, 31)))


def ret_maju(jumat, harga, h):
    keluar = []
    for f in jumat:
        a = harga.get((f + timedelta(days=1)).isoformat())
        b = harga.get((f + timedelta(days=1 + 7 * h)).isoformat())
        keluar.append(math.log(b / a) if a and b else None)
    return keluar


def potong(jumat, deret, awal, akhir):
    return [v if awal <= f <= akhir else None for f, v in zip(jumat, deret)]


def median_persen(xs):
    xs = sorted(xs)
    return (math.exp(xs[len(xs) // 2]) - 1) * 100 if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placebo", type=int, default=2000)
    a = ap.parse_args()
    rng = random.Random(BENIH)
    hari_ini = datetime.now(timezone.utc).date()
    fred, gagal = jl.ambil_fred()
    if gagal:
        sys.exit(f"FRED gagal: {gagal}")
    jumat = jl.jumat_dari(date.fromisoformat(jl.MULAI), hari_ini)
    L = jl.deret_likuiditas(fred, jumat)
    liq = L["likuiditas"]

    print("== 1. ALTCOIN: skor Liquidity vs return 12 minggu ==")
    for sim, mulai in ALTCOIN:
        harga = jl.harga_yahoo(sim)
        r = ret_maju(jumat, harga, 12)
        s = potong(jumat, liq, mulai, hari_ini)
        ic = uj.spearman(s, r)
        p = uj.placebo_p(s, r, ic, a.placebo, rng)
        idx = [f for f, x, y in zip(jumat, s, r) if x is not None and y is not None]
        tengah = idx[len(idx) // 2]
        paruh = [uj.spearman(potong(jumat, s, mulai, tengah), r),
                 uj.spearman(potong(jumat, s, tengah + timedelta(days=1), hari_ini), r)]
        lolos = ic > 0 and p < 0.05 / len(ALTCOIN) and all(x > 0 for x in paruh)
        print(f"{sim:<8} N={len(idx)}  IC={ic:+.3f}  p={p:.4f}  paruh={paruh[0]:+.3f}/"
              f"{paruh[1]:+.3f} (belah {tengah})  -> {'LOLOS' if lolos else 'tidak lolos'}")

    import gelombang as gl
    funding, cat = gl.funding_harian()
    G = gl.deret_gelombang(funding, gl.fear_greed(), jumat)
    gel = G["gelombang"]
    btc = jl.harga_yahoo("BTC-USD")
    print(f"\n== 2. GELOMBANG vs return BTC (hipotesis IC < 0) · {'; '.join(cat)} ==")
    n_gel = sum(v is not None for v in gel)
    print(f"{n_gel} minggu berskor, mulai "
          f"{next(f for f, v in zip(jumat, gel) if v is not None)}")
    for h in (4, 8, 12):
        r = ret_maju(jumat, btc, h)
        ic = uj.spearman(gel, r)
        p = uj.placebo_p([None if v is None else -v for v in gel], r, -ic, a.placebo, rng)
        era = [uj.spearman(potong(jumat, gel, *e), r) for e in ERA_GEL]
        lolos = ic < 0 and p < 0.05 / 3 and all(x is not None and x < 0 for x in era)
        print(f"h={h:>2}  IC={ic:+.3f}  p={p:.4f}  era21-23={era[0]:+.3f}  "
              f"era24-26={era[1]:+.3f}  -> {'LOLOS' if lolos else 'tidak lolos'}")
    for k in ("skor_W1", "skor_W2"):
        print(f"  {k} IC h=12: {uj.spearman(G[k], ret_maju(jumat, btc, 12)):+.3f}")
    for h in (4, 12):
        r = ret_maju(jumat, btc, h)
        atas = [y for x, y in zip(gel, r) if x is not None and y is not None and x > 0.5]
        bawah = [y for x, y in zip(gel, r) if x is not None and y is not None and x <= 0.5]
        print(f"  aturan > 0,5, h={h}: median {median_persen(atas):+.1f}% (N={len(atas)}) vs "
              f"{median_persen(bawah):+.1f}% (N={len(bawah)})")

    import adopsi
    arus, sumber, _ = adopsi.arus_etf()
    A = jl.deret_adopsi(arus, btc, jumat)
    st = A["struktural"]
    print(f"\n== 3. ADOPSI (A1+A2, {sumber}) — cek arah, TANPA vonis ==")
    n_ad = sum(v is not None for v in st)
    print(f"{n_ad} minggu berskor (~{n_ad // 12} jendela 12 minggu independen)")
    for h in (4, 12):
        r = ret_maju(jumat, btc, h)
        ic = uj.spearman(st, r)
        print(f"h={h:>2}  IC={ic:+.3f}  arah {'SESUAI' if ic > 0 else 'BERLAWANAN dengan'} teori")
    for k in ("skor_A1", "skor_A2"):
        print(f"  {k} IC h=12: {uj.spearman(A[k], ret_maju(jumat, btc, 12)):+.3f}")

    print("\n== 4. STRATEGI sejak skor adopsi ada (deskriptif) ==")
    for nama, pakai_a, pakai_g in (("Liquidity saja", False, False),
                                    ("+ Struktural", True, False),
                                    ("+ Struktural + Gelombang", True, True)):
        nilai, puncak, dd, e_now, n = 1.0, 1.0, 0.0, None, 0
        for i, f in enumerate(jumat):
            if st[i] is None or liq[i] is None or (pakai_g and gel[i] is None):
                continue
            pa = btc.get((f + timedelta(days=1)).isoformat())
            pb = btc.get((f + timedelta(days=8)).isoformat())
            if not pa or not pb:
                continue
            t = jl.eksposur(liq[i], st[i] if pakai_a else None, L["resesi"][i],
                            gel[i] if pakai_g else None)
            if e_now is None or abs(t - e_now) >= jl.AMBANG_UBAH:
                e_now = t
            nilai *= 1 + e_now * (pb / pa - 1)
            puncak = max(puncak, nilai)
            dd = min(dd, nilai / puncak - 1)
            n += 1
        print(f"{nama:<26} {n} minggu  hasil {(nilai - 1) * 100:+.1f}%  maxDD {dd * 100:.0f}%")
    bh = [btc.get((f + timedelta(days=1)).isoformat()) for i, f in enumerate(jumat)
          if st[i] is not None]
    bh = [x for x in bh if x]
    print(f"{'Beli-tahan':<26} hasil {(bh[-1] / bh[0] - 1) * 100:+.1f}%")


if __name__ == "__main__":
    main()

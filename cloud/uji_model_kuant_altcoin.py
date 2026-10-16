"""Uji walk-forward peluang Liquidity untuk ETH & SOL — DIDAFTARKAN SEBELUM DIJALANKAN
(16 Okt 2026).

Perluasan uji_model_kuant.py (BTC). Hanya versi LIKUIDITAS_SAJA: versi gabungan 12 sinyal
sudah GAGAL di BTC, jadi tidak diuji ulang di sini (menguji banyak varian per aset sampai
ada yang lolos = mencari kebetulan).

  Skor      : skor Liquidity Jumat t (sama dengan BTC; tidak ada parameter yang disetel).
  Target    : log-return aset h=12 minggu dari penutupan Sabtu (Yahoo <ASET>-USD).
  Peluang   : logistik skor -> P(naik), dilatih ulang tiap tahun uji hanya dengan minggu yang
              targetnya sudah terwujud sebelum 1 Jan tahun itu (jeda 12 minggu).
  Tahun uji : mulai tahun pertama yang punya >= 100 minggu latih (ETH 2020, SOL 2023).

KRITERIA (Bonferroni 2 aset): IC OOS > 0 dan p placebo < 0,025; Brier skill > 0; IC > 0 di
>= 60% tahun uji. Lolos -> peluang aset itu ditampilkan bot; gagal -> tidak.

    python cloud/uji_model_kuant_altcoin.py
"""
import json
import math
import os
import random
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jam_likuiditas as jl  # noqa: E402
import model_kuant as mk  # noqa: E402
import uji_jam_likuiditas as uj  # noqa: E402

ASET = ("ETH", "SOL")
H = 12
P_MAKS = 0.05 / len(ASET)
PORSI_TAHUN = 0.6
BENIH = 20261017


def walk_forward(jumat, liq, y):
    skor, prob, dasar, idx = [], [], [], []
    for th in range(2016, 2027):
        latih = [i for i in mk.indeks_latih(jumat, y, date(th, 1, 1), H) if liq[i] is not None]
        if len(latih) < 100:
            continue
        a, b = mk.logistik([liq[i] for i in latih], [1 if y[i] > 0 else 0 for i in latih])
        laju = sum(1 for i in latih if y[i] > 0) / len(latih)
        for i, f in enumerate(jumat):
            if f.year == th and y[i] is not None and liq[i] is not None:
                skor.append(liq[i])
                prob.append(mk.sigmoid(a + b * liq[i]))
                dasar.append(laju)
                idx.append(i)
    return skor, prob, dasar, idx


def main():
    rng = random.Random(BENIH)
    hari_ini = datetime.now(timezone.utc).date()
    fred, gagal = jl.ambil_fred()
    if gagal:
        sys.exit(f"FRED gagal: {gagal}")
    fred.pop("_cadangan", None)
    jumat = jl.jumat_dari(date.fromisoformat(jl.MULAI), hari_ini)
    liq = jl.deret_likuiditas(fred, jumat)["likuiditas"]
    status = mk._muat_status()
    status.setdefault("aset", {})
    for aset in ASET:
        harga = jl.harga_yahoo(f"{aset}-USD")
        y = mk.target(jumat, harga, H)
        skor, prob, dasar, idx = walk_forward(jumat, liq, y)
        ret = [y[i] for i in idx]
        naik = [1 if r > 0 else 0 for r in ret]
        ic = mk.spearman(skor, ret)
        p = uj.placebo_p(skor, ret, ic, 2000, rng)
        bs = sum((q - o) ** 2 for q, o in zip(prob, naik)) / len(naik)
        bs0 = sum((q - o) ** 2 for q, o in zip(dasar, naik)) / len(naik)
        per_th = {}
        for th in sorted({jumat[i].year for i in idx}):
            s = [a for a, i in zip(skor, idx) if jumat[i].year == th]
            r = [y[i] for i in idx if jumat[i].year == th]
            v = mk.spearman(s, r) if len(s) >= 20 else None
            if v is not None:
                per_th[th] = round(v, 3)
        pos = sum(1 for v in per_th.values() if v > 0)
        kel = {}
        for q, o in zip(prob, naik):
            bkt = "<45%" if q < .45 else "45-55%" if q < .55 else "55-65%" if q < .65 else ">=65%"
            kel.setdefault(bkt, []).append(o)
        keandalan = {b: f"terjadi {sum(v) / len(v) * 100:.0f}% (N={len(v)})"
                     for b, v in sorted(kel.items())}
        lolos = (ic > 0 and p < P_MAKS and 1 - bs / bs0 > 0
                 and pos >= math.ceil(PORSI_TAHUN * len(per_th)))
        hasil = {"versi": "likuiditas_saja" if lolos else None, "diadopsi": lolos,
                 "ic_oos": round(ic, 3), "p_placebo": round(p, 4),
                 "brier_skill": round(1 - bs / bs0, 3), "tahun_positif": f"{pos}/{len(per_th)}",
                 "ic_per_tahun": per_th, "keandalan": keandalan, "n_minggu_oos": len(idx),
                 "tahun_uji": f"{min(per_th)}-{max(per_th)}" if per_th else None,
                 "vonis": "LOLOS" if lolos else "TIDAK LOLOS"}
        status["aset"][aset] = {str(H): hasil}
        print(f"{aset}: IC {ic:+.3f} p {p:.4f} BrierSkill {1 - bs / bs0:+.3f} thn+ {pos}/"
              f"{len(per_th)} N={len(idx)} -> {hasil['vonis']}")
        print(f"     per tahun {per_th}")
        print(f"     keandalan {keandalan}")
    with open(mk.STATUS_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

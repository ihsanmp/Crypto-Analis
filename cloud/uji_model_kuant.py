"""Uji WALK-FORWARD model kuant (model_kuant.py) — DIDAFTARKAN SEBELUM DIJALANKAN (16 Okt 2026).

Prosedur, per horizon h (12 minggu utama, 4 minggu sekunder):
  - Tahun uji 2019..2026. Untuk tiap tahun Y, model DILATIH ULANG hanya dengan minggu yang
    targetnya sudah terwujud sebelum 1 Jan Y (jeda h minggu; tidak ada tumpang-tindih yang
    bocor). Bobot = IC Spearman tiap fitur di data latih; peluang = logistik di data latih.
  - Prediksi seluruh minggu tahun Y dengan model itu (out-of-sample, OOS).
  - Pembanding: skor Liquidity sendirian (tanpa bobot), peluangnya juga logistik walk-forward.

Ukuran (OOS, gabungan semua tahun uji):
  IC  = Spearman skor vs log-return h minggu.  p = placebo geser-melingkar 2.000x.
  Brier skill = 1 - Brier(model) / Brier(laju dasar data latih)  (>0 = lebih baik dari
  menebak laju dasar). Tahun positif = jumlah tahun uji dengan IC > 0.

KRITERIA ADOPSI (Bonferroni 2 horizon):
  A. IC > 0 dan p < 0,025      B. Brier skill > 0      C. IC > 0 di >= 5 dari 8 tahun
  D. IC gabungan >= IC Liquidity-saja
  A+B+C+D -> pakai "gabungan_ic".  Gabungan gagal tapi Liquidity-saja lolos A+B+C ->
  pakai "likuiditas_saja".  Keduanya gagal -> horizon itu TIDAK dipakai (tanpa peluang).

Hasil disimpan ke cloud/data/model_kuant_uji.json dan dibaca model_kuant.py.

    python cloud/uji_model_kuant.py [--placebo 2000]
"""
import argparse
import json
import os
import random
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_kuant as mk  # noqa: E402
import uji_jam_likuiditas as uj  # noqa: E402

TAHUN_UJI = tuple(range(2019, 2027))
BENIH = 20261016


def walk_forward(jumat, fit, y, h, hanya_likuiditas=False):
    skor, prob, dasar, idx, bobot_th = [], [], [], [], {}
    for th in TAHUN_UJI:
        awal = date(th, 1, 1)
        latih = mk.indeks_latih(jumat, y, awal, h)
        if len(latih) < 100:
            continue
        if hanya_likuiditas:
            pas = [(fit["likuiditas"][i], 1 if y[i] > 0 else 0) for i in latih
                   if fit["likuiditas"][i] is not None]
            a, b = mk.logistik(*zip(*pas))
            m = {"a": a, "b": b, "laju_dasar": sum(p[1] for p in pas) / len(pas),
                 "bobot": {"likuiditas": 1.0}}
        else:
            m = mk.latih(fit, y, latih)
            bobot_th[th] = m["bobot"]
        for i, f in enumerate(jumat):
            if f.year != th or y[i] is None:
                continue
            s = (fit["likuiditas"][i] if hanya_likuiditas else mk.gabung(fit, m["bobot"], i))
            if s is None:
                continue
            skor.append(s)
            prob.append(mk.peluang(m, s))
            dasar.append(m["laju_dasar"])
            idx.append(i)
    return skor, prob, dasar, idx, bobot_th


def nilai(nama, skor, prob, dasar, idx, y, jumat, rng, n_placebo):
    ret = [y[i] for i in idx]
    naik = [1 if r > 0 else 0 for r in ret]
    ic = mk.spearman(skor, ret)
    p = uj.placebo_p(skor, ret, ic, n_placebo, rng) if ic is not None else 1.0
    bs = sum((q - o) ** 2 for q, o in zip(prob, naik)) / len(naik)
    bs0 = sum((q - o) ** 2 for q, o in zip(dasar, naik)) / len(naik)
    per_th = {}
    for th in TAHUN_UJI:
        s = [a for a, i in zip(skor, idx) if jumat[i].year == th]
        r = [y[i] for i in idx if jumat[i].year == th]
        v = mk.spearman(s, r) if len(s) >= 20 else None
        if v is not None:
            per_th[th] = round(v, 3)
    hasil = {"ic_oos": round(ic, 3), "p_placebo": round(p, 4), "brier": round(bs, 4),
             "brier_laju_dasar": round(bs0, 4), "brier_skill": round(1 - bs / bs0, 3),
             "ic_per_tahun": per_th,
             "tahun_positif": f"{sum(1 for v in per_th.values() if v > 0)}/{len(per_th)}",
             "n_minggu_oos": len(skor)}
    # Keandalan: peluang yang diramal vs frekuensi naik yang terjadi
    kel = {}
    for q, o in zip(prob, naik):
        b = "<45%" if q < .45 else "45-55%" if q < .55 else "55-65%" if q < .65 else ">=65%"
        kel.setdefault(b, []).append(o)
    hasil["keandalan"] = {b: f"terjadi {sum(v) / len(v) * 100:.0f}% (N={len(v)})"
                          for b, v in sorted(kel.items())}
    print(f"  {nama:<16} IC={ic:+.3f} p={p:.4f} BrierSkill={hasil['brier_skill']:+.3f} "
          f"tahun+={hasil['tahun_positif']} N={len(skor)}")
    print(f"  {'':<16} per tahun {per_th}")
    print(f"  {'':<16} keandalan {hasil['keandalan']}")
    return hasil


def lolos_abc(h):
    pos, n = (int(x) for x in h["tahun_positif"].split("/"))
    return h["ic_oos"] > 0 and h["p_placebo"] < 0.025 and h["brier_skill"] > 0 and pos >= 5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placebo", type=int, default=2000)
    a = ap.parse_args()
    rng = random.Random(BENIH)
    jumat, harga, fit = mk.muat_data()
    cakupan = {k: next((f.isoformat() for f, v in zip(jumat, s) if v is not None), None)
               for k, s in fit.items()}
    print("Fitur mulai:", cakupan)
    keluar = {"diuji_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "cakupan_fitur": cakupan, "horizon": {}}
    for h in mk.HORIZON:
        print(f"\n== horizon {h} minggu ==")
        y = mk.target(jumat, harga, h)
        sg, pg, dg, ig, bobot_th = walk_forward(jumat, fit, y, h)
        g = nilai("gabungan_ic", sg, pg, dg, ig, y, jumat, rng, a.placebo)
        sl, pl, dl, il, _ = walk_forward(jumat, fit, y, h, hanya_likuiditas=True)
        lq = nilai("likuiditas_saja", sl, pl, dl, il, y, jumat, rng, a.placebo)
        rata_bobot = {k: round(sum(b[k] for b in bobot_th.values()) / len(bobot_th), 3)
                      for k in mk.FITUR}
        print("  rata-rata bobot (IC latih):", dict(sorted(rata_bobot.items(),
                                                          key=lambda t: -abs(t[1]))))
        if lolos_abc(g) and g["ic_oos"] >= lq["ic_oos"]:
            versi, vonis = "gabungan_ic", "LOLOS: gabungan IC dipakai"
        elif lolos_abc(lq):
            versi, vonis = "likuiditas_saja", ("gabungan TIDAK lolos (A-D); Liquidity-saja "
                                               "lolos A-C dan dipakai")
        else:
            versi, vonis = None, "TIDAK LOLOS: horizon ini tidak memberi peluang"
        print("  VONIS:", vonis)
        dipakai = {"gabungan_ic": g, "likuiditas_saja": lq}.get(versi, g)
        keluar["horizon"][str(h)] = {
            # Statistik di tingkat atas = milik versi yang DIPAKAI; keduanya disimpan utuh.
            **{k: dipakai[k] for k in ("ic_oos", "p_placebo", "brier_skill",
                                       "tahun_positif", "keandalan")},
            "ic_oos_gabungan": g["ic_oos"], "ic_oos_likuiditas": lq["ic_oos"],
            "gabungan_ic": g, "likuiditas_saja": lq, "rata_bobot_gabungan": rata_bobot,
            "diadopsi": versi is not None, "versi": versi, "vonis": vonis}
    with open(mk.STATUS_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(keluar, f, ensure_ascii=False, indent=1)
    print("\ndisimpan:", mk.STATUS_PATH)


if __name__ == "__main__":
    main()

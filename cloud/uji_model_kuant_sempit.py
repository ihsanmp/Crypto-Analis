"""Uji gabungan SEMPIT: Liquidity + SATU faktor — DIDAFTARKAN SEBELUM DIJALANKAN (16 Okt 2026).

Langkah 1 (uji_model_kuant.py): gabungan 12 sinyal GAGAL (overfit); Liquidity-saja lolos
12 minggu. Pertanyaan di sini: apakah SATU faktor tambahan menambah nilai di atas Liquidity?

KANDIDAT (dipilih dari literatur, BUKAN dari bobot langkah 1; tidak boleh ditambah sesudah
melihat hasil):
  mom_52      momentum deret waktu 12 bulan (Moskowitz-Ooi-Pedersen 2012)
  tren_200h   jarak harga ke rata-rata 200 hari (filter tren klasik)
  fear_greed  sentimen ritel (Fear & Greed, sejak 2018)

Metode = langkah 1 (bobot IC data latih, logistik, latih ulang per tahun 2019-2026, jeda =
horizon), fitur hanya {likuiditas, kandidat}. Pembanding: Liquidity-saja di minggu yang sama.

KRITERIA (3 kandidat x 2 horizon -> Bonferroni p < 0,05/6):
  12 minggu: IC > 0 & p < 0,0083; Brier skill > Brier skill Liquidity-saja (dan > 0);
             IC tahunan > IC tahunan Liquidity-saja di >= 6 dari 8 tahun.
  4 minggu : (Liquidity-saja gagal) IC > 0 & p < 0,0083; Brier skill > 0; IC > 0 di >= 5/8.
  Lebih dari satu lolos -> dipilih Brier skill tertinggi. Tidak ada yang lolos -> tetap.

    python cloud/uji_model_kuant_sempit.py [--placebo 2000]
"""
import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_kuant as mk  # noqa: E402
import uji_model_kuant as umk  # noqa: E402

KANDIDAT = ("mom_52", "tren_200h", "fear_greed")
P_MAKS = 0.05 / (len(KANDIDAT) * 2)
BENIH = 20261018


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placebo", type=int, default=2000)
    a = ap.parse_args()
    rng = random.Random(BENIH)
    jumat, harga, fit = mk.muat_data()
    status = mk._muat_status()
    keluar = {"diuji_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "p_maks": round(P_MAKS, 4), "horizon": {}}
    for h in mk.HORIZON:
        print(f"\n== horizon {h} minggu ==")
        y = mk.target(jumat, harga, h)
        sl, pl, dl, il, _ = umk.walk_forward(jumat, fit, y, h, hanya_likuiditas=True)
        lq = umk.nilai("likuiditas_saja", sl, pl, dl, il, y, jumat, rng, a.placebo)
        hasil_h = {"likuiditas_saja": lq, "kandidat": {}}
        lolos = []
        for k in KANDIDAT:
            sub = {"likuiditas": fit["likuiditas"], k: fit[k]}
            sg, pg, dg, ig, bobot = umk.walk_forward(jumat, sub, y, h)
            g = umk.nilai(f"liq+{k}", sg, pg, dg, ig, y, jumat, rng, a.placebo)
            pos, n = (int(x) for x in g["tahun_positif"].split("/"))
            kalah_menang = sum(1 for th, v in g["ic_per_tahun"].items()
                               if v > lq["ic_per_tahun"].get(th, float("-inf")))
            if h == 12:
                ok = (g["ic_oos"] > 0 and g["p_placebo"] < P_MAKS
                      and g["brier_skill"] > max(lq["brier_skill"], 0)
                      and kalah_menang >= 6)
            else:
                ok = (g["ic_oos"] > 0 and g["p_placebo"] < P_MAKS and g["brier_skill"] > 0
                      and pos >= 5)
            g["tahun_unggul_atas_likuiditas"] = f"{kalah_menang}/{len(g['ic_per_tahun'])}"
            g["rata_bobot"] = {f: round(sum(b[f] for b in bobot.values()) / len(bobot), 3)
                               for f in sub}
            g["lolos"] = ok
            print(f"  {'':<16} unggul atas Liquidity {g['tahun_unggul_atas_likuiditas']} tahun; "
                  f"bobot rata2 {g['rata_bobot']} -> {'LOLOS' if ok else 'tidak lolos'}")
            hasil_h["kandidat"][k] = g
            if ok:
                lolos.append((g["brier_skill"], k))
        pilih = max(lolos)[1] if lolos else None
        hasil_h["dipilih"] = pilih
        hasil_h["vonis"] = (f"LOLOS: likuiditas + {pilih}" if pilih else
                            "TIDAK ADA kandidat yang lolos — model tetap")
        print("  VONIS:", hasil_h["vonis"])
        keluar["horizon"][str(h)] = hasil_h
    status["gabungan_sempit"] = keluar
    with open(mk.STATUS_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

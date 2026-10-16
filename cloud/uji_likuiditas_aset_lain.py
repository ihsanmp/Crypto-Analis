"""Uji skor Liquidity pada S&P 500, Nasdaq-100, dan EMAS — DIDAFTARKAN SEBELUM DIJALANKAN
(16 Okt 2026).

Pertanyaan BARU (bukan pengulangan pada data BTC): apakah rezim likuiditas Fed/dolar/
kondisi keuangan juga memprediksi return 12 minggu kelas aset lain yang riwayatnya panjang?

  Hipotesis : likuiditas longgar (skor +) mendukung ketiganya — saham lewat biaya dana murah,
              emas lewat dolar & yield riil turun. Uji satu sisi: IC > 0.
  Skor      : skor Liquidity jam_likuiditas.py TANPA perubahan parameter; FRED ditarik sejak
              2006. KOREKSI sesudah dijalankan (kriteria TIDAK diubah): perkiraan "skor sejak
              ~2008" keliru — RRPONTSYD nyaris kosong sebelum 2013 (fasilitas belum dipakai),
              jadi L2 & skor baru ada sejak Okt 2014 dan tahun uji 2017-2026.
  Masuk     : penutupan hari bursa PERTAMA sesudah Jumat sinyal (pasar tutup akhir pekan);
              keluar: penutupan hari bursa pertama sesudah Jumat t + 12 minggu.
  Peluang   : logistik skor -> P(naik), dilatih ulang tiap tahun uji hanya dengan target yang
              sudah terwujud (jeda 12 minggu); tahun uji mulai saat latih >= 100 minggu.

KRITERIA (Bonferroni 3 aset): IC OOS > 0 dan p placebo < 0,0167; Brier skill > 0; IC > 0 di
>= 60% tahun uji. Lolos -> peluang aset itu boleh ditampilkan bot; gagal -> tidak.

    python cloud/uji_likuiditas_aset_lain.py
"""
import json
import math
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jam_likuiditas as jl  # noqa: E402
import model_kuant as mk  # noqa: E402
import uji_jam_likuiditas as uj  # noqa: E402

ASET = {"SPX": "^GSPC", "NDX": "^NDX", "EMAS": "GC=F"}
H = 12
MULAI_FRED = "2006-01-01"
P_MAKS = 0.05 / len(ASET)
PORSI_TAHUN = 0.6
BENIH = 20261019


def _harga_pertama_sesudah(harga, tgl, maks=6):
    for i in range(1, maks + 1):
        p = harga.get((tgl + timedelta(days=i)).isoformat())
        if p:
            return p
    return None


def target_pasar(jumat, harga, h=H):
    """log-return dari hari bursa pertama sesudah Jumat t ke hari bursa pertama sesudah t+h mg."""
    keluar = []
    for f in jumat:
        a = _harga_pertama_sesudah(harga, f)
        b = _harga_pertama_sesudah(harga, f + timedelta(days=7 * h))
        keluar.append(math.log(b / a) if a and b else None)
    return keluar


def walk_forward(jumat, liq, y):
    skor, prob, dasar, idx = [], [], [], []
    for th in range(2008, 2027):
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
    jl_simpan = jl._simpan_fred
    jl._simpan_fred = lambda data: None          # salinan cadangan bot tetap riwayat 2012
    try:
        fred, gagal = jl.ambil_fred(MULAI_FRED)
    finally:
        jl._simpan_fred = jl_simpan
    if gagal:
        sys.exit(f"FRED gagal: {gagal}")
    fred.pop("_cadangan", None)
    jumat = jl.jumat_dari(date.fromisoformat(MULAI_FRED), hari_ini)
    liq = jl.deret_likuiditas(fred, jumat)["likuiditas"]
    awal_skor = next(f for f, v in zip(jumat, liq) if v is not None)
    print(f"skor Liquidity tersedia sejak {awal_skor}")
    status = mk._muat_status()
    status.setdefault("aset_lain", {})
    for nama, sim in ASET.items():
        harga = jl.harga_yahoo(sim)
        y = target_pasar(jumat, harga)
        skor, prob, dasar, idx = walk_forward(jumat, liq, y)
        ret = [y[i] for i in idx]
        naik = [1 if r > 0 else 0 for r in ret]
        ic = mk.spearman(skor, ret)
        p = uj.placebo_p(skor, ret, ic, 2000, rng)
        bs = sum((q - o) ** 2 for q, o in zip(prob, naik)) / len(naik)
        bs0 = sum((q - o) ** 2 for q, o in zip(dasar, naik)) / len(naik)
        per_th = {}
        for th in sorted({jumat[i].year for i in idx}):
            s_ = [a for a, i in zip(skor, idx) if jumat[i].year == th]
            r_ = [y[i] for i in idx if jumat[i].year == th]
            v = mk.spearman(s_, r_) if len(s_) >= 20 else None
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
        status["aset_lain"][nama] = {str(H): {
            "simbol_yahoo": sim, "versi": "likuiditas_saja" if lolos else None,
            "diadopsi": lolos, "ic_oos": round(ic, 3), "p_placebo": round(p, 4),
            "brier_skill": round(1 - bs / bs0, 3), "tahun_positif": f"{pos}/{len(per_th)}",
            "ic_per_tahun": per_th, "keandalan": keandalan, "n_minggu_oos": len(idx),
            "tahun_uji": f"{min(per_th)}-{max(per_th)}", "vonis": "LOLOS" if lolos else "TIDAK LOLOS"}}
        print(f"\n{nama} ({sim}) {min(per_th)}-{max(per_th)}: IC {ic:+.3f} p {p:.4f} "
              f"BrierSkill {1 - bs / bs0:+.3f} thn+ {pos}/{len(per_th)} N={len(idx)} -> "
              f"{'LOLOS' if lolos else 'TIDAK LOLOS'}")
        print(f"   per tahun {per_th}")
        print(f"   keandalan {keandalan}")
    with open(mk.STATUS_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

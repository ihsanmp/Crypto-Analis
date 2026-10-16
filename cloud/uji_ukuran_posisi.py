"""Uji ukuran posisi berbasis VOLATILITAS — DIDAFTARKAN SEBELUM DIJALANKAN (16 Okt 2026).

Pertanyaan: apakah mengecilkan eksposur saat BTC bergejolak (dan membesarkannya saat tenang)
memperbaiki strategi eksposur Jam Likuiditas?

  Vol terealisasi : simpangan baku log-return harian 30 hari s/d Jumat t, x akar(365).
  Target vol      : MEDIAN vol terealisasi seluruh hari SEBELUM Jumat t (minimal 365 hari).
                    Tidak ada parameter yang disetel.
  A  Liquidity saja   : eksposur = 0,5 + 0,5 x skor (strategi sekarang).
  B  Volatilitas saja : eksposur = 0,5 x (target/vol), pengali dipotong [0, 2], hasil [0, 1].
  C  Gabungan         : eksposur = eksposur A x (target/vol), pengali [0, 2], hasil [0, 1].
  Semua: sinyal Jumat, masuk penutupan Sabtu, ubah hanya bila selisih >= 10 pp, biaya 0,15%
  per sisi x |perubahan|, filter resesi Sahm tetap berlaku (maks 50%).

KRITERIA ADOPSI: C dipakai bila Sharpe C > Sharpe A DAN maxDD C tidak lebih dalam dari A,
di periode penuh DAN di kedua paruh (2015-2020, 2021-2026). Selain itu tidak dipakai.
B dilaporkan deskriptif (apakah volatilitas sendirian sudah cukup).

    python cloud/uji_ukuran_posisi.py
"""
import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jam_likuiditas as jl  # noqa: E402
import uji_jam_likuiditas as uj  # noqa: E402

JENDELA_VOL = 30
RIWAYAT_MIN = 365
PENGALI_MAKS = 2.0
BIAYA = 0.0015
PARUH = (date(2015, 1, 1), date(2020, 12, 31)), (date(2021, 1, 1), date(2026, 12, 31))
HASIL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                          "ukuran_posisi_uji.json")


def vol_terealisasi(tutup, f, n=JENDELA_VOL):
    """Vol tahunan dari n log-return harian yang berakhir pada hari f. None bila bolong."""
    h = [tutup.get(f - timedelta(days=i)) for i in range(n + 1)]
    if any(x is None for x in h):
        return None
    r = [math.log(h[i] / h[i + 1]) for i in range(n)]
    m = sum(r) / n
    return math.sqrt(sum((x - m) ** 2 for x in r) / (n - 1)) * math.sqrt(365)


def deret_vol(tutup):
    """{hari: vol 30 hari} untuk semua hari yang lengkap."""
    hari = sorted(tutup)
    return {d: v for d in hari if (v := vol_terealisasi(tutup, d)) is not None}


def target_vol(vol_per_hari, f):
    """Median vol seluruh hari SEBELUM f (tanpa melihat masa depan)."""
    lalu = sorted(v for d, v in vol_per_hari.items() if d < f)
    if len(lalu) < RIWAYAT_MIN:
        return None
    return lalu[len(lalu) // 2]


def pengali(vol_per_hari, f):
    v, t = vol_per_hari.get(f), target_vol(vol_per_hari, f)
    if not v or not t:
        return None
    return max(0.0, min(PENGALI_MAKS, t / v))


def simulasi(jumat, target, tutup, awal, akhir, biaya=BIAYA):
    """Eksposur target[i] (0..1 atau None) -> metrik setelah biaya pada [awal, akhir]."""
    e_now, nilai, puncak, dd, ret, total_biaya, ubah = None, 1.0, 1.0, 0.0, [], 0.0, 0
    for f, t in zip(jumat, target):
        if t is None or not (awal <= f <= akhir):
            continue
        a, b = tutup.get(f + timedelta(days=1)), tutup.get(f + timedelta(days=8))
        if not a or not b:
            continue
        if e_now is None or abs(t - e_now) >= jl.AMBANG_UBAH:
            potong = abs(t - (e_now or 0.0)) * biaya
            nilai *= 1 - potong
            total_biaya += potong
            ubah += e_now is not None
            e_now = t
        r = e_now * (b / a - 1)
        nilai *= 1 + r
        ret.append(r)
        puncak = max(puncak, nilai)
        dd = min(dd, nilai / puncak - 1)
    if len(ret) < 52:
        return None
    th = len(ret) / 52
    mu = sum(ret) / len(ret)
    sd = math.sqrt(sum((x - mu) ** 2 for x in ret) / (len(ret) - 1))
    return {"cagr": round((nilai ** (1 / th) - 1) * 100, 1), "maxdd": round(dd * 100, 1),
            "sharpe": round(mu / sd * math.sqrt(52), 3), "ubah": ubah,
            "biaya_persen": round(total_biaya * 100, 1)}


def main():
    tutup = uj.muat_btc()
    akhir = max(tutup)
    fred, gagal = jl.ambil_fred()
    if gagal:
        sys.exit(f"FRED gagal: {gagal}")
    fred.pop("_cadangan", None)
    jumat = jl.jumat_dari(date.fromisoformat(jl.MULAI), akhir)
    L = jl.deret_likuiditas(fred, jumat)
    vol = deret_vol(tutup)
    k = [pengali(vol, f) for f in jumat]
    varian = {}
    a_, b_, c_ = [], [], []
    for s, rs, p in zip(L["likuiditas"], L["resesi"], k):
        ea = jl.eksposur(s, None, rs) if s is not None else None
        a_.append(ea)
        b_.append(None if p is None else min(min(1.0, 0.5 * p), jl.BATAS_RESESI if rs else 1.0))
        c_.append(None if ea is None or p is None
                  else min(min(1.0, ea * p), jl.BATAS_RESESI if rs else 1.0))
    # Semua varian dinilai pada minggu yang SAMA (yang ketiganya punya nilai).
    sama = [a is not None and b is not None and c is not None for a, b, c in zip(a_, b_, c_)]
    for nama, t in (("A_likuiditas", a_), ("B_volatilitas", b_), ("C_gabungan", c_),
                    ("beli_tahan", [1.0] * len(jumat)), ("tetap_50", [0.5] * len(jumat))):
        t = [x if ok else None for x, ok in zip(t, sama)]
        varian[nama] = {"penuh": simulasi(jumat, t, tutup, uj.MULAI_UJI, akhir)}
        for i, (aw, ak) in enumerate(PARUH, 1):
            varian[nama][f"paruh_{i}"] = simulasi(jumat, t, tutup, aw, min(ak, akhir))
    print("varian            periode    CAGR    maxDD  Sharpe  ubah biaya")
    for nama, per in varian.items():
        for p, m in per.items():
            if m:
                print(f"{nama:<17} {p:<9} {m['cagr']:6.1f}% {m['maxdd']:6.1f}% {m['sharpe']:6.3f} "
                      f"{m['ubah']:5d} {m['biaya_persen']:4.1f}%")

    def unggul(p):
        a, c = varian["A_likuiditas"][p], varian["C_gabungan"][p]
        return a and c and c["sharpe"] > a["sharpe"] and c["maxdd"] >= a["maxdd"]
    lolos = all(unggul(p) for p in ("penuh", "paruh_1", "paruh_2"))
    vonis = ("LOLOS: pengali volatilitas dipakai di target eksposur" if lolos else
             "TIDAK LOLOS: pengali volatilitas TIDAK dipakai")
    print("\nVONIS:", vonis)
    with open(HASIL_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"diuji_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "varian": varian, "diadopsi": lolos, "vonis": vonis}, f,
                  ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

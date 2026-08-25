"""Menguji metode sebaran proyeksi.py — puncak & dasar yang tercapai, bukan harga penutup.

KENAPA ADA. uji_timesfm.py menemukan bahwa sebaran empiris kalah dari jalan acak sederhana
pada harga PENUTUP di ketiga aset. proyeksi.py memakai pendekatan yang sama, tapi mengukur
hal yang BERBEDA: puncak dan dasar yang TERCAPAI di dalam jendela, bukan di mana harga
berakhir. Temuan itu karena itu belum otomatis berlaku — dan menganggapnya berlaku adalah
persis lompatan yang harus dihindari.

Berkas ini menguji yang sebenarnya dipakai. Blok OUTLOOK dan tabel kelayakan berdiri di
atas angka ini, jadi kalau metodenya kalah, keduanya perlu diperbaiki.

TIGA METODE:
  baserate  — sebaran empiris puncak/dasar dari jendela historis sebelum titik asal.
              Ini yang dipakai proyeksi.py sekarang.
  gauss     — jalan acak, kuantil maksimum lewat asas pantulan (reflection principle):
              maks q-kuantil = sigma*akar(T) * PPF((1+q)/2). Satu rumus, tanpa riwayat
              panjang.
  bootstrap — resampling imbal hasil harian dari konteks, lalu diambil maks/min tiap
              lintasan. Mempertahankan ekor tebal yang gauss buang, tapi memutus urutan
              historis yang membuat baserate terpaku pada satu jalan yang kebetulan terjadi.

Diukur pada IMBAL HASIL, bukan harga, supaya angkanya sebanding antar-aset.

Pemakaian:
    python cloud/uji_sebaran.py --aset BTC-USD,ETH-USD,SOL-USD --horizon 60
"""

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

KUANTIL = (0.1, 0.25, 0.5, 0.75, 0.9)
KONTEKS = 512
LANGKAH = 7
LINTASAN = 1000        # jumlah lintasan bootstrap per titik asal


def _ppf(p):
    return statistics.NormalDist().inv_cdf(p)


def _kuantil(nilai, q):
    if not nilai:
        return None
    s = sorted(nilai)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    b = int(pos)
    if b + 1 >= len(s):
        return s[-1]
    return s[b] + (pos - b) * (s[b + 1] - s[b])


def pinball(aktual, ramalan, q):
    d = aktual - ramalan
    return q * d if d >= 0 else (q - 1) * d


def _ekstrem_historis(konteks, horizon):
    """(daftar puncak, daftar dasar) dalam imbal hasil, dari jendela di dalam konteks."""
    puncak, dasar = [], []
    for i in range(len(konteks) - horizon):
        awal = konteks[i]
        if not awal:
            continue
        jendela = konteks[i + 1:i + 1 + horizon]
        if not jendela:
            continue
        puncak.append(max(jendela) / awal - 1.0)
        dasar.append(min(jendela) / awal - 1.0)
    return puncak, dasar


def ramal_baserate(konteks, horizon):
    """Yang dipakai proyeksi.py: kuantil empiris puncak/dasar dari riwayat sebelum titik asal."""
    puncak, dasar = _ekstrem_historis(konteks, horizon)
    if len(puncak) < 30:
        return None
    return {"puncak": {q: _kuantil(puncak, q) for q in KUANTIL},
            "dasar": {q: _kuantil(dasar, q) for q in KUANTIL}}


def _sigma(konteks):
    log = [__import__("math").log(konteks[i + 1] / konteks[i])
           for i in range(len(konteks) - 1) if konteks[i] and konteks[i + 1]]
    return statistics.pstdev(log) if len(log) > 2 else None


def ramal_gauss(konteks, horizon):
    """Asas pantulan: maks jalan acak tanpa hanyutan punya kuantil sigma*akar(T)*PPF((1+q)/2).

    Tidak butuh riwayat panjang — hanya volatilitas harian. Kalau ini menang, sebagian besar
    isi sebaran empiris ternyata cuma volatilitas yang ditulis panjang.
    """
    import math
    s = _sigma(konteks)
    if not s:
        return None
    lebar = s * (horizon ** 0.5)
    puncak = {q: math.exp(lebar * _ppf((1 + q) / 2)) - 1.0 for q in KUANTIL}
    dasar = {q: math.exp(-lebar * _ppf(1 - q / 2)) - 1.0 for q in KUANTIL}
    return {"puncak": puncak, "dasar": dasar}


def ramal_bootstrap(konteks, horizon, lintasan=LINTASAN, rng=None):
    """Resampling imbal hasil harian: mempertahankan ekor tebal, memutus urutan historis.

    Divektorkan numpy. Versi Python murni butuh ~80 juta pengambilan acak untuk evaluasi
    penuh tiga aset — cukup lambat untuk membuat ujinya tidak pernah dijalankan, dan uji
    yang tidak dijalankan sama saja dengan tidak ada.
    """
    import math

    import numpy as np
    log = np.diff(np.log(np.asarray(konteks, dtype=np.float64)))
    log = log[np.isfinite(log)]
    if log.size < 60:
        return None
    gen = rng if isinstance(rng, np.random.Generator) else np.random.default_rng(7)
    idx = gen.integers(0, log.size, size=(lintasan, horizon))
    jalan = np.cumsum(log[idx], axis=1)
    # Puncak/dasar TIDAK BOLEH melewati nol: harga di hari ke-0 adalah titik acuannya,
    # jadi maksimum minimal 0 dan minimum maksimal 0. Tanpa penjepitan ini, jendela yang
    # bergerak satu arah menghasilkan "dasar" positif — mustahil menurut definisinya.
    hi = np.exp(np.clip(jalan.max(axis=1), 0, None)) - 1.0
    lo = np.exp(np.clip(jalan.min(axis=1), None, 0)) - 1.0
    return {"puncak": {q: float(np.quantile(hi, q)) for q in KUANTIL},
            "dasar": {q: float(np.quantile(lo, q)) for q in KUANTIL}}


def evaluasi(simbol, horizon, lintasan=LINTASAN, batas_asal=None):
    from market import tarik
    c, _, err = tarik(simbol, "10y", "1d")
    if err or not c:
        return {"simbol": simbol, "tidak_tersedia": err or "kosong"}
    harga = [b[4] for b in c if b[4]]
    if len(harga) < KONTEKS + horizon + 10:
        return {"simbol": simbol,
                "tidak_tersedia": f"riwayat {len(harga)} titik, butuh "
                                  f"{KONTEKS + horizon + 10}"}

    import numpy as np
    rng = np.random.default_rng(7)
    asal = list(range(KONTEKS, len(harga) - horizon, LANGKAH))
    if batas_asal:
        asal = asal[-batas_asal:]

    skor = {n: {"puncak": [], "dasar": []} for n in ("baserate", "gauss", "bootstrap")}
    cakup = {n: {"puncak": 0, "dasar": 0} for n in skor}
    n_pakai = 0

    for a in asal:
        konteks = harga[a - KONTEKS:a]
        awal = harga[a - 1]
        depan = harga[a:a + horizon]
        if not awal or not depan:
            continue
        nyata = {"puncak": max(depan) / awal - 1.0, "dasar": min(depan) / awal - 1.0}

        ramal = {"baserate": ramal_baserate(konteks, horizon),
                 "gauss": ramal_gauss(konteks, horizon),
                 "bootstrap": ramal_bootstrap(konteks, horizon, lintasan, rng)}
        if not all(ramal.values()):
            continue
        n_pakai += 1
        for nama, r in ramal.items():
            for sisi in ("puncak", "dasar"):
                skor[nama][sisi].append(
                    statistics.fmean(pinball(nyata[sisi], r[sisi][q], q) for q in KUANTIL))
                if r[sisi][0.1] <= nyata[sisi] <= r[sisi][0.9]:
                    cakup[nama][sisi] += 1

    hasil = {"simbol": simbol, "horizon_hari": horizon, "titik_asal": n_pakai,
             "riwayat_titik": len(harga), "metode": {}}
    for nama in skor:
        if not skor[nama]["puncak"]:
            continue
        hasil["metode"][nama] = {
            sisi: {"pinball": round(statistics.fmean(skor[nama][sisi]) * 100, 3),
                   "cakupan_persen": round(cakup[nama][sisi] / n_pakai * 100, 1)}
            for sisi in ("puncak", "dasar")
        }
    return hasil


def vonis(semua):
    """baserate harus menang, atau proyeksi.py yang perlu diperbaiki."""
    rinci, kalah = {}, []
    for h in semua:
        m = h.get("metode") or {}
        if "baserate" not in m:
            continue
        for sisi in ("puncak", "dasar"):
            pes = {n: m[n][sisi]["pinball"] for n in m}
            terbaik = min(pes, key=pes.get)
            rinci[f"{h['simbol']}/{sisi}"] = {
                "terbaik": terbaik,
                "baserate": pes.get("baserate"),
                "selisih_persen": round(
                    (pes["baserate"] - pes[terbaik]) / pes[terbaik] * 100, 1)
                if pes.get(terbaik) else None,
            }
            if terbaik != "baserate":
                kalah.append(f"{h['simbol']}/{sisi}")
    return {
        "baserate_kalah_di": kalah,
        "rinci": rinci,
        "kesimpulan": (
            "baserate (metode proyeksi.py) menang di semua — pertahankan" if not kalah else
            f"baserate KALAH di {len(kalah)} dari {len(rinci)} pengukuran — "
            "blok OUTLOOK dan tabel kelayakan perlu diperbaiki"),
        "cara_baca": (
            "Pinball dalam POIN PERSEN imbal hasil, jadi sebanding antar-aset. Lebih kecil "
            "lebih baik. Dibaca per SISI: puncak dan dasar bisa berbeda pemenangnya, dan "
            "itu penting — target diambil dari sisi puncak, invalidasi dari sisi dasar."),
    }


def main():
    p = argparse.ArgumentParser(description="Uji metode sebaran puncak/dasar proyeksi.py")
    p.add_argument("--aset", default="BTC-USD,ETH-USD,SOL-USD")
    p.add_argument("--horizon", type=int, default=60)
    p.add_argument("--lintasan", type=int, default=LINTASAN)
    p.add_argument("--batas-asal", type=int, default=0)
    a = p.parse_args()
    semua = []
    for sim in [s.strip() for s in a.aset.split(",") if s.strip()]:
        print(f"[uji] {sim} ...", file=sys.stderr)
        semua.append(evaluasi(sim, a.horizon, a.lintasan, a.batas_asal or None))
    print(json.dumps({
        "diuji_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "horizon_hari": a.horizon, "lintasan_bootstrap": a.lintasan,
        "hasil": semua, "vonis": vonis(semua)}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

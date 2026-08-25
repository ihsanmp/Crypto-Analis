"""Menguji TimesFM terhadap base rate — sebelum satu barisnya masuk jalur produksi.

PERTANYAANNYA BUKAN "apakah TimesFM bagus", melainkan "apakah ia MENGUNGGULI apa yang
sudah kita punya". proyeksi.py sudah memberi sebaran empiris gerakan h-hari dari riwayat.
Untuk deret yang mendekati jalan acak, base rate seperti itu sering sudah mendekati
optimal — jadi model 200 juta parameter harus membuktikan dirinya, bukan diasumsikan.

Kalau dipasang tanpa uji ini, kita menambahkan tepat satu hal yang berbulan-bulan
dihabiskan untuk dihapus dari bot ini: angka yang terdengar yakin tanpa bisa diperiksa.

CARA MENGUJI. Walk-forward: di tiap titik asal, ketiga metode HANYA melihat data sebelum
titik itu, lalu meramal h hari ke depan. Hasil sebenarnya dibandingkan terhadap ramalan.

TIGA METODE YANG DIADU:
  timesfm   — model fondasi, kuantil p10..p90 langsung dari modelnya
  baserate  — sebaran empiris gerakan h-hari dari riwayat sebelum titik asal.
              Ini padanan proyeksi.py, dan inilah pembanding yang sebenarnya.
  gauss     — jalan acak dengan interval +-z*sigma*sqrt(h). Pembanding paling murah;
              kalau TimesFM tidak mengalahkan ini pun, tidak ada yang perlu dibahas.

DUA UKURAN YANG MENENTUKAN:
  pinball   — skor kuantil yang benar. Menghukum interval yang meleset DAN yang
              kelewat lebar sekaligus, jadi tidak bisa dicurangi dengan melebarkan
              interval sampai selalu "benar". Makin kecil makin baik.
  cakupan   — berapa persen hasil sebenarnya jatuh di dalam p10-p90. Targetnya 80%.
              95% berarti intervalnya terlalu lebar untuk berguna; 50% berarti
              modelnya terlalu percaya diri. Cakupan SENDIRIAN bisa menyesatkan —
              interval selebar samudra selalu mencapai 100% — jadi selalu dibaca
              bersama lebar rata-ratanya.

Pemakaian:
    python cloud/uji_timesfm.py --aset BTC-USD,ETH-USD --horizon 30
"""

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

KUANTIL = (0.1, 0.5, 0.9)
KONTEKS = 512          # titik riwayat yang dilihat tiap metode
LANGKAH = 7            # titik asal tiap pekan; harian membuat sampelnya nyaris kembar
MODEL_HF = "google/timesfm-2.5-200m-pytorch"


def deret_harga(simbol, rentang="10y"):
    """Penutupan harian dari Yahoo — sumber yang sama dengan sebab.py, riwayatnya panjang."""
    from market import tarik
    c, _, err = tarik(simbol, rentang, "1d")
    if err or not c:
        return [], err or "kosong"
    return [b[4] for b in c if b[4]], None


def pinball(aktual, ramalan, q):
    """Skor kuantil. Menghukum meleset ke bawah dan ke atas dengan bobot berbeda."""
    d = aktual - ramalan
    return q * d if d >= 0 else (q - 1) * d


def _kuantil(nilai, q):
    """Persentil linear. statistics.quantiles butuh n>=2 dan indeks tetap, ini lebih lentur."""
    if not nilai:
        return None
    s = sorted(nilai)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    bawah = int(pos)
    sisa = pos - bawah
    if bawah + 1 >= len(s):
        return s[-1]
    return s[bawah] + sisa * (s[bawah + 1] - s[bawah])


def ramal_baserate(konteks, horizon):
    """Sebaran empiris gerakan `horizon` hari dari riwayat SEBELUM titik asal.

    Ini padanan proyeksi.py. Tidak ada satu pun titik setelah titik asal yang dilihat —
    kalau bocor, seluruh perbandingan jadi tidak berarti.
    """
    if len(konteks) <= horizon + 2:
        return None
    gerak = [konteks[i + horizon] / konteks[i] - 1.0
             for i in range(len(konteks) - horizon)]
    akhir = konteks[-1]
    return {q: akhir * (1 + _kuantil(gerak, q)) for q in KUANTIL}


def ramal_gauss(konteks, horizon):
    """Jalan acak: median = harga terakhir, lebar dari volatilitas harian."""
    if len(konteks) < 30:
        return None
    imbal = [konteks[i + 1] / konteks[i] - 1.0 for i in range(len(konteks) - 1)]
    sigma = statistics.pstdev(imbal)
    if sigma == 0:
        return None
    akhir = konteks[-1]
    lebar = sigma * (horizon ** 0.5)
    Z = {0.1: -1.2816, 0.5: 0.0, 0.9: 1.2816}
    return {q: akhir * (1 + Z[q] * lebar) for q in KUANTIL}


def muat_timesfm(horizon):
    """Muat model sekali. Impor ditunda supaya modul ini tetap bisa diimpor tanpa torch."""
    import timesfm
    import torch
    torch.set_float32_matmul_precision("high")
    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(MODEL_HF)
    model.compile(timesfm.ForecastConfig(
        max_context=KONTEKS,
        max_horizon=max(horizon, 32),
        normalize_inputs=True,
        use_continuous_quantile_head=True,
        force_flip_invariance=True,
        infer_is_positive=True,
        fix_quantile_crossing=True,
    ))
    return model


def evaluasi(simbol, horizon, model=None, batas_asal=None):
    harga, err = deret_harga(simbol)
    if err:
        return {"simbol": simbol, "tidak_tersedia": err}
    if len(harga) < KONTEKS + horizon + 10:
        return {"simbol": simbol,
                "tidak_tersedia": f"riwayat {len(harga)} titik, butuh minimal "
                                  f"{KONTEKS + horizon + 10}"}

    asal = list(range(KONTEKS, len(harga) - horizon, LANGKAH))
    if batas_asal:
        asal = asal[-batas_asal:]
    konteks = [harga[a - KONTEKS:a] for a in asal]
    aktual = [harga[a + horizon - 1] for a in asal]

    ramal = {"baserate": [], "gauss": []}
    for k in konteks:
        ramal["baserate"].append(ramal_baserate(k, horizon))
        ramal["gauss"].append(ramal_gauss(k, horizon))

    if model is not None:
        import numpy as np
        ramal["timesfm"] = []
        # Dipotong per 32 supaya jejak memorinya rata; runner Actions cuma 7 GB.
        for i in range(0, len(konteks), 32):
            potong = [np.asarray(k, dtype=np.float32) for k in konteks[i:i + 32]]
            _titik, kuant = model.forecast(horizon=horizon, inputs=potong)
            for baris in kuant:
                # (horizon, 10): kolom 0 mean, lalu p10..p90. Titik terakhir horizon.
                akhir = baris[horizon - 1]
                ramal["timesfm"].append({0.1: float(akhir[1]),
                                         0.5: float(akhir[5]),
                                         0.9: float(akhir[9])})

    hasil = {"simbol": simbol, "horizon_hari": horizon, "konteks": KONTEKS,
             "titik_asal": len(asal), "riwayat_titik": len(harga), "metode": {}}
    for nama, daftar in ramal.items():
        pas = [(a, r) for a, r in zip(aktual, daftar) if r]
        if not pas:
            continue
        skor = statistics.fmean(
            statistics.fmean(pinball(a, r[q], q) for q in KUANTIL) for a, r in pas)
        dalam = sum(1 for a, r in pas if r[0.1] <= a <= r[0.9])
        lebar = statistics.fmean((r[0.9] - r[0.1]) / r[0.5] * 100
                                 for a, r in pas if r[0.5])
        hasil["metode"][nama] = {
            "pinball": round(skor, 2),
            "cakupan_persen": round(dalam / len(pas) * 100, 1),
            "lebar_interval_persen": round(lebar, 1),
            "n": len(pas),
        }
    return hasil


def vonis(semua):
    """Menang hanya kalau pinball lebih kecil daripada KEDUA pembanding.

    Versi pertama hanya membandingkan terhadap baserate, dan itu cacat: gauss sengaja
    dipasang sebagai "pembanding termurah — kalau tidak mengalahkan ini pun tidak ada yang
    perlu dibahas", lalu tidak ikut divonis sama sekali. Hasilnya harness menulis "layak
    dipertimbangkan" untuk model yang KALAH dari jalan acak di ketiga aset.

    Mengalahkan pembanding yang lemah bukan kemenangan kalau pembanding yang kuat ada di
    meja yang sama.
    """
    menang, kalah, lewat = [], [], []
    rinci = {}
    for h in semua:
        m = h.get("metode") or {}
        if "timesfm" not in m:
            lewat.append(h["simbol"])
            continue
        t = m["timesfm"]["pinball"]
        pesaing = {n: m[n]["pinball"] for n in ("baserate", "gauss") if n in m}
        if not pesaing:
            lewat.append(h["simbol"])
            continue
        terbaik = min(pesaing, key=pesaing.get)
        rinci[h["simbol"]] = {
            "timesfm": t,
            "pembanding_terbaik": terbaik,
            "pinball_pembanding": pesaing[terbaik],
            "selisih_persen": round((t - pesaing[terbaik]) / pesaing[terbaik] * 100, 1),
            "cakupan_timesfm": m["timesfm"]["cakupan_persen"],
        }
        (menang if t < pesaing[terbaik] else kalah).append(h["simbol"])

    if not menang and not kalah:
        kesimpulan = ("BELUM DIUJI — model tidak berhasil dimuat atau riwayatnya kurang. "
                      "Ini BUKAN vonis kalah; jangan dibaca sebagai bukti apa pun.")
    elif not kalah:
        kesimpulan = "TimesFM mengungguli SELURUH pembanding — layak dipertimbangkan"
    elif not menang:
        kesimpulan = ("TimesFM KALAH dari pembanding terbaik di semua aset — jangan "
                      "dipasang ke produksi")
    else:
        kesimpulan = (f"Campur: menang di {len(menang)}, kalah di {len(kalah)}. Belum "
                      "cukup untuk membenarkan biayanya.")
    return {
        "menang_atas_pembanding_terbaik": menang,
        "kalah_dari_pembanding_terbaik": kalah,
        "tidak_diuji": lewat,
        "rinci": rinci,
        "kesimpulan": kesimpulan,
        "cara_baca": (
            "Pinball lebih kecil = lebih baik; ia menghukum interval yang meleset DAN yang "
            "kelewat lebar, jadi tidak bisa dicurangi dengan melebarkan interval. Cakupan "
            "dibaca BERSAMA lebar interval: cakupan 100% dengan interval dua kali lebih "
            "lebar bukan kemenangan, itu cuma pengakuan tidak tahu yang ditulis lebih "
            "panjang. Cakupan JAUH DI BAWAH 80% berarti modelnya terlalu percaya diri — "
            "intervalnya terlalu sempit untuk sesering itu meleset."),
    }


def main():
    p = argparse.ArgumentParser(description="Uji TimesFM vs base rate")
    p.add_argument("--aset", default="BTC-USD,ETH-USD,SOL-USD")
    p.add_argument("--horizon", type=int, default=30)
    p.add_argument("--tanpa-model", action="store_true",
                   help="jalankan pembanding saja, tanpa memuat TimesFM")
    p.add_argument("--batas-asal", type=int, default=0,
                   help="pakai N titik asal terakhir saja (untuk uji cepat)")
    a = p.parse_args()

    model = None
    catatan = None
    if not a.tanpa_model:
        try:
            model = muat_timesfm(a.horizon)
        except Exception as e:
            catatan = f"TimesFM tidak bisa dimuat: {type(e).__name__}: {e}"
            print(f"[uji] {catatan}", file=sys.stderr)

    semua = []
    for sim in [s.strip() for s in a.aset.split(",") if s.strip()]:
        print(f"[uji] {sim} ...", file=sys.stderr)
        semua.append(evaluasi(sim, a.horizon, model, a.batas_asal or None))

    keluar = {"diuji_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
              "horizon_hari": a.horizon, "hasil": semua, "vonis": vonis(semua)}
    if catatan:
        keluar["catatan"] = catatan
    print(json.dumps(keluar, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

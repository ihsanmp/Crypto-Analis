"""Liquidity & Adoption Clock — filter rezim mingguan untuk BTC (rancangan user, 15 Okt 2026).

Dua "jam" dari catatan mentor diubah menjadi skor -1..+1:

  LIQUIDITY  L1 yield 2 tahun (DGS2, tanda -)          perubahan 4 minggu
             L2 likuiditas bersih Fed = WALCL - TGA (WDTGAL) - reverse repo (RRPONTSYD)
             L3 dolar luas (log DTWEXBGS, tanda -)
             L4 kondisi keuangan (NFCI, tanda -)
             L5 filter resesi: SAHMREALTIME >= 0,5 -> eksposur maks 50% (override, bukan skor)
  ADOPSI     A1 arus ETF spot 20 hari bursa / total aset ETF
  STRUKTURAL A2 persentase hari arus positif dalam 20 hari bursa
             A3 (13F) dan A4 (treasury korporasi) BELUM ada sumbernya -> skor PARSIAL.
             Skor Gelombang (funding, sentimen) belum dibangun, sesuai catatan rancangan.

Skor tiap komponen: perubahan k minggu -> z-score bergulir yang HANYA memakai minggu
sebelumnya -> dipotong +-3 -> tanh(z/2). Skor Liquidity = rata-rata L1..L4, KOSONG kalau
satu komponen hilang (tidak diam-diam dihitung dari sisanya). Jarum jam = atan2(momentum
4 minggu, posisi). Target eksposur = 0,5 + 0,5 x skor gabungan, long-only, 0..100%.

POINT-IN-TIME. Setiap titik FRED diberi tanggal KETERSEDIAAN (tanggal ukur + jeda rilis
konservatif, lihat JEDA_RILIS), lalu sinyal Jumat hanya memakai titik yang sudah tersedia.
Revisi data (ALFRED) tidak dipakai: ALFRED tidak terjangkau dari jaringan pengembang, dan
WALCL/WDTGAL/RRP/DGS2 praktis tidak direvisi — NFCI direvisi tiap minggu, itu batasnya.

Sumber FRED lewat makro.ambil (fredgraph.csv publik, TANPA API key). Arus ETF lewat
sosovalue.historis_etf (~300 hari bursa terakhir; cukup untuk adopsi, tidak untuk uji).

STATUS BUKTI dicatat di STATUS_BUKTI — diisi dari uji_jam_likuiditas.py, bukan dari teori.

Pemakaian:
    python cloud/jam_likuiditas.py            # JSON lengkap
    python cloud/jam_likuiditas.py --ringkas  # untuk brief bot
"""
import argparse
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MULAI = "2012-01-01"        # cukup untuk lookback 104 minggu sebelum uji 2015
K_MINGGU = 4
LOOKBACK = 104
MIN_RIWAYAT = 52
LOOKBACK_ADOPSI = 104       # riwayat ETF pendek: pakai semua minggu yang ada, ...
MIN_ADOPSI = 26             # ... minimal setengah tahun
AMBANG_RESESI = 0.5
BATAS_RESESI = 0.5
AMBANG_UBAH = 0.10          # eksposur hanya diubah kalau selisihnya >= 10 poin persen

# Jeda tanggal-ukur -> tanggal-tersedia (hari kalender), dibuat KONSERVATIF.
JEDA_RILIS = {
    "WALCL": 1,          # Rabu, rilis H.4.1 Kamis sore
    "WDTGAL": 1,         # idem
    "RRPONTSYD": 1,      # harian, rilis sore hari yang sama
    "DGS2": 1,           # harian, hari kerja berikutnya
    "DTWEXBGS": 10,      # H.10 rilis Senin untuk minggu SEBELUMNYA
    "NFCI": 5,           # minggu yang berakhir Jumat, rilis Rabu berikutnya
    "SAHMREALTIME": 40,  # bertanggal tgl 1, rilis setelah laporan kerja bulan berikutnya
}
SERI = tuple(JEDA_RILIS)

# Diisi dari uji_jam_likuiditas.py (BTC 2015-2026). Lihat cloud/data/jam_likuiditas.md.
STATUS_BUKTI = (
    "Skor Liquidity TERUJI pada BTC 2015-2026 (609 minggu, pra-registrasi): IC Spearman vs "
    "return 12 minggu +0,33, p placebo geser-melingkar < 0,001, lolos Bonferroni, positif di "
    "kedua era (2015-20 +0,29 / 2021-26 +0,35), tetap lolos tanpa NFCI yang direvisi "
    "(+0,28). Horizon 4 minggu TIDAK lolos (IC +0,05), 8 minggu nyaris (+0,22, p 0,02). "
    "MOMENTUM jarum TIDAK mendukung rancangan: 'ketat mulai membaik' justru kuadran "
    "terburuk. Satu rezim 11,7 tahun ~ 50 jendela 12 minggu independen — kuat, bukan "
    "kepastian. Skor Adopsi: BELUM DIUJI (ETF baru sejak Jan 2024).")

# Hasil uji_jam_likuiditas.py — return BTC 12 minggu sesudah sinyal, 2015-2026. Sumber
# KEBENARAN untuk arti kuadran; teks rancangan disimpan hanya untuk dibandingkan.
TERUKUR_KUADRAN_12MG = {
    "LONGGAR, MULAI MELAMBAT": "median +32,2%, naik 78% dari 102 minggu",
    "LONGGAR & MAKIN LONGGAR": "median +17,2%, naik 66% dari 199 minggu",
    "KETAT & MAKIN KETAT": "median -0,2%, naik 50% dari 204 minggu",
    "KETAT, MULAI MEMBAIK": ("median -7,5%, naik 40% dari 92 minggu — rancangan menyebutnya "
                             "titik balik terbaik, data MENOLAKNYA: ini yang terburuk"),
}
TERUKUR_TERSIL_12MG = (
    (-0.09, "RENDAH (skor <= -0,09): median -5,8%, naik 41%"),
    (0.11, "TENGAH (-0,09..+0,11): median +8,0%, naik 57%"),
    (None, "TINGGI (skor > +0,11): median +25,4%, naik 77%"),
)


# ------------------------------------------------------------------ data
def ambil_fred(mulai=MULAI):
    """{kode: [(tanggal_tersedia, nilai), ...]} atau error per kode."""
    import makro

    def satu(kode):
        # makro.ambil merangkai id ke URL fredgraph; cosd memotong riwayat sejak `mulai`.
        data, err = makro.ambil(f"{kode}&cosd={mulai}")
        if err:
            return kode, None, err
        jeda = timedelta(days=JEDA_RILIS[kode])
        return kode, [(date.fromisoformat(t) + jeda, v) for t, v in data], None

    keluar, gagal = {}, {}
    with ThreadPoolExecutor(len(SERI)) as ex:
        for kode, data, err in ex.map(satu, SERI):
            if err:
                gagal[kode] = err
            else:
                keluar[kode] = data
    return keluar, gagal


def jumat_dari(awal, akhir):
    d = awal + timedelta(days=(4 - awal.weekday()) % 7)
    keluar = []
    while d <= akhir:
        keluar.append(d)
        d += timedelta(days=7)
    return keluar


def ke_mingguan(titik, jumat, maks_basi=21):
    """Nilai terakhir yang SUDAH tersedia pada tiap Jumat. None kalau terlalu basi."""
    keluar, i, terakhir = [], 0, None
    for f in jumat:
        while i < len(titik) and titik[i][0] <= f:
            terakhir = titik[i]
            i += 1
        ok = terakhir is not None and (f - terakhir[0]).days <= maks_basi
        keluar.append(terakhir[1] if ok else None)
    return keluar


# ------------------------------------------------------------------ skor
def skor(x, k=K_MINGGU, lookback=LOOKBACK, min_riwayat=MIN_RIWAYAT, tanda=1):
    """Perubahan k minggu -> z bergulir (hanya masa lalu) -> tanh(clip(z,+-3)/2) x tanda.
    k=0: level dipakai langsung (untuk besaran yang sudah berupa aliran, mis. A1)."""
    d = [None] * len(x)
    for i in range(len(x)):
        if k == 0:
            d[i] = x[i]
        elif i >= k and x[i] is not None and x[i - k] is not None:
            d[i] = x[i] - x[i - k]
    keluar = [None] * len(x)
    for i in range(len(x)):
        if d[i] is None:
            continue
        lalu = [v for v in d[max(0, i - lookback):i] if v is not None]
        if len(lalu) < min_riwayat:
            continue
        mu = sum(lalu) / len(lalu)
        sd = math.sqrt(sum((v - mu) ** 2 for v in lalu) / (len(lalu) - 1))
        if sd == 0:
            continue
        z = max(-3.0, min(3.0, (d[i] - mu) / sd))
        keluar[i] = tanda * math.tanh(z / 2)
    return keluar


def _rata(*nilai):
    return None if any(v is None for v in nilai) else sum(nilai) / len(nilai)


KUADRAN = {
    (False, True): ("KETAT, MULAI MEMBAIK", "sering rasio risk/reward terbaik; titik balik"),
    (True, True): ("LONGGAR & MAKIN LONGGAR", "angin paling kuat"),
    (True, False): ("LONGGAR, MULAI MELAMBAT", "masih mendukung, kurangi agresivitas"),
    (False, False): ("KETAT & MAKIN KETAT", "fase terburuk; defensif"),
}


def jarum(posisi, momentum, terukur=False):
    if posisi is None or momentum is None:
        return None
    nama, arti = KUADRAN[(posisi >= 0, momentum >= 0)]
    keluar = {"posisi": round(posisi, 3), "momentum_4mg": round(momentum, 3),
              "sudut_derajat": round(math.degrees(math.atan2(momentum, posisi)), 1),
              "fase": nama, "menurut_rancangan": arti}
    if terukur:
        keluar["riwayat_btc_12mg_kuadran_ini"] = TERUKUR_KUADRAN_12MG[nama]
        keluar["riwayat_btc_12mg_tersil_skor"] = next(
            t for b, t in TERUKUR_TERSIL_12MG if b is None or posisi <= b)
    else:
        keluar["riwayat"] = "BELUM DIUJI — arti kuadran hanya teori rancangan"
    return keluar


def deret_likuiditas(fred, jumat):
    w = {k: ke_mingguan(fred[k], jumat, 45 if k == "SAHMREALTIME" else 21) for k in SERI}
    # Seragamkan ke miliar USD: WALCL & WDTGAL dalam JUTA, RRPONTSYD dalam MILIAR.
    net = [a / 1e3 - b / 1e3 - c if None not in (a, b, c) else None
           for a, b, c in zip(w["WALCL"], w["WDTGAL"], w["RRPONTSYD"])]
    logdx = [math.log(v) if v else None for v in w["DTWEXBGS"]]
    komp = {"L1_bunga": skor(w["DGS2"], tanda=-1),
            "L2_likuiditas_bersih": skor(net, tanda=+1),
            "L3_dolar": skor(logdx, tanda=-1),
            "L4_kondisi_keuangan": skor(w["NFCI"], tanda=-1)}
    liq = [_rata(*v) for v in zip(*komp.values())]
    resesi = [None if s is None else s >= AMBANG_RESESI for s in w["SAHMREALTIME"]]
    return {"komponen": komp, "likuiditas": liq, "resesi": resesi, "mentah": w,
            "likuiditas_bersih_miliar": net}


def deret_adopsi(baris_etf, jumat):
    """A1 & A2 per Jumat dari arus harian (arus tanggal d dianggap tersedia d+1)."""
    hari = []
    for b in baris_etf:
        try:
            hari.append((date.fromisoformat(b["date"]) + timedelta(days=1),
                         float(b["totalNetInflow"]), float(b.get("totalNetAssets") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    a1, a2 = [], []
    for f in jumat:
        lalu = [h for h in hari if h[0] <= f][-20:]
        if len(lalu) < 20 or not lalu[-1][2] or (f - lalu[-1][0]).days > 7:
            a1.append(None)
            a2.append(None)
            continue
        a1.append(sum(h[1] for h in lalu) / lalu[-1][2])
        a2.append(sum(1 for h in lalu if h[1] > 0) / 20)
    s1 = skor(a1, k=0, lookback=LOOKBACK_ADOPSI, min_riwayat=MIN_ADOPSI)
    s2 = skor(a2, k=0, lookback=LOOKBACK_ADOPSI, min_riwayat=MIN_ADOPSI)
    return {"A1": a1, "A2": a2, "skor_A1": s1, "skor_A2": s2,
            "struktural": [_rata(x, y) for x, y in zip(s1, s2)]}


def eksposur(liq, struktural, resesi):
    gabung = liq if struktural is None else 0.5 * liq + 0.5 * struktural
    e = max(0.0, min(1.0, 0.5 + 0.5 * gabung))
    return min(e, BATAS_RESESI) if resesi else e


# ------------------------------------------------------------------ keluaran
def _terakhir_isi(deret):
    for i in range(len(deret) - 1, -1, -1):
        if deret[i] is not None:
            return i
    return None


def analisa(hari_ini=None):
    hari_ini = hari_ini or datetime.now(timezone.utc).date()
    fred, gagal = ambil_fred()
    if gagal:
        return {"tidak_tersedia": f"seri FRED gagal: {gagal}. Skor Liquidity sengaja "
                                  "TIDAK dihitung dari komponen yang tersisa."}
    jumat = jumat_dari(date.fromisoformat(MULAI), hari_ini)
    L = deret_likuiditas(fred, jumat)
    i = _terakhir_isi(L["likuiditas"])
    if i is None or i < K_MINGGU:
        return {"tidak_tersedia": "skor Liquidity belum bisa dihitung (riwayat kurang)"}
    liq = L["likuiditas"]
    mom = liq[i] - liq[i - K_MINGGU] if liq[i - K_MINGGU] is not None else None
    hasil = {
        "sinyal_jumat": jumat[i].isoformat(),
        "skor_likuiditas": round(liq[i], 3),
        "komponen": {k: round(v[i], 3) for k, v in L["komponen"].items()},
        "jam_likuiditas": jarum(liq[i], mom, terukur=True),
        "filter_resesi_L5": {"aktif": bool(L["resesi"][i]),
                             "sahm_realtime": L["mentah"]["SAHMREALTIME"][i]},
        "likuiditas_bersih_miliar_usd": round(L["likuiditas_bersih_miliar"][i], 1),
    }
    if (jumat[-1] - jumat[i]).days > 7:
        hasil["peringatan_basi"] = (f"sinyal terakhir yang lengkap bertanggal {jumat[i]} — "
                                    "ada komponen yang belum diperbarui; sebutkan tanggalnya")

    struk = None
    try:
        import sosovalue
        baris, err = sosovalue.historis_etf("us-btc-spot")
    except Exception as e:
        baris, err = None, type(e).__name__
    if err or not baris:
        hasil["adopsi_struktural"] = {"tidak_tersedia": err or "riwayat ETF kosong"}
    else:
        A = deret_adopsi(baris, jumat)
        j = _terakhir_isi(A["struktural"])
        if j is None:
            hasil["adopsi_struktural"] = {"tidak_tersedia": "riwayat ETF < 26 minggu"}
        else:
            struk = A["struktural"][j]
            mom_a = (struk - A["struktural"][j - K_MINGGU]
                     if j >= K_MINGGU and A["struktural"][j - K_MINGGU] is not None else None)
            hasil["adopsi_struktural"] = {
                "sinyal_jumat": jumat[j].isoformat(),
                "skor": round(struk, 3),
                "A1_arus_20hari_per_aset_persen": round(A["A1"][j] * 100, 2),
                "A2_hari_arus_positif_persen": round(A["A2"][j] * 100),
                "jam_adopsi": jarum(struk, mom_a),
                "cakupan": "PARSIAL 2 dari 4 komponen (A3 13F & A4 treasury belum ada "
                           "sumbernya); skor Gelombang belum dibangun",
            }
    e = eksposur(liq[i], struk, L["resesi"][i])
    hasil["target_eksposur_btc_persen"] = round(e * 100)
    hasil["dasar_eksposur"] = ("0,5 + 0,5 x rata-rata(Liquidity, Struktural)" if struk is not None
                               else "0,5 + 0,5 x Liquidity (adopsi tidak tersedia)")
    hasil["status_bukti"] = STATUS_BUKTI
    hasil["wajib_dibaca"] = (
        "Ini FILTER REZIM ~12 minggu (seberapa besar eksposur), BUKAN sinyal entry harian "
        "dan bukan arah harga besok/pekan depan (horizon 4 minggu tidak terbukti). Long-only/"
        "cash. Pakai angka riwayat_btc_12mg, BUKAN teks menurut_rancangan, bila keduanya "
        "berbeda. Teruji pada BTC saja — untuk altcoin sebut itu.")
    return hasil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ringkas", action="store_true", help="JSON padat untuk brief")
    a = ap.parse_args()
    h = analisa()
    print(json.dumps(h, ensure_ascii=False, separators=(",", ":") if a.ringkas else None,
                     indent=None if a.ringkas else 2))


if __name__ == "__main__":
    main()

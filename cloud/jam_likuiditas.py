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
    "kepastian. Juga LOLOS untuk ETH (IC +0,30) dan SOL (+0,34) pada 12 minggu, kedua "
    "paruh sampel positif (uji_jam_lanjutan.py).")
STATUS_GELOMBANG = (
    "Hipotesis rancangan (Gelombang tinggi = rawan koreksi) DITOLAK pada BTC 2021-2026: IC "
    "justru POSITIF (+0,09..+0,11, p ekor bawah 0,96) di kedua era. Sesudah minggu skor "
    "> 0,5 median return 12 minggu +20,1% vs -0,1% sisanya. Karena itu aturan 'potong 25 pp' "
    "TIDAK diterapkan pada target eksposur. Funding sendiri ~nol (IC -0,02); Fear & Greed "
    "+0,23 = momentum sentimen, bukan sinyal puncak. Dengan basis CME ikut di W1 hasilnya "
    "SAMA: IC +0,12..+0,13, p 0,97; basis sendiri +0,15; sesudah skor > 0,5 median 12 "
    "minggu +29,8%.")
STATUS_ADOPSI = (
    "BELUM TERBUKTI: arus ETF baru 114 minggu (~9 jendela 12 minggu independen). Arah "
    "campur — IC 4 minggu +0,22 (sesuai teori), 12 minggu -0,06 (berlawanan). Bobot "
    "ditetapkan rancangan, tidak dioptimasi.")
# Aturan Gelombang > 0,5 -> potong 25 pp dari rancangan. Dimatikan: datanya menunjukkan
# minggu-minggu itu justru diikuti return TERTINGGI (lihat STATUS_GELOMBANG).
PAKAI_ATURAN_GELOMBANG = False

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
        # Jam ADOPSI: nama kuadran likuiditas ("longgar/ketat") tidak berarti di sini.
        keluar["fase"] = {(True, True): "ADOPSI KUAT & MENGUAT",
                          (True, False): "ADOPSI KUAT, MULAI MELEMAH",
                          (False, True): "ADOPSI LEMAH, MULAI MEMBAIK",
                          (False, False): "ADOPSI LEMAH & MELEMAH"}[(posisi >= 0, momentum >= 0)]
        del keluar["menurut_rancangan"]
        keluar["riwayat"] = STATUS_ADOPSI
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


def harga_yahoo(simbol="BTC-USD"):
    """{tanggal ISO: penutupan harian} dari Yahoo (riwayat penuh, gratis)."""
    import urllib.request
    import makro
    # range=max diam-diam menurunkan resolusi ke BULANAN; period1/period2 tetap harian.
    url = makro.YAHOO + simbol + f"?period1=0&period2={int(datetime.now().timestamp())}&interval=1d"
    req = urllib.request.Request(url, headers=makro.UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        d = json.loads(r.read().decode())["chart"]["result"][0]
    tutup = d["indicators"]["quote"][0]["close"]
    return {datetime.fromtimestamp(t, timezone.utc).date().isoformat(): c
            for t, c in zip(d["timestamp"], tutup) if c}


def _harga_pada(harga, tgl, mundur=7):
    for i in range(mundur + 1):
        p = harga.get((tgl - timedelta(days=i)).isoformat())
        if p:
            return p
    return None


def _skor_tetap(pertumbuhan_persen, skala):
    """Skala TETAP (bukan z-score) untuk komponen dengan titik terlalu sedikit untuk
    z bergulir: 13F hanya ~10 kuartal. tanh(g/skala), skala ditetapkan di awal."""
    return None if pertumbuhan_persen is None else math.tanh(pertumbuhan_persen / skala)


# Jenis pemegang 13F (etf_13f.py, Form ADV 5.D) yang dihitung sebagai PERMINTAAN NYATA.
# HEDGE_FUND_DANA_PRIVAT dikeluarkan: di situ pelaku basis trade (long ETF + short
# futures, netral arah) berada. TIDAK_TERKLASIFIKASI juga dikeluarkan — isinya tidak
# diketahui, jadi tidak boleh diam-diam dihitung sebagai adopsi.
JENIS_INTI = ("PENASIHAT_KEKAYAAN", "INSTITUSI", "BANK", "MANAJER_REKSA_DANA", "LAINNYA")


def _inti_13f(q):
    """(pemegang, nilai_usd) inti — atau total kalau berkas lama belum punya per_jenis."""
    pj = q.get("per_jenis")
    if not pj:
        return q["pemegang"], q["nilai_usd"]
    return (sum(pj.get(j, {}).get("pemegang", 0) for j in JENIS_INTI),
            sum(pj.get(j, {}).get("nilai_usd", 0) for j in JENIS_INTI))


def deret_adopsi(arus, harga, jumat, kuartal_13f=(), treasury=()):
    """Skor struktural per Jumat.

    arus      [(tanggal, US$ juta)] — arus tanggal d dianggap tersedia d+1.
    harga     {tanggal: harga BTC} — untuk menormalkan A1 dengan estimasi aset ETF.
    kuartal_13f [(tanggal_tersedia, {"akhir_kuartal","pemegang","nilai_usd"})].
    treasury  [{"tanggal","total_btc"}] dari arsip mingguan.
    """
    import adopsi
    milik = adopsi.kepemilikan_btc(arus, harga)
    hari = [(date.fromisoformat(t) + timedelta(days=1), v, t) for t, v in arus]
    a1, a2, s3, info3 = [], [], [], []
    for f in jumat:
        lalu = [h for h in hari if h[0] <= f][-20:]
        p = harga.get(lalu[-1][2]) if lalu else None
        if len(lalu) < 20 or not p or (f - lalu[-1][0]).days > 7:
            a1.append(None)
            a2.append(None)
        else:
            aset = milik[lalu[-1][2]] * p
            a1.append(sum(h[1] for h in lalu) * 1e6 / aset)
            a2.append(sum(1 for h in lalu if h[1] > 0) / 20)
        sudah = [q for t, q in kuartal_13f if t <= f]
        if len(sudah) >= 2:
            kini, dulu = sudah[-1], sudah[-2]
            (hk, vk), (hd, vd) = _inti_13f(kini), _inti_13f(dulu)
            gh = (hk / hd - 1) * 100 if hd else None
            pk = _harga_pada(harga, date.fromisoformat(kini["akhir_kuartal"]))
            pd_ = _harga_pada(harga, date.fromisoformat(dulu["akhir_kuartal"]))
            gb = ((vk / pk) / (vd / pd_) - 1) * 100 if pk and pd_ and vd else None
            # 10% per kuartal -> tanh(1) = 0,76. Ditetapkan sebelum melihat data.
            s3.append(_rata(_skor_tetap(gh, 10), _skor_tetap(gb, 10)))
            pj = kini.get("per_jenis") or {}
            info3.append({
                "kuartal": kini["akhir_kuartal"], "pemegang_total": kini["pemegang"],
                "pemegang_inti": hk,
                "inti_qoq_persen": round(gh, 1) if gh is not None else None,
                "inti_btc_setara_qoq_persen": round(gb, 1) if gb is not None else None,
                "porsi_nilai_persen": {j: round(x["nilai_usd"] / kini["nilai_usd"] * 100, 1)
                                       for j, x in pj.items()} if kini["nilai_usd"] else {},
                # None (bukan 0) kalau etf_13f.json belum punya pemisahan jenis.
                "hedge_fund_btc_setara": round(pj.get("HEDGE_FUND_DANA_PRIVAT", {})
                                               .get("nilai_usd", 0) / pk)
                if pk and pj else None})
        else:
            s3.append(None)
            info3.append(None)
    t4 = [(date.fromisoformat(r["tanggal"]), r["total_btc"]) for r in treasury]
    w4 = ke_mingguan(t4, jumat, maks_basi=10)
    s4 = skor(w4, lookback=LOOKBACK_ADOPSI, min_riwayat=MIN_ADOPSI)
    s1 = skor(a1, k=0, lookback=LOOKBACK_ADOPSI, min_riwayat=MIN_ADOPSI)
    s2 = skor(a2, k=0, lookback=LOOKBACK_ADOPSI, min_riwayat=MIN_ADOPSI)
    struk, pakai = [], []
    for v in zip(s1, s2, s3, s4):
        # A1 & A2 (harian) WAJIB ada; A3 & A4 ikut kalau sudah tersedia.
        if v[0] is None or v[1] is None:
            struk.append(None)
            pakai.append(())
            continue
        ada = [(n, x) for n, x in zip(("A1", "A2", "A3", "A4"), v) if x is not None]
        struk.append(sum(x for _, x in ada) / len(ada))
        pakai.append(tuple(n for n, _ in ada))
    return {"A1": a1, "A2": a2, "skor_A1": s1, "skor_A2": s2, "skor_A3": s3,
            "info_A3": info3, "treasury_btc": w4, "skor_A4": s4,
            "struktural": struk, "komponen_terpakai": pakai}


FASE_ADOPSI = {
    (True, False): ("AKUMULASI SEHAT", "institusi membeli diam-diam; kondisi terbaik"),
    (True, True): ("EUFORIA TERDUKUNG", "masih naik, risiko koreksi tajam meningkat"),
    (False, True): ("SPEKULASI MURNI", "kenaikan tanpa pembeli kuat; rawan puncak"),
    (False, False): ("DIABAIKAN", "sering dekat dasar, belum ada pemicu"),
}


def eksposur(liq, struktural, resesi, gelombang=None):
    """0,5 + 0,5 x gabungan; Gelombang > 0,5 memotong 25 pp; resesi membatasi 50%."""
    import gelombang as gl
    gabung = liq if struktural is None else 0.5 * liq + 0.5 * struktural
    e = 0.5 + 0.5 * gabung
    if PAKAI_ATURAN_GELOMBANG and gelombang is not None and gelombang > gl.AMBANG_GELOMBANG:
        e -= gl.POTONG_EKSPOSUR
    e = max(0.0, min(1.0, e))
    return min(e, BATAS_RESESI) if resesi else e


# Rentang wajar nilai TERAKHIR — penjaga satuan (checklist rancangan: "WALCL & WDTGAL dalam
# juta, RRPONTSYD dalam miliar"). Kalau FRED mengganti satuan, skor L2 akan salah 1000x
# tanpa error apa pun; lebih baik ditolak.
RENTANG_WAJAR = {"WALCL": (1e6, 2e7), "WDTGAL": (1e3, 3e6), "RRPONTSYD": (0, 5e3),
                 "DGS2": (-2, 20), "DTWEXBGS": (50, 250), "NFCI": (-3, 10),
                 "SAHMREALTIME": (-1, 10)}
BATAS_BASI_HARI = {"SAHMREALTIME": 75}       # bulanan; lainnya 10 hari (checklist)


def validasi(fred, hari_ini):
    """(masalah_satuan, peringatan_basi)."""
    satuan, basi = [], []
    for k, titik in fred.items():
        lo, hi = RENTANG_WAJAR[k]
        if not lo <= titik[-1][1] <= hi:
            satuan.append(f"{k}={titik[-1][1]} di luar {lo}..{hi}")
        ukur = titik[-1][0] - timedelta(days=JEDA_RILIS[k])
        umur = (hari_ini - ukur).days
        if umur > BATAS_BASI_HARI.get(k, 10):
            basi.append(f"{k} terakhir {ukur} ({umur} hari)")
    return satuan, basi


# ------------------------------------------------------------------ keluaran
def _terakhir_isi(deret):
    for i in range(len(deret) - 1, -1, -1):
        if deret[i] is not None:
            return i
    return None


def _bagian_adopsi(jumat, hasil):
    """Isi hasil["adopsi_struktural"] & ["gelombang"]. Return (struktural, gelombang)."""
    import adopsi
    import gelombang as gl
    struk = gel = None
    try:
        harga = harga_yahoo("BTC-USD")
    except Exception as e:
        harga = {}
        hasil["adopsi_struktural"] = {"tidak_tersedia": f"harga BTC gagal ({type(e).__name__})"}
    arus, sumber, err = adopsi.arus_etf(perbarui=True)
    if harga and not arus:
        hasil["adopsi_struktural"] = {"tidak_tersedia": err}
    elif harga:
        A = deret_adopsi(arus, harga, jumat, adopsi.seri_13f(), adopsi.seri_treasury())
        j = _terakhir_isi(A["struktural"])
        if j is None:
            hasil["adopsi_struktural"] = {"tidak_tersedia": "riwayat arus ETF < 26 minggu"}
        else:
            struk = A["struktural"][j]
            s0 = A["struktural"][j - K_MINGGU] if j >= K_MINGGU else None
            hilang = [n for n in ("A3", "A4") if n not in A["komponen_terpakai"][j]]
            hasil["adopsi_struktural"] = {
                "sinyal_jumat": jumat[j].isoformat(),
                "skor": round(struk, 3),
                "komponen": {n: round(A[f"skor_{n}"][j], 3)
                             for n in A["komponen_terpakai"][j]},
                "A1_arus_20hari_per_aset_persen": round(A["A1"][j] * 100, 2),
                "A2_hari_arus_positif_persen": round(A["A2"][j] * 100),
                "A3_13f": A["info_A3"][j] or "belum ada 2 kuartal 13F (etf_13f.py)",
                "jam_adopsi": jarum(struk, None if s0 is None else struk - s0),
                "sumber_arus": sumber + (f" — {err}" if err else ""),
            }
            if hilang:
                hasil["adopsi_struktural"]["belum_ikut"] = (
                    f"{', '.join(hilang)} belum ikut skor: A3 butuh etf_13f.json (workflow "
                    "jam-mingguan, perlu SEC_CONTACT); A4 butuh >= 30 minggu arsip treasury "
                    "(sumber gratis hanya memberi angka hari ini, arsip mulai 15 Okt 2026)")
    try:
        funding, cat = gl.funding_harian()
        try:
            basis = gl.basis_cme(gl.spot_jam_cme(), harga_yahoo("BTC=F"))
        except Exception as e:
            basis = None
            cat.append(f"basis CME gagal ({type(e).__name__}) — W1 hanya funding")
        G = gl.deret_gelombang(funding, gl.fear_greed(), jumat, basis)
        k = _terakhir_isi(G["gelombang"])
        if k is None:
            hasil["gelombang"] = {"tidak_tersedia": "; ".join(cat) or "riwayat kurang"}
        else:
            gel = G["gelombang"][k]
            hasil["gelombang"] = {
                "sinyal_jumat": jumat[k].isoformat(), "skor": round(gel, 3),
                "W1_funding_persen_per_8jam": round(G["W1_funding"][k], 4),
                "W1_basis_cme_tahunan_persen": (round(G["W1_basis"][k], 1)
                                                if G.get("W1_basis") and G["W1_basis"][k]
                                                is not None else None),
                "W2_fear_greed_7hari": round(G["W2_fng"][k]),
                "aturan_rancangan": ("skor > 0,5 memotong eksposur 25 pp — TIDAK "
                                     "diterapkan, ditolak data"),
                "status_bukti": STATUS_GELOMBANG}
            if (jumat[-1] - jumat[k]).days > 7:
                hasil["gelombang"]["peringatan_basi"] = "; ".join(cat)
    except Exception as e:
        hasil["gelombang"] = {"tidak_tersedia": f"{type(e).__name__}"}
    try:
        c = [x for t, x in adopsi.cftc_leveraged() if t <= jumat[-1]]
        if c:
            kini, lalu = c[-1], (c[-5] if len(c) >= 5 else c[0])
            hasil["jejak_basis_trade_cftc"] = {
                "short_bersih_leveraged_funds_btc": kini["short_bersih_btc"],
                "perubahan_4_laporan_btc": kini["short_bersih_btc"] - lalu["short_bersih_btc"],
                "arti": ("short bersih hedge fund/CTA di futures BTC CME (CFTC TFF) = kaki "
                         "short basis trade; bandingkan dengan hedge_fund_btc_setara di A3. "
                         "Naik bersama arus ETF = sebagian arus itu basis trade, bukan "
                         "permintaan arah")}
    except Exception as e:
        hasil["jejak_basis_trade_cftc"] = {"tidak_tersedia": type(e).__name__}
    if struk is not None and gel is not None:
        nama, arti = FASE_ADOPSI[(struk >= 0, gel >= 0)]
        hasil["fase_adopsi"] = {"fase": nama, "menurut_rancangan": arti,
                                "status_bukti": "BELUM TERBUKTI — sumbu Gelombang-nya "
                                                "terbalik dari teori (lihat gelombang)"}
    return struk, gel


def analisa(hari_ini=None):
    hari_ini = hari_ini or datetime.now(timezone.utc).date()
    fred, gagal = ambil_fred()
    if gagal:
        return {"tidak_tersedia": f"seri FRED gagal: {gagal}. Skor Liquidity sengaja "
                                  "TIDAK dihitung dari komponen yang tersisa."}
    satuan, basi = validasi(fred, hari_ini)
    if satuan:
        return {"tidak_tersedia": f"satuan FRED tidak wajar: {satuan}. Skor sengaja tidak "
                                  "dihitung — salah satuan membuat L2 meleset 1000x."}
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
    if basi:
        hasil["peringatan_basi"] = basi
    if (jumat[-1] - jumat[i]).days > 7:
        hasil["peringatan_sinyal"] = (f"sinyal lengkap terakhir bertanggal {jumat[i]}; "
                                      "sebutkan tanggalnya")
    struk, gel = _bagian_adopsi(jumat, hasil)
    e = eksposur(liq[i], struk, L["resesi"][i], gel)
    hasil["target_eksposur_btc_persen"] = round(e * 100)
    hasil["dasar_eksposur"] = (
        ("0,5 + 0,5 x rata-rata(Liquidity, Struktural)" if struk is not None
         else "0,5 + 0,5 x Liquidity (adopsi tidak tersedia)")
        + ("; dibatasi 50% oleh filter resesi" if L["resesi"][i] else ""))
    # Separuh bobot rancangan jatuh ke Struktural yang belum terbukti. Versi yang hanya
    # memakai komponen TERUJI disajikan berdampingan supaya bedanya terlihat.
    hasil["eksposur_komponen_teruji_saja_persen"] = round(
        eksposur(liq[i], None, L["resesi"][i]) * 100)
    hasil["status_bukti"] = STATUS_BUKTI
    hasil["wajib_dibaca"] = (
        "Ini FILTER REZIM ~12 minggu (seberapa besar eksposur), BUKAN sinyal entry harian "
        "dan bukan arah harga besok/pekan depan (horizon 4 minggu tidak terbukti). Long-only/"
        "cash; eksposur hanya diubah bila selisihnya >= 10 pp. Pakai angka riwayat_btc_12mg, "
        "BUKAN teks menurut_rancangan, bila berbeda. Lihat status_bukti tiap bagian; "
        "sebut kedua angka eksposur kalau berbeda >= 10 pp.")
    return hasil


def pesan(h):
    """Ringkasan Telegram mingguan dari hasil analisa()."""
    if "tidak_tersedia" in h:
        return "🕰 JAM LIKUIDITAS: tidak tersedia — " + h["tidak_tersedia"]
    j = h["jam_likuiditas"]
    baris = [f"🕰 JAM LIKUIDITAS & ADOPSI (sinyal {h['sinyal_jumat']})",
             f"Liquidity {h['skor_likuiditas']:+.2f} · fase {j['fase']}",
             f"  riwayat BTC 12 mg fase ini: {j['riwayat_btc_12mg_kuadran_ini']}",
             "  komponen: " + " · ".join(f"{k.split('_')[0]} {v:+.2f}"
                                         for k, v in h["komponen"].items()),
             f"Filter resesi: {'AKTIF' if h['filter_resesi_L5']['aktif'] else 'tidak aktif'}"]
    a = h.get("adopsi_struktural") or {}
    baris.append(f"Adopsi struktural {a['skor']:+.2f} ({', '.join(a['komponen'])}) · "
                 f"{a['jam_adopsi']['fase'] if a.get('jam_adopsi') else '-'} — belum terbukti"
                 if "skor" in a else f"Adopsi: {a.get('tidak_tersedia', '-')}")
    g = h.get("gelombang") or {}
    if "skor" in g:
        baris.append(f"Gelombang {g['skor']:+.2f} (funding {g['W1_funding_persen_per_8jam']}%"
                     f"/8j, F&G {g['W2_fear_greed_7hari']}) — aturan potong ditolak data")
    baris += ["",
              f"Target eksposur BTC (rancangan): {h['target_eksposur_btc_persen']}%",
              f"Komponen teruji saja: {h['eksposur_komponen_teruji_saja_persen']}%",
              "Filter rezim ~12 minggu, long-only — bukan sinyal entry, bukan nasihat."]
    for w in (h.get("peringatan_basi") or []):
        baris.append(f"⚠ basi: {w}")
    return "\n".join(baris)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ringkas", action="store_true", help="JSON padat untuk brief")
    ap.add_argument("--pesan", action="store_true",
                    help="baca JSON analisa dari stdin, cetak pesan Telegram")
    a = ap.parse_args()
    if a.pesan:
        print(pesan(json.load(sys.stdin)))
        return
    h = analisa()
    print(json.dumps(h, ensure_ascii=False, separators=(",", ":") if a.ringkas else None,
                     indent=None if a.ringkas else 2))


if __name__ == "__main__":
    main()

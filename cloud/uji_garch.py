"""Uji ramalan VOLATILITAS: GARCH(1,1) & EWMA vs sigma 90 hari — DIDAFTARKAN SEBELUM DIJALANKAN
(28 Okt 2026). Kriteria di bawah tidak boleh diubah sesudah hasil terlihat.

Pertanyaan: lebar kisaran PREDIKSI HARGA bot (proyeksi.py, prediksi_harga) memakai simpangan
baku imbal hasil log 90 hari x akar(h). Volatilitas berkelompok (volatility clustering), jadi
model yang bereaksi lebih cepat seharusnya meramal lebar kisaran lebih tepat. Ini BUKAN uji
arah harga — yang diramal hanya besarnya gerak.

PEMBANDING (dipakai bot sekarang)
  SIGMA90 : var = pstdev(r[t-89..t])^2, ramalan h hari = h x var.

KANDIDAT (dua saja, dipilih dari literatur standar, tidak ditambah sesudah melihat hasil)
  EWMA    : RiskMetrics lambda 0,94 (tanpa estimasi). var_{t+1} = 0,94 var_t + 0,06 r_t^2,
            dimulai dari varians 90 hari pertama. Ramalan h hari = h x var_{t+1}.
  GARCH   : GARCH(1,1) Gauss, rata-rata nol, variance targeting (omega = var_latih x
            (1 - alpha - beta)). alpha di {0,01..0,30 langkah 0,01}, persistensi alpha+beta di
            {0,800..0,995 langkah 0,005}; dipilih likelihood terbesar pada SELURUH data latih
            sebelum 1 Jan tahun uji (diestimasi ulang tiap tahun, latih >= 730 hari).
            Ramalan h hari = sum_{k=1..h} [vL + (a+b)^(k-1) (var_{t+1} - vL)].

DATA & TITIK UJI
  Aset    : BTC (Bitstamp CSV 2012-), ETH-USD, SOL-USD, ^GSPC, GC=F, EURUSD=X (Yahoo harian).
            Pasar tradisional: "hari" = hari bursa (sama seperti candle di proyeksi.py).
            Semua deret dipotong mulai 2010-01-01 (BTC mulai 2012): menyamakan era antar-aset
            dan menjaga estimasi grid GARCH tetap terjangkau (^GSPC Yahoo mulai 1927).
  Horizon : 1, 7, 30 candle (horizon prediksi_harga). Titik asal tiap candle (h=1) / tiap
            7 candle (h=7, 30). Ketiga model dinilai di titik asal yang SAMA: mulai tahun
            pertama yang punya >= 730 candle latih untuk GARCH.
  Target  : realized variance RV = jumlah r^2 harian pada h candle sesudah titik asal.

UKURAN
  Utama   : QLIKE = RV/F - ln(RV/F) - 1 (Patton 2011: tahan terhadap derau proksi RV).
  Uji     : Diebold-Mariano satu sisi (kandidat < SIGMA90) pada d = QLIKE_base - QLIKE_kand,
            varians HAC Newey-West, lag = max(ceil(h/langkah), floor(4 (n/100)^(2/9))).
  Kedua   : cakupan kisaran 80% (p10-p90) & 50% (p25-p75) lognormal tanpa drift, kuantil
            z sama dengan proyeksi.py; galat cakupan = |cakupan - target|.

KRITERIA ADOPSI per kandidat per horizon (semuanya harus terpenuhi)
  1. QLIKE rata-rata kandidat < SIGMA90 di >= 5 dari 6 aset.
  2. BTC (riwayat terpanjang): DM p < 0,05/6 = 0,0083 (Bonferroni 2 kandidat x 3 horizon).
  3. BTC: QLIKE kandidat < SIGMA90 di KEDUA paruh periode uji (stabil lintas era).
  4. Galat cakupan 80% rata-rata 6 aset tidak lebih buruk dari SIGMA90 + 2 poin persen.
  Lolos keduanya -> dipilih QLIKE rata-rata (relatif) terbaik. Tidak ada yang lolos ->
  sigma 90 hari tetap. Hasil dicatat apa adanya di cloud/data/uji_garch.json.

    python cloud/uji_garch.py
"""
import csv
import gzip
import json
import math
import os
import statistics
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HASIL_PATH = os.path.join(BASE_DIR, "data", "uji_garch.json")
ASET = ("BTC", "ETH-USD", "SOL-USD", "^GSPC", "GC=F", "EURUSD=X")
HORIZON = (1, 7, 30)
JENDELA = 90
LAMBDA = 0.94
LATIH_MIN = 730
DATA_MULAI = "2010-01-01"
P_MAKS = 0.05 / 6
Z = {"10": -1.2816, "25": -0.6745, "75": 0.6745, "90": 1.2816}
ALFA = [i / 100 for i in range(1, 31)]
PERSIS = [0.800 + 0.005 * i for i in range(40)]


# ------------------------------------------------------------------ data
def muat(aset):
    """-> (tanggal[], tutup[]) harian, urut, tanpa nol."""
    if aset == "BTC":
        tgl, tutup = [], []
        with gzip.open(os.path.join(BASE_DIR, "data", "btc_daily_bitstamp.csv.gz"), "rt",
                       encoding="utf-8") as f:
            for b in csv.DictReader(f):
                try:
                    c = float(b["close"])
                except (TypeError, ValueError):
                    continue
                if c > 0:
                    tgl.append(b["dt"][:10])
                    tutup.append(c)
        return tgl, tutup
    import jam_likuiditas as jl
    h = jl.harga_yahoo(aset)
    tgl = sorted(t for t, c in h.items() if c and c > 0 and t >= DATA_MULAI)
    return tgl, [h[t] for t in tgl]


# ------------------------------------------------------------------ model
def garch_varians(r, a, p, v0):
    """Deret var_{t+1|t} GARCH(1,1) variance-targeted. v[t] = ramalan untuk r[t]."""
    w = v0 * (1 - p)
    b = p - a
    v = [v0]
    for x in r[:-1]:
        v.append(w + a * x * x + b * v[-1])
    return v


def garch_fit(r):
    """Grid alpha x persistensi, likelihood Gauss rata-rata nol. -> (a, p, vL)."""
    vL = sum(x * x for x in r) / len(r)
    r2 = [x * x for x in r]
    terbaik = None
    for p in PERSIS:
        w = vL * (1 - p)
        for a in ALFA:
            if a >= p:
                continue
            b = p - a
            v, ll = vL, 0.0
            for x2 in r2:
                ll -= math.log(v) + x2 / v
                v = w + a * x2 + b * v
            if terbaik is None or ll > terbaik[0]:
                terbaik = (ll, a, p)
    return terbaik[1], terbaik[2], vL


def ramal_garch(v_next, a, p, vL, h):
    return sum(vL + p ** (k - 1) * (v_next - vL) for k in range(1, h + 1))


# ------------------------------------------------------------------ ukuran
def qlike(rv, f):
    if rv <= 0:
        rv = 1e-12
    q = rv / f
    return q - math.log(q) - 1


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def diebold_mariano(d, lag):
    """Satu sisi: H1 mean(d) > 0. Varians HAC Newey-West (Bartlett)."""
    n = len(d)
    m = sum(d) / n
    e = [x - m for x in d]
    g0 = sum(x * x for x in e) / n
    s = g0
    for k in range(1, lag + 1):
        gk = sum(e[t] * e[t - k] for t in range(k, n)) / n
        s += 2 * (1 - k / (lag + 1)) * gk
    if s <= 0:
        return None, None
    dm = m / math.sqrt(s / n)
    return dm, 1 - _phi(dm)


def cakupan(f, ret):
    s = math.sqrt(f)
    return (Z["10"] * s <= ret <= Z["90"] * s, Z["25"] * s <= ret <= Z["75"] * s)


# ------------------------------------------------------------------ uji
def uji_aset(aset):
    tgl, c = muat(aset)
    r = [math.log(c[i] / c[i - 1]) for i in range(1, len(c))]
    tr = tgl[1:]                                    # tanggal milik r[i]
    # EWMA berjalan di seluruh deret (hanya masa lalu).
    ew = [statistics.pvariance(r[:JENDELA])]
    for x in r[:-1]:
        ew.append(LAMBDA * ew[-1] + (1 - LAMBDA) * x * x)   # ew[t] = ramalan untuk r[t]
    tahun_awal = None
    for th in range(int(tr[0][:4]) + 1, date.today().year + 1):
        if sum(1 for t in tr if t < f"{th}-01-01") >= LATIH_MIN:
            tahun_awal = th
            break
    if tahun_awal is None:
        return {"error": "riwayat kurang"}
    hasil = {"riwayat": f"{tgl[0]} s/d {tgl[-1]}", "tahun_uji_mulai": tahun_awal,
             "garch_per_tahun": {}, "horizon": {}}
    # GARCH: estimasi per tahun uji, varians bersyarat dihitung maju dengan parameter tahun itu.
    v_garch = [None] * len(r)
    for th in range(tahun_awal, int(tr[-1][:4]) + 1):
        latih = [x for x, t in zip(r, tr) if t < f"{th}-01-01"]
        a, p, vL = garch_fit(latih)
        hasil["garch_per_tahun"][th] = {"alfa": a, "persistensi": round(p, 3)}
        v = garch_varians(r, a, p, vL)
        for i, t in enumerate(tr):
            if t[:4] == str(th):
                v_garch[i] = (v[i], a, p, vL)
    for h in HORIZON:
        langkah = 1 if h == 1 else 7
        titik = []
        for i in range(JENDELA, len(r) - h + 1, langkah):
            # titik asal: sesudah r[i-1] diketahui; ramalan untuk r[i..i+h-1]
            if v_garch[i] is None:
                continue
            rv = sum(x * x for x in r[i:i + h])
            ret = sum(r[i:i + h])
            f_base = h * statistics.pvariance(r[i - JENDELA:i])
            f_ew = h * ew[i]
            vg, a, p, vL = v_garch[i]
            f_g = ramal_garch(vg, a, p, vL, h)
            titik.append((tr[i], rv, ret, {"SIGMA90": f_base, "EWMA": f_ew, "GARCH": f_g}))
        n = len(titik)
        lag = max(math.ceil(h / langkah), math.floor(4 * (n / 100) ** (2 / 9)))
        q = {m: [qlike(rv, f[m]) for _, rv, _, f in titik] for m in ("SIGMA90", "EWMA", "GARCH")}
        tengah = n // 2
        per_model = {}
        for m in ("SIGMA90", "EWMA", "GARCH"):
            cak = [cakupan(f[m], ret) for _, _, ret, f in titik]
            per_model[m] = {
                "qlike": round(sum(q[m]) / n, 4),
                "qlike_paruh": [round(sum(q[m][:tengah]) / tengah, 4),
                                round(sum(q[m][tengah:]) / (n - tengah), 4)],
                "cakupan_80": round(100 * sum(a for a, _ in cak) / n, 1),
                "cakupan_50": round(100 * sum(b for _, b in cak) / n, 1)}
        for m in ("EWMA", "GARCH"):
            d = [b - k for b, k in zip(q["SIGMA90"], q[m])]
            dm, p = diebold_mariano(d, lag)
            per_model[m]["dm"] = round(dm, 2) if dm is not None else None
            per_model[m]["p_dm"] = round(p, 5) if p is not None else None
        hasil["horizon"][str(h)] = {"titik": n, "lag_hac": lag,
                                    "periode": f"{titik[0][0]} s/d {titik[-1][0]}",
                                    "model": per_model}
    return hasil


def vonis(semua):
    keluar = {}
    for h in map(str, HORIZON):
        keluar[h] = {}
        lolos = []
        for m in ("EWMA", "GARCH"):
            asetnya = [a for a in ASET if "horizon" in semua.get(a, {})]
            menang = sum(1 for a in asetnya
                         if semua[a]["horizon"][h]["model"][m]["qlike"]
                         < semua[a]["horizon"][h]["model"]["SIGMA90"]["qlike"])
            btc = semua["BTC"]["horizon"][h]["model"]
            k1 = menang >= 5
            k2 = (btc[m]["p_dm"] or 1) < P_MAKS
            k3 = all(x < y for x, y in zip(btc[m]["qlike_paruh"], btc["SIGMA90"]["qlike_paruh"]))
            gal = lambda mm: sum(abs(semua[a]["horizon"][h]["model"][mm]["cakupan_80"] - 80)
                                 for a in asetnya) / len(asetnya)
            k4 = gal(m) <= gal("SIGMA90") + 2
            rel = sum(semua[a]["horizon"][h]["model"][m]["qlike"]
                      / semua[a]["horizon"][h]["model"]["SIGMA90"]["qlike"]
                      for a in asetnya) / len(asetnya)
            keluar[h][m] = {"menang_aset": f"{menang}/{len(asetnya)}", "k1": k1,
                            "btc_p_dm": btc[m]["p_dm"], "k2": k2, "k3_btc_dua_paruh": k3,
                            "galat_cakupan80": round(gal(m), 1),
                            "galat_cakupan80_sigma90": round(gal("SIGMA90"), 1), "k4": k4,
                            "qlike_relatif": round(rel, 3), "lolos": k1 and k2 and k3 and k4}
            if keluar[h][m]["lolos"]:
                lolos.append((rel, m))
        keluar[h]["dipilih"] = min(lolos)[1] if lolos else None
        keluar[h]["vonis"] = (f"LOLOS: {keluar[h]['dipilih']}" if lolos
                              else "TIDAK ADA yang lolos — sigma 90 hari tetap")
    return keluar


def main():
    semua = {}
    for a in ASET:
        try:
            semua[a] = uji_aset(a)
        except Exception as e:
            semua[a] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
        print(f"{a}: selesai", file=sys.stderr)
        for h, v in (semua[a].get("horizon") or {}).items():
            m = v["model"]
            print(f"  {a:9} h={h:>2} n={v['titik']:5} QLIKE base {m['SIGMA90']['qlike']:.4f} "
                  f"EWMA {m['EWMA']['qlike']:.4f} (p {m['EWMA']['p_dm']}) "
                  f"GARCH {m['GARCH']['qlike']:.4f} (p {m['GARCH']['p_dm']}) | cak80 "
                  f"{m['SIGMA90']['cakupan_80']}/{m['EWMA']['cakupan_80']}/"
                  f"{m['GARCH']['cakupan_80']}")
    v = vonis(semua)
    for h, isi in v.items():
        print(f"h={h}: {isi['vonis']}")
        for m in ("EWMA", "GARCH"):
            print(f"   {m}: {isi[m]}")
    with open(HASIL_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"didaftarkan": "2026-10-28", "aset": semua, "vonis": v}, f,
                  ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

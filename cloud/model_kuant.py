"""Model kuant penggabung sinyal — satu skor & PELUANG terkalibrasi, bukan penimbangan naratif.

Sebelum model ini, kesimpulan arah disusun model bahasa yang membaca ~60 rb token brief dan
menimbang sinyal secara naratif ("konfluensi 3 kategori"). Di sini KODE yang menghitung:

  1. Fitur mingguan (Jumat, point-in-time), masing-masing dinormalkan dengan z-score bergulir
     104 minggu yang hanya memakai masa lalu -> tanh -> [-1, 1] (jam_likuiditas.skor).
  2. Bobot tiap fitur = IC Spearman fitur vs return BTC h minggu ke depan pada DATA LATIH.
     Skor gabungan = sum(bobot x fitur) / sum(|bobot|). Fitur yang belum ada datanya = 0.
  3. Skor gabungan -> P(return > 0) lewat regresi logistik satu variabel (data latih).

Data latih hanya memakai target yang SUDAH TERWUJUD sebelum titik prediksi (jeda = h minggu),
sehingga return tumpang tindih tidak bocor ke titik uji. Uji walk-forward per tahun dan
kriteria adopsi ada di uji_model_kuant.py (didaftarkan sebelum dijalankan).

    python cloud/model_kuant.py            # prediksi terkini (JSON)
    python cloud/model_kuant.py --ringkas  # untuk brief bot
"""
import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jam_likuiditas as jl  # noqa: E402

MULAI = date(2014, 10, 3)        # harga Yahoo BTC-USD mulai Sep 2014
HORIZON = (12, 4)                # utama dulu
STATUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                           "model_kuant_uji.json")

FITUR = ("likuiditas", "mom_4", "mom_12", "mom_26", "mom_52", "tren_200h", "vol_30h",
         "rsi_14", "jarak_puncak", "fear_greed", "basis_cme", "funding")


# ------------------------------------------------------------------ statistik kecil
def peringkat(x):
    urut = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(urut):
        j = i
        while j + 1 < len(urut) and x[urut[j + 1]] == x[urut[i]]:
            j += 1
        for k in range(i, j + 1):
            r[urut[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a, b):
    pas = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pas) < 20:
        return None
    ra, rb = peringkat([p[0] for p in pas]), peringkat([p[1] for p in pas])
    n = len(pas)
    ma, mb = sum(ra) / n, sum(rb) / n
    kov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return kov / (va * vb) if va and vb else None


def logistik(xs, ys, l2=1.0, iterasi=50):
    """P(y=1) = sigmoid(a + b x). Newton-Raphson dengan L2 kecil pada b (stabil)."""
    a, b = 0.0, 0.0
    for _ in range(iterasi):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in zip(xs, ys):
            p = 1 / (1 + math.exp(-(a + b * x)))
            w = p * (1 - p)
            ga += y - p
            gb += (y - p) * x
            haa += w
            hab += w * x
            hbb += w * x * x
        gb -= l2 * b
        hbb += l2
        det = haa * hbb - hab * hab
        if det <= 1e-12:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        a, b = a + da, b + db
        if abs(da) + abs(db) < 1e-9:
            break
    return a, b


def sigmoid(z):
    return 1 / (1 + math.exp(-z))


# ------------------------------------------------------------------ fitur
def _harga_pada(harga, tgl, mundur=4):
    for i in range(mundur + 1):
        p = harga.get((tgl - timedelta(days=i)).isoformat())
        if p:
            return p
    return None


def _rsi(tutup, n=14):
    if len(tutup) <= n:
        return None
    naik = turun = 0.0
    for i in range(1, n + 1):
        d = tutup[i] - tutup[i - 1]
        naik += max(d, 0)
        turun += max(-d, 0)
    naik, turun = naik / n, turun / n
    for i in range(n + 1, len(tutup)):
        d = tutup[i] - tutup[i - 1]
        naik = (naik * (n - 1) + max(d, 0)) / n
        turun = (turun * (n - 1) + max(-d, 0)) / n
    return 100.0 if turun == 0 else 100 - 100 / (1 + naik / turun)


def fitur_harga(harga, jumat):
    """Fitur dari harga harian sampai DAN TERMASUK Jumat itu (penutupan hari Jumat UTC)."""
    hari = sorted(harga)
    idx = {t: i for i, t in enumerate(hari)}
    tutup = [harga[t] for t in hari]
    puncak, mx = [], 0.0
    for c in tutup:
        mx = max(mx, c)
        puncak.append(mx)
    keluar = {k: [] for k in ("mom_4", "mom_12", "mom_26", "mom_52", "tren_200h", "vol_30h",
                              "rsi_14", "jarak_puncak")}
    for f in jumat:
        i = idx.get(f.isoformat())
        if i is None or i < 365:
            for k in keluar:
                keluar[k].append(None)
            continue
        p = tutup[i]
        for w in (4, 12, 26, 52):
            lalu = _harga_pada(harga, f - timedelta(days=7 * w))
            keluar[f"mom_{w}"].append(math.log(p / lalu) if lalu else None)
        keluar["tren_200h"].append(math.log(p / (sum(tutup[i - 199:i + 1]) / 200)))
        r = [math.log(tutup[j] / tutup[j - 1]) for j in range(i - 29, i + 1)]
        m = sum(r) / len(r)
        keluar["vol_30h"].append(math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)))
        keluar["rsi_14"].append(_rsi(tutup[i - 150:i + 1]))
        keluar["jarak_puncak"].append(math.log(p / puncak[i]))
    return keluar


def bangun_fitur(jumat, harga, likuiditas, fng=None, basis=None, funding=None):
    """{nama: deret skor [-1,1] atau None} — semua sudah dinormalkan bergulir."""
    import gelombang as gl
    mentah = fitur_harga(harga, jumat)
    if fng:
        mentah["fear_greed"] = gl.ke_mingguan(fng, jumat)
    if basis:
        mentah["basis_cme"] = gl.ke_mingguan(basis, jumat)
    if funding:
        mentah["funding"] = gl.ke_mingguan(funding, jumat)
    fit = {k: jl.skor(v, k=0) for k, v in mentah.items()}
    fit["likuiditas"] = list(likuiditas)          # sudah skor [-1,1]
    return {k: fit.get(k, [None] * len(jumat)) for k in FITUR}


def target(jumat, harga, h):
    """log-return dari penutupan Sabtu (t+1) ke t+1+7h — sama dengan uji_jam_likuiditas."""
    keluar = []
    for f in jumat:
        a = harga.get((f + timedelta(days=1)).isoformat())
        b = harga.get((f + timedelta(days=1 + 7 * h)).isoformat())
        keluar.append(math.log(b / a) if a and b else None)
    return keluar


# ------------------------------------------------------------------ model
def latih(fit, y, idx_latih):
    """Bobot IC + logistik dari baris idx_latih. Return dict model."""
    bobot = {}
    for k, s in fit.items():
        ic = spearman([s[i] for i in idx_latih], [y[i] for i in idx_latih])
        bobot[k] = ic or 0.0
    skor_l = [gabung(fit, bobot, i) for i in idx_latih]
    pas = [(s, 1 if y[i] > 0 else 0) for s, i in zip(skor_l, idx_latih)
           if s is not None and y[i] is not None]
    a, b = logistik([p[0] for p in pas], [p[1] for p in pas])
    dasar = sum(p[1] for p in pas) / len(pas) if pas else 0.5
    return {"bobot": bobot, "a": a, "b": b, "laju_dasar": dasar, "n_latih": len(pas)}


def gabung(fit, bobot, i):
    total = sum(abs(w) for w in bobot.values())
    if not total:
        return None
    s = sum(w * (fit[k][i] if fit[k][i] is not None else 0.0) for k, w in bobot.items())
    return s / total


def peluang(model, skor):
    return sigmoid(model["a"] + model["b"] * skor)


def indeks_latih(jumat, y, sampai, h):
    """Baris yang targetnya sudah TERWUJUD sebelum `sampai` (titik prediksi)."""
    batas = sampai - timedelta(days=7 * h + 1)
    return [i for i, f in enumerate(jumat) if f <= batas and y[i] is not None]


# ------------------------------------------------------------------ data & keluaran
def muat_data(hari_ini=None):
    import gelombang as gl
    hari_ini = hari_ini or datetime.now(timezone.utc).date()
    harga = jl.harga_yahoo("BTC-USD")
    jumat = jl.jumat_dari(MULAI, hari_ini)
    fred, gagal = jl.ambil_fred()
    if gagal:
        raise RuntimeError(f"FRED gagal: {gagal}")
    fred.pop("_cadangan", None)
    jumat_jl = jl.jumat_dari(date.fromisoformat(jl.MULAI), hari_ini)
    L = jl.deret_likuiditas(fred, jumat_jl)
    peta = dict(zip(jumat_jl, L["likuiditas"]))
    likuiditas = [peta.get(f) for f in jumat]
    try:
        fng = gl.fear_greed()
    except Exception:
        fng = None
    try:
        basis = gl.basis_cme(gl.spot_jam_cme(), jl.harga_yahoo("BTC=F"))
    except Exception:
        basis = None
    try:
        funding, _ = gl.funding_harian()
    except Exception:
        funding = None
    fit = bangun_fitur(jumat, harga, likuiditas, fng, basis, funding)
    return jumat, harga, fit


def _muat_status():
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def status_horizon(h):
    return ((_muat_status().get("horizon") or {}).get(str(h))) or {}


def peluang_likuiditas(jumat, liq, harga, i, h=12):
    """Versi 'likuiditas_saja' (yang lolos uji walk-forward 12 minggu): logistik skor
    Liquidity -> P(BTC naik h minggu), dilatih HANYA pada minggu yang targetnya sudah
    terwujud sebelum Jumat ke-i. None bila versi itu tidak diadopsi untuk horizon h."""
    uji = status_horizon(h)
    if uji.get("versi") != "likuiditas_saja" or liq[i] is None:
        return None
    y = target(jumat, harga, h)
    pas = [(liq[j], 1 if y[j] > 0 else 0) for j in indeks_latih(jumat, y, jumat[i], h)
           if liq[j] is not None]
    if len(pas) < 100:
        return None
    a, b = logistik(*zip(*pas))
    return {"horizon_minggu": h,
            "peluang_btc_naik_persen": round(sigmoid(a + b * liq[i]) * 100),
            "laju_dasar_naik_persen": round(sum(p[1] for p in pas) / len(pas) * 100),
            "uji_walk_forward": (f"OOS 2019-26 IC {uji['ic_oos']:+.2f} p {uji['p_placebo']} "
                                 f"BrierSkill {uji['brier_skill']:+.3f} thn+ "
                                 f"{uji['tahun_positif']}; gabungan 12 sinyal GAGAL "
                                 f"(IC {uji.get('ic_oos_gabungan', 0):+.2f})"),
            "keandalan_oos": uji.get("keandalan"),
            # Menempel pada angkanya: uji jawaban 16 Okt menyebut "weekly uptrend vs peluang
            # 38% — dua kategori berlawanan, tidak ada arah", padahal tren itulah yang gagal.
            "cara_pakai": ("Arah 12 mg MENGIKUTI angka ini. Tren/momentum/RSI gagal uji OOS: "
                           "sebut sebagai kondisi, BUKAN penyeimbang setara.")}


def analisa(hari_ini=None):
    """Prediksi terkini per horizon, sesuai versi yang diadopsi uji_model_kuant.py."""
    hari_ini = hari_ini or datetime.now(timezone.utc).date()
    jumat, harga, fit = muat_data(hari_ini)
    i = max(k for k, f in enumerate(jumat) if fit["likuiditas"][k] is not None)
    hasil = {"sinyal_jumat": jumat[i].isoformat(), "aset": "BTC", "per_horizon": []}
    for h in HORIZON:
        uji = status_horizon(h)
        if not uji:
            hasil["per_horizon"].append({"horizon_minggu": h, "tidak_dipakai": "BELUM DIUJI"})
        elif not uji.get("diadopsi"):
            hasil["per_horizon"].append({"horizon_minggu": h, "tidak_dipakai": uji["vonis"]})
        elif uji["versi"] == "likuiditas_saja":
            hasil["per_horizon"].append(peluang_likuiditas(jumat, fit["likuiditas"], harga, i, h))
        else:
            y = target(jumat, harga, h)
            m = latih(fit, y, indeks_latih(jumat, y, jumat[i], h))
            s = gabung(fit, m["bobot"], i)
            total = sum(abs(w) for w in m["bobot"].values())
            kontribusi = sorted(((k, w * (fit[k][i] or 0.0) / total)
                                 for k, w in m["bobot"].items() if w), key=lambda t: -abs(t[1]))
            hasil["per_horizon"].append({
                "horizon_minggu": h, "peluang_btc_naik_persen": round(peluang(m, s) * 100),
                "laju_dasar_naik_persen": round(m["laju_dasar"] * 100),
                "skor_gabungan": round(s, 3),
                "kontribusi_terbesar": [{"fitur": k, "sumbangan": round(c, 3)}
                                        for k, c in kontribusi[:5]]})
    hasil["wajib_dibaca"] = WAJIB_DIBACA
    return hasil


WAJIB_DIBACA = (
    "Peluang ini DIHITUNG KODE dari model yang lolos uji walk-forward; jangan menggantinya "
    "dengan penimbangan naratif. Gabungan 12 sinyal (momentum, tren, RSI, volatilitas, "
    "sentimen, basis, funding + Liquidity) GAGAL di data yang belum dilihat — konfluensi "
    "teknikal tidak boleh dipakai untuk membantah angka ini. Bandingkan dengan laju dasar. "
    "Horizon dalam minggu, bukan arah besok. Horizon 4 minggu: tidak ada model yang lolos.")


# ------------------------------------------------------------------ uji MAJU
# Walk-forward 2019-2026 masih riwayat. Uji maju mencatat prediksi SEBELUM hasilnya ada,
# lalu menilainya sesudah h minggu: satu-satunya bukti yang tidak mungkin bocor.
MAJU_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kuant_maju.jsonl")


def _muat_maju():
    try:
        with open(MAJU_PATH, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except OSError:
        return []


def _tulis_maju(baris):
    with open(MAJU_PATH, "w", encoding="utf-8", newline="\n") as f:
        for b in baris:
            f.write(json.dumps(b, ensure_ascii=False) + "\n")


def catat_maju(jumat, peluang, laju_dasar, h=12):
    """Satu prediksi per Jumat per horizon; tidak menimpa yang sudah ada."""
    baris = _muat_maju()
    if any(b["jumat"] == jumat and b["horizon_minggu"] == h for b in baris):
        return False
    baris.append({"jumat": jumat, "horizon_minggu": h, "peluang_naik_persen": peluang,
                  "laju_dasar_persen": laju_dasar,
                  "dicatat_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    _tulis_maju(baris)
    return True


def nilai_maju(harga, hari_ini=None):
    """Isi hasil untuk prediksi yang jendelanya sudah lewat. Return jumlah yang baru dinilai."""
    hari_ini = hari_ini or datetime.now(timezone.utc).date()
    baris, baru = _muat_maju(), 0
    for b in baris:
        if "naik" in b:
            continue
        f = date.fromisoformat(b["jumat"])
        akhir = f + timedelta(days=1 + 7 * b["horizon_minggu"])
        if akhir >= hari_ini:
            continue
        r = target([f], harga, b["horizon_minggu"])[0]
        if r is not None:
            b["naik"] = r > 0
            b["return_persen"] = round((math.exp(r) - 1) * 100, 2)
            baru += 1
    if baru:
        _tulis_maju(baris)
    return baru


def ringkas_maju():
    """Brier model vs laju dasar pada prediksi maju yang sudah dinilai."""
    dinilai = [b for b in _muat_maju() if "naik" in b]
    total = len(_muat_maju())
    if not dinilai:
        return {"dicatat": total, "dinilai": 0,
                "catatan": "belum ada prediksi maju yang jatuh tempo (horizon 12 minggu)"}
    o = [1 if b["naik"] else 0 for b in dinilai]
    bs = sum((b["peluang_naik_persen"] / 100 - y) ** 2 for b, y in zip(dinilai, o)) / len(o)
    bs0 = sum((b["laju_dasar_persen"] / 100 - y) ** 2 for b, y in zip(dinilai, o)) / len(o)
    return {"dicatat": total, "dinilai": len(dinilai), "brier": round(bs, 4),
            "brier_laju_dasar": round(bs0, 4), "brier_skill": round(1 - bs / bs0, 3) if bs0 else None,
            "catatan": ("sampel kecil — prediksi 12 minggu tumpang tindih, ~4 prediksi "
                        "independen per tahun" if len(dinilai) < 26 else "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ringkas", action="store_true")
    ap.add_argument("--maju", action="store_true",
                    help="catat prediksi minggu ini + nilai yang jatuh tempo (workflow mingguan)")
    a = ap.parse_args()
    if a.maju:
        h = analisa()
        harga = jl.harga_yahoo("BTC-USD")
        for p in h["per_horizon"]:
            if p and "peluang_btc_naik_persen" in p:
                catat_maju(h["sinyal_jumat"], p["peluang_btc_naik_persen"],
                           p["laju_dasar_naik_persen"], p["horizon_minggu"])
        print("baru dinilai:", nilai_maju(harga), "·", json.dumps(ringkas_maju(),
                                                                ensure_ascii=False))
        return
    try:
        h = analisa()
    except Exception as e:
        h = {"tidak_tersedia": f"{type(e).__name__}: {str(e)[:150]}"}
    print(json.dumps(h, ensure_ascii=False, separators=(",", ":") if a.ringkas else None,
                     indent=None if a.ringkas else 2))


if __name__ == "__main__":
    main()

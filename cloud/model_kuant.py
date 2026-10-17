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


def status_aset(aset, h=12):
    """BTC dari 'horizon' (uji_model_kuant.py); ETH/SOL dari 'aset' (uji_model_kuant_altcoin.py)."""
    st = _muat_status()
    if aset == "BTC":
        return (st.get("horizon") or {}).get(str(h)) or {}
    return ((st.get("aset") or {}).get(aset) or {}).get(str(h)) or {}


def _keranjang(p):
    return "<45%" if p < .45 else "45-55%" if p < .55 else "55-65%" if p < .65 else ">=65%"


def peringatan_keranjang(uji, p):
    """Penjaga PENYAJIAN (ditambahkan sesudah melihat uji ETH, 16 Okt 2026 — dicatat terbuka):
    bila keranjang ramalan saat ini terbukti TERBALIK di data uji (>= 30 minggu), angkanya
    tidak boleh dibaca sebagai arah. ETH: ramalan <45% -> nyatanya naik 63% dari 126 minggu."""
    k = (uji.get("keandalan") or {}).get(_keranjang(p))
    if not k:
        return None
    try:
        terjadi = float(k.split()[1].rstrip("%")) / 100
        n = int(k.split("N=")[-1].rstrip(")"))
    except (IndexError, ValueError):
        return None
    if n >= 30 and (p - 0.5) * (terjadi - 0.5) < 0:
        return (f"TIDAK TERKALIBRASI di rentang ini: ramalan {_keranjang(p)} di data uji "
                f"nyatanya naik {terjadi * 100:.0f}% ({n} minggu) — JANGAN dipakai sebagai arah")
    return None


def peluang_aset(jumat, liq, harga, i, aset="BTC", h=12):
    """Versi 'likuiditas_saja' yang lolos uji walk-forward untuk aset itu: logistik skor
    Liquidity -> P(aset naik h minggu), dilatih HANYA pada minggu yang targetnya sudah
    terwujud sebelum Jumat ke-i. None bila versi itu tidak diadopsi untuk aset/horizon ini."""
    uji = status_aset(aset, h)
    if uji.get("versi") != "likuiditas_saja" or liq[i] is None:
        return None
    maju = teks_maju(aset) if h == 12 else ""
    if maju.endswith("vonis GAGAL"):
        # Aturan uji maju yang didaftarkan 17 Okt 2026: angka tidak ditampilkan lagi.
        return {"horizon_minggu": h, "gagal_uji_maju": maju,
                "cara_pakai": (f"Model peluang {aset} GAGAL uji maju (lebih buruk dari laju "
                               "dasar pada prediksi yang dicatat sebelum hasilnya ada). Tidak "
                               "ada peluang terkalibrasi untuk arah 12 mg aset ini.")}
    y = target(jumat, harga, h)
    pas = [(liq[j], 1 if y[j] > 0 else 0) for j in indeks_latih(jumat, y, jumat[i], h)
           if liq[j] is not None]
    if len(pas) < 100:
        return None
    a, b = logistik(*zip(*pas))
    p = sigmoid(a + b * liq[i])
    tahun = uji.get("tahun_uji") or "2019-26"
    hasil = {"horizon_minggu": h,
             f"peluang_{aset.lower()}_naik_persen": round(p * 100),
             "laju_dasar_naik_persen": round(sum(x[1] for x in pas) / len(pas) * 100),
             "uji_walk_forward": (f"OOS {tahun} IC {uji['ic_oos']:+.2f} p {uji['p_placebo']} "
                                  f"BrierSkill {uji['brier_skill']:+.3f} thn+ "
                                  f"{uji['tahun_positif']}"
                                  + (f"; gabungan 12 sinyal GAGAL (IC "
                                     f"{uji['ic_oos_gabungan']:+.2f})"
                                     if "ic_oos_gabungan" in uji else "")),
             "keandalan_oos": uji.get("keandalan"),
             # Menempel pada angkanya: uji jawaban 16 Okt menyebut "weekly uptrend vs peluang
             # 38% — dua kategori berlawanan, tidak ada arah", padahal tren itulah yang gagal.
             "cara_pakai": ("Arah 12 mg MENGIKUTI angka ini. Tren/momentum/RSI gagal uji OOS: "
                            "sebut sebagai kondisi, BUKAN penyeimbang setara.")}
    if maju:
        hasil["uji_maju"] = maju
    w = peringatan_keranjang(uji, p)
    if w:
        hasil["peringatan_kalibrasi"] = w
        hasil["cara_pakai"] = ("Sebut angkanya bersama peringatan_kalibrasi; JANGAN jadikan "
                               "arah. Arah 12 mg untuk aset ini: tidak ada yang terkalibrasi.")
    return hasil


def peluang_likuiditas(jumat, liq, harga, i, h=12):
    """BTC — dipertahankan untuk pemanggil lama."""
    return peluang_aset(jumat, liq, harga, i, "BTC", h)


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
#
# ATURAN VONIS — DIDAFTARKAN 17 Okt 2026, SEBELUM satu pun prediksi jatuh tempo (yang
# pertama baru Jan 2027). Per aset, horizon 12 minggu, Brier model vs laju dasar yang
# dicatat bersama prediksinya:
#   dinilai <  26                        -> BELUM (angka tetap tampil, berlabel sampel kecil)
#   dinilai >= 26 dan Brier skill < -0,05 -> GAGAL (stop dini: jelas lebih buruk dari laju dasar)
#   dinilai >= 52 dan Brier skill <= 0    -> GAGAL
#   dinilai >= 52 dan Brier skill >  0    -> BERTAHAN
# GAGAL -> peluang_aset TIDAK lagi menampilkan angkanya (bot & Telegram), tanpa campur tangan.
# Prediksi mingguan 12 minggu tumpang tindih: 52 prediksi ~ 13 pengamatan independen, jadi
# BERTAHAN berarti "belum terbantah", bukan "terbukti". Ambang tidak boleh diubah sesudah
# hasil terlihat.
MAJU_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kuant_maju.jsonl")
MAJU_STOP_DINI, MAJU_VONIS, MAJU_BATAS_DINI = 26, 52, -0.05


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


def _aset_baris(b):
    return b.get("aset", "BTC")          # baris lama (sebelum ETH ikut) semuanya BTC


def catat_maju(jumat, peluang, laju_dasar, h=12, aset="BTC"):
    """Satu prediksi per Jumat per horizon per aset; tidak menimpa yang sudah ada."""
    baris = _muat_maju()
    if any(b["jumat"] == jumat and b["horizon_minggu"] == h and _aset_baris(b) == aset
           for b in baris):
        return False
    baris.append({"jumat": jumat, "aset": aset, "horizon_minggu": h,
                  "peluang_naik_persen": peluang, "laju_dasar_persen": laju_dasar,
                  "dicatat_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    _tulis_maju(baris)
    return True


def nilai_maju(harga, hari_ini=None):
    """Isi hasil untuk prediksi yang jendelanya sudah lewat. `harga`: {aset: {tgl: harga}}
    (atau satu dict harga BTC, bentuk lama). Return jumlah yang baru dinilai."""
    if harga and not isinstance(next(iter(harga.values())), dict):
        harga = {"BTC": harga}
    hari_ini = hari_ini or datetime.now(timezone.utc).date()
    baris, baru = _muat_maju(), 0
    for b in baris:
        hg = harga.get(_aset_baris(b))
        if "naik" in b or not hg:
            continue
        f = date.fromisoformat(b["jumat"])
        akhir = f + timedelta(days=1 + 7 * b["horizon_minggu"])
        if akhir >= hari_ini:
            continue
        r = target([f], hg, b["horizon_minggu"])[0]
        if r is not None:
            b["naik"] = r > 0
            b["return_persen"] = round((math.exp(r) - 1) * 100, 2)
            baru += 1
    if baru:
        _tulis_maju(baris)
    return baru


def ringkas_maju(aset="BTC", h=12):
    """Brier model vs laju dasar pada prediksi maju aset itu yang sudah dinilai + vonis."""
    semua = [b for b in _muat_maju() if _aset_baris(b) == aset and b["horizon_minggu"] == h]
    dinilai = [b for b in semua if "naik" in b]
    if not dinilai:
        return {"dicatat": len(semua), "dinilai": 0, "vonis": "BELUM",
                "catatan": f"belum ada prediksi maju yang jatuh tempo (horizon {h} minggu)"}
    o = [1 if b["naik"] else 0 for b in dinilai]
    bs = sum((b["peluang_naik_persen"] / 100 - y) ** 2 for b, y in zip(dinilai, o)) / len(o)
    bs0 = sum((b["laju_dasar_persen"] / 100 - y) ** 2 for b, y in zip(dinilai, o)) / len(o)
    skill = round(1 - bs / bs0, 3) if bs0 else None
    n = len(dinilai)
    if skill is not None and (n >= MAJU_VONIS and skill <= 0
                              or n >= MAJU_STOP_DINI and skill < MAJU_BATAS_DINI):
        vonis = "GAGAL"
    elif skill is not None and n >= MAJU_VONIS:
        vonis = "BERTAHAN"
    else:
        vonis = "BELUM"
    return {"dicatat": len(semua), "dinilai": n, "brier": round(bs, 4),
            "brier_laju_dasar": round(bs0, 4), "brier_skill": skill, "vonis": vonis,
            "catatan": (f"sampel kecil — vonis di {MAJU_VONIS} prediksi jatuh tempo; prediksi "
                        "12 minggu tumpang tindih, ~4 independen per tahun"
                        if vonis == "BELUM" else "")}


def teks_maju(aset="BTC"):
    """Satu baris status uji maju untuk brief & Telegram; '' bila belum ada catatan."""
    rm = ringkas_maju(aset)
    if not rm.get("dicatat"):
        return ""
    t = f"{rm['dinilai']}/{rm['dicatat']} prediksi jatuh tempo"
    if rm.get("brier_skill") is not None:
        t += f", Brier skill {rm['brier_skill']:+.3f}"
    return t + (f" — vonis {rm['vonis']}" if rm["vonis"] != "BELUM"
                else f" (vonis di {MAJU_VONIS})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ringkas", action="store_true")
    ap.add_argument("--maju", action="store_true",
                    help="catat prediksi minggu ini + nilai yang jatuh tempo (workflow mingguan)")
    a = ap.parse_args()
    if a.maju:
        h = analisa()
        harga = {"BTC": jl.harga_yahoo("BTC-USD")}
        for p in h["per_horizon"]:
            if p and "peluang_btc_naik_persen" in p:
                catat_maju(h["sinyal_jumat"], p["peluang_btc_naik_persen"],
                           p["laju_dasar_naik_persen"], p["horizon_minggu"])
        # ETH ikut dicatat sejak 17 Okt 2026 — termasuk saat peringatan_kalibrasi aktif:
        # yang dinilai modelnya, bukan hanya minggu-minggu yang tampak bagus.
        if status_aset("ETH").get("diadopsi"):
            try:
                harga["ETH"] = jl.harga_yahoo("ETH-USD")
                jumat, _, fit = muat_data()
                i = max(k for k, f in enumerate(jumat) if fit["likuiditas"][k] is not None)
                pe = peluang_aset(jumat, fit["likuiditas"], harga["ETH"], i, "ETH")
                if pe and "peluang_eth_naik_persen" in pe:
                    catat_maju(jumat[i].isoformat(), pe["peluang_eth_naik_persen"],
                               pe["laju_dasar_naik_persen"], 12, "ETH")
            except Exception as e:
                print("ETH tidak dicatat:", type(e).__name__, file=sys.stderr)
        print("baru dinilai:", nilai_maju(harga), "·",
              json.dumps({k: ringkas_maju(k) for k in harga}, ensure_ascii=False))
        return
    try:
        h = analisa()
    except Exception as e:
        h = {"tidak_tersedia": f"{type(e).__name__}: {str(e)[:150]}"}
    print(json.dumps(h, ensure_ascii=False, separators=(",", ":") if a.ringkas else None,
                     indent=None if a.ringkas else 2))


if __name__ == "__main__":
    main()

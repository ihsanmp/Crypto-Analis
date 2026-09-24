"""Regresi logaritmik BTC — chart 2014 yang ditanam, lalu DIUJI terhadap yang terjadi sesudahnya.

ASALNYA: chart "Logarithmic (non linear) Regression" dari BitcoinTalk (Trolololo, v1,
14 Okt 2014), dikirim user 24 Sep 2026. Isinya satu rumus:

    log10(harga) = 2,9065 · ln(hari sejak 9 Jan 2009) − 19,493        R² = 0,9886

(Angka di chart memakai apostrof sebagai tanda desimal: 2'9065, 0'9886.)

BACAAN CHART INI SUDAH DIBUKTIKAN, BUKAN DITAFSIRKAN. Rumus di atas menghasilkan ulang
semua angka di gambarnya — lihat tes:
  - tonggak $1 / $10 / $100 / $1rb / $10rb / $100rb jatuh di tanggal yang tercetak di
    chart (6 Apr 2011 … 16 Jul 2021), meleset paling jauh 3 hari (pembulatan a dan b);
  - deretan angka di atas chart (0,004 · 0,44 · 6,77 · … · 332.632) adalah nilai garis di
    AKHIR tiap tahun — labelnya diletakkan di awal tahun;
  - jeda antar-10x (336 · 474 · 669 · 943 · 1.332 hari) tumbuh dengan rasio tetap 1,41;
  - PERSEN di chart adalah KELIPATAN × 100, bukan kenaikan: "159%" = 1,59× setahun (naik
    59%), "262%" di baris hijau = naik 162%. Satu-satunya pengecualian `[-46%]` dalam
    kurung — perubahan 2014 hingga tanggal chart. Salah membaca ini melipatgandakan
    "pertumbuhan tahunan" yang dikutip orang dari chart ini.
Hari nol-nya 9 Jan 2009 (rilis Bitcoin v0.1), bukan blok genesis 3 Jan: dengan 3 Jan
semua tonggak bergeser 6-9 hari.

YANG DITANAM BUKAN CHART-NYA, MELAINKAN UJIANNYA. Chart ini dibuat Oktober 2014; ada 12
tahun data sesudahnya yang tidak pernah ia lihat. Diuji pada data itu (Bitstamp harian di
repo ini):
  - harga berada DI ATAS garis 2014 hanya 53 dari 4.340 hari (1,2%, per 1 Sep 2026), dan
    KE-53 HARI ITU SEMUANYA di puncak gelembung Des 2017–Jan 2018 (terakhir 28 Jan 2018).
    Di luar sampelnya, garis yang seharusnya "tengah" bekerja sebagai garis PUNCAK siklus
    — lalu sejak itu tak pernah tersentuh lagi;
  - ramalan $10rb meleset 10 hari (21 Nov vs 1 Des 2017 — luar biasa), tapi ramalan
    $100rb terlambat 1.244 hari (13 Jul 2021 vs 8 Des 2024);
  - garisnya kini di ~$1 juta sementara harga di kisaran $80rb.
Satu tebakan jitu tidak menyelamatkan sebuah model; yang dihitung adalah semuanya.

TIGA HAL YANG BUKAN BUKTI, dan harus disebut begitu kalau muncul:
  1. R² tinggi. Autokorelasi residu lag-1 = 0,998: simpangan dari garis bertahan
     bertahun-tahun, jadi hampir seluruh R² berasal dari kenaikan jangka panjang yang
     sudah diketahui — bukan dari kemampuan meramal titik berikutnya.
  2. "Tiap 10x makin lama 1,41×". Itu e^(1/a) — konsekuensi bentuk rumusnya sendiri,
     bukan temuan terpisah. Mengutipnya sebagai bukti tambahan berarti menghitung satu
     asumsi dua kali.
  3. Nilai "wajar" hari ini. Fit ulang pada data s.d. 2017, s.d. 2021, dan s.d. kini
     memberi garis yang berbeda puluhan persen untuk hari yang sama — tergantung di
     mana datanya dipotong. Garis yang bergeser sejauh itu tidak bisa jadi jangkar harga.

BATAS DATA: riwayat di repo mulai 1 Jan 2012, sedangkan chart asli memakai data sejak
2010. Parameter fit ulang karena itu TIDAK bisa dibandingkan langsung dengan 2,9065.

Pemakaian:
    python cloud/logregresi.py --ringkas
    python cloud/logregresi.py --ringkas --harga 84156
    python cloud/logregresi.py --json --offline
"""

import argparse
import csv
import datetime as dt
import gzip
import json
import math
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(BASE_DIR, "data", "btc_daily_bitstamp.csv.gz")

# --- Chart 2014, apa adanya ----------------------------------------------------------------
A_2014 = 2.9065
B_2014 = -19.493
R2_2014 = 0.9886
NOL = dt.date(2009, 1, 9)
TGL_CHART = dt.date(2014, 10, 14)
# Tonggak yang tercetak di chart — dipakai tes untuk membuktikan bacaannya.
TONGGAK_CHART = {1: "2011-04-06", 10: "2012-03-07", 100: "2013-06-24", 1000: "2015-04-24",
                 10000: "2017-11-22", 100000: "2021-07-16"}

# --- Parameter uji, ditetapkan SEBELUM melihat hasil ---------------------------------------
# Titik potong kepekaan dipilih di akhir tiap siklus besar yang sudah selesai, bukan
# dicari-cari sampai perbedaannya terlihat dramatis.
POTONG_KEPEKAAN = (dt.date(2017, 12, 31), dt.date(2021, 12, 31))
# Tonggak ramalan yang diperiksa terhadap kenyataan: semua yang tanggalnya SESUDAH chart.
TONGGAK_UJI = (10000, 100000, 1000000)


def garis(tgl, a=A_2014, b=B_2014):
    """Nilai garis (USD) pada tanggal tertentu."""
    return 10 ** (a * math.log((tgl - NOL).days) + b)


def tanggal_untuk(harga, a=A_2014, b=B_2014):
    """Tanggal ketika garis mencapai harga ini."""
    return NOL + dt.timedelta(days=math.exp((math.log10(harga) - b) / a))


def rasio_10x(a):
    """Berapa kali lebih lama tiap kenaikan 10x berikutnya — e^(1/a), BAWAAN rumus."""
    return math.exp(1 / a)


def muat(jalur=CSV):
    """{tanggal: close} dari riwayat harian di repo."""
    data = {}
    with gzip.open(jalur, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                c = float(r["close"])
            except (TypeError, ValueError):
                continue
            if c > 0:
                data[dt.date.fromisoformat(r["dt"][:10])] = c
    return data


def tambah_terbaru(data):
    """Sambung riwayat dengan candle harian terbaru. (data, sumber | None, galat | None).

    CSV di repo tidak diperbarui otomatis oleh runner, jadi celahnya melebar tiap hari.
    Gagal menyambung TIDAK menggagalkan hasil — tanggal akhir datanya yang disebut.
    """
    try:
        from indicators import fetch_base, resolve_cg_id
        candles, sumber, _kualitas, err = fetch_base("BTC", resolve_cg_id("BTC"), "1d")
    except Exception as e:
        return data, None, type(e).__name__
    if not candles:
        return data, None, err or "tidak ada candle"
    akhir = max(data)
    baru = dict(data)
    for c in candles:
        try:
            t = dt.datetime.fromtimestamp(int(c[0]) / 1000, dt.timezone.utc).date()
            harga = float(c[4])
        except (TypeError, ValueError, IndexError):
            continue
        if t > akhir and harga > 0:
            baru[t] = harga          # candle terakhir per tanggal yang dipakai
    return baru, sumber, None


def fit(data):
    """OLS log10(harga) ~ ln(hari). -> (a, b, R², residu[], autokorelasi lag-1)."""
    urut = sorted(data.items())
    xs = [math.log((t - NOL).days) for t, _ in urut]
    ys = [math.log10(c) for _, c in urut]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    b = my - a * mx
    res = [y - (a * x + b) for x, y in zip(xs, ys)]
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1 - sum(r * r for r in res) / ss_tot
    ac1 = sum(res[i] * res[i - 1] for i in range(1, n)) / sum(r * r for r in res)
    return a, b, r2, res, ac1


def analisa(data, harga=None, tgl=None):
    """Semua angka yang boleh dipakai model, dihitung KODE."""
    # Akhir RIWAYAT dicatat sebelum harga dari brief ditempel. Tanpa ini laporannya
    # berbunyi "data s.d. 24 Sep" padahal riwayatnya berhenti 1 Sep dan 24 Sep hanyalah
    # satu titik harga — celah 22 hari yang tidak pernah disebut (run lokal 24 Sep 2026).
    akhir_riwayat = max(data)
    if harga and tgl:
        data = dict(data)
        data[tgl] = harga
    tgl = tgl or max(data)
    harga = data[tgl]
    urut = sorted(data.items())

    # A. Chart 2014 di luar sampelnya sendiri.
    sesudah = [(t, c) for t, c in urut if t > TGL_CHART]
    hari_atas = [t for t, c in sesudah if c > garis(t)]
    di_atas = len(hari_atas)
    ramalan = []
    for p in TONGGAK_UJI:
        t_ramal = tanggal_untuk(p)
        t_nyata = next((t for t, c in urut if c >= p), None)
        ramalan.append({"harga": p, "ramalan_2014": t_ramal.isoformat(),
                        "nyata_close_pertama": t_nyata.isoformat() if t_nyata else None,
                        "selisih_hari": (t_nyata - t_ramal).days if t_nyata else None,
                        "sudah_lewat": t_ramal <= tgl})

    # B. Fit ulang pada seluruh data.
    a, b, r2, res, ac1 = fit(data)
    kini = res[-1]
    persentil = 100 * sum(1 for r in res if r <= kini) / len(res)

    # C. Kepekaan: garis untuk HARI YANG SAMA dari fit dengan potongan data berbeda.
    kepekaan = []
    for batas in POTONG_KEPEKAAN:
        bagian = {t: c for t, c in data.items() if t <= batas}
        if len(bagian) > 365:
            ak, bk, *_ = fit(bagian)
            kepekaan.append({"data_sampai": batas.isoformat(), "a": round(ak, 4),
                             "garis_hari_ini": round(garis(tgl, ak, bk))})
    kepekaan.append({"data_sampai": tgl.isoformat(), "a": round(a, 4), "semua": True,
                     "garis_hari_ini": round(garis(tgl, a, b))})
    nilai = [k["garis_hari_ini"] for k in kepekaan]

    return {
        "tanggal": tgl.isoformat(), "harga": harga,
        "data": {"awal": urut[0][0].isoformat(), "akhir_riwayat": akhir_riwayat.isoformat(),
                 "hari": len(urut),
                 "celah_hari": max(0, (tgl - akhir_riwayat).days - 1)},
        "chart_2014": {
            "rumus": "log10(P) = 2,9065·ln(hari sejak 9 Jan 2009) − 19,493",
            "r2_tercetak": R2_2014, "dibuat": TGL_CHART.isoformat(),
            "garis_hari_ini": round(garis(tgl)), "harga_per_garis": round(harga / garis(tgl), 3),
            "hari_sesudah_chart": len(sesudah), "hari_di_atas_garis": di_atas,
            "persen_di_atas_garis": round(100 * di_atas / len(sesudah), 1) if sesudah else None,
            "pertama_di_atas": hari_atas[0].isoformat() if hari_atas else None,
            "terakhir_di_atas": hari_atas[-1].isoformat() if hari_atas else None,
            "ramalan": ramalan, "rasio_10x_bawaan": round(rasio_10x(A_2014), 2)},
        "fit_ulang": {
            "a": round(a, 4), "b": round(b, 3), "r2": round(r2, 4),
            "autokorelasi_residu_lag1": round(ac1, 3),
            "garis_hari_ini": round(garis(tgl, a, b)),
            "harga_per_garis": round(harga / garis(tgl, a, b), 3),
            "persentil_residu": round(persentil),
            "rentang_historis": [round(10 ** min(res), 2), round(10 ** max(res), 2)],
            "rasio_10x_bawaan": round(rasio_10x(a), 2)},
        "kepekaan": kepekaan,
        "kepekaan_selisih_persen": round(100 * (max(nilai) / min(nilai) - 1)) if nilai else None,
    }


def _d(x, desimal=0):
    """Angka gaya Indonesia: ribuan titik, desimal koma. Satu pintu untuk semua angka —
    `.replace(",", ".")` pada kalimat utuh sempat ikut mengganti koma KALIMAT jadi titik
    ("nyata 8 Des 2024. terlambat")."""
    utuh, _, pecahan = f"{abs(x):,.{desimal}f}".partition(".")
    teks = utuh.replace(",", ".") + ("," + pecahan if pecahan else "")
    return ("-" if x < 0 else "") + teks


def _usd(x):
    return ("-" if x < 0 else "") + "$" + _d(abs(x))


def _tgl(s):
    if not s:
        return "belum"
    t = dt.date.fromisoformat(s)
    bulan = "Jan Feb Mar Apr Mei Jun Jul Agu Sep Okt Nov Des".split()
    return f"{t.day} {bulan[t.month - 1]} {t.year}"


def ringkas(h, sumber_baru=None, galat_baru=None):
    """Blok DATA BRIEF. Setiap kalimat yang bisa disalahpahami membawa batasnya sendiri."""
    c, f, d = h["chart_2014"], h["fit_ulang"], h["data"]
    keterangan = f"Data harian {_tgl(d['awal'])} s.d. {_tgl(d['akhir_riwayat'])}"
    if sumber_baru and not d["celah_hari"]:
        keterangan += f" (hari-hari terbaru dari {sumber_baru})"
    if galat_baru:
        # Cukup inti sebabnya. Daftar enam sumber yang gagal satu per satu tidak menolong
        # model memahami apa pun — hanya menghabiskan ruang brief.
        inti = galat_baru if len(galat_baru) <= 80 else galat_baru[:77].rstrip(" ;,") + "…"
        keterangan += f"; penyambung data terbaru GAGAL ({inti})"
    if d["celah_hari"]:
        keterangan += (f"; harga hari ini ditempel sebagai titik terakhir — "
                       f"{_d(d['celah_hari'])} hari di antaranya TIDAK ADA di data")
    baris = [
        "REGRESI LOGARITMIK BTC — garis tren jangka panjang, BUKAN ramalan harga",
        keterangan,
        f"Harga acuan: {_usd(h['harga'])} ({_tgl(h['tanggal'])})",
        "",
        f"A. Chart asli 2014 (BitcoinTalk, {c['rumus']}, R² tercetak "
        f"{_d(c['r2_tercetak'], 4)})",
        f"   - garis hari ini {_usd(c['garis_hari_ini'])}; harga = "
        f"{_d(c['harga_per_garis'], 3)}× garis",
        f"   - sesudah chart dibuat ({_tgl(c['dibuat'])}), harga di atas garis hanya "
        f"{_d(c['hari_di_atas_garis'])} dari {_d(c['hari_sesudah_chart'])} hari "
        f"({_d(c['persen_di_atas_garis'], 1)}%)"
        + (f", semuanya antara {_tgl(c['pertama_di_atas'])} dan "
           f"{_tgl(c['terakhir_di_atas'])} — di luar sampelnya garis ini bekerja sebagai "
           "garis PUNCAK siklus, bukan garis tengah" if c["pertama_di_atas"] else ""),
    ]
    for r in c["ramalan"]:
        if not r["sudah_lewat"]:
            baris.append(f"   - ramalan {_usd(r['harga'])} jatuh {_tgl(r['ramalan_2014'])} "
                         f"— belum lewat, belum bisa dinilai")
            continue
        if r["selisih_hari"] is None:
            nasib = "harga BELUM PERNAH sampai ke sana"
        elif abs(r["selisih_hari"]) <= 30:
            nasib = f"nyata {_tgl(r['nyata_close_pertama'])}, meleset {abs(r['selisih_hari'])} hari"
        else:
            arah = "terlambat" if r["selisih_hari"] > 0 else "lebih cepat"
            nasib = (f"nyata {_tgl(r['nyata_close_pertama'])}, {arah} "
                     f"{_d(abs(r['selisih_hari']))} hari")
        baris.append(f"   - ramalan {_usd(r['harga'])} {_tgl(r['ramalan_2014'])} → {nasib}")
    baris += [
        "   => garis 2014 SUDAH GAGAL di luar sampelnya sendiri: jangan dipakai sebagai "
        "nilai wajar, target, atau 'harga seharusnya'.",
        "",
        "B. Fit ulang pada seluruh data yang ada (rumus sama, parameter dihitung ulang)",
        f"   - a={_d(f['a'], 4)} b={_d(f['b'], 3)} R²={_d(f['r2'], 4)} → garis hari ini "
        f"{_usd(f['garis_hari_ini'])}; harga = {_d(f['harga_per_garis'], 3)}× garis",
        f"   - posisi: persentil {f['persentil_residu']} dari sejarah simpangannya "
        f"(rentang {_d(f['rentang_historis'][0], 2)}×–{_d(f['rentang_historis'][1], 2)}× "
        "garis). "
        "Ini IN-SAMPLE: fit yang sama dipakai mengukur posisinya sendiri.",
        "   - kepekaan — garis untuk HARI INI menurut fit dengan potongan data berbeda:",
    ]
    for k in h["kepekaan"]:
        label = "seluruh data" if k.get("semua") else f"data s.d. {_tgl(k['data_sampai'])}"
        baris.append(f"       {label}: a={_d(k['a'], 4)} → "
                     f"{_usd(k['garis_hari_ini'])}")
    baris += [
        f"     garis 'wajar' bergeser {h['kepekaan_selisih_persen']}% hanya karena batas "
        "datanya digeser — terlalu goyah untuk jadi jangkar harga.",
        "",
        "C. Yang BUKAN bukti (sebut begitu kalau muncul):",
        f"   - R² tinggi: autokorelasi residu lag-1 = {_d(f['autokorelasi_residu_lag1'], 3)}. "
        "Simpangan bertahan bertahun-tahun, jadi R² tidak mengukur daya ramal.",
        f"   - 'tiap 10x makin lama {_d(c['rasio_10x_bawaan'], 2)}×' di chart 2014 adalah "
        f"e^(1/a) — bawaan rumus, bukan temuan. Fit ulang memberi "
        f"{_d(f['rasio_10x_bawaan'], 2)}×.",
        "   - data di repo mulai 2012, chart asli memakai data sejak 2010: parameter fit ulang "
        "tidak bisa dibandingkan langsung dengan 2,9065.",
    ]
    return "\n".join(baris)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harga", type=float, default=None,
                    help="harga acuan hari ini (dari brief), supaya angkanya konsisten")
    ap.add_argument("--offline", action="store_true", help="tanpa menyambung data terbaru")
    ap.add_argument("--ringkas", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    data = muat()
    sumber, galat = None, None
    if not a.offline:
        data, sumber, galat = tambah_terbaru(data)
    tgl = dt.datetime.now(dt.timezone.utc).date() if a.harga else None
    h = analisa(data, a.harga, tgl)
    if a.json:
        print(json.dumps(h, indent=2, ensure_ascii=False))
        return
    print(ringkas(h, sumber, galat))


if __name__ == "__main__":
    main()

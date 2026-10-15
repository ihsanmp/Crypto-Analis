"""Skor GELOMBANG Adoption Clock: W1 leverage (funding) + W2 sentimen ritel (Fear & Greed).

Gelombang tinggi = kenaikan didorong leverage dan spekulasi. Rancangan: di atas 0,5,
eksposur dikurangi 25 poin persen. Tandanya POSITIF = makin spekulatif (bukan makin bullish).

  W1  Funding perpetual BTCUSDT Binance, rata-rata harian dalam % per 8 jam. Riwayat dari
      arsip publik data.binance.vision (bulanan, sejak Jan 2020) — API fapi Binance
      menolak IP AS, arsip statisnya tidak. Bulan berjalan belum diarsipkan Binance, jadi
      ditambal Coinalyze (kunci ada di Actions) bila tersedia. Disalin ke
      cloud/data/funding_btcusdt_harian.json supaya tidak menarik ulang 80 berkas.
      Basis CME tidak dipakai: datanya berbayar (rancangan: "funding sudah cukup").
  W2  Fear & Greed Index alternative.me, riwayat penuh sejak Feb 2018, gratis.

Skor: level rata-rata mingguan -> z bergulir (104 minggu, minimal 52, hanya masa lalu) ->
tanh. Gelombang = rata-rata W1 & W2, kosong kalau salah satu hilang.
"""
import io
import json
import os
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARSIP = ("https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/"
         "BTCUSDT-fundingRate-{}.zip")
FUNDING_PATH = os.path.join(BASE_DIR, "data", "funding_btcusdt_harian.json")
FNG = "https://api.alternative.me/fng/?limit=0&format=json"
MULAI_FUNDING = date(2020, 1, 1)
UA = {"User-Agent": "riset-pasar/1.0 (research)"}
AMBANG_GELOMBANG = 0.5
POTONG_EKSPOSUR = 0.25


def _get(url, biner=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        b = r.read()
    return b if biner else b.decode("utf-8", errors="replace")


def _bulan(awal, akhir):
    y, m = awal.year, awal.month
    while (y, m) <= (akhir.year, akhir.month):
        yield f"{y}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _urai_csv_binance(teks):
    """{tanggal: [rate % per 8 jam, ...]} — rate dinormalkan ke interval 8 jam."""
    per = {}
    for b in teks.splitlines()[1:]:
        t, jam, r = b.split(",")[:3]
        tgl = datetime.fromtimestamp(int(t) / 1000, timezone.utc).date().isoformat()
        per.setdefault(tgl, []).append(float(r) * 100 * 8 / float(jam or 8))
    return per


def funding_harian(perbarui=True, hari_ini=None):
    """({tanggal: rata2 % per 8 jam}, catatan). Bulan lengkap dari arsip, sisanya Coinalyze."""
    hari_ini = hari_ini or datetime.now(timezone.utc).date()
    try:
        with open(FUNDING_PATH, encoding="utf-8") as f:
            simpan = json.load(f)
    except (OSError, ValueError):
        simpan = {"bulan": [], "harian": {}}
    catatan = []
    if perbarui:
        bulan_lalu = (hari_ini.replace(day=1) - timedelta(days=1))
        baru = [b for b in _bulan(MULAI_FUNDING, bulan_lalu) if b not in simpan["bulan"]]
        for b in baru:
            try:
                z = zipfile.ZipFile(io.BytesIO(_get(ARSIP.format(b), biner=True)))
                per = _urai_csv_binance(z.read(z.namelist()[0]).decode())
            except Exception as e:
                catatan.append(f"arsip {b} gagal ({type(e).__name__})")
                continue
            for t, xs in per.items():
                simpan["harian"][t] = round(sum(xs) / len(xs), 6)
            simpan["bulan"].append(b)
        if baru:
            simpan["bulan"].sort()
            os.makedirs(os.path.dirname(FUNDING_PATH), exist_ok=True)
            with open(FUNDING_PATH, "w", encoding="utf-8", newline="\n") as f:
                json.dump(simpan, f, separators=(",", ":"), sort_keys=True)
    harian = dict(simpan["harian"])
    # Tambalan bulan berjalan. TIDAK disimpan ke salinan — arsip Binance resmi yang menimpa.
    try:
        import coinalyze
        if coinalyze._kunci():
            sim = coinalyze._simbol_btc()
            titik, err = coinalyze._riwayat("/funding-rate-history", sim, 40)
            n = 0
            for x in titik if not err else []:
                tgl = datetime.fromtimestamp(x["t"], timezone.utc).date().isoformat()
                c = x.get("c")
                # Satuan Coinalyze dalam PERSEN. Nilai > 0,5%/8 jam bukan funding wajar —
                # tanda satuannya berubah; lebih baik dibuang daripada mencemari z-score.
                if tgl not in harian and c is not None and abs(c) < 0.5:
                    harian[tgl] = c
                    n += 1
            catatan.append(f"bulan berjalan: {n} hari dari Coinalyze" if n else
                           f"Coinalyze tidak menambal ({err or 'kosong'})")
        else:
            catatan.append("bulan berjalan belum ada (Binance mengarsipkan per bulan; "
                           "COINALYZE_API_KEY kosong)")
    except Exception as e:
        catatan.append(f"tambalan Coinalyze gagal ({type(e).__name__})")
    return harian, catatan


def fear_greed():
    """{tanggal: nilai 0..100}."""
    d = json.loads(_get(FNG))
    return {datetime.fromtimestamp(int(x["timestamp"]), timezone.utc).date().isoformat():
            float(x["value"]) for x in d.get("data") or []}


def ke_mingguan(harian, jumat, maks_basi=10):
    """Rata-rata 7 hari yang berakhir Jumat (data tanggal d dianggap tersedia d+1)."""
    keluar = []
    for f in jumat:
        xs = [harian.get((f - timedelta(days=i)).isoformat()) for i in range(1, 8)]
        xs = [x for x in xs if x is not None]
        ok = len(xs) >= 4
        keluar.append(sum(xs) / len(xs) if ok else None)
    return keluar


def deret_gelombang(funding, fng, jumat):
    import jam_likuiditas as jl
    w1 = ke_mingguan(funding, jumat)
    w2 = ke_mingguan(fng, jumat)
    s1 = jl.skor(w1, k=0)
    s2 = jl.skor(w2, k=0)
    return {"W1_funding": w1, "W2_fng": w2, "skor_W1": s1, "skor_W2": s2,
            "gelombang": [jl._rata(a, b) for a, b in zip(s1, s2)]}

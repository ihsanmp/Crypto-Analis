"""Studi peristiwa: bagaimana harga BEREAKSI pada rilis data, dipisah menurut arah KEJUTAN.

Pertanyaan "prediksi CPI nanti bullish untuk emas?" selama ini tidak bisa dijawab dari data.
Yang ada cuma backtest.py::uji_makro, dan itu sengaja hanya mengukur BESAR gerakan pada
jendela tanggal tebakan (tgl 10-15), bukan arahnya, bukan pada tanggal rilis sebenarnya.
Jadi bot cuma bisa bilang "hari CPI biasanya lebih bergejolak" — benar, tapi bukan jawaban.

Yang membuat studi ini mungkin: berkas nowcast Cleveland Fed memuat SATU CHART PER BULAN
TARGET sejak 2013, masing-masing berisi lintasan nowcast harian DAN garis "Actual" yang baru
muncul pada hari rilis. Dari situ tiga hal bisa diperas sekaligus:

  - tanggal rilis SEBENARNYA (hari pertama garis "Actual" terisi),
  - ramalan terakhir sebelum rilis (nowcast di hari sebelum "Actual" muncul),
  - angka aktualnya.

kejutan = aktual - nowcast_terakhir. Itulah yang menggerakkan harga; angka mentahnya tidak.

BATAS YANG WAJIB DISEBUT SAAT MENGUTIP — ini model Cleveland Fed, BUKAN median survei ekonom
Wall Street. Konsensus pasar bisa berbeda, jadi "kejutan" di sini adalah kejutan terhadap
model, bukan terhadap posisi pasar. Perlakukan sebagai perkiraan arah, jangan sebagai
pengukuran kejutan pasar yang presisi.

Pemakaian:
    python cloud/kejutan.py --indikator CPI --simbol GOLD --pasar
    python cloud/kejutan.py --indikator "Core CPI" --simbol BTC
    python cloud/kejutan.py --indikator CPI            # sejarah kejutan saja, tanpa harga
"""

import argparse
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from statistics import median

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "data", "kejutan_cache.json")
CACHE_UMUR = 12 * 3600          # rilis bulanan; tidak berubah tiap jam

CF_URL = ("https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/"
          "nowcast_month.json?sc_lang=en")
UA = {"User-Agent": "Crypto-Analis Research bot"}
TIMEOUT = 60

# Nama seri di berkas Cleveland Fed. Kunci = yang boleh diketik user.
INDIKATOR = {
    "CPI": "CPI Inflation",
    "CORE CPI": "Core CPI Inflation",
    "PCE": "PCE Inflation",
    "CORE PCE": "Core PCE Inflation",
}

# Berapa hari perdagangan ke depan yang diukur. H = hari rilis itu sendiri.
HORIZON = (0, 1, 5)


def _muat_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _simpan_cache(c):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False)
    except Exception as e:
        print(f"[kejutan] gagal menyimpan cache: {e}")


def _angka(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bedah_bulan(entri, seri_nowcast, seri_aktual):
    """Peras (tanggal rilis, nowcast terakhir, aktual) dari satu chart bulan target."""
    bulan = (entri.get("chart") or {}).get("subcaption")
    kategori = (entri.get("categories") or [{}])[0].get("category") or []
    label = [c.get("label") for c in kategori]

    seri = {}
    for s in entri.get("dataset") or []:
        seri[s.get("seriesname")] = [x.get("value") for x in (s.get("data") or [])]

    nowcast, aktual = seri.get(seri_nowcast) or [], seri.get(seri_aktual) or []
    terisi = [i for i, v in enumerate(aktual) if _angka(v) is not None]
    if not terisi or not bulan:
        return None                      # aktual belum rilis

    i0 = terisi[0]
    # Ramalan yang dipakai adalah yang BERLAKU sebelum rilis. Memakai nowcast setelah
    # tanggal rilis akan mencampur informasi yang belum ada saat itu — look-ahead bias.
    sebelum = [_angka(v) for v in nowcast[:i0] if _angka(v) is not None]
    if not sebelum:
        return None

    a = _angka(aktual[i0])
    f = sebelum[-1]
    tanggal = label[i0] if i0 < len(label) else None
    if not tanggal or a is None:
        return None

    # Label sumbu-x cuma "MM/DD"; tahunnya diambil dari bulan target. Rilis selalu jatuh
    # SETELAH bulan targetnya, jadi bulan rilis yang lebih kecil berarti sudah ganti tahun.
    try:
        thn_target, bln_target = (int(x) for x in bulan.split("-")[:2])
        bln_rilis, hari_rilis = (int(x) for x in tanggal.split("/")[:2])
    except (ValueError, IndexError):
        return None
    thn_rilis = thn_target + 1 if bln_rilis < bln_target else thn_target
    try:
        iso = datetime(thn_rilis, bln_rilis, hari_rilis, tzinfo=timezone.utc).date().isoformat()
    except ValueError:
        return None

    return {"bulan_target": bulan, "tanggal_rilis": iso,
            "nowcast_mom_persen": round(f, 3), "aktual_mom_persen": round(a, 3),
            "kejutan_pp": round(a - f, 3)}


def deret_kejutan(indikator, paksa=False):
    """Riwayat (tanggal rilis, nowcast, aktual, kejutan) + rilis yang BELUM keluar."""
    nama = INDIKATOR[indikator]
    nama_aktual = f"Actual {nama}"
    kunci = f"kejutan_{indikator}"

    cache = _muat_cache()
    simpan = cache.get(kunci) or {}
    if simpan.get("data") and time.time() - simpan.get("waktu", 0) < CACHE_UMUR:
        return simpan["data"], True, None

    try:
        with urllib.request.urlopen(urllib.request.Request(CF_URL, headers=UA),
                                    timeout=TIMEOUT) as r:
            mentah = json.loads(r.read().decode(errors="replace"))
    except Exception as e:
        if simpan.get("data"):
            return simpan["data"], True, f"{type(e).__name__} (pakai cache lama)"
        return None, False, f"{type(e).__name__}: {e}"

    riwayat, menunggu = [], []
    for entri in mentah if isinstance(mentah, list) else []:
        hasil = _bedah_bulan(entri, nama, nama_aktual)
        if hasil:
            riwayat.append(hasil)
            continue
        # Belum rilis: nowcast terakhirnya tetap berguna sebagai ramalan yang berlaku.
        bulan = (entri.get("chart") or {}).get("subcaption")
        seri = {s.get("seriesname"): [x.get("value") for x in (s.get("data") or [])]
                for s in entri.get("dataset") or []}
        nilai = [_angka(v) for v in (seri.get(nama) or []) if _angka(v) is not None]
        if bulan and nilai:
            menunggu.append({"bulan_target": bulan, "nowcast_mom_persen": round(nilai[-1], 3)})

    riwayat.sort(key=lambda x: x["tanggal_rilis"])
    data = {"riwayat": riwayat, "belum_rilis": menunggu[-2:]}

    # Payload aslinya 7,5 MB. Yang disimpan HANYA hasil perasan — pernah ada bug cache
    # 13,9 MB di kalender.py karena menyimpan payload mentah.
    cache[kunci] = {"data": data, "waktu": time.time()}
    _simpan_cache(cache)
    return data, False, None


def _sebaran(nilai):
    """Ringkasan sebaran yang jujur: arah, besar, dan seberapa menyebar."""
    if not nilai:
        return None
    naik = [x for x in nilai if x > 0]
    n = len(nilai)
    r = {"n": n,
         "persen_naik": round(len(naik) / n * 100, 1),
         "median_persen": round(median(nilai), 2),
         "rata2_persen": round(sum(nilai) / n, 2),
         "terbaik_persen": round(max(nilai), 2),
         "terburuk_persen": round(min(nilai), 2)}
    if n < 10:
        r["peringatan"] = (f"SAMPEL KECIL ({n} rilis) — tidak bermakna secara statistik. "
                           "Sebut sebagai catatan, jangan sebagai bukti.")
    return r


def reaksi_harga(simbol, riwayat, pasar, rentang="15y"):
    """Sambungkan tanggal rilis dengan candle harian, pisahkan menurut arah kejutan."""
    if pasar:
        from market import tarik
        KOM = {"GOLD": "GC=F", "EMAS": "GC=F", "XAUUSD": "GC=F", "SILVER": "SI=F",
               "PERAK": "SI=F", "XAGUSD": "SI=F", "OIL": "CL=F", "WTI": "CL=F",
               "DXY": "DX-Y.NYB", "SPX": "^GSPC"}
        s = KOM.get(simbol.upper(), simbol.upper())
        candles, _, err = tarik(s, rentang, "1d")
    else:
        from indicators import fetch_base, resolve_cg_id
        s = simbol.upper()
        candles, _, _, err = fetch_base(s, resolve_cg_id(s), "1d")
    if err or not candles:
        return {"tidak_tersedia": err or "candle kosong"}

    # (tanggal ISO -> indeks) supaya rilis bisa dipetakan ke hari perdagangan.
    baris, urut = {}, []
    for i, c in enumerate(candles):
        ts = c[0]
        tgl = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat()
        baris[tgl] = i
        urut.append(tgl)
    if not urut:
        return {"tidak_tersedia": "candle kosong"}

    awal, akhir = urut[0], urut[-1]
    panas = {h: [] for h in HORIZON}
    dingin = {h: [] for h in HORIZON}
    semua = {h: [] for h in HORIZON}
    dipakai, di_luar_jangkauan, tanpa_padanan = 0, 0, 0

    for r in riwayat:
        tgl = r["tanggal_rilis"]
        if tgl < awal or tgl > akhir:
            di_luar_jangkauan += 1
            continue
        i = baris.get(tgl)
        if i is None:
            # Rilis jatuh di hari libur bursa: pakai hari perdagangan BERIKUTNYA.
            berikut = [t for t in urut if t > tgl]
            if not berikut:
                tanpa_padanan += 1
                continue
            i = baris[berikut[0]]
        dipakai += 1
        for h in HORIZON:
            j = i + h
            if j >= len(candles):
                continue
            buka = candles[i][1] if h == 0 else candles[i][4]
            tutup = candles[j][4]
            if not buka or not tutup:
                continue
            ret = (tutup - buka) / buka * 100
            semua[h].append(ret)
            (panas if r["kejutan_pp"] > 0 else dingin)[h].append(ret)

    def bungkus(d):
        return {f"H+{h}" if h else "H (hari rilis)": _sebaran(v) for h, v in d.items()}

    hasil = {
        "simbol": s,
        "rilis_terpakai": dipakai,
        "jendela_harga": f"{awal} s/d {akhir}",
        "diukur": ("H = open->close hari rilis; H+1 dan H+5 = close hari rilis -> close "
                   "n hari perdagangan berikutnya. Semua dalam persen."),
        "semua_rilis": bungkus(semua),
        "kejutan_lebih_panas": bungkus(panas),
        "kejutan_lebih_dingin": bungkus(dingin),
    }
    if di_luar_jangkauan:
        hasil["di_luar_jangkauan_harga"] = di_luar_jangkauan
    if tanpa_padanan:
        hasil["tanpa_hari_perdagangan"] = tanpa_padanan

    # Selisih arah inilah isi jawabannya. Kalau tipis, katakan tipis. Dihitung untuk SEMUA
    # horizon: pada emas, selisih H+1 sering nyaris nol sementara H+5 baru terlihat — memakai
    # satu horizon saja bisa menyembunyikan atau melebih-lebihkan efeknya.
    selisih = {}
    for h in HORIZON:
        if panas[h] and dingin[h]:
            nama_h = f"H+{h}" if h else "H (hari rilis)"
            selisih[nama_h] = round(median(panas[h]) - median(dingin[h]), 2)
    if selisih:
        hasil["selisih_median_panas_dikurangi_dingin_persen"] = selisih
        hasil["cara_baca"] = (
            "Selisih inilah yang menjawab 'bullish atau tidak'. Selisih di bawah ~0,3% pada "
            "emas praktis tidak bisa dibedakan dari derau harian — sebut sebagai TIDAK ADA "
            "EDGE ARAH, jangan dipaksa jadi kesimpulan. Ingat juga kejutan diukur terhadap "
            "model Cleveland Fed, BUKAN konsensus ekonom, sehingga posisi pasar bisa "
            "berbeda dari yang tersirat di sini.")
    return hasil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indikator", default="CPI",
                    help="CPI | Core CPI | PCE | Core PCE")
    ap.add_argument("--simbol", help="aset yang diukur reaksinya, mis. GOLD / BTC / SPX")
    ap.add_argument("--pasar", action="store_true",
                    help="simbol berupa komoditas/saham/forex (via market.py)")
    ap.add_argument("--ringkas", action="store_true",
                    help="buang panduan statis (dipakai saat dikirim ke model)")
    args = ap.parse_args()

    ind = args.indikator.strip().upper()
    if ind not in INDIKATOR:
        print(json.dumps({"tidak_tersedia": f"indikator '{args.indikator}' tidak dikenal",
                          "pilihan": list(INDIKATOR)}, indent=2, ensure_ascii=False))
        return

    data, dari_cache, err = deret_kejutan(ind)
    keluar = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "indikator": ind,
        "sumber": ("Cleveland Fed inflation nowcasting — RAMALAN MODEL, bukan median survei "
                   "ekonom Wall Street. Sebut demikian saat mengutip."),
        "dari_cache": dari_cache,
    }
    if err or not data:
        keluar["tidak_tersedia"] = err or "gagal mengurai berkas nowcast"
        print(json.dumps(keluar, indent=2, ensure_ascii=False))
        return

    riwayat = data["riwayat"]
    kejut = [r["kejutan_pp"] for r in riwayat]
    keluar["belum_rilis"] = data["belum_rilis"]
    keluar["sejarah_kejutan"] = {
        "jumlah_rilis": len(riwayat),
        "jendela": f"{riwayat[0]['tanggal_rilis']} s/d {riwayat[-1]['tanggal_rilis']}"
                   if riwayat else None,
        "kejutan_median_pp": round(median(kejut), 3) if kejut else None,
        "persen_lebih_panas": round(sum(1 for k in kejut if k > 0) / len(kejut) * 100, 1)
                              if kejut else None,
        "kejutan_12_terakhir": riwayat[-12:],
    }
    if args.simbol:
        keluar["reaksi_harga"] = reaksi_harga(args.simbol, riwayat, args.pasar)

    if args.ringkas:
        from backtest import buang_panduan
        keluar = buang_panduan(keluar)
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

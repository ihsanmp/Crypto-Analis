"""Jadwal rilis RESMI + angka aktual NFP/PPI — semuanya tanpa kunci API.

Kenapa ini perlu padahal kalender.py sudah ada: kalender.py bersandar pada feed Forex
Factory, yang TIDAK RESMI, berbatas laju ketat, dan pernah berpindah host. Untuk aturan
"jangan masuk menjelang rilis berdampak kuat", tanggalnya sebaiknya datang dari penerbitnya
sendiri. Feed FF tetap dipakai untuk KONSENSUS — itu yang tidak diterbitkan BLS maupun Fed.

Tiga sumber, semuanya gratis dan tanpa pendaftaran:

  - bls.ics                    jadwal rilis resmi BLS (Employment Situation/NFP, CPI, PPI)
  - api.bls.gov v1             angka aktual; tanpa kunci dibatasi 25 permintaan/hari
  - federalreserve.gov         tanggal rapat FOMC, termasuk penanda rapat berproyeksi

BATAS YANG TIDAK BISA DITEMBUS SUMBER GRATIS — dan harus dikatakan apa adanya:
tidak ada satu pun dari sumber ini yang menyimpan KONSENSUS HISTORIS. Karena itu studi
reaksi menurut arah kejutan seperti kejutan.py untuk CPI TIDAK BISA dibuat untuk NFP, PPI,
atau FOMC. Yang tersedia hanya jadwal, angka aktual, dan perubahannya terhadap bulan lalu.
Jangan menyajikan "perubahan terhadap bulan lalu" seolah itu kejutan terhadap ekspektasi —
yang menggerakkan harga adalah selisih terhadap konsensus, bukan terhadap bulan sebelumnya.

Pemakaian:
    python cloud/jadwal.py
    python cloud/jadwal.py --ringkas
"""

import argparse
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "data", "jadwal_cache.json")
CACHE_UMUR = 12 * 3600

ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
UA = {"User-Agent": "Crypto-Analis Research bot"}
TIMEOUT = 45

# Hanya rilis yang benar-benar menggerakkan pasar. Sisanya (JOLTS regional dll) diabaikan
# supaya keluarannya tidak membengkak jadi daftar puluhan acara.
ACARA_PENTING = {
    "employment situation": "NFP (Employment Situation)",
    "consumer price index": "CPI",
    "producer price index": "PPI",
}

SERI_BLS = {
    "NFP": ("CES0000000001", "level total nonfarm, ribuan pekerja, SA"),
    "PPI": ("WPSFD4", "PPI Final Demand, indeks, SA"),
}


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
        print(f"[jadwal] gagal menyimpan cache: {e}")


def _ambil(kunci, url, data=None, headers=None, paksa=False):
    """Ambil dengan cache 12 jam. Return (teks, dari_cache, error)."""
    cache = _muat_cache()
    simpan = cache.get(kunci) or {}
    if not paksa and simpan.get("teks") and time.time() - simpan.get("waktu", 0) < CACHE_UMUR:
        return simpan["teks"], True, None
    try:
        h = dict(UA)
        if headers:
            h.update(headers)
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h),
                                    timeout=TIMEOUT) as r:
            teks = r.read().decode(errors="replace")
    except Exception as e:
        kode = getattr(e, "code", None)
        pesan = f"{type(e).__name__}" + (f" {kode}" if kode else "")
        if simpan.get("teks"):
            return simpan["teks"], True, f"{pesan} (pakai cache lama)"
        return None, False, pesan
    cache[kunci] = {"teks": teks, "waktu": time.time()}
    _simpan_cache(cache)
    return teks, False, None


def rilis_bls(paksa=False):
    """Jadwal rilis RESMI dari kalender ICS milik BLS."""
    teks, dari_cache, err = _ambil("bls_ics", ICS_URL, paksa=paksa)
    if err and not teks:
        return {"tidak_tersedia": err}

    # Format ICS: pasangan DTSTART/SUMMARY di dalam blok VEVENT.
    acara = []
    hari_ini = datetime.now(timezone.utc).date()
    for blok in teks.split("BEGIN:VEVENT")[1:]:
        m_t = re.search(r"DTSTART[^:]*:(\d{8})", blok)
        m_s = re.search(r"SUMMARY:(.+)", blok)
        if not (m_t and m_s):
            continue
        judul = m_s.group(1).strip()
        cocok = next((label for kunci, label in ACARA_PENTING.items()
                      if kunci in judul.lower()), None)
        if not cocok:
            continue
        try:
            tgl = datetime.strptime(m_t.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if tgl < hari_ini:
            continue
        acara.append({"acara": cocok, "tanggal": tgl.isoformat(),
                      "hari_lagi": (tgl - hari_ini).days})
    acara.sort(key=lambda x: x["tanggal"])

    hasil = {"berikutnya": acara[:6], "dari_cache": dari_cache,
             "sumber": "kalender ICS resmi BLS (bls.gov/schedule)"}
    if err:
        hasil["peringatan"] = err
    dekat = [a for a in acara[:6] if a["hari_lagi"] <= 2]
    if dekat:
        hasil["peringatan_rilis_dekat"] = (
            f"{dekat[0]['acara']} kurang dari 3 hari lagi ({dekat[0]['tanggal']}) — "
            "gap risk tinggi. Untuk yang BELUM punya posisi, bias default TUNGGU DULU.")
    return hasil


def fomc(paksa=False):
    """Tanggal rapat FOMC. Tanda bintang di situs = rapat disertai proyeksi ekonomi."""
    teks, dari_cache, err = _ambil("fomc", FOMC_URL, paksa=paksa)
    if err and not teks:
        return {"tidak_tersedia": err}

    BULAN = {b: i for i, b in enumerate(
        ["January", "February", "March", "April", "May", "June", "July", "August",
         "September", "October", "November", "December"], 1)}
    hari_ini = datetime.now(timezone.utc).date()
    rapat = []

    # Halaman dikelompokkan per tahun; tahunnya HARUS diambil dari judul kelompok, bukan
    # ditebak dari tanggal sekarang — halaman memuat tahun lalu sampai tahun depan.
    potong = re.split(r"(\d{4})\s+FOMC Meetings", teks)
    for i in range(1, len(potong) - 1, 2):
        try:
            tahun = int(potong[i])
        except ValueError:
            continue
        blok = potong[i + 1]
        bulan = re.findall(r'fomc-meeting__month[^"]*">\s*<strong>([^<]+)</strong>', blok)
        hari = re.findall(r'fomc-meeting__date[^"]*">\s*([^<]+?)\s*<', blok)
        for b, h in zip(bulan, hari):
            nama_bulan = b.strip().split("/")[0].strip()
            if nama_bulan not in BULAN:
                continue
            proyeksi = "*" in h
            # "27-28" -> keputusan keluar pada hari TERAKHIR rapat.
            angka = re.findall(r"\d{1,2}", h)
            if not angka:
                continue
            try:
                tgl = datetime(tahun, BULAN[nama_bulan], int(angka[-1]),
                               tzinfo=timezone.utc).date()
            except ValueError:
                continue
            if tgl >= hari_ini:
                rapat.append({"tanggal_keputusan": tgl.isoformat(),
                              "hari_lagi": (tgl - hari_ini).days,
                              "disertai_proyeksi_ekonomi": proyeksi})
    rapat.sort(key=lambda x: x["tanggal_keputusan"])
    # Halaman memuat beberapa tahun sekaligus; duplikat mungkin muncul dari tabel ringkasan.
    unik, terlihat = [], set()
    for r in rapat:
        if r["tanggal_keputusan"] not in terlihat:
            terlihat.add(r["tanggal_keputusan"])
            unik.append(r)

    hasil = {"berikutnya": unik[:4], "dari_cache": dari_cache,
             "sumber": "federalreserve.gov/monetarypolicy/fomccalendars.htm",
             "catatan": ("Rapat berproyeksi ekonomi (dot plot) biasanya bergerak lebih besar "
                         "daripada rapat biasa. Tanggal di sini adalah hari KEPUTUSAN.")}
    if err:
        hasil["peringatan"] = err
    return hasil


def nilai_terbaru(paksa=False):
    """Angka aktual NFP & PPI langsung dari BLS. Tanpa kunci: 25 permintaan/hari."""
    tahun = datetime.now(timezone.utc).year
    badan = json.dumps({"seriesid": [s for s, _ in SERI_BLS.values()],
                        "startyear": str(tahun - 1), "endyear": str(tahun)}).encode()
    teks, dari_cache, err = _ambil("bls_nilai", BLS_API, data=badan,
                                   headers={"Content-Type": "application/json"}, paksa=paksa)
    if err and not teks:
        return {"tidak_tersedia": err}
    try:
        data = json.loads(teks)
    except ValueError:
        return {"tidak_tersedia": "balasan BLS bukan JSON"}
    if data.get("status") != "REQUEST_SUCCEEDED":
        return {"tidak_tersedia": f"BLS: {data.get('status')}",
                "pesan": (data.get("message") or [None])[0]}

    per_id = {s.get("seriesID"): (s.get("data") or [])
              for s in (data.get("Results") or {}).get("series", [])}
    hasil = {"dari_cache": dari_cache,
             "sumber": "api.bls.gov v1 (tanpa kunci, 25 permintaan/hari)"}
    for nama, (sid, arti) in SERI_BLS.items():
        titik = per_id.get(sid) or []
        if len(titik) < 2:
            hasil[nama] = {"tidak_tersedia": f"data {sid} kosong"}
            continue
        baru, lama = titik[0], titik[1]
        try:
            n_baru, n_lama = float(baru["value"]), float(lama["value"])
        except (KeyError, ValueError):
            hasil[nama] = {"tidak_tersedia": "nilai tidak terbaca"}
            continue
        # "arti" dibuang --ringkas; satuannya wajib ikut supaya 158858 tidak dibaca
        # sebagai dolar atau persen.
        item = {"seri": sid, "satuan": arti,
                "periode": f"{baru.get('periodName')} {baru.get('year')}",
                "nilai": n_baru}
        if nama == "NFP":
            item["perubahan_ribu_pekerja"] = round(n_baru - n_lama)
        else:
            item["perubahan_mom_persen"] = round((n_baru - n_lama) / n_lama * 100, 2)
        hasil[nama] = item
    return hasil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paksa", action="store_true", help="abaikan cache")
    ap.add_argument("--ringkas", action="store_true", help="buang panduan statis")
    args = ap.parse_args()

    keluar = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "rilis_bls": rilis_bls(args.paksa),
        "fomc": fomc(args.paksa),
        "nilai_terbaru": nilai_terbaru(args.paksa),
        "batas_penting": (
            "TIDAK ADA konsensus historis di sumber gratis mana pun, jadi reaksi harga "
            "menurut ARAH KEJUTAN tidak bisa diukur untuk NFP, PPI, maupun FOMC — beda "
            "dengan CPI yang punya nowcast Cleveland Fed (lihat kejutan.py). Untuk ketiga "
            "acara ini sampaikan JADWAL dan ANGKA AKTUAL saja, dan katakan terus terang "
            "bahwa arah reaksinya tidak bisa diprediksi dari data yang ada. 'Perubahan "
            "terhadap bulan lalu' BUKAN kejutan terhadap ekspektasi."),
    }
    if args.ringkas:
        from backtest import buang_panduan
        keluar = buang_panduan(keluar)
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

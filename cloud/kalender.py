"""Konsensus & jadwal rilis data ekonomi — melengkapi makro.py yang hanya punya AKTUAL.

Yang menggerakkan harga adalah SELISIH aktual vs konsensus. makro.py (FRED) memberi angka
aktual yang sudah dirilis; konsensusnya selama ini harus diminta ke user setiap kali.
Berkas ini menutup sebagian besar lubang itu.

DUA SUMBER, BEDA SIFAT — jangan dicampur saat mengutip:

1. CLEVELAND FED INFLATION NOWCASTING (penopang) — khusus CPI & PCE.
   Resmi Federal Reserve, domain publik, stabil. TAPI ini KELUARAN MODEL, bukan konsensus
   survei ekonom. Diberi label "nowcast_clevelandfed" dan HARUS disebut demikian.

2. FOREX FACTORY (pelengkap) — semua rilis, dengan kolom forecast/previous/actual.
   Field "forecast" itulah konsensus yang selama ini diminta ke user. TAPI ini KOMPILASI
   Forex Factory, bukan median survei resmi (Bloomberg/Reuters) — sebut sumbernya.

   Feed-nya GRATIS: nfs.faireconomy.media/ff_calendar_*.json adalah tombol export yang
   disediakan Forex Factory sendiri, tanpa akun dan tanpa key. Yang berbayar adalah
   pembungkusnya (FireAPI, RapidAPI, Apify) yang men-scrape ulang feed yang sama.

   TAPI TIDAK ADA API RESMI. URL-nya pernah berpindah antara nfs.faireconomy.media dan
   cdn-nfs.faireconomy.media, dan tiap kali berpindah semua yang memakainya rusak
   berjamaah. Tidak ada SLA, tidak ada pengumuman perubahan. Karena itu sumber ini
   PELENGKAP: kegagalannya TIDAK boleh mematikan script, dan Cleveland Fed yang jadi
   penopang — bukan sebaliknya.

BATAS LAJU: Forex Factory hanya mengizinkan 2 unduhan per 5 menit. Kalau terlampaui, yang
keluar adalah HALAMAN HTML berisi "Request Denied", BUKAN JSON. Bot ini bisa jalan puluhan
kali per jam lewat webhook, jadi CACHE bukan optimasi melainkan syarat. Berkas Cleveland Fed
juga besar (~7 MB) sehingga sama-sama wajib di-cache.

Pemakaian:
    python cloud/kalender.py --pekan-ini
    python cloud/kalender.py --mata-uang USD --dampak tinggi
    python cloud/kalender.py --cari CPI
    python cloud/kalender.py --inflasi
    python cloud/kalender.py --ringkas
"""

import argparse
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "data", "kalender_cache.json")
CACHE_UMUR = 6 * 3600          # detik

# User-Agent browser biasa — permintaan tanpa UA sering ditolak.
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
TIMEOUT = 30

FF_URL = {
    "pekan_ini": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "pekan_depan": "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
}
CF_URL = {
    "bulanan": "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/"
               "nowcast_month.json?sc_lang=en",
    "tahunan": "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/"
               "nowcast_year.json?sc_lang=en",
}


# ----------------------------------------------------------------- cache

def _muat_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _simpan_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        print(f"[kalender] gagal menyimpan cache: {e}")


def ambil(kunci, url, paksa=False, urai=None):
    """Ambil URL dengan cache 6 jam. Return (data, dari_cache, waktu_ambil, error).

    Deteksi rate limit: Forex Factory membalas HALAMAN HTML saat batas terlampaui, bukan
    error HTTP. Kalau respons tidak diawali "[" atau "{", itu bukan JSON — perlakukan
    sebagai gagal dan pakai cache yang ada, JANGAN diurai paksa.

    `urai` dipakai untuk menyimpan HASIL URAIAN, bukan payload mentah. Penting: berkas
    Cleveland Fed ~7 MB per berkas, dan cache ini HARUS ikut ter-commit supaya berguna —
    runner GitHub selalu bersih, jadi cache yang tidak di-commit tidak pernah terpakai di
    run berikutnya. Menyimpan mentahnya membuat cache 14 MB, jauh lebih buruk daripada
    berkas 2 MB yang sudah dikeluhkan di rencana perbaikan.
    """
    cache = _muat_cache()
    simpan = cache.get(kunci) or {}
    umur = time.time() - simpan.get("waktu", 0)
    if not paksa and simpan.get("data") is not None and umur < CACHE_UMUR:
        return simpan["data"], True, simpan.get("waktu_utc"), None

    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                    timeout=TIMEOUT) as r:
            mentah = r.read().decode("utf-8", "replace")
    except Exception as e:
        err = f"{type(e).__name__}: {getattr(e, 'code', e)}"
        if simpan.get("data") is not None:
            return simpan["data"], True, simpan.get("waktu_utc"), f"{err} (pakai cache lama)"
        return None, False, None, err

    if mentah.lstrip()[:1] not in ("[", "{"):
        err = "bukan JSON (kemungkinan batas laju: 2 unduhan per 5 menit)"
        if simpan.get("data") is not None:
            return simpan["data"], True, simpan.get("waktu_utc"), f"{err} (pakai cache lama)"
        return None, False, None, err

    try:
        data = json.loads(mentah)
    except Exception as e:
        return None, False, None, f"JSON rusak: {type(e).__name__}"

    if urai is not None:
        data = urai(data)          # simpan hasilnya saja, bukan payload mentahnya
    waktu_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    cache[kunci] = {"data": data, "waktu": time.time(), "waktu_utc": waktu_utc}
    _simpan_cache(cache)
    return data, False, waktu_utc, None


# -------------------------------------------------------- Cleveland Fed

_SERI_CF = {
    "CPI Inflation": "cpi",
    "Core CPI Inflation": "core_cpi",
    "PCE Inflation": "pce",
    "Core PCE Inflation": "core_pce",
}


def _urai_nowcast(data):
    """Ambil nilai TERAKHIR tiap seri dari entri periode terbaru."""
    if not isinstance(data, list) or not data:
        return None, None, None
    akhir = data[-1]
    grafik = akhir.get("chart") or {}
    periode = grafik.get("subcaption")
    per_tanggal = grafik.get("_comment")
    keluar = {}
    for seri in akhir.get("dataset") or []:
        nama = _SERI_CF.get(seri.get("seriesname"))
        if not nama:
            continue
        nilai = [x.get("value") for x in (seri.get("data") or [])
                 if x.get("value") not in (None, "")]
        if nilai:
            try:
                keluar[nama] = round(float(nilai[-1]), 3)
            except ValueError:
                pass
    return keluar, periode, per_tanggal


def nowcast_inflasi(paksa=False):
    """Nowcast inflasi Cleveland Fed: m/m dari nowcast_month, y/y dari nowcast_year."""
    hasil = {
        "sumber": "Cleveland Fed Inflation Nowcasting (resmi Federal Reserve, tanpa API key)",
        "jenis": "NOWCAST MODEL — BUKAN konsensus survei ekonom. Sebut demikian saat mengutip.",
    }
    catatan = []
    for kunci, label in (("bulanan", "mom_persen"), ("tahunan", "yoy_persen")):
        # Diurai SEBELUM disimpan: yang di-cache hanya beberapa angka, bukan 7 MB JSON.
        data, dari_cache, waktu, err = ambil(f"cf_{kunci}", CF_URL[kunci], paksa,
                                             urai=lambda d: list(_urai_nowcast(d)))
        if err:
            catatan.append(f"{kunci}: {err}")
        if not data:
            continue
        nilai, periode, per_tanggal = data
        if not nilai:
            catatan.append(f"{kunci}: struktur tidak dikenali")
            continue
        hasil[label] = nilai
        hasil.setdefault("periode", periode)
        hasil.setdefault("nowcast_per", per_tanggal)
        hasil.setdefault("dari_cache", dari_cache)
        hasil.setdefault("waktu_ambil_utc", waktu)
    if catatan:
        hasil["catatan"] = catatan
    if "mom_persen" not in hasil and "yoy_persen" not in hasil:
        hasil["tidak_tersedia"] = "kedua berkas nowcast gagal diambil"
    return hasil


# --------------------------------------------------------- Forex Factory

_DAMPAK = {"high": "tinggi", "medium": "sedang", "low": "rendah", "holiday": "libur"}


def _bersih(v):
    """Kolom kosong berarti TIDAK ADA. Jangan diisi 0 atau ditebak."""
    v = (v or "").strip()
    return v or None


def kalender_rilis(pekan_depan=False, paksa=False):
    kunci = "ff_nextweek" if pekan_depan else "ff_thisweek"
    url = FF_URL["pekan_depan" if pekan_depan else "pekan_ini"]
    data, dari_cache, waktu, err = ambil(kunci, url, paksa)
    hasil = {
        "sumber": "Forex Factory (gratis, TANPA API resmi — feed bisa berpindah host)",
        "jenis": ("KOMPILASI Forex Factory, BUKAN median survei ekonom resmi "
                  "(Bloomberg/Reuters). Sebut sumbernya saat mengutip konsensus."),
        "dari_cache": dari_cache,
        "waktu_ambil_utc": waktu,
    }
    if err:
        hasil["peringatan"] = err
    if not isinstance(data, list):
        hasil["tidak_tersedia"] = "kalender rilis gagal diambil"
        hasil["rilis"] = []
        return hasil

    rilis = []
    for e in data:
        rilis.append({
            "nama": e.get("title"),
            "mata_uang": e.get("country"),
            "waktu": e.get("date"),
            "dampak": _DAMPAK.get((e.get("impact") or "").lower(), e.get("impact")),
            "konsensus": _bersih(e.get("forecast")),
            "sebelumnya": _bersih(e.get("previous")),
            "aktual": _bersih(e.get("actual")),
        })
    hasil["rilis"] = rilis
    hasil["jumlah"] = len(rilis)

    # Feed ini hanya memuat pekan berjalan; begitu pekannya lewat, konsensusnya hilang
    # selamanya. Diarsipkan supaya studi kejutan untuk NFP/PPI/FOMC — yang mustahil sekarang
    # karena tidak ada sumber gratis berisi konsensus historis — menjadi mungkin nanti.
    # Kegagalan mengarsip TIDAK boleh menggagalkan kalender: ini fitur sampingan.
    try:
        import arsip
        baru, diperbarui, total = arsip.catat(rilis)
        if baru or diperbarui:
            print(f"[kalender] arsip konsensus: +{baru} baru, {diperbarui} diperbarui, "
                  f"{total} total")
    except Exception as e:
        print(f"[kalender] arsip konsensus gagal: {type(e).__name__}: {e}")
    return hasil


def _saring(rilis, mata_uang=None, dampak=None, cari=None):
    keluar = rilis
    if mata_uang:
        mu = {m.strip().upper() for m in mata_uang.split(",")}
        keluar = [r for r in keluar if (r.get("mata_uang") or "").upper() in mu]
    if dampak:
        dm = {d.strip().lower() for d in dampak.split(",")}
        keluar = [r for r in keluar if (r.get("dampak") or "").lower() in dm]
    if cari:
        c = cari.lower()
        keluar = [r for r in keluar if c in (r.get("nama") or "").lower()]
    return keluar


def _dalam_hari(rilis, hari):
    batas = datetime.now(timezone.utc) + timedelta(days=hari)
    keluar = []
    for r in rilis:
        try:
            t = datetime.fromisoformat(r["waktu"])
            if datetime.now(timezone.utc) - timedelta(hours=12) <= t <= batas:
                keluar.append(r)
        except Exception:
            keluar.append(r)     # waktu tak terbaca: jangan dibuang diam-diam
    return keluar


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pekan-ini", action="store_true", help="semua rilis pekan ini")
    ap.add_argument("--pekan-depan", action="store_true", help="semua rilis pekan depan")
    ap.add_argument("--mata-uang", help="saring mata uang, mis. USD atau USD,EUR")
    ap.add_argument("--dampak", help="saring dampak: tinggi/sedang/rendah")
    ap.add_argument("--cari", help="saring nama rilis, mis. CPI")
    ap.add_argument("--inflasi", action="store_true", help="nowcast Cleveland Fed saja")
    ap.add_argument("--ringkas", action="store_true",
                    help="rilis berdampak tinggi 7 hari ke depan + nowcast inflasi")
    ap.add_argument("--paksa", action="store_true", help="abaikan cache (untuk uji)")
    args = ap.parse_args()

    keluar = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}

    if args.inflasi:
        keluar["nowcast_clevelandfed"] = nowcast_inflasi(args.paksa)
        print(json.dumps(keluar, indent=2, ensure_ascii=False))
        return

    if args.ringkas:
        keluar["nowcast_clevelandfed"] = nowcast_inflasi(args.paksa)
        kal = kalender_rilis(False, args.paksa)
        rilis = _dalam_hari(_saring(kal["rilis"], dampak="tinggi"), 7)
        # Pekan ini sering tinggal beberapa hari; ambil pekan depan supaya 7 hari penuh.
        if len(rilis) < 3:
            kal2 = kalender_rilis(True, args.paksa)
            rilis += _dalam_hari(_saring(kal2.get("rilis") or [], dampak="tinggi"), 7)
        keluar["rilis_dampak_tinggi_7_hari"] = {
            "sumber": kal["sumber"], "jenis": kal["jenis"],
            "dari_cache": kal.get("dari_cache"),
            "waktu_ambil_utc": kal.get("waktu_ambil_utc"),
            "peringatan": kal.get("peringatan"),
            "daftar": rilis,
        }
        keluar["cara_pakai"] = [
            "Yang menggerakkan harga adalah SELISIH aktual vs konsensus, bukan angka "
            "absolutnya.",
            "Konsensus di sini KOMPILASI Forex Factory — sebut sumbernya. Nowcast Cleveland "
            "Fed adalah KELUARAN MODEL, bukan konsensus. Jangan dicampur.",
            "Kalau kedua sumber berbeda jauh, SEBUTKAN keduanya beserta selisihnya — jangan "
            "diam-diam memilih satu.",
            "Kolom konsensus yang bernilai null berarti TIDAK ADA. Minta ke user, jangan "
            "ditebak.",
        ]
        print(json.dumps(keluar, indent=2, ensure_ascii=False))
        return

    kal = kalender_rilis(args.pekan_depan, args.paksa)
    kal["rilis"] = _saring(kal["rilis"], args.mata_uang, args.dampak, args.cari)
    kal["jumlah"] = len(kal["rilis"])
    keluar["kalender"] = kal
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

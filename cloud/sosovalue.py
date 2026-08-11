"""Adapter SoSoValue — arus dana ETF spot & konsensus makro historis. BUTUH API KEY.

KENAPA ADA ADAPTER, BUKAN PANGGILAN LANGSUNG DI MANA-MANA: tier gratisnya berstatus "Demo",
dan dokumentasinya menyebut paid plan akan menyusul. Kalau suatu saat berbayar, yang dicabut
cukup berkas ini — bukan membongkar pipeline. Karena itu SEMUA akses SoSoValue lewat sini.

DUA HAL YANG DICARI, dan nilainya berbeda jauh:

1. ARUS DANA ETF SPOT — ini yang paling berharga. Sinyal institusional yang tidak tertangkap
   CoinGecko, DefiLlama, maupun sentimen X. Buat analisa crypto, ini KATEGORI SINYAL BARU,
   bukan sekadar tambahan angka.
2. KONSENSUS MAKRO HISTORIS (`forecast` pada /macro/events/.../history) — berguna, TAPI
   hanya sebagai SUMBER PEMBANDING. Dokumentasinya tidak menyebut asal `forecast` itu dan
   tidak ada jejak vintage, jadi masalah backfill yang sama seperti scrape Forex Factory
   masih berlaku. Dipakai untuk mengaudit arsip kita sendiri, bukan menggantikannya.

CATATAN PENTING SOAL ALAMAT: riset yang beredar menyebut path seperti `/macro/events/...`.
Itu SALAH — diuji langsung, path tanpa awalan mengembalikan 404 sementara `/openapi/v1/...`
mengembalikan 401. Tapi 401 juga muncul untuk path yang jelas tidak ada, karena auth dicek
SEBELUM routing. Artinya nama endpoint TIDAK BISA diverifikasi tanpa kunci. Karena itu
`--periksa` ada: jalankan sekali dengan kunci terpasang, dan biarkan API sendiri yang
memberi tahu endpoint mana yang hidup dan sedalam apa datanya.

Batas laju: 20 permintaan/menit, 100.000/bulan. Jangan burst.

KUNCI: daftar di sosovalue.com/developer/dashboard, lalu masukkan sendiri ke GitHub Secrets
sebagai SOSOVALUE_API_KEY. JANGAN mengirimkannya lewat chat.

Pemakaian:
    python cloud/sosovalue.py --periksa
    python cloud/sosovalue.py --etf us-btc-spot
    python cloud/sosovalue.py --riwayat "Nonfarm Payrolls" --mulai 2015-01-01
"""

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "data", "sosovalue_cache.json")
CACHE_UMUR = 3 * 3600

BASE = "https://openapi.sosovalue.com"
UA = {"User-Agent": "Crypto-Analis Research bot"}
TIMEOUT = 30

# Dokumentasi menyebut 20 permintaan/menit, tapi diuji langsung: jeda 3,2 detik masih kena
# 429 setelah 10 panggilan beruntun. Batas sebenarnya lebih ketat daripada yang ditulis.
JEDA_MINIMUM = 6.5
ULANG_SAAT_429 = 2
_terakhir = [0.0]

# Kandidat endpoint. Nama sebenarnya tidak bisa diverifikasi tanpa kunci (auth dicek sebelum
# routing), jadi --periksa mencoba semuanya dan melaporkan mana yang hidup. Setelah ketahuan,
# yang mati dihapus dari daftar ini.
KANDIDAT = [
    ("acara makro", "GET", "/openapi/v1/macro/events", None),
    ("riwayat makro", "GET", "/openapi/v1/macro/events/{acara}/history", None),
]

# Putaran pertama membuktikan kedua endpoint makro HIDUP dan riwayatnya sampai 2018-05,
# sementara semua tebakan ETF membalas 404. Tidak ada spesifikasi publik (/v3/api-docs
# membalas 403), jadi alamat ETF hanya bisa dicari lewat percobaan. Daftar ini dicoba
# sekali; yang tetap 404 semua berarti ETF memang tidak terjangkau dari plan ini.
# TERBUKTI: yang hidup versi v2, bukan v1. Lima pola v1 lain membalas 404.
ETF_METRIK = "/openapi/v2/etf/currentEtfDataMetrics"
KANDIDAT_ETF = [
    ("POST", ETF_METRIK, {"type": "us-btc-spot"}),
    ("POST", "/openapi/v2/etf/historicalInflowChart", {"type": "us-btc-spot"}),
]

# Nama acara harus PERSIS. Daftar /macro/events cuma memuat dua pekan ke depan, jadi nama
# untuk acara yang tidak sedang dijadwalkan tidak muncul di situ dan harus diuji satu-satu.
# TERBUKTI HIDUP beserta kedalamannya — semuanya memuat kolom forecast:
#   Nonfarm Payrolls  2018-05-04 .. 2026-08-07
#   CPI (MoM)         2018-03-13 .. 2026-08-12
#   Core CPI (MoM)    2018-03-13 .. 2026-08-12
#   PPI (MoM)         2018-05-09 .. 2026-08-13
ACARA_TERBUKTI = {
    "NFP": "Nonfarm Payrolls",
    "CPI": "CPI (MoM)",
    "CORE CPI": "Core CPI (MoM)",
    "PPI": "PPI (MoM)",
}
KANDIDAT_ACARA = [
    "Fed Interest Rate Decision", "FOMC Interest Rate Decision",
    "Unemployment Rate", "Average Hourly Earnings (MoM)",
]


def _kunci():
    return (os.environ.get("SOSOVALUE_API_KEY") or "").strip()


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
        print(f"[sosovalue] gagal menyimpan cache: {e}")


def panggil(jalur, metode="GET", badan=None, params=None, pakai_cache=True, percobaan=0):
    """Satu-satunya pintu ke SoSoValue. Return (data, dari_cache, error).

    Kunci TIDAK PERNAH ikut ke keluaran mana pun — repo ini publik dan log Actions ikut
    terbaca publik.
    """
    key = _kunci()
    if not key:
        return None, False, "SOSOVALUE_API_KEY kosong"

    url = BASE + jalur + (("?" + urllib.parse.urlencode(params)) if params else "")
    kunci_cache = f"{metode} {jalur} {json.dumps(params or {}, sort_keys=True)} " \
                  f"{json.dumps(badan or {}, sort_keys=True)}"
    cache = _muat_cache()
    simpan = cache.get(kunci_cache) or {}
    if pakai_cache and simpan.get("data") is not None \
            and time.time() - simpan.get("waktu", 0) < CACHE_UMUR:
        return simpan["data"], True, None

    jeda = JEDA_MINIMUM - (time.time() - _terakhir[0])
    if jeda > 0:
        time.sleep(jeda)
    _terakhir[0] = time.time()

    h = dict(UA)
    h["x-soso-api-key"] = key
    data = None
    if badan is not None:
        data = json.dumps(badan).encode()
        h["Content-Type"] = "application/json"

    try:
        req = urllib.request.Request(url, data=data, headers=h, method=metode)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            isi = json.loads(r.read().decode(errors="replace"))
    except urllib.error.HTTPError as e:
        pesan = f"HTTP {e.code}"
        if e.code == 401:
            pesan += " — kunci ditolak, periksa SOSOVALUE_API_KEY"
        elif e.code == 404:
            pesan += " — endpoint tidak ada (alamatnya berubah?)"
        elif e.code == 429:
            tunggu = e.headers.get("retry_after") or e.headers.get("Retry-After")
            if percobaan < ULANG_SAAT_429:
                jeda = float(tunggu) if (tunggu or "").replace(".", "").isdigit() else 20.0
                print(f"[sosovalue] 429 — tunggu {jeda:.0f} detik lalu ulangi")
                time.sleep(jeda)
                return panggil(jalur, metode, badan, params, pakai_cache, percobaan + 1)
            pesan += f" — batas laju terlampaui{f', tunggu {tunggu}s' if tunggu else ''}"
        if simpan.get("data") is not None:
            return simpan["data"], True, f"{pesan} (pakai cache lama)"
        return None, False, pesan
    except Exception as e:
        if simpan.get("data") is not None:
            return simpan["data"], True, f"{type(e).__name__} (pakai cache lama)"
        return None, False, f"{type(e).__name__}"

    cache[kunci_cache] = {"data": isi, "waktu": time.time()}
    _simpan_cache(cache)
    return isi, False, None


def _tanggal_terjauh(isi):
    """Cari tanggal paling tua di dalam balasan — menjawab 'sedalam apa datanya'."""
    ditemukan = []

    def telusur(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and len(v) >= 10 and v[:4].isdigit() and v[4] in "-/":
                    ditemukan.append(v[:10])
                else:
                    telusur(v)
        elif isinstance(o, list):
            for v in o[:200]:
                telusur(v)

    telusur(isi)
    return (min(ditemukan), max(ditemukan)) if ditemukan else (None, None)


def periksa(acara="Nonfarm Payrolls"):
    """Jalankan SEKALI dengan kunci terpasang: endpoint mana hidup, dan sedalam apa datanya.

    Ini menggantikan tebakan. Nama endpoint tidak bisa diverifikasi tanpa kunci karena auth
    dicek sebelum routing, jadi API-nya sendiri yang harus menjawab.
    """
    hasil = []
    for metode, jalur, badan in KANDIDAT_ETF:
        isi, _, err = panggil(jalur, metode, badan, None, pakai_cache=False)
        hasil.append({"nama": "ETF", "metode": metode, "jalur": jalur,
                      "hasil": f"GAGAL: {err}" if err else "OK",
                      **({} if err else {"cuplikan": json.dumps(isi, ensure_ascii=False)[:300]})})

    for nm in KANDIDAT_ACARA:
        j = f"/openapi/v1/macro/events/{urllib.parse.quote(nm)}/history"
        isi, _, err = panggil(j, "GET", None, {"start_date": "2010-01-01", "limit": 100},
                              pakai_cache=False)
        baris = {"nama": f"acara: {nm}", "metode": "GET", "jalur": "(history)"}
        if err:
            baris["hasil"] = f"GAGAL: {err}"
        else:
            data = (isi or {}).get("data") if isinstance(isi, dict) else None
            awal, akhir = _tanggal_terjauh(isi)
            baris["hasil"] = "OK" if data else "KOSONG"
            baris["jumlah"] = len(data) if isinstance(data, list) else None
            if awal:
                baris["rentang_tanggal"] = f"{awal} s/d {akhir}"
            if isinstance(data, list) and data:
                baris["contoh"] = json.dumps(data[0], ensure_ascii=False)[:160]
        hasil.append(baris)

    for nama, metode, jalur, badan in KANDIDAT:
        j = jalur.replace("{acara}", urllib.parse.quote(acara))
        params = {"start_date": "2010-01-01", "limit": 100} if "history" in j else None
        isi, _, err = panggil(j, metode, badan, params, pakai_cache=False)
        baris = {"nama": nama, "metode": metode, "jalur": j}
        if err:
            baris["hasil"] = f"GAGAL: {err}"
        else:
            awal, akhir = _tanggal_terjauh(isi)
            baris["hasil"] = "OK"
            baris["kunci_teratas"] = list(isi)[:8] if isinstance(isi, dict) else type(isi).__name__
            if awal:
                baris["rentang_tanggal"] = f"{awal} s/d {akhir}"
            baris["cuplikan"] = json.dumps(isi, ensure_ascii=False)[:400]
        hasil.append(baris)
    return hasil


def riwayat_makro(acara, mulai=None, sampai=None, limit=100):
    """Konsensus & aktual historis. HANYA untuk pembanding — lihat catatan di kepala berkas."""
    params = {"limit": min(limit, 100)}
    if mulai:
        params["start_date"] = mulai
    if sampai:
        params["end_date"] = sampai
    jalur = f"/openapi/v1/macro/events/{urllib.parse.quote(acara)}/history"
    isi, dari_cache, err = panggil(jalur, "GET", None, params)
    if err:
        return {"tidak_tersedia": err}
    return {"acara": acara, "dari_cache": dari_cache, "data": isi,
            "cara_pakai": ("Kolom forecast di sini TIDAK punya jejak vintage — tidak ada "
                           "cara memastikan angkanya sama dengan yang tampil sebelum rilis. "
                           "Pakai untuk MEMBANDINGKAN dengan arsip.py, bukan menggantikannya. "
                           "Kalau keduanya berbeda jauh, laporkan ketidaksesuaiannya, jangan "
                           "diam-diam memilih salah satu.")}


def arus_etf(jenis="us-btc-spot"):
    """Arus dana ETF spot — kategori sinyal yang tidak dipunyai sumber lain di repo ini."""
    isi, dari_cache, err = panggil(ETF_METRIK, "POST", {"type": jenis})
    if err:
        return {"tidak_tersedia": err}
    return {"jenis": jenis, "dari_cache": dari_cache, "data": isi,
            "cara_pakai": ("Arus ETF adalah kategori sinyal TERSENDIRI (arus dana), terpisah "
                           "dari teknikal dan on-chain. Inilah yang menaikkan konfluensi dari "
                           "satu kategori jadi dua. Arus masuk beruntun saat harga menyamping "
                           "berarti lain daripada arus masuk saat harga sudah naik banyak — "
                           "sebutkan konteks harganya.")}


RIWAYAT_PATH = os.path.join(BASE_DIR, "data", "sosovalue_riwayat.json")


def tarik_riwayat():
    """Tarik riwayat konsensus keempat acara terbukti, simpan sebagai berkas data.

    Kenapa disimpan, bukan dipanggil saat analisa: kuncinya hanya ada di GitHub Secrets,
    sementara studi kejutan perlu jalan di setiap analisa. Dengan berkas ini, kejutan.py
    tidak butuh kunci sama sekali — persis pola kejutan_cache.json. Datanya juga cuma
    berubah sebulan sekali, jadi menariknya tiap analisa itu pemborosan sekaligus risiko
    kena batas laju.
    """
    keluar = {"ditarik_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
              "sumber": "SoSoValue OpenAPI /macro/events/{acara}/history",
              "acara": {}}
    for label, nama in ACARA_TERBUKTI.items():
        semua, batas = [], None
        # limit maksimum 100 per permintaan, jadi ditarik mundur per potongan sampai habis.
        for _ in range(6):
            params = {"limit": 100, "start_date": "2010-01-01"}
            if batas:
                params["end_date"] = batas
            isi, _, err = panggil(f"/openapi/v1/macro/events/{urllib.parse.quote(nama)}"
                                  "/history", "GET", None, params, pakai_cache=False)
            if err:
                keluar["acara"][label] = {"tidak_tersedia": err, "nama": nama}
                break
            baris = (isi or {}).get("data") or []
            if not baris:
                break
            semua.extend(baris)
            tanggal = sorted(b.get("date", "") for b in baris if b.get("date"))
            if not tanggal or tanggal[0] == batas:
                break
            batas = tanggal[0]
            if len(baris) < 100:
                break
        if label not in keluar["acara"]:
            unik = {b.get("date"): b for b in semua if b.get("date")}
            keluar["acara"][label] = {
                "nama": nama, "jumlah": len(unik),
                "rentang": (f"{min(unik)} s/d {max(unik)}" if unik else None),
                "data": [unik[d] for d in sorted(unik)],
            }
    os.makedirs(os.path.dirname(RIWAYAT_PATH), exist_ok=True)
    with open(RIWAYAT_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(keluar, f, ensure_ascii=False, indent=1)
    return {k: {kk: vv for kk, vv in v.items() if kk != "data"}
            for k, v in keluar["acara"].items()}


ETF_HISTORIS = "/openapi/v2/etf/historicalInflowChart"
ETF_PATH = os.path.join(BASE_DIR, "data", "sosovalue_etf.json")
ETF_JENIS = ("us-btc-spot", "us-eth-spot")


def tarik_etf():
    """Tarik metrik & arus historis ETF, simpan mentah + laporkan BENTUKNYA.

    Bentuk balasan belum pernah dilihat, dan menebak struktur JSON adalah cara tercepat
    menghasilkan pembacaan yang salah tapi terlihat benar. Jadi putaran ini menyimpan apa
    adanya dan melaporkan kunci-kuncinya, bukan langsung mengurai.
    """
    keluar = {"ditarik_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "data": {}}
    ringkas = {}
    for jenis in ETF_JENIS:
        for nama, jalur in (("metrik", ETF_METRIK), ("historis", ETF_HISTORIS)):
            isi, _, err = panggil(jalur, "POST", {"type": jenis}, None, pakai_cache=False)
            kunci = f"{jenis}/{nama}"
            if err:
                keluar["data"][kunci] = {"tidak_tersedia": err}
                ringkas[kunci] = f"GAGAL: {err}"
                continue
            keluar["data"][kunci] = isi
            badan = isi.get("data") if isinstance(isi, dict) else isi
            bentuk = {"tipe": type(badan).__name__}
            if isinstance(badan, dict):
                bentuk["kunci"] = list(badan)[:14]
            elif isinstance(badan, list):
                bentuk["jumlah"] = len(badan)
                if badan and isinstance(badan[0], dict):
                    bentuk["kunci_baris"] = list(badan[0])[:14]
                    bentuk["baris_pertama"] = json.dumps(badan[0], ensure_ascii=False)[:220]
                    bentuk["baris_terakhir"] = json.dumps(badan[-1], ensure_ascii=False)[:220]
            awal, akhir = _tanggal_terjauh(isi)
            if awal:
                bentuk["rentang_tanggal"] = f"{awal} s/d {akhir}"
            ringkas[kunci] = bentuk
    os.makedirs(os.path.dirname(ETF_PATH), exist_ok=True)
    with open(ETF_PATH, "w", encoding="utf-8", newline=chr(10)) as f:
        json.dump(keluar, f, ensure_ascii=False, indent=1)
    return ringkas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--periksa", action="store_true",
                    help="uji endpoint mana yang hidup & sedalam apa datanya")
    ap.add_argument("--etf", nargs="?", const="us-btc-spot", help="arus dana ETF spot")
    ap.add_argument("--riwayat", help='nama acara makro, mis. "Nonfarm Payrolls"')
    ap.add_argument("--mulai", help="tanggal awal YYYY-MM-DD")
    ap.add_argument("--sampai", help="tanggal akhir YYYY-MM-DD")
    ap.add_argument("--tarik-riwayat", dest="tarik_riwayat", action="store_true",
                    help="tarik riwayat konsensus & simpan ke cloud/data/")
    ap.add_argument("--tarik-etf", dest="tarik_etf", action="store_true",
                    help="tarik data ETF & laporkan bentuknya")
    ap.add_argument("--ringkas", action="store_true", help="buang panduan statis")
    args = ap.parse_args()

    keluar = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": "SoSoValue OpenAPI (tier Demo gratis; paid plan disebut akan menyusul)",
    }
    if not _kunci():
        keluar["tidak_tersedia"] = (
            "SOSOVALUE_API_KEY belum diisi. Arus ETF dan konsensus makro dari SoSoValue "
            "TIDAK tersedia — sampaikan apa adanya. Analisa tetap jalan dari sumber lain.")
        print(json.dumps(keluar, indent=2, ensure_ascii=False))
        return

    if args.periksa:
        keluar["pemeriksaan"] = periksa()
    if args.tarik_riwayat:
        keluar["riwayat_tersimpan"] = tarik_riwayat()
    if args.tarik_etf:
        keluar["bentuk_etf"] = tarik_etf()
    if args.etf:
        keluar["arus_etf"] = arus_etf(args.etf)
    if args.riwayat:
        keluar["riwayat_makro"] = riwayat_makro(args.riwayat, args.mulai, args.sampai)
    if not (args.periksa or args.etf or args.riwayat or args.tarik_riwayat or args.tarik_etf):
        keluar["catatan"] = "tidak ada yang diminta; pakai --periksa, --etf, atau --riwayat"

    if args.ringkas:
        from backtest import buang_panduan
        keluar = buang_panduan(keluar)
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

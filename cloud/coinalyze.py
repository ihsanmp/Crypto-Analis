"""Coinalyze — likuidasi & riwayat open interest, satu-satunya celah yang tersisa.

KENAPA BERKAS INI ADA. derivatif.py sudah menutup funding & OI SAAT INI tanpa kunci
(CoinGecko + Hyperliquid), tapi dua hal tetap kosong: LIKUIDASI, yang tidak ada di sumber
keyless mana pun, dan RIWAYAT OI, yang terpaksa ditumbuhkan sendiri sejak run pertama
sehingga angka perubahannya baru muncul setelah berhari-hari.

Dokumentasi resminya menyebut "The API is free", batas 40 panggilan per menit, dan — yang
menentukan — riwayat granularitas HARIAN tidak pernah dihapus (hanya intraday yang dipangkas
ke 1.500-2.000 titik). Kalau itu benar, arsip harian kita jadi tidak perlu.

TAPI "gratis" di dokumentasi belum tentu berarti "terbuka untuk kunci ini". CoinMarketCap
sudah mengajarkan itu: endpoint yang tertulis tersedia ternyata membalas 403 tergantung
paket. Karena itu berkas ini dimulai dari --periksa, bukan dari asumsi, dan tidak ada satu
pun fungsi pengambil data dibangun sebelum pemeriksaannya lulus.

Mereka meminta atribusi kalau datanya dipakai di tempat publik. Itu wajar dan murah;
jalur analisa harus menyebut Coinalyze saat memakai angkanya.

Kunci dibaca dari environment (COINALYZE_API_KEY) dan TIDAK PERNAH dicetak.

Pemakaian:
    python cloud/coinalyze.py --periksa
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.coinalyze.net/v1"
TIMEOUT = 25
# 40 panggilan/menit = 1,5 detik per panggilan. Dipakai jeda 1,6 detik supaya pemeriksaan
# beruntun tidak pernah menyentuh 429 dan hasilnya tidak tercemar oleh batas laju sendiri.
JEDA = 1.6


def _kunci():
    return os.environ.get("COINALYZE_API_KEY", "").strip() or None


def panggil(jalur, params=None):
    """Return (data, error). Kunci dikirim lewat HEADER, tidak pernah lewat query string.

    Dokumentasinya mengizinkan keduanya. Header dipilih karena URL bocor ke log, pesan
    error, dan riwayat proxy jauh lebih mudah daripada header — dan repo ini publik.
    """
    kunci = _kunci()
    if not kunci:
        return None, "COINALYZE_API_KEY tidak diset"
    url = API + jalur + (("?" + urllib.parse.urlencode(params)) if params else "")
    req = urllib.request.Request(url, headers={
        "api_key": kunci, "Accept": "application/json",
        "User-Agent": "riset-koin/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode(errors="replace")), None
    except urllib.error.HTTPError as e:
        tubuh = ""
        try:
            tubuh = e.read(200).decode(errors="replace")[:150]
        except Exception:
            pass
        tunggu = e.headers.get("Retry-After") if e.headers else None
        pesan = f"HTTP {e.code}" + (f" — {tubuh}" if tubuh else "")
        if tunggu:
            pesan += f" (Retry-After {tunggu}s)"
        return None, pesan
    except Exception as e:
        return None, f"{type(e).__name__}"


def _simbol_btc():
    """Cari kode pasar perpetual BTC yang dipakai Coinalyze. Kodenya milik mereka sendiri."""
    data, err = panggil("/future-markets")
    if err:
        return None, err
    calon = [m for m in (data or [])
             if (m.get("base_asset") or "").upper() == "BTC"
             and m.get("is_perpetual")
             and (m.get("quote_asset") or "").upper() in ("USDT", "USD")]
    if not calon:
        return None, "tidak ada pasar perpetual BTC di daftar"
    # Binance lebih dulu kalau ada: pasar paling dalam, jadi paling mewakili.
    calon.sort(key=lambda m: (0 if "A" == (m.get("exchange") or "") else 1,
                              m.get("symbol") or ""))
    return calon[0].get("symbol"), None


def periksa():
    """Tiga pertanyaan yang harus terjawab SEBELUM apa pun dibangun di atasnya."""
    if not _kunci():
        return {"tidak_bisa_diperiksa":
                "COINALYZE_API_KEY tidak ada di environment. Kuncinya hanya di GitHub "
                "Secrets — jalankan pemeriksaan ini di Actions, JANGAN menempelkan "
                "kuncinya ke mana pun."}

    hasil = {"diperiksa_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
             "terbuka": [], "tertutup": []}

    sim, err = _simbol_btc()
    hasil["simbol_btc_dipakai"] = sim or f"gagal: {err}"
    if not sim:
        hasil["ringkasan"] = "daftar pasar tidak terbaca — pemeriksaan berhenti"
        return hasil

    akhir = int(time.time())
    mulai_30 = akhir - 30 * 86400
    mulai_400 = akhir - 400 * 86400        # menguji klaim "riwayat harian tidak dihapus"

    UJI = (
        ("funding_sekarang", "/funding-rate", {"symbols": sim},
         "funding saat ini — pembanding silang untuk derivatif.py"),
        ("oi_sekarang", "/open-interest", {"symbols": sim, "convert_to_usd": "true"},
         "OI saat ini"),
        ("oi_riwayat_30h", "/open-interest-history",
         {"symbols": sim, "interval": "daily", "from": mulai_30, "to": akhir,
          "convert_to_usd": "true"},
         "RIWAYAT OI — kalau ini terbuka, arsip harian kita tidak perlu lagi"),
        ("oi_riwayat_400h", "/open-interest-history",
         {"symbols": sim, "interval": "daily", "from": mulai_400, "to": akhir,
          "convert_to_usd": "true"},
         "menguji klaim dokumentasi bahwa riwayat HARIAN tidak pernah dihapus"),
        ("likuidasi_30h", "/liquidation-history",
         {"symbols": sim, "interval": "daily", "from": mulai_30, "to": akhir,
          "convert_to_usd": "true"},
         "LIKUIDASI — satu-satunya celah yang tidak tertutup sumber keyless mana pun"),
        ("long_short_30h", "/long-short-ratio-history",
         {"symbols": sim, "interval": "daily", "from": mulai_30, "to": akhir},
         "rasio long/short — posisi ritel"),
        ("funding_riwayat_30h", "/funding-rate-history",
         {"symbols": sim, "interval": "daily", "from": mulai_30, "to": akhir},
         "riwayat funding untuk melihat ARAH, bukan cuma level"),
    )

    for nama, jalur, params, kenapa in UJI:
        time.sleep(JEDA)
        data, e = panggil(jalur, params)
        baris = {"nama": nama, "jalur": jalur, "kenapa": kenapa}
        if e:
            baris["alasan"] = e
            hasil["tertutup"].append(baris)
            continue
        # Bentuk balasannya: daftar per simbol, tiap simbol punya `history`.
        titik = []
        if isinstance(data, list) and data:
            titik = data[0].get("history") or []
        baris["titik"] = len(titik)
        if titik:
            def _tgl(t):
                return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
            baris["rentang"] = f"{_tgl(titik[0].get('t'))} s/d {_tgl(titik[-1].get('t'))}"
            baris["contoh_terakhir"] = titik[-1]
        elif isinstance(data, list) and data:
            baris["contoh"] = {k: v for k, v in list(data[0].items())[:6]}
        hasil["terbuka"].append(baris)

    hasil["ringkasan"] = (f"{len(hasil['terbuka'])} terbuka, {len(hasil['tertutup'])} "
                          "tertutup untuk kunci ini")
    hasil["yang_menentukan"] = (
        "Kalau likuidasi_30h TERBUKA, celah terakhir tertutup. Kalau oi_riwayat_400h "
        "mengembalikan ratusan titik, arsip harian di derivatif.py tidak perlu lagi "
        "ditumbuhkan. Kalau keduanya tertutup, katakan apa adanya dan jangan bangun "
        "apa pun di atasnya.")
    return hasil


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PASAR_CACHE = os.path.join(BASE_DIR, "data", "coinalyze_pasar.json")
PASAR_UMUR = 7 * 86400        # daftar pasar nyaris statis; menariknya tiap run itu boros


def _daftar_pasar():
    """{ASET: simbol pasar} untuk perpetual USDT/USD. Dicache seminggu."""
    try:
        with open(PASAR_CACHE, encoding="utf-8") as f:
            c = json.load(f)
        if time.time() - c.get("waktu", 0) < PASAR_UMUR and c.get("data"):
            return c["data"], None
    except Exception:
        pass
    data, err = panggil("/future-markets")
    if err:
        return {}, err
    peta = {}
    for m in data or []:
        if not m.get("is_perpetual"):
            continue
        if (m.get("quote_asset") or "").upper() not in ("USDT", "USD"):
            continue
        aset = (m.get("base_asset") or "").upper()
        sim = m.get("symbol") or ""
        # Akhiran ".A" = Binance di penamaan Coinalyze: pasar terdalam, jadi paling
        # mewakili. Kalau tidak ada, pakai yang pertama muncul dan sebutkan bursanya.
        if aset and (aset not in peta or sim.endswith(".A")):
            peta[aset] = sim
    try:
        os.makedirs(os.path.dirname(PASAR_CACHE), exist_ok=True)
        with open(PASAR_CACHE, "w", encoding="utf-8") as f:
            json.dump({"waktu": time.time(), "data": peta}, f)
    except OSError:
        pass
    return peta, None


def _riwayat(jalur, sim, hari, tambahan=None):
    """Deret harian untuk satu simbol. Return (list titik, error)."""
    akhir = int(time.time())
    p = {"symbols": sim, "interval": "daily",
         "from": akhir - hari * 86400, "to": akhir}
    p.update(tambahan or {})
    data, err = panggil(jalur, p)
    if err:
        return [], err
    if isinstance(data, list) and data:
        return data[0].get("history") or [], None
    return [], "balasan kosong"


def _ubah(titik, hari):
    """Perubahan persen antara titik terakhir dan ~`hari` lalu. None kalau kurang data."""
    if len(titik) < 2:
        return None
    i = max(0, len(titik) - 1 - hari)
    awal, kini = titik[i].get("c"), titik[-1].get("c")
    if not awal or kini is None:
        return None
    return round((kini - awal) / awal * 100, 2)


def ringkas(simbol, hari=30):
    """Likuidasi, OI, rasio long/short, dan funding — semuanya berikut ARAHNYA."""
    simbol = (simbol or "").upper()
    hasil = {"simbol": simbol, "sumber": "Coinalyze",
             "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}
    if not _kunci():
        hasil["tidak_tersedia"] = "COINALYZE_API_KEY tidak diset"
        return hasil

    peta, err = _daftar_pasar()
    if err:
        hasil["tidak_tersedia"] = f"daftar pasar gagal: {err}"
        return hasil
    sim = peta.get(simbol)
    if not sim:
        hasil["tidak_tersedia"] = (
            f"{simbol} tidak punya pasar perpetual di Coinalyze. Perlakukan sebagai TIDAK "
            "ADA pasar derivatif, bukan sebagai data yang gagal diambil.")
        return hasil
    hasil["pasar"] = sim

    # LIKUIDASI. `l` = posisi long yang dilikuidasi, `s` = short. Long besar berarti
    # pembeli berleverage dipaksa keluar (kaskade turun); short besar berarti bahan bakar
    # short squeeze. Yang menentukan adalah SELISIHNYA, bukan totalnya.
    liq, e = _riwayat("/liquidation-history", sim, hari, {"convert_to_usd": "true"})
    if e:
        hasil["likuidasi_tidak_tersedia"] = e
    elif liq:
        tot_l = sum(x.get("l") or 0 for x in liq)
        tot_s = sum(x.get("s") or 0 for x in liq)
        akhir = liq[-1]
        hasil["likuidasi"] = {
            "hari": len(liq),
            "long_usd": round(tot_l),
            "short_usd": round(tot_s),
            "sisi_lebih_terpukul": ("LONG" if tot_l > tot_s * 1.2 else
                                    "SHORT" if tot_s > tot_l * 1.2 else "seimbang"),
            "hari_terakhir": {
                "tanggal": datetime.fromtimestamp(akhir.get("t", 0),
                                                  timezone.utc).strftime("%Y-%m-%d"),
                "long_usd": round(akhir.get("l") or 0),
                "short_usd": round(akhir.get("s") or 0),
            },
        }

    # OPEN INTEREST berikut arahnya — ini yang dulu harus ditumbuhkan sendiri berhari-hari.
    oi, e = _riwayat("/open-interest-history", sim, 90, {"convert_to_usd": "true"})
    if e:
        hasil["oi_tidak_tersedia"] = e
    elif oi:
        hasil["open_interest"] = {
            "kini_usd": round(oi[-1].get("c") or 0),
            "ubah_7h_persen": _ubah(oi, 7),
            "ubah_30h_persen": _ubah(oi, 30),
            "hari_riwayat": len(oi),
        }

    ls, e = _riwayat("/long-short-ratio-history", sim, hari)
    if not e and ls:
        akhir = ls[-1]
        hasil["long_short"] = {
            "rasio": akhir.get("r"),
            "long_persen": akhir.get("l"),
            "short_persen": akhir.get("s"),
            "rasio_30h_lalu": ls[0].get("r"),
        }

    fr, e = _riwayat("/funding-rate-history", sim, hari)
    if not e and fr:
        nilai = [x.get("c") for x in fr if x.get("c") is not None]
        if nilai:
            hasil["funding"] = {
                "kini_persen": nilai[-1],
                "rata2_persen": round(sum(nilai) / len(nilai), 5),
                "hari_negatif": sum(1 for v in nilai if v < 0),
                "dari_hari": len(nilai),
            }

    hasil["wajib_dibaca"] = (
        "LIKUIDASI: `long_usd` besar = pembeli berleverage dipaksa keluar (kaskade turun); "
        "`short_usd` besar = bahan bakar short squeeze. Yang menentukan SELISIHNYA, bukan "
        "totalnya — total besar di kedua sisi cuma berarti pasarnya bergejolak. "
        "OPEN INTEREST: naik BERSAMA harga = uang baru masuk (tren lebih kokoh); TURUN saat "
        "harga naik = posisi short ditutup, bukan pembelian baru (reli lebih rapuh). Selalu "
        "pasangkan arah OI dengan arah harga sebelum menyimpulkan. "
        "FUNDING: `hari_negatif` menunjukkan seberapa sering short yang membayar — nol dari "
        "30 hari berarti tekanan long tak pernah reda. "
        "Sebut 'Sumber derivatif: Coinalyze' satu kali saat memakai angka-angka ini.")
    return hasil


def main():
    p = argparse.ArgumentParser(description="Coinalyze: likuidasi, OI, funding")
    p.add_argument("simbol", nargs="?", help="ticker koin, mis. BTC")
    p.add_argument("--periksa", action="store_true", help="periksa akses tiap endpoint")
    p.add_argument("--ringkas", action="store_true", help="tanpa indentasi")
    a = p.parse_args()
    if a.periksa:
        print(json.dumps(periksa(), ensure_ascii=False, indent=1))
    elif a.simbol:
        print(json.dumps(ringkas(a.simbol), ensure_ascii=False,
                         indent=None if a.ringkas else 1))
    else:
        p.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()

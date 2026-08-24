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


def main():
    p = argparse.ArgumentParser(description="Coinalyze: periksa akses tier gratis")
    p.add_argument("--periksa", action="store_true")
    a = p.parse_args()
    if not a.periksa:
        p.print_help()
        sys.exit(2)
    print(json.dumps(periksa(), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

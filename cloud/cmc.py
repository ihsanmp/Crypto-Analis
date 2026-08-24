"""CoinMarketCap — apa yang SUNGGUH bisa diambil kunci kita, bukan apa yang tertulis di brosur.

TEMUAN YANG MENENTUKAN: API CoinMarketCap TIDAK PUNYA satu pun endpoint funding rate,
open interest, likuidasi, derivatif, atau perpetual. Nol dari 51 endpoint. Jadi angka
funding dan likuidasi yang muncul di CMC AI TIDAK berasal dari API yang mereka jual —
itu data internal. Mengejarnya lewat API ini hanya membuang waktu, dan derivatif.py
(CoinGecko + Hyperliquid) tetap satu-satunya jalan gratis untuk funding & OI.

YANG JUSTRU BERGUNA dan belum dipakai di sini: riwayat metrik global. CoinGecko /global
hanya memberi dominasi BTC SAAT INI, sehingga kalimat seperti "dominasi naik dari 58,39%
ke 59,51%" mustahil disusun. Endpoint global-metrics/quotes/historical memberi persis itu
— KALAU paket kuncinya mengizinkan.

Dan di situlah masalahnya: paket gratis memblokir sebagian endpoint dengan 402/403, dan
mana yang diblokir TIDAK bisa ditebak dari dokumentasi. `cryptoCategories` sudah pernah
403 di sini (lihat kategori.py). Karena itu berkas ini dimulai dari PEMERIKSAAN, bukan dari
asumsi: `--periksa` menembak tiap kandidat dengan parameter paling murah lalu melaporkan
apa adanya.

Kunci dibaca dari environment (COINMARKETCAP_API_KEY) dan TIDAK PERNAH dicetak.

Pemakaian:
    python cloud/cmc.py --periksa
    python cloud/cmc.py --dominasi 7
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://pro-api.coinmarketcap.com"
TIMEOUT = 20

# Kandidat yang RELEVAN untuk bot ini saja — bukan seluruh 51 endpoint. Tiap baris:
# (nama, jalur, params, kenapa kita peduli).
KANDIDAT = (
    ("key_info", "/v1/key/info", {},
     "paket & sisa kredit — menentukan sisanya bisa dipakai atau tidak"),
    ("global_now", "/v1/global-metrics/quotes/latest", {},
     "dominasi BTC saat ini (CoinGecko sudah punya; ini pembanding silang)"),
    ("global_riwayat", "/v1/global-metrics/quotes/historical",
     {"time_start": "", "time_end": "", "interval": "daily", "count": "8"},
     "RIWAYAT dominasi BTC — satu-satunya cara menyusun 'dominasi naik dari X ke Y'"),
    ("fear_greed_now", "/v3/fear-and-greed/latest", {},
     "Fear & Greed resmi CMC"),
    ("fear_greed_riwayat", "/v3/fear-and-greed/historical", {"limit": "10"},
     "riwayat Fear & Greed untuk melihat perubahan sentimen, bukan level"),
    ("cmc100", "/v3/index/cmc100-latest", {},
     "indeks 100 koin — pembanding pasar yang lebih baik daripada hitungan sendiri"),
    ("cmc100_riwayat", "/v3/index/cmc100-historical", {"count": "8"},
     "riwayat indeks: pembanding 'seluruh pasar' untuk isolasi gerakan"),
    ("performa", "/v2/cryptocurrency/price-performance-stats/latest",
     {"symbol": "BTC", "time_period": "all_time"},
     "ROI & jarak dari ATH/ATL per periode, sudah dihitung di sisi CMC"),
    ("gainers_losers", "/v1/cryptocurrency/trending/gainers-losers", {"limit": "10"},
     "penggerak terbesar hari ini"),
    ("trending_token", "/v1/community/trending/token", {},
     "narasi yang sedang ramai — pembanding untuk sentiment.py"),
    ("kategori", "/v1/cryptocurrency/categories", {"limit": "1"},
     "sudah terbukti 403 di paket gratis; diperiksa ulang supaya catatannya mutakhir"),
)


def _kunci():
    k = os.environ.get("COINMARKETCAP_API_KEY", "").strip()
    return k or None


def panggil(jalur, params=None):
    """Return (data, error). Kunci tidak pernah masuk ke pesan error."""
    kunci = _kunci()
    if not kunci:
        return None, "COINMARKETCAP_API_KEY tidak diset"
    url = API + jalur + (("?" + urllib.parse.urlencode(params)) if params else "")
    req = urllib.request.Request(url, headers={
        "X-CMC_PRO_API_KEY": kunci, "Accept": "application/json",
        "User-Agent": "riset-koin/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode(errors="replace")), None
    except urllib.error.HTTPError as e:
        pesan = ""
        try:
            tubuh = json.loads(e.read().decode(errors="replace"))
            pesan = (tubuh.get("status") or {}).get("error_message") or ""
        except Exception:
            pass
        return None, f"HTTP {e.code}" + (f" — {pesan}" if pesan else "")
    except Exception as e:
        return None, f"{type(e).__name__}"


def periksa():
    """Tembak tiap kandidat, laporkan mana yang benar-benar terbuka untuk kunci ini."""
    if not _kunci():
        return {"tidak_bisa_diperiksa":
                "COINMARKETCAP_API_KEY tidak ada di environment. Di GitHub Actions kunci "
                "sudah dioper lewat secrets; jalankan pemeriksaan ini di sana, JANGAN "
                "menempelkan kuncinya ke mana pun."}
    akhir = datetime.now(timezone.utc)
    hasil = {"diperiksa_utc": akhir.strftime("%Y-%m-%d %H:%M"), "terbuka": [], "tertutup": []}
    for nama, jalur, params, kenapa in KANDIDAT:
        p = dict(params)
        if p.get("time_start") == "":
            p["time_start"] = (akhir - timedelta(days=8)).strftime("%Y-%m-%d")
            p["time_end"] = akhir.strftime("%Y-%m-%d")
        data, err = panggil(jalur, p or None)
        baris = {"nama": nama, "jalur": jalur, "kenapa": kenapa}
        if err:
            baris["alasan"] = err
            hasil["tertutup"].append(baris)
        else:
            kredit = ((data.get("status") or {}).get("credit_count")
                      if isinstance(data, dict) else None)
            baris["kredit"] = kredit
            hasil["terbuka"].append(baris)
    hasil["ringkasan"] = (f"{len(hasil['terbuka'])} terbuka, {len(hasil['tertutup'])} "
                          "tertutup untuk kunci ini")
    hasil["wajib_dibaca"] = (
        "API CoinMarketCap TIDAK punya funding rate, open interest, maupun likuidasi — "
        "nol dari 51 endpoint. Angka-angka itu di CMC AI berasal dari data internal, bukan "
        "dari API yang dijual. Untuk funding & OI tetap pakai derivatif.py.")
    return hasil


def dominasi(hari=7):
    """Perubahan dominasi BTC selama `hari` terakhir. None-friendly: melapor kalau tertutup."""
    akhir = datetime.now(timezone.utc)
    data, err = panggil("/v1/global-metrics/quotes/historical", {
        "time_start": (akhir - timedelta(days=hari + 1)).strftime("%Y-%m-%d"),
        "time_end": akhir.strftime("%Y-%m-%d"),
        "interval": "daily", "count": str(hari + 2)})
    if err:
        return {"tidak_tersedia": err,
                "arti": ("Riwayat dominasi tidak terbuka untuk kunci ini. Pakai dominasi "
                         "SAAT INI dari pasarglobal.py dan JANGAN menyebut perubahannya — "
                         "arah dominasi tanpa data riwayat adalah tebakan.")}
    titik = ((data.get("data") or {}).get("quotes")
             if isinstance(data, dict) else None) or []
    if len(titik) < 2:
        return {"tidak_tersedia": f"hanya {len(titik)} titik dikembalikan"}
    awal, kini = titik[0], titik[-1]
    a = awal.get("btc_dominance")
    b = kini.get("btc_dominance")
    if a is None or b is None:
        return {"tidak_tersedia": "field btc_dominance kosong"}
    return {
        "dari_persen": round(a, 2), "ke_persen": round(b, 2),
        "ubah_pp": round(b - a, 2),
        "dari_tanggal": (awal.get("timestamp") or "")[:10],
        "sampai_tanggal": (kini.get("timestamp") or "")[:10],
        "arti": ("Dominasi NAIK = dana mengumpul ke BTC, altcoin melemah relatif. "
                 "TURUN = sebaliknya."),
    }


def main():
    p = argparse.ArgumentParser(description="CoinMarketCap: periksa akses & riwayat dominasi")
    p.add_argument("--periksa", action="store_true",
                   help="tembak tiap endpoint kandidat, laporkan mana yang terbuka")
    p.add_argument("--dominasi", type=int, metavar="HARI",
                   help="perubahan dominasi BTC selama N hari")
    a = p.parse_args()
    if a.periksa:
        print(json.dumps(periksa(), ensure_ascii=False, indent=1))
    elif a.dominasi:
        print(json.dumps(dominasi(a.dominasi), ensure_ascii=False, indent=1))
    else:
        p.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()

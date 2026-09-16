"""Altcoin Season Index — DIHITUNG sendiri dari harga, lalu diadu dengan angka terbitan.

Langkah 5 kerangka #Kalimasada memakai "musim altcoin" sebagai konteks timing. Indeks yang
dikutip orang biasanya milik blockchaincenter.net: dari 50 koin teratas (tanpa stablecoin dan
token beragun aset), BERAPA PERSEN yang mengungguli Bitcoin selama 90 hari terakhir.
>= 75 disebut Altcoin Season, <= 25 Bitcoin Season.

KENAPA DUA ANGKA, BUKAN SATU. Paket gratis CoinGecko TIDAK memberi perubahan 90 hari — diuji
16 Sep 2026: meminta `price_change_percentage=30d,90d` hanya mengembalikan yang 30d. Jadi:

  - Jendela 30 HARI DIHITUNG SENDIRI di sini, dari harga, dengan definisi yang sama persis.
  - Jendela 90 HARI (indeks "musim" yang sesungguhnya) DIAMBIL dari halaman blockchaincenter,
    karena tidak bisa dihitung dari sumber gratis.

Dan justru karena keduanya ada, pembacaan halaman itu MEMERIKSA DIRINYA SENDIRI: halaman yang
sama juga menerbitkan angka 30 hari ("Month"). Tiap kali dijalankan, angka 30 hari kita
dibandingkan dengan angka 30 hari mereka. Kalau keduanya jauh berbeda, yang salah hampir pasti
pembacaan halamannya — dan itu dilaporkan, bukan didiamkan. Scraper yang tidak punya cara
ketahuan salah adalah scraper yang suatu hari mengarang angka tanpa ada yang sadar.

HASIL PENGUJIAN (16 Sep 2026): hitungan kita 30 · terbitan mereka 33 — selisih 3 poin, yaitu
1-2 koin. Sisa selisihnya dari daftar pengecualian dan jam pengambilan yang tidak sama persis.

PENGECUALIAN TIDAK DITULIS TANGAN. Daftar stablecoin / wrapped / liquid-staking / emas
tokenisasi diambil dari KATEGORI CoinGecko, bukan dari daftar simbol yang diketik di sini.
Daftar ketikan tangan membusuk diam-diam: token baru masuk 50 besar dan ikut terhitung sebagai
"altcoin yang mengungguli BTC" padahal ia cuma dolar.

Pemakaian:
    python cloud/musim.py
    python cloud/musim.py --json
    python cloud/musim.py --paksa      # abaikan cache
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.environ.get("CACHE_DIR_MUSIM") or os.path.join(BASE_DIR, "data")
CACHE_PATH = os.path.join(CACHE_DIR, "musim_cache.json")
UA = "riset-koin/1.0"

# Indeksnya bergerak lambat (jendela 30-90 hari). Menghitung ulang tiap pesan cuma memakan
# jatah rate limit CoinGecko yang dipakai bagian lain bot ini.
UMUR_INDEKS_DETIK = 6 * 3600
UMUR_KATEGORI_DETIK = 7 * 24 * 3600

N_TERATAS = 50
KATEGORI_DIKECUALIKAN = ("stablecoins", "wrapped-tokens", "liquid-staking-tokens",
                         "tokenized-gold")
AMBANG_ALTSEASON = 75
AMBANG_BTCSEASON = 25
# Selisih yang masih wajar antara hitungan kita dan terbitan mereka, dalam poin indeks.
# 6 poin = 3 koin dari 50; di atas itu bukan lagi beda jam pengambilan.
TOLERANSI_SILANG = 6

HASIL_UJI = ("Diuji 16 Sep 2026: indeks 30 hari hitungan sendiri 30, terbitan "
             "blockchaincenter 33 — selisih 3 poin (1-2 koin dari 50).")


def _curl(url, timeout=40, ua=UA):
    try:
        p = subprocess.run(["curl", "-s", "-L", "--max-time", str(timeout), "-A", ua, url],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout + 10)
        return p.stdout if p.returncode == 0 else ""
    except Exception:
        return ""


def _json(url):
    try:
        return json.loads(_curl(url) or "null")
    except json.JSONDecodeError:
        return None


def _baca_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _tulis_cache(isi):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(isi, f, ensure_ascii=False, indent=1, sort_keys=True)
    except OSError:
        pass


# --- Bahan ------------------------------------------------------------------------------
def _pasar(kategori=None, per_page=100):
    u = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
         f"&order=market_cap_desc&per_page={per_page}&page=1&sparkline=false"
         "&price_change_percentage=30d")
    if kategori:
        u += "&category=" + kategori
    d = _json(u)
    return d if isinstance(d, list) else None


def dikecualikan(cache=None, paksa=False):
    """id CoinGecko yang bukan altcoin menurut KATEGORI CoinGecko. None kalau gagal diambil.

    DICOCOKKAN LEWAT id, BUKAN SIMBOL. Simbol tidak unik: "Wrapped SOL" bersimbol `sol` dan
    ada token terbungkus bersimbol `btc`, jadi versi pertama alat ini mencoret SOLANA dan
    BITCOIN sendiri dari daftar altcoin — indeksnya tetap keluar, tetap masuk akal dibaca,
    dan tetap salah. id CoinGecko unik, jadi tabrakan itu tidak bisa terjadi.

    None penting: daftar pengecualian yang diam-diam kosong membuat semua stablecoin
    dihitung sebagai altcoin yang kalah dari BTC, dan indeksnya turun tanpa sebab nyata.
    """
    cache = _baca_cache() if cache is None else cache
    simpan = cache.get("kategori") or {}
    # Syarat `simpan.get("id")` bukan basa-basi: cache versi lama menyimpan kunci lain, dan
    # tanpa syarat ini ia dianggap masih segar lalu mengembalikan daftar kosong selamanya.
    if (not paksa and simpan.get("id")
            and time.time() - (simpan.get("waktu") or 0) < UMUR_KATEGORI_DETIK):
        return set(simpan["id"])
    keluar = set()
    for kat in KATEGORI_DIKECUALIKAN:
        d = _pasar(kategori=kat)
        if d is None:
            return set(simpan.get("id") or []) or None       # 429: pakai yang lama
        keluar |= {c.get("id") for c in d if c.get("id")}
    cache["kategori"] = {"waktu": time.time(), "id": sorted(keluar)}
    _tulis_cache(cache)
    return keluar or None


def hitung_30h(kecuali, pasar=None):
    """Indeks 30 hari, definisi blockchaincenter: berapa persen dari 50 koin teratas
    (tanpa BTC dan tanpa yang dikecualikan) yang perubahan 30 harinya di atas BTC.

    `pasar` boleh diisi supaya hitungannya bisa diuji tanpa jaringan."""
    d = pasar if pasar is not None else _pasar()
    if not d:
        return None
    btc = next((c for c in d if c.get("symbol") == "btc"), None)
    acuan = (btc or {}).get("price_change_percentage_30d_in_currency")
    if acuan is None:
        return None
    layak = [c for c in d
             if c.get("id") not in kecuali
             and c.get("price_change_percentage_30d_in_currency") is not None]
    lima_puluh = layak[:N_TERATAS]
    if len(lima_puluh) < N_TERATAS:
        return None                      # kurang dari 50: indeksnya bukan indeks yang sama
    alt = [c for c in lima_puluh if c.get("symbol") != "btc"]
    unggul = [c for c in alt if c["price_change_percentage_30d_in_currency"] > acuan]
    return {"indeks": round(len(unggul) / N_TERATAS * 100),
            "n_unggul": len(unggul), "n_altcoin": len(alt),
            "btc_30h_persen": round(acuan, 1),
            "unggul_teratas": [c["symbol"].upper() for c in unggul[:8]]}


_RE_NILAI = re.compile(r"(Altcoin Season|Month|Year)\s*\(\s*(?:<!--\s*-->)?\s*(\d{1,3})")


def situs():
    """Angka terbitan blockchaincenter. None kalau halamannya berubah bentuk.

    Halamannya aplikasi Next.js, jadi angkanya diambil dari label tombol ("Altcoin Season
    (27)"). Kalau suatu hari labelnya berganti, yang benar adalah GAGAL — bukan menebak
    angka lain yang kebetulan ada di halaman.
    """
    return urai_situs(_curl("https://www.blockchaincenter.net/en/altcoin-season-index/",
                            ua="Mozilla/5.0"))


def urai_situs(html):
    """Pemisahan dari pengambilannya supaya bisa diuji dengan potongan halaman sungguhan."""
    if not html:
        return None
    nilai = {m.group(1): int(m.group(2)) for m in _RE_NILAI.finditer(html)}
    if "Altcoin Season" not in nilai:
        return None
    keluar = {"musim_90h": nilai["Altcoin Season"]}
    if "Month" in nilai:
        keluar["bulan_30h"] = nilai["Month"]
    if "Year" in nilai:
        keluar["tahun_365h"] = nilai["Year"]
    if any(not 0 <= v <= 100 for v in keluar.values()):
        return None
    return keluar


def vonis(indeks):
    if indeks is None:
        return None
    if indeks >= AMBANG_ALTSEASON:
        return "ALTCOIN SEASON"
    if indeks <= AMBANG_BTCSEASON:
        return "BITCOIN SEASON"
    return "tidak keduanya"


def _rakit():
    cache = _baca_cache()
    kecuali = dikecualikan(cache) or set()
    sendiri = hitung_30h(kecuali) if kecuali else None
    terbit = situs()
    silang = None
    if sendiri and terbit and terbit.get("bulan_30h") is not None:
        selisih = abs(sendiri["indeks"] - terbit["bulan_30h"])
        silang = {"selisih_poin": selisih,
                  "cocok": selisih <= TOLERANSI_SILANG,
                  "keterangan": ("hitungan sendiri dan terbitan blockchaincenter untuk jendela "
                                 "30 hari saling mendekati" if selisih <= TOLERANSI_SILANG else
                                 "hitungan sendiri dan terbitan blockchaincenter BERBEDA JAUH "
                                 "untuk jendela 30 hari — angka 90 hari dari situs itu patut "
                                 "dicurigai, jangan dikutip sebagai fakta")}
    if terbit and silang and not silang["cocok"]:
        terbit = dict(terbit, meragukan=True)
    hasil = {
        "indeks_30h_dihitung_sendiri": sendiri,
        "indeks_terbitan_blockchaincenter": terbit,
        "periksa_silang": silang,
        "vonis_90h": (vonis((terbit or {}).get("musim_90h"))
                      if terbit and not terbit.get("meragukan") else None),
        "vonis_30h": vonis((sendiri or {}).get("indeks")),
        "ambang": {"altcoin_season": AMBANG_ALTSEASON, "bitcoin_season": AMBANG_BTCSEASON},
        "hasil_uji": HASIL_UJI,
        "waktu": time.time(),
    }
    if not kecuali:
        hasil["peringatan"] = ("daftar pengecualian (stablecoin/wrapped) gagal diambil — "
                               "indeks 30 hari tidak dihitung supaya tidak menyesatkan")
    return hasil, cache


def musim(paksa=False):
    cache = _baca_cache()
    lama = cache.get("indeks")
    if not paksa and lama and time.time() - (lama.get("waktu") or 0) < UMUR_INDEKS_DETIK:
        return dict(lama, dari_cache=True,
                    umur_jam=round((time.time() - lama["waktu"]) / 3600, 1))
    baru, cache = _rakit()
    if (baru["indeks_30h_dihitung_sendiri"] is None
            and baru["indeks_terbitan_blockchaincenter"] is None):
        if lama:
            return dict(lama, dari_cache=True, gagal_segarkan=True,
                        umur_jam=round((time.time() - lama["waktu"]) / 3600, 1))
        return baru
    cache["indeks"] = baru
    _tulis_cache(cache)
    return dict(baru, dari_cache=False)


def main():
    ap = argparse.ArgumentParser(description="Altcoin Season Index (hitung sendiri + silang)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--paksa", action="store_true", help="abaikan cache")
    args = ap.parse_args()
    h = musim(paksa=args.paksa)
    print(json.dumps(h, indent=None if args.json else 2, ensure_ascii=False))
    return 0 if (h.get("indeks_30h_dihitung_sendiri")
                 or h.get("indeks_terbitan_blockchaincenter")) else 1


if __name__ == "__main__":
    sys.exit(main())

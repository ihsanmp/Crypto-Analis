"""Screening narasi cara mentor #2 — narasi KATEGORI dan narasi CHAIN, dikerjakan KODE.

Asal: transkrip webinar mentor yang dikirim user 27 Sep 2026. Metodenya, apa adanya:

NARASI KATEGORI
  1. CoinGecko → Categories → yang sedang menguat. Bedakan narasi BESAR (mis. AI) dari
     narasi KECIL.
  2. Koin yang naik (contohnya NEAR) → lihat kategorinya → pilih kategori utamanya (AI).
  3. Di kategori itu: siapa pemimpin (big cap) yang sudah naik? Likuiditas diduga turun
     ke koin berikutnya yang belum naik ("konsep elevator": NEAR/TAO naik → cari
     VIRTUAL, GRASS, dst).
NARASI CHAIN
  4. Big cap (top market cap) mana yang unggul 7 hari? Mentor: ETH +5% & BNB +4% "biasa
     aja", XRP +11% "lumayan", SOL +14% & LINK +19% "bagus".
  5. Kalau itu layer 1, JANGAN lihat kategori "Layer 1" — lihat EKOSISTEM chain-nya.
  6. Buang stablecoin & aset bridge, dan hanya ambil koin yang BENAR-BENAR dibangun di
     chain itu. Mentor: ETH, CAKE (BNB), STRK (Ethereum), dan RENDER ("awalnya dibentuk
     jaringan Ethereum") dicoret; JUP, RAY, PUMP, PENGU jadi kandidat.
  Penutup mentor sendiri: "tetap harus di-charting lagi sendiri. Jangan masuk asal."

LANGKAH 6 TIDAK LAGI BUTUH HAFALAN. Mentor mengaku tahu asal tiap token karena "udah di
market bertahun-tahun". Kode memakai PLATFORM UTAMA dari CoinGecko (`asset_platform_id`),
yang ternyata sama dengan platform PERTAMA di `/coins/list?include_platform=true` — satu
panggilan gratis untuk 21 rb koin. Diperiksa 27 Sep 2026 pada 9 token, 9 cocok, dan hasilnya
persis keputusan mentor: RENDER → ethereum, CAKE → binance-smart-chain, STRK → ethereum,
USDT → ethereum (semua dicoret); JUP, RAY, PENGU, BONK → solana (lolos). Jumlah platform
TIDAK dipakai: PENGU dan BONK asli Solana tapi di-bridge ke 6–7 chain.

"KONSEP ELEVATOR" ADALAH HIPOTESIS. Mentor menyatakannya dari pengalaman; repo ini belum
mengujinya (lihat uji_rotasi.py). Kandidat yang dikeluarkan di sini adalah DAFTAR PANTAU —
koin besar di narasi yang sama yang belum ikut bergerak — bukan ramalan bahwa mereka akan
naik. Mentor sendiri: "taunya gimana kalau grass pasti naik? Gak ada yang tau."

AMBANG DITETAPKAN SEKALI, di bawah. +10% 7 hari diambil dari penilaian mentor sendiri.

Pemakaian:
    python cloud/rotasi.py --ringkas
    python cloud/rotasi.py --json
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kategori  # noqa: E402

# --- Ambang a priori ----------------------------------------------------------------------
KATEGORI_MIN_MCAP = 100e6          # sama dengan kategori.py --daftar
BESAR_MIN, SEDANG_MIN = 5e9, 1e9   # narasi besar ≥ $5 M, sedang $1–5 M, kecil < $1 M
TOP_KATEGORI = 5                   # kategori menguat yang dibedah pemimpin & kandidatnya
PEMIMPIN = 3                       # tiga market cap teratas = pemimpin kategori
AMBANG_GERAK = 10.0                # % 7 hari: "sudah bergerak" / "unggul" (penilaian mentor)
KANDIDAT_MAKS = 8
MELEMAH = -10.0                    # % 7 hari: di bawah ini koin MELEMAH, bukan "belum bergerak"
# Jalur A hanya untuk narasi TEMA. Ekosistem chain milik jalur B (mentor memisahkan dua
# tipe itu), dan kategori portofolio VC bukan narasi — mentor melewatinya saat membedah
# NEAR ("Camera Capital Portfolio dan lain sebagainya").
_BUKAN_TEMA = re.compile(r"ecosystem|portfolio|holdings|made in|alleged|index|coinbase 50|"
                         r"gmci|launchpool|binance alpha|binance hodler", re.I)
VOL_MCAP_MIN = 0.005               # likuiditas minimum kandidat (sama dengan narasi.md)
BIGCAP_N = 20                      # mentor memasukkan LINK & ZEC — keduanya di luar top 10
UMUR_PLATFORM = 24 * 3600

# Koin chain → (kategori ekosistem CoinGecko, kunci platform di /coins/list). Hanya
# dipakai kalau chain-nya UNGGUL; id kategori diperiksa saat jalan, bukan dipercaya.
CHAIN = {
    "solana": ("solana-ecosystem", {"solana"}),
    "ethereum": ("ethereum-ecosystem", {"ethereum"}),
    "binancecoin": ("binance-smart-chain", {"binance-smart-chain"}),
    "sui": ("sui-ecosystem", {"sui"}),
    "avalanche-2": ("avalanche-ecosystem", {"avalanche"}),
    "tron": ("tron-ecosystem", {"tron"}),
    "hyperliquid": ("hyperliquid-ecosystem", {"hyperliquid", "hyperevm"}),
    "near": ("near-protocol-ecosystem", {"near-protocol"}),
    "cardano": ("cardano-ecosystem", {"cardano"}),
    "the-open-network": ("ton-ecosystem", {"the-open-network"}),
    "aptos": ("aptos-ecosystem", {"aptos"}),
}
HIPOTESIS = ("Rotasi pemimpin → koin berikutnya ('konsep elevator') adalah HIPOTESIS mentor; "
             "kandidat di bawah adalah DAFTAR PANTAU (koin besar di narasi yang sama yang "
             "belum ikut bergerak), bukan ramalan naik. Mentor sendiri: tetap charting "
             "sendiri, jangan masuk asal.")


def _pasar(params):
    d, _cache, err = kategori.ambil("/coins/markets", dict(
        {"vs_currency": "usd", "order": "market_cap_desc", "page": 1,
         "price_change_percentage": "7d,30d"}, **params))
    return (d if isinstance(d, list) else None), err


def platform_utama(jalur_cache=None):
    """{id: platform utama}. Cache 24 jam di folder SEMENTARA — bukan kategori_cache.json:
    daftar ini 4,5 MB dan kategori_cache.json ikut di-commit."""
    jalur_cache = jalur_cache or os.path.join(tempfile.gettempdir(), "rotasi_platform.json")
    try:
        with open(jalur_cache, encoding="utf-8") as f:
            simpan = json.load(f)
        if time.time() - simpan.get("waktu", 0) < UMUR_PLATFORM:
            return simpan["platform"]
    except Exception:
        pass
    url = f"{kategori.API}/coins/list?include_platform=true"
    try:
        req = urllib.request.Request(url, headers={**kategori.UA,
                                                   **kategori.cgkunci.header_untuk(url)})
        with urllib.request.urlopen(req, timeout=60) as r:
            daftar = json.loads(r.read().decode(errors="replace"))
    except Exception:
        return None
    # Platform PERTAMA yang beralamat = platform utama (asset_platform_id).
    peta = {}
    for c in daftar:
        utama = next((k for k, v in (c.get("platforms") or {}).items() if v), "")
        peta[c["id"]] = utama
    try:
        with open(jalur_cache, "w", encoding="utf-8") as f:
            json.dump({"waktu": time.time(), "platform": peta}, f)
    except Exception:
        pass
    return peta


def tingkat(mcap):
    if mcap >= BESAR_MIN:
        return "BESAR"
    return "SEDANG" if mcap >= SEDANG_MIN else "KECIL"


def _mirip_stabil(k):
    """Harga ~$1 dan nyaris diam seminggu. Daftar pengecualian musim.py hanya 100 stablecoin
    teratas, sehingga PSTUSDC, USDM, DJED, USDC.E, FRAX lolos sebagai "koin asli" di run
    36321348811."""
    h, u = k.get("harga"), k.get("ubah_7h")
    return h is not None and 0.9 <= h <= 1.1 and u is not None and abs(u) <= 3.0


def _bridge_aset_lain(k, simbol_besar):
    """Representasi bridge dari big cap lain yang DICETAK di chain ini: platform utamanya
    memang chain ini, tapi isinya BTC/ETH. Run 36321348811: BTC, ETH, NBTC tampil sebagai
    koin asli NEAR. Aturan platform tidak bisa membedakan 'dibangun di chain ini' dari
    'dijembatani ke chain ini' — simbolnya yang bisa."""
    s = k["simbol"].split(".")[0]
    return s in simbol_besar or (len(s) > 3 and s[0] in "WN" and s[1:] in simbol_besar)


def _koin(c):
    return {"id": c.get("id"), "simbol": (c.get("symbol") or "").upper(),
            "harga": c.get("current_price"),
            "mcap": c.get("market_cap") or 0, "volume": c.get("total_volume") or 0,
            "ubah_7h": c.get("price_change_percentage_7d_in_currency"),
            "ubah_30h": c.get("price_change_percentage_30d_in_currency")}


def pemimpin_dan_kandidat(anggota, kecuali=()):
    """Dari anggota (urut market cap): pemimpin, apakah sudah bergerak, dan kandidat —
    koin yang BELUM ikut bergerak dan cukup likuid."""
    koin = [k for k in anggota if k["id"] not in kecuali and k["ubah_7h"] is not None]
    pem = koin[:PEMIMPIN]
    terbaik = max((k["ubah_7h"] for k in pem), default=None)
    bergerak = terbaik is not None and terbaik >= AMBANG_GERAK
    kandidat, melemah = [], []
    if bergerak:
        for k in koin[PEMIMPIN:]:
            likuid = k["mcap"] and k["volume"] / k["mcap"] >= VOL_MCAP_MIN
            # "Belum bergerak" memakai ambang YANG SAMA dengan "sudah bergerak". Versi
            # pertama hanya membandingkan dengan setengah kenaikan pemimpin, sehingga
            # CYBER +16,4% ikut disebut belum bergerak karena pemimpinnya +37%.
            if MELEMAH <= k["ubah_7h"] < min(AMBANG_GERAK, terbaik / 2) and likuid:
                kandidat.append(k)
            elif k["ubah_7h"] < MELEMAH and likuid:
                melemah.append(k)
            if len(kandidat) >= KANDIDAT_MAKS:
                break
    return {"pemimpin": pem, "pemimpin_terbaik_7h": terbaik, "pemimpin_bergerak": bergerak,
            "kandidat": kandidat, "melemah": melemah[:4]}


def narasi_kategori(kecuali=()):
    kat, _c, err = kategori.ambil("/coins/categories")
    if not isinstance(kat, list):
        return {"galat": f"daftar kategori gagal: {err}"}
    layak = [c for c in kat if (c.get("market_cap") or 0) >= KATEGORI_MIN_MCAP
             and c.get("market_cap_change_24h") is not None
             and not _BUKAN_TEMA.search(f"{c.get('id', '')} {c.get('name', '')}")]
    layak.sort(key=lambda c: -c["market_cap_change_24h"])
    hasil = []
    for c in layak[:TOP_KATEGORI]:
        anggota, err = _pasar({"category": c["id"], "per_page": 30})
        rinci = (pemimpin_dan_kandidat([_koin(x) for x in anggota], kecuali)
                 if anggota else {"galat": err})
        hasil.append({"id": c["id"], "nama": c.get("name"), "mcap": c["market_cap"],
                      "tingkat": tingkat(c["market_cap"]),
                      "ubah_24j": round(c["market_cap_change_24h"], 1), **rinci})
    return {"kategori": hasil}


def satu_kategori(kat_id, kecuali=()):
    """JALUR A (user menyebut narasinya): pemimpin & kandidat untuk SATU kategori."""
    anggota, err = _pasar({"category": kat_id, "per_page": 30})
    if not anggota:
        return {"kategori": [{"id": kat_id, "nama": kat_id, "mcap": 0, "tingkat": "?",
                              "ubah_24j": 0.0, "galat": err or "kategori kosong/tidak dikenal"}]}
    mcap = sum((x.get("market_cap") or 0) for x in anggota)
    return {"kategori": [{"id": kat_id, "nama": kat_id, "mcap": mcap, "tingkat": tingkat(mcap),
                          "ubah_24j": 0.0,
                          **pemimpin_dan_kandidat([_koin(x) for x in anggota], kecuali)}]}


def narasi_chain(kecuali=(), platform=None):
    atas, err = _pasar({"per_page": BIGCAP_N + 15})
    if not atas:
        return {"galat": f"daftar big cap gagal: {err}"}
    big = [_koin(c) for c in atas if c.get("id") not in kecuali
           and not _mirip_stabil(_koin(c))][:BIGCAP_N]
    simbol_besar = {k["simbol"] for k in big}
    unggul = [k for k in big if (k["ubah_7h"] or 0) >= AMBANG_GERAK]
    chain = []
    for k in unggul:
        if k["id"] not in CHAIN:
            continue
        kat_id, kunci = CHAIN[k["id"]]
        if platform is None:
            chain.append({"koin": k, "galat": "peta platform gagal diambil — koin asli "
                                               "tidak bisa dipisahkan dari aset bridge"})
            continue
        anggota, err = _pasar({"category": kat_id, "per_page": 100})
        if not anggota:
            chain.append({"koin": k, "galat": f"ekosistem {kat_id} kosong/gagal: {err}"})
            continue
        asli = [kk for kk in (_koin(x) for x in anggota
                              if x.get("id") != k["id"] and x.get("id") not in kecuali
                              and platform.get(x.get("id"), "") in kunci)
                if not _mirip_stabil(kk) and not _bridge_aset_lain(kk, simbol_besar - {k["simbol"]})]
        dicoret = sum(1 for x in anggota if x.get("id") != k["id"]) - len(asli)
        chain.append({"koin": k, "ekosistem": kat_id, "dicoret_bukan_asli": dicoret,
                      "asli": asli[:12]})
    return {"big_cap": big, "unggul": unggul, "chain": chain,
            "unggul_bukan_chain": [k for k in unggul if k["id"] not in CHAIN]}


def _p(x):
    return "n/a" if x is None else f"{x:+.1f}%".replace(".", ",")


def _m(x):
    return f"${x / 1e9:.1f} M".replace(".", ",") if x >= 1e9 else f"${x / 1e6:.0f} jt"


def ringkas(kat, ch):
    b = ["SCREENING NARASI CARA MENTOR #2 (dikerjakan kode, rotasi.py)", "",
         "A. NARASI KATEGORI — kategori CoinGecko yang paling menguat 24 jam (mcap ≥ $100 jt)"]
    for c in kat.get("kategori", []):
        b.append(f"  • {c['nama']} [{c['tingkat']}, {_m(c['mcap'])}] 24j {_p(c['ubah_24j'])}")
        if c.get("galat"):
            b.append(f"      isi gagal: {c['galat']}")
            continue
        b.append("      pemimpin: " + ", ".join(f"{k['simbol']} {_p(k['ubah_7h'])}"
                                                for k in c["pemimpin"]))
        if not c["pemimpin_bergerak"]:
            b.append(f"      pemimpin BELUM bergerak (terbaik 7h {_p(c['pemimpin_terbaik_7h'])} "
                     f"< +10%) — rotasi belum bisa dibaca")
        elif c["kandidat"]:
            b.append("      belum ikut bergerak: " + ", ".join(
                f"{k['simbol']} {_p(k['ubah_7h'])}" for k in c["kandidat"]))
        else:
            b.append("      pemimpin bergerak, tapi anggota lain yang likuid sudah ikut naik")
        if c.get("melemah"):
            b.append("      MELEMAH saat narasinya naik (bukan kandidat): " + ", ".join(
                f"{k['simbol']} {_p(k['ubah_7h'])}" for k in c["melemah"]))
    if kat.get("galat"):
        b.append(f"  gagal: {kat['galat']}")
    b += ["", f"B. NARASI CHAIN — {BIGCAP_N} big cap (tanpa stablecoin/wrapped), 7 hari"]
    if ch.get("galat"):
        b.append(f"  gagal: {ch['galat']}")
    else:
        b.append("  " + " · ".join(f"{k['simbol']} {_p(k['ubah_7h'])}" for k in ch["big_cap"]))
        b.append("  unggul (≥ +10% 7h): " + (", ".join(k["simbol"] for k in ch["unggul"])
                                              or "tidak ada"))
        for c in ch["chain"]:
            if c.get("galat"):
                b.append(f"  • {c['koin']['simbol']}: {c['galat']}")
                continue
            b.append(f"  • {c['koin']['simbol']} unggul → ekosistem {c['ekosistem']}: "
                     f"{c['dicoret_bukan_asli']} koin dicoret (stablecoin, bridge, atau "
                     f"dibangun di chain lain); yang asli:")
            b.append("      " + ", ".join(f"{k['simbol']} {_p(k['ubah_7h'])}"
                                          for k in c["asli"]) if c["asli"] else "      (tidak ada)")
        if ch["unggul_bukan_chain"]:
            # Sebagian di antaranya memang layer 1 (XRP, XLM, DOGE, BCH, ZEC) — yang tidak
            # ada adalah PETA EKOSISTEM token-nya di sini, bukan status chain-nya.
            b.append("  unggul, tanpa peta ekosistem token di sini (pakai jalur kategori "
                     "koinnya): " + ", ".join(k["simbol"] for k in ch["unggul_bukan_chain"]))
    b += ["", HIPOTESIS]
    return "\n".join(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ringkas", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--kategori", default=None,
                    help="id kategori CoinGecko (JALUR A: user menyebut narasinya)")
    a = ap.parse_args()
    try:
        import musim
        kecuali = musim.dikecualikan() or set()
    except Exception:
        kecuali = set()
    if a.kategori:
        kat = satu_kategori(a.kategori, kecuali)
        ch = {"galat": "tidak dijalankan — mode satu kategori"}
    else:
        kat = narasi_kategori(kecuali)
        ch = narasi_chain(kecuali, platform_utama())
    if a.json:
        print(json.dumps({"kategori": kat, "chain": ch}, indent=2, ensure_ascii=False))
        return
    print(ringkas(kat, ch))


if __name__ == "__main__":
    main()

"""Peta sektor/narasi crypto — pengganti `cryptoCategories` CoinMarketCap yang 403.

MASALAH YANG DIPECAHKAN: endpoint kategori CoinMarketCap tidak tersedia di paket gratis
(403/dibatasi paket), sehingga screening narasi terpaksa disusun MANUAL dari listing
top-150 lalu diurutkan sendiri. Cara itu tidak salah, tapi cakupannya sempit — koin bagus
di sektor kecil yang tidak masuk top-150 tidak akan pernah terlihat, dan pengelompokan
sektornya jadi tebakan.

CoinGecko menyediakan padanannya GRATIS TANPA KUNCI: 749 kategori lengkap dengan market cap
dan perubahannya, plus daftar koin di dalam tiap kategori beserta perubahan 7 hari dan 30
hari. Itu persis yang dibutuhkan screening narasi.

UKURAN: balasan mentah kategori 358 rb karakter — sebagian besar berupa URL gambar dan
deskripsi panjang. Semua itu dibuang di sini; yang tersisa untuk top-12 hanya ~1,6 rb.

BATAS YANG WAJIB DISEBUT:
  - Keanggotaan kategori ditentukan CoinGecko, bukan standar baku. Satu koin bisa masuk
    beberapa kategori, dan ada kategori yang tumpang tindih (mis. "AI" vs "AI Agents").
  - `ubah_24j_persen` adalah perubahan MARKET CAP kategori, bukan rata-rata harga koinnya.
    Kategori yang didominasi satu koin besar akan mengikuti koin itu saja.
  - Tanpa API key, CoinGecko membatasi laju permintaan. Cache 30 menit wajib.

Pemakaian:
    python cloud/kategori.py --daftar
    python cloud/kategori.py --isi artificial-intelligence
    python cloud/kategori.py --cari "privacy"
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "data", "kategori_cache.json")
CACHE_UMUR = 30 * 60

API = "https://api.coingecko.com/api/v3"
UA = {"User-Agent": "Crypto-Analis Research bot"}
TIMEOUT = 40

# Kategori bermarket cap mungil bergerak liar karena satu transaksi. Disaring supaya
# peringkat teratas tidak selalu diisi sektor yang isinya dua koin tak likuid.
MCAP_MINIMUM = 100_000_000
VOLUME_MINIMUM = 1_000_000


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
        print(f"[kategori] gagal menyimpan cache: {e}")


def ambil(jalur, params=None):
    """GET dengan cache 30 menit. Return (data, dari_cache, error)."""
    url = f"{API}{jalur}" + (("?" + urllib.parse.urlencode(params)) if params else "")
    cache = _muat_cache()
    simpan = cache.get(url) or {}
    if simpan.get("data") is not None and time.time() - simpan.get("waktu", 0) < CACHE_UMUR:
        return simpan["data"], True, None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                    timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode(errors="replace"))
    except Exception as e:
        kode = getattr(e, "code", None)
        pesan = f"{type(e).__name__}" + (f" {kode}" if kode else "")
        if kode == 429:
            pesan += " — batas laju CoinGecko tanpa kunci terlampaui, coba lagi nanti"
        if simpan.get("data") is not None:
            return simpan["data"], True, f"{pesan} (pakai cache lama)"
        return None, False, pesan
    cache[url] = {"data": data, "waktu": time.time()}
    _simpan_cache(cache)
    return data, False, None


def daftar(n=12, cari=None):
    """Sektor yang sedang bergerak. Yang mentah 358 rb karakter dipangkas jadi ~1,6 rb."""
    data, dari_cache, err = ambil("/coins/categories")
    if err and not data:
        return {"tidak_tersedia": err}

    bersih = []
    for k in data or []:
        mcap = k.get("market_cap") or 0
        if mcap < MCAP_MINIMUM:
            continue
        bersih.append({
            "id": k.get("id"), "nama": k.get("name"),
            "mcap_usd": round(mcap),
            "ubah_24j_persen": round(k.get("market_cap_change_24h") or 0, 2),
            "volume_24j_usd": round(k.get("volume_24h") or 0),
        })
    if cari:
        c = cari.lower()
        cocok = [b for b in bersih if c in (b["nama"] or "").lower()
                 or c in (b["id"] or "").lower()]
        return {"dicari": cari, "cocok": cocok[:10], "dari_cache": dari_cache,
                "total_kategori_terperiksa": len(bersih)}

    bersih.sort(key=lambda x: -(x["ubah_24j_persen"] or 0))
    hasil = {
        "dari_cache": dari_cache,
        "total_kategori": len(bersih),
        "teratas_24j": bersih[:n],
        "terbawah_24j": bersih[-5:],
    }
    if err:
        hasil["peringatan"] = err
    hasil["wajib_dibaca"] = (
        "`ubah_24j_persen` adalah perubahan MARKET CAP kategori, bukan rata-rata harga "
        "koinnya — kategori yang didominasi satu koin besar hanya mengikuti koin itu. "
        "Satu hari juga terlalu pendek untuk menyimpulkan narasi: pakai ini untuk MEMILIH "
        "kandidat sektor, lalu periksa isinya dengan --isi untuk melihat performa 7 dan 30 "
        "hari per koin. Keanggotaan kategori ditentukan CoinGecko dan bisa tumpang tindih.")
    return hasil


def isi(kategori, n=15):
    """Koin di dalam satu kategori, dengan perubahan 7 & 30 hari."""
    data, dari_cache, err = ambil("/coins/markets", {
        "vs_currency": "usd", "category": kategori, "order": "market_cap_desc",
        "per_page": n, "page": 1, "price_change_percentage": "7d,30d"})
    if err and not data:
        return {"tidak_tersedia": err}
    if not data:
        return {"tidak_tersedia": f"kategori '{kategori}' tidak dikenal atau kosong. "
                                  "Cari id yang benar dengan --cari."}

    koin, tak_likuid = [], 0
    for c in data:
        vol = c.get("total_volume") or 0
        if vol < VOLUME_MINIMUM:
            tak_likuid += 1
            continue
        koin.append({
            "simbol": (c.get("symbol") or "").upper(),
            "harga_usd": c.get("current_price"),
            "mcap_usd": c.get("market_cap"),
            "volume_24j_usd": round(vol),
            "ubah_24j": _bulat(c.get("price_change_percentage_24h")),
            "ubah_7h": _bulat(c.get("price_change_percentage_7d_in_currency")),
            "ubah_30h": _bulat(c.get("price_change_percentage_30d_in_currency")),
            "dari_ath_persen": _bulat(c.get("ath_change_percentage")),
        })
    hasil = {"kategori": kategori, "dari_cache": dari_cache, "koin": koin}
    if tak_likuid:
        hasil["disaring_tak_likuid"] = (
            f"{tak_likuid} koin dibuang karena volume 24 jam di bawah "
            f"${VOLUME_MINIMUM:,} — tidak bisa dimasuki tanpa slippage besar.")
    hasil["wajib_dibaca"] = (
        "Bandingkan ubah_7h dan ubah_30h, JANGAN hanya 24 jam. Koin yang naik 7 hari tapi "
        "turun 30 hari berarti pantulan di dalam tren turun, bukan narasi baru. "
        "`dari_ath_persen` menunjukkan seberapa jauh dari puncaknya — koin -95% dari ATH "
        "butuh kenaikan 20x sekadar untuk kembali, dan itu harus disebut.")
    return hasil


def data_koin(id_atau_simbol):
    """Mcap, FDV, volume, dan pasokan satu koin — yang selama ini n/a di brief.

    Kenapa penting: tanpa mcap, SEMUA rasio valuasi ikut mati (MC/TVL, P/S, P/F, FDV/MC,
    volume/mcap). fundamentals.py sebenarnya sudah bisa menghitung semuanya dan menerima
    --mcap, tapi tidak pernah diberi angkanya; DefiLlama sering mengembalikan mcap kosong
    karena melekat pada token induk. CoinGecko menyediakannya gratis tanpa kunci.

    Rasio yang dihitung di sini bukan hiasan:
      FDV/MC        seberapa besar pasokan yang BELUM beredar — 4,5x berarti sebagian
                    besar token masih akan masuk pasar, dan itu tekanan jual terjadwal.
      volume/mcap   likuiditas relatif; di bawah ~1% berarti sulit keluar tanpa slippage.
      beredar/total porsi yang sudah beredar, pasangan langsung dari FDV/MC.
    """
    kunci = (id_atau_simbol or "").strip().lower()
    if not kunci:
        return {"tidak_tersedia": "simbol kosong"}
    data, dari_cache, err = ambil("/coins/markets", {
        "vs_currency": "usd", "ids": kunci, "price_change_percentage": "7d,30d"})
    if (not data) and not err:
        # Yang diberikan mungkin ticker, bukan id CoinGecko. Coba resolusi sekali.
        try:
            sys.path.insert(0, BASE_DIR)
            from indicators import resolve_cg_id
            cid = resolve_cg_id(id_atau_simbol)
        except Exception:
            cid = None
        if cid and cid.lower() != kunci:
            data, dari_cache, err = ambil("/coins/markets", {
                "vs_currency": "usd", "ids": cid, "price_change_percentage": "7d,30d"})
    if err and not data:
        return {"tidak_tersedia": err}
    if not data:
        return {"tidak_tersedia": f"'{id_atau_simbol}' tidak ditemukan di CoinGecko"}

    c = data[0]
    mc = c.get("market_cap")
    fdv = c.get("fully_diluted_valuation")
    vol = c.get("total_volume")
    beredar, total = c.get("circulating_supply"), c.get("total_supply")
    hasil = {
        "simbol": (c.get("symbol") or "").upper(),
        "id_coingecko": c.get("id"),
        "dari_cache": dari_cache,
        "harga_usd": c.get("current_price"),
        "mcap_usd": mc,
        "peringkat_mcap": c.get("market_cap_rank"),
        "fdv_usd": fdv,
        "volume_24j_usd": vol,
        "pasokan_beredar": beredar,
        "pasokan_total": total,
        "pasokan_maks": c.get("max_supply"),
        "dari_ath_persen": _bulat(c.get("ath_change_percentage")),
        "ubah_24j": _bulat(c.get("price_change_percentage_24h")),
        "ubah_7h": _bulat(c.get("price_change_percentage_7d_in_currency")),
        "ubah_30h": _bulat(c.get("price_change_percentage_30d_in_currency")),
    }
    if mc and fdv:
        hasil["fdv_per_mcap"] = round(fdv / mc, 2)
    if mc and vol:
        hasil["volume_per_mcap"] = round(vol / mc, 4)
    if beredar and total:
        hasil["beredar_per_total_persen"] = round(beredar / total * 100, 1)
    hasil["wajib_dibaca"] = (
        "FDV/MC jauh di atas 1 berarti sebagian besar pasokan BELUM beredar — itu tekanan "
        "jual terjadwal, bukan sekadar angka besar. Sebutkan bersama porsi beredarnya. "
        "volume_per_mcap di bawah 0,01 berarti likuiditas tipis: posisi besar sulit keluar "
        "tanpa menggerakkan harga sendiri. Angka mcap di sini juga yang dipakai menghitung "
        "MC/TVL, P/S, dan P/F di fundamentals.py — kalau bagian ini gagal, rasio-rasio itu "
        "ikut kosong dan itu HARUS disebut sebagai data hilang, bukan sebagai valuasi murah.")
    return hasil


def _bulat(v):
    return round(v, 2) if isinstance(v, (int, float)) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daftar", action="store_true", help="sektor yang sedang bergerak")
    ap.add_argument("--isi", help="id kategori, mis. artificial-intelligence")
    ap.add_argument("--cari", help="cari id kategori dari kata kunci")
    ap.add_argument("--koin", help="mcap/FDV/volume/pasokan satu koin (id atau ticker)")
    ap.add_argument("--jumlah", type=int, default=12)
    ap.add_argument("--ringkas", action="store_true", help="buang panduan statis")
    args = ap.parse_args()

    keluar = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": ("CoinGecko /coins/categories & /coins/markets — gratis, TANPA API key. "
                   "Pengganti cryptoCategories CoinMarketCap yang tidak tersedia di paket "
                   "gratis."),
    }
    if args.cari:
        keluar["pencarian"] = daftar(cari=args.cari)
    if args.isi:
        keluar["isi_kategori"] = isi(args.isi, args.jumlah)
    if args.koin:
        keluar["data_pasar_koin"] = data_koin(args.koin)
    if args.daftar or not (args.cari or args.isi or args.koin):
        keluar["peta_sektor"] = daftar(args.jumlah)

    if args.ringkas:
        from backtest import buang_panduan
        keluar = buang_panduan(keluar)
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

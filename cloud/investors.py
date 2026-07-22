"""Penarik data kepemilikan on-chain (konsentrasi holder / whale).

Menjawab bagian "siapa yang memegang koin ini dan seberapa besar" dari sisi ANGKA.
Sumber: Ethplorer (gratis, tanpa daftar, memakai apiKey=freekey).

BATASAN YANG HARUS DISAMPAIKAN APA ADANYA:
  1. Hanya untuk token berbasis ETHEREUM. Token di chain lain (Solana, BSC, Tron,
     atau koin L1 sendiri seperti BTC) tidak bisa diambil lewat sumber ini.
  2. Ethplorer gratis TIDAK memberi label alamat. Yang keluar adalah alamat mentah,
     jadi belum bisa dibedakan mana bursa, mana kontrak staking/treasury, mana whale
     sungguhan. Pelabelan HARUS dilakukan lewat riset (WebSearch) — jangan menebak.
  3. Alamat bursa & kontrak protokol biasanya mendominasi daftar teratas. Porsi besar
     di kontrak staking BUKAN berarti terkonsentrasi di satu orang. Salah tafsir di
     sini menyesatkan, jadi jangan simpulkan konsentrasi sebelum alamatnya dikenali.

Untuk "investor institusi" (VC, dana kelola, perusahaan treasury, ETF) sumbernya
BUKAN script ini melainkan riset berita — lihat arahan di prompt.

Pemakaian:
    python cloud/investors.py AAVE
    python cloud/investors.py AAVE --address 0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9
"""

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
TIMEOUT = 25
ETHPLORER = "https://api.ethplorer.io"


def try_json(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"__err": f"{type(e).__name__}: {str(e)[:90]}"}


def resolve_address(ticker):
    """Cari alamat kontrak Ethereum dari daftar protokol DefiLlama."""
    data = try_json("https://api.llama.fi/protocols")
    if not isinstance(data, list):
        return None, "Gagal mengambil daftar protokol DefiLlama."

    hits = [p for p in data
            if (p.get("symbol") or "").upper() == ticker.upper() and p.get("address")]
    if not hits:
        return None, (f"Alamat kontrak untuk {ticker} tidak ada di DefiLlama. "
                      "Kemungkinan koin ini bukan token Ethereum (mis. L1 sendiri).")

    hits.sort(key=lambda p: -(p.get("tvl") or 0))
    raw = str(hits[0]["address"])
    # DefiLlama kadang menulis "ethereum:0x..." atau "solana:..."
    if ":" in raw:
        chain, _, alamat = raw.partition(":")
        if chain.lower() not in ("ethereum", "eth"):
            return None, (f"Token {ticker} berada di chain '{chain}', bukan Ethereum. "
                          "Data holder on-chain tidak tersedia lewat sumber gratis ini.")
        raw = alamat
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", raw):
        return None, f"Alamat '{raw[:24]}' bukan format alamat Ethereum."
    return raw, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--address", default=None, help="alamat kontrak Ethereum (kalau otomatis meleset)")
    ap.add_argument("--limit", type=int, default=10, help="jumlah holder teratas (maks 100)")
    args = ap.parse_args()
    ticker = args.ticker.upper().replace("$", "")

    hasil = {
        "symbol": ticker,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": "Ethplorer (gratis) + DefiLlama untuk resolusi alamat",
        "peringatan": [
            "Alamat di bawah TANPA LABEL. Sebelum menyimpulkan konsentrasi, kenali dulu "
            "tiap alamat lewat WebSearch — mayoritas pemegang teratas biasanya dompet BURSA "
            "atau KONTRAK protokol (staking/treasury/vesting), bukan investor perorangan.",
            "Porsi besar di kontrak staking BUKAN tanda konsentrasi berbahaya.",
        ],
    }

    address = args.address
    if not address:
        address, err = resolve_address(ticker)
        if err:
            hasil["error"] = err
            hasil["saran"] = ("Untuk koin non-Ethereum, cari data kepemilikan lewat WebSearch "
                              "(mis. explorer chain terkait) dan sebutkan keterbatasannya.")
            print(json.dumps(hasil, indent=2, ensure_ascii=False))
            return

    hasil["kontrak"] = address

    info = try_json(f"{ETHPLORER}/getTokenInfo/{address}?apiKey=freekey")
    if "__err" not in info:
        hasil["token"] = {
            "nama": info.get("name"),
            "symbol": info.get("symbol"),
            "jumlah_holder": info.get("holdersCount"),
        }
    else:
        hasil["token"] = {"catatan": f"info token gagal diambil ({info['__err']})"}

    limit = max(1, min(args.limit, 100))
    top = try_json(f"{ETHPLORER}/getTopTokenHolders/{address}?apiKey=freekey&limit={limit}")
    if "__err" in top:
        hasil["error"] = f"Gagal mengambil daftar holder: {top['__err']}"
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return

    holders = top.get("holders") or []
    daftar = []
    for h in holders:
        share = h.get("share")
        daftar.append({
            "alamat": h.get("address"),
            "persen_supply": round(float(share), 2) if share is not None else None,
            "label": "BELUM DIKENALI — cari tahu lewat WebSearch",
        })
    hasil["holder_teratas"] = daftar

    persen = [d["persen_supply"] for d in daftar if d["persen_supply"] is not None]
    if persen:
        hasil["konsentrasi"] = {
            "top10_persen": round(sum(persen[:10]), 2),
            "terbesar_persen": persen[0],
            "acuan_penilaian": ("top10 <20% sangat tersebar · 20-35% sehat · 35-50% sedang · "
                                "50-70% terkonsentrasi · >70% sangat terkonsentrasi. "
                                "Nilai ini HANYA berarti setelah alamat bursa/kontrak dikeluarkan."),
        }

    hasil["investor_institusi"] = None
    hasil["catatan_institusi"] = (
        "Identitas investor besar (VC, dana kelola, perusahaan treasury, ETF) TIDAK ada di "
        "sumber on-chain gratis. Cari lewat WebSearch: putaran pendanaan dan investornya, "
        "kepemilikan treasury perusahaan publik, aliran dana ETF, serta laporan whale. "
        "Sebutkan nominal dan tanggalnya bila ada; kalau tidak ketemu, katakan tidak tersedia.")

    print(json.dumps(hasil, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

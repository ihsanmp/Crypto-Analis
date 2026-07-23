"""Pelacak WALLET ADDRESS — isi dompet + nilai USD, multi-chain (ala Arkham, versi gratis).

Beda dengan investors.py (yang melihat holder sebuah TOKEN), script ini melihat SATU
ALAMAT DOMPET: apa saja yang dipegang, berapa nilainya, dan (kalau dikenal) siapa dia.

SUMBER:
  - EVM (Ethereum, BSC, Base, Arbitrum, Polygon, Optimism, Avalanche) -> Moralis
    `/wallets/{addr}/tokens` (saldo + harga + % portofolio). Butuh MORALIS_API_KEY gratis.
  - Solana -> Moralis Solana Gateway `/account/mainnet/{addr}/portfolio`.
  - Label alamat Ethereum diperkaya dari eth_labels.json lokal (bursa/kontrak/dll).

BATASAN:
  - Alamat EVM sama bentuknya di semua chain — default Ethereum; pakai --chain untuk chain lain.
  - Token spam/scam ditandai possible_spam dan TIDAK dihitung ke nilai bersih.
  - USD di Solana bisa sebagian saja (tergantung ketersediaan harga di Moralis).

Pemakaian:
    python cloud/wallet.py 0xF977814e90dA44bFA03b6295A0616a897441aceC          # ETH (default)
    python cloud/wallet.py 0xF977...aceC --chain bsc
    python cloud/wallet.py 5xoBq7f7CDg...  --chain solana
"""

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
TIMEOUT = 25
MORALIS_EVM = "https://deep-index.moralis.io/api/v2.2"
MORALIS_SOL = "https://solana-gateway.moralis.io"
MORALIS_KEY = os.environ.get("MORALIS_API_KEY", "").strip()

EVM_SLUG = {
    "ethereum": "eth", "bsc": "bsc", "polygon": "polygon", "arbitrum": "arbitrum",
    "base": "base", "optimism": "optimism", "avalanche": "avalanche",
}
ALIAS = {
    "eth": "ethereum", "bnb": "bsc", "binance": "bsc", "matic": "polygon",
    "arb": "arbitrum", "op": "optimism", "avax": "avalanche", "sol": "solana",
}

_LABELS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "eth_labels.json")

_BURSA = ("binance", "coinbase", "kraken", "kucoin", "okx", "okex", "bybit", "gate",
          "huobi", "htx", "bitfinex", "bitget", "mexc", "crypto.com", "gemini",
          "upbit", "bithumb", "exchange", "hot wallet", "cold wallet")


def load_labels():
    try:
        with open(_LABELS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def try_json(url, headers=None):
    h = dict(UA)
    if headers:
        h.update(headers)
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()[:120]
        except Exception:
            body = ""
        return {"__err": f"HTTP {e.code} {body}".strip()}
    except Exception as e:
        return {"__err": f"{type(e).__name__}: {str(e)[:90]}"}


def is_evm(addr):
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", addr or ""))


def label_alamat(addr):
    teks = load_labels().get((addr or "").lower())
    if not teks:
        return None, None
    low = teks.lower()
    kat = "BURSA" if any(k in low for k in _BURSA) else "TERLABELI"
    return teks, kat


def evm_wallet(addr, chain):
    if not MORALIS_KEY:
        return {"error": "MORALIS_API_KEY belum di-set."}
    slug = EVM_SLUG[chain]
    data = try_json(f"{MORALIS_EVM}/wallets/{addr}/tokens?chain={slug}",
                    headers={"X-API-Key": MORALIS_KEY, "accept": "application/json"})
    if "__err" in data:
        return {"error": f"Moralis gagal: {data['__err']}"}
    total = 0.0
    holdings = []
    for t in (data.get("result") or []):
        if t.get("possible_spam"):
            continue
        usd = t.get("usd_value")
        usd = float(usd) if isinstance(usd, (int, float)) else 0.0
        total += usd
        holdings.append({
            "symbol": t.get("symbol"),
            "nama": t.get("name"),
            "jumlah": t.get("balance_formatted"),
            "usd": round(usd, 2),
            "persen_portofolio": t.get("portfolio_percentage"),
            "native": bool(t.get("native_token")),
            "terverifikasi": t.get("verified_contract"),
        })
    holdings.sort(key=lambda x: -(x["usd"] or 0))
    return {"nilai_bersih_usd": round(total, 2),
            "jumlah_aset": len(holdings),
            "holdings": holdings[:25]}


def solana_wallet(addr):
    if not MORALIS_KEY:
        return {"error": "MORALIS_API_KEY belum di-set."}
    data = try_json(f"{MORALIS_SOL}/account/mainnet/{addr}/portfolio",
                    headers={"X-API-Key": MORALIS_KEY, "accept": "application/json"})
    if "__err" in data:
        return {"error": f"Moralis Solana gagal: {data['__err']}"}
    holdings = []
    native = data.get("nativeBalance") or {}
    if native:
        holdings.append({"symbol": "SOL", "nama": "Solana (native)",
                         "jumlah": native.get("solana") or native.get("lamports"),
                         "native": True})
    for t in (data.get("tokens") or []):
        holdings.append({
            "symbol": t.get("symbol"),
            "nama": t.get("name"),
            "jumlah": t.get("amount") or t.get("amountRaw"),
            "mint": t.get("mint") or t.get("associatedTokenAddress"),
        })
    return {"jumlah_aset": len(holdings),
            "holdings": holdings[:25],
            "catatan": "Nilai USD di Solana bisa tidak lengkap; jumlah token tetap akurat."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("--chain", default=None,
                    help="ethereum|bsc|polygon|arbitrum|base|optimism|avalanche|solana (default: auto)")
    args = ap.parse_args()
    addr = args.address.strip()
    chain = args.chain.lower().strip() if args.chain else None
    chain = ALIAS.get(chain, chain)

    # Auto-deteksi: 0x... -> EVM (default ethereum); selain itu anggap Solana.
    if not chain:
        chain = "ethereum" if is_evm(addr) else "solana"

    hasil = {
        "alamat": addr,
        "chain": chain,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": "Moralis (gratis) + label lokal etherscan-labels (khusus Ethereum)",
        "peringatan": [
            "Alamat bursa memegang dana banyak nasabah — bukan kekayaan satu orang.",
            "Token possible_spam sudah dibuang dari nilai bersih; sisa aset tak berharga bisa muncul.",
            "Satu alamat EVM bisa aktif di banyak chain — cek chain lain dengan --chain bila perlu.",
        ],
    }

    # Label identitas alamat (khusus Ethereum, dari data lokal).
    if is_evm(addr):
        nm, kat = label_alamat(addr)
        hasil["identitas"] = {"label": nm, "kategori": kat} if nm else \
            {"label": None, "kategori": "TIDAK DIKENALI — cek lewat WebSearch"}

    if chain == "solana":
        hasil["portofolio"] = solana_wallet(addr)
    elif chain in EVM_SLUG:
        if not is_evm(addr):
            hasil["error"] = f"Alamat '{addr[:24]}' bukan format EVM (0x + 40 hex)."
            print(json.dumps(hasil, indent=2, ensure_ascii=False))
            return
        hasil["portofolio"] = evm_wallet(addr, chain)
    else:
        hasil["error"] = f"Chain '{chain}' tidak dikenal. Pilihan: {list(EVM_SLUG) + ['solana']}"
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return

    port = hasil.get("portofolio") or {}
    if isinstance(port, dict) and "MORALIS_API_KEY" in str(port.get("error", "")):
        hasil["saran"] = ("Daftar gratis di moralis.com, salin API key, simpan sebagai GitHub "
                          "Secret MORALIS_API_KEY.")

    print(json.dumps(hasil, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

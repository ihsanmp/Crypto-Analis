"""Penarik data kepemilikan on-chain (konsentrasi holder / whale) — MULTI-CHAIN.

Menjawab bagian "siapa yang memegang koin ini dan seberapa besar" dari sisi ANGKA.

SUMBER per chain:
  - Ethereum  -> Ethplorer (gratis, apiKey=freekey) + pelabelan lokal eth_labels.json.
                 Jalur ini TIDAK butuh Moralis, jadi ETH tetap jalan tanpa key baru.
  - Chain EVM lain (BSC, Base, Arbitrum, Polygon, Optimism, Avalanche) -> Moralis
                 `/erc20/{addr}/owners` (butuh MORALIS_API_KEY gratis).
  - Solana    -> Moralis Solana Gateway `/token/mainnet/{addr}/top-holders`
                 (butuh MORALIS_API_KEY gratis).

Alamat kontrak per chain diresolusi dari CoinGecko (`platforms`), keyless.

BATASAN YANG HARUS DISAMPAIKAN APA ADANYA:
  1. Pelabelan paling kaya hanya di Ethereum (eth_labels.json, 29 rb alamat). Di chain
     lain label bergantung pada data Moralis (`entity`/`is_contract`) — lebih terbatas,
     jadi alamat "TIDAK DIKENALI" WAJIB dicek lewat WebSearch sebelum disebut whale.
  2. Porsi besar di kontrak staking/treasury/bridge BUKAN tanda konsentrasi di satu
     orang. Jangan simpulkan konsentrasi sebelum alamatnya dikenali.
  3. Untuk "investor institusi" (VC, dana kelola, treasury perusahaan, ETF) sumbernya
     BUKAN script ini melainkan riset berita — lihat arahan di prompt.

Pemakaian:
    python cloud/investors.py AAVE                     # auto-deteksi chain
    python cloud/investors.py CAKE --chain bsc
    python cloud/investors.py JUP  --chain solana
    python cloud/investors.py AAVE --address 0x7Fc6...  --chain ethereum
"""

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
TIMEOUT = 25
ETHPLORER = "https://api.ethplorer.io"
MORALIS_EVM = "https://deep-index.moralis.io/api/v2.2"
MORALIS_SOL = "https://solana-gateway.moralis.io"
CG = "https://api.coingecko.com/api/v3"
MORALIS_KEY = os.environ.get("MORALIS_API_KEY", "").strip()

# Registry chain: nama internal -> kunci platform CoinGecko, slug chain Moralis, tipe.
CHAINS = {
    "ethereum":  {"cg": "ethereum",            "moralis": "eth",       "tipe": "evm"},
    "bsc":       {"cg": "binance-smart-chain", "moralis": "bsc",       "tipe": "evm"},
    "polygon":   {"cg": "polygon-pos",         "moralis": "polygon",   "tipe": "evm"},
    "arbitrum":  {"cg": "arbitrum-one",        "moralis": "arbitrum",  "tipe": "evm"},
    "base":      {"cg": "base",                "moralis": "base",      "tipe": "evm"},
    "optimism":  {"cg": "optimistic-ethereum", "moralis": "optimism",  "tipe": "evm"},
    "avalanche": {"cg": "avalanche",           "moralis": "avalanche", "tipe": "evm"},
    "solana":    {"cg": "solana",              "moralis": "mainnet",   "tipe": "solana"},
}
# Alias input supaya "eth", "bnb", "sol", dll tetap dikenali.
ALIAS = {
    "eth": "ethereum", "bnb": "bsc", "binance": "bsc", "bep20": "bsc",
    "matic": "polygon", "poly": "polygon", "arb": "arbitrum",
    "op": "optimism", "avax": "avalanche", "sol": "solana",
}

_LABELS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "eth_labels.json")

_BURSA = ("binance", "coinbase", "kraken", "kucoin", "okx", "okex", "bybit", "gate.io",
          "gate ", "huobi", "htx", "bitfinex", "bitget", "mexc", "crypto.com", "gemini",
          "upbit", "bithumb", "exchange", "hot wallet", "cold wallet")
_KONTRAK = ("contract", "staking", "stake", "vault", "pool", "router", "bridge", "treasury",
            "vesting", "timelock", "proxy", "deployer", "token", "protocol", "dao",
            "reserve", "foundation", "rewards", "reward", "distributor", "multisig",
            "gnosis safe", "safe:", "governance", "locker", "escrow", "team", "airdrop")


def load_labels():
    try:
        with open(_LABELS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def kategori_label(teks):
    low = (teks or "").lower()
    if any(k in low for k in _BURSA):
        return "BURSA"
    if any(k in low for k in _KONTRAK):
        return "KONTRAK/PROTOKOL"
    return "TERLABELI"


def klasifikasi_moralis(entity, label, is_contract):
    """Beri label + kategori untuk holder dari Moralis (chain non-Ethereum)."""
    teks = (entity or label or "").strip()
    if teks:
        return teks, kategori_label(teks)
    if is_contract:
        return "kontrak (tak bernama)", "KONTRAK/PROTOKOL"
    return "belum dikenali", "TIDAK DIKENALI — cek lewat WebSearch"


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


def cg_platforms(ticker):
    """Kembalikan (platforms_dict, nama_koin, error) dari CoinGecko — keyless."""
    s = try_json(f"{CG}/search?query={urllib.parse.quote(ticker)}")
    coins = s.get("coins") if isinstance(s, dict) else None
    if not coins:
        return None, None, f"Koin '{ticker}' tidak ditemukan di CoinGecko."
    exact = [c for c in coins if (c.get("symbol") or "").upper() == ticker.upper()]
    pick = (exact or coins)[0]
    cid = pick.get("id")
    d = try_json(f"{CG}/coins/{cid}?localization=false&tickers=false"
                 "&market_data=false&community_data=false&developer_data=false")
    if not isinstance(d, dict) or "__err" in d:
        return None, None, "Gagal mengambil detail koin dari CoinGecko."
    plats = {k: v for k, v in (d.get("platforms") or {}).items() if v}
    return plats, d.get("name"), None


def deteksi_chain(platforms):
    """Pilih chain default: utamakan Ethereum, lalu urutan di CHAINS yang punya alamat."""
    cg_to_chain = {info["cg"]: name for name, info in CHAINS.items()}
    for name in CHAINS:  # dict menjaga urutan sisip; ethereum pertama
        cg_key = CHAINS[name]["cg"]
        if platforms.get(cg_key):
            return name, platforms[cg_key]
    # Ada di chain yang tak kami dukung
    lain = ", ".join(sorted(platforms.keys()))
    return None, lain


def is_valid_evm(addr):
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", addr or ""))


# ---- Pengambil holder per sumber ---------------------------------------------

def ethplorer_holders(address, limit):
    labels = load_labels()
    info = try_json(f"{ETHPLORER}/getTokenInfo/{address}?apiKey=freekey")
    token = {}
    if "__err" not in info:
        token = {"nama": info.get("name"), "symbol": info.get("symbol"),
                 "jumlah_holder": info.get("holdersCount")}
    top = try_json(f"{ETHPLORER}/getTopTokenHolders/{address}?apiKey=freekey&limit={limit}")
    if "__err" in top:
        return None, token, f"Gagal mengambil daftar holder: {top['__err']}"
    daftar = []
    for h in (top.get("holders") or []):
        share = h.get("share")
        addr = h.get("address") or ""
        teks = labels.get(addr.lower())
        if teks:
            nm, kat = teks, kategori_label(teks)
        else:
            nm, kat = "belum dikenali", "TIDAK DIKENALI — cek lewat WebSearch"
        daftar.append({"alamat": addr,
                       "persen_supply": round(float(share), 2) if share is not None else None,
                       "label": nm, "kategori": kat})
    return daftar, token, None


def moralis_evm_holders(address, chain_slug, limit):
    if not MORALIS_KEY:
        return None, {}, "MORALIS_API_KEY belum di-set (perlu untuk chain selain Ethereum)."
    url = (f"{MORALIS_EVM}/erc20/{address}/owners"
           f"?chain={chain_slug}&order=DESC&limit={min(limit, 100)}")
    data = try_json(url, headers={"X-API-Key": MORALIS_KEY, "accept": "application/json"})
    if "__err" in data:
        return None, {}, f"Moralis gagal: {data['__err']}"
    daftar = []
    for h in (data.get("result") or []):
        pct = h.get("percentage_relative_to_total_supply")
        nm, kat = klasifikasi_moralis(h.get("entity"),
                                      h.get("owner_address_label") or h.get("label"),
                                      bool(h.get("is_contract")))
        daftar.append({"alamat": h.get("owner_address"),
                       "persen_supply": round(float(pct), 2) if pct is not None else None,
                       "label": nm, "kategori": kat})
    return daftar, {}, None


def moralis_solana_holders(address, limit):
    if not MORALIS_KEY:
        return None, {}, "MORALIS_API_KEY belum di-set (perlu untuk Solana)."
    url = f"{MORALIS_SOL}/token/mainnet/{address}/top-holders?limit={min(limit, 100)}"
    data = try_json(url, headers={"X-API-Key": MORALIS_KEY, "accept": "application/json"})
    if "__err" in data:
        return None, {}, f"Moralis Solana gagal: {data['__err']}"
    rows = data.get("result") if isinstance(data, dict) else data
    daftar = []
    for h in (rows or []):
        pct = (h.get("percentageRelativeToTotalSupply")
               or h.get("percentage_relative_to_total_supply"))
        addr = h.get("ownerAddress") or h.get("owner_address") or h.get("address")
        nm, kat = klasifikasi_moralis(None,
                                      h.get("label") or h.get("ownerAddressLabel"),
                                      bool(h.get("isContract") or h.get("is_contract")))
        daftar.append({"alamat": addr,
                       "persen_supply": round(float(pct), 2) if pct is not None else None,
                       "label": nm, "kategori": kat})
    return daftar, {}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--chain", default=None,
                    help="ethereum|bsc|polygon|arbitrum|base|optimism|avalanche|solana (default: auto)")
    ap.add_argument("--address", default=None, help="alamat kontrak (kalau resolusi otomatis meleset)")
    ap.add_argument("--limit", type=int, default=10, help="jumlah holder teratas (maks 100)")
    args = ap.parse_args()
    ticker = args.ticker.upper().replace("$", "")
    limit = max(1, min(args.limit, 100))

    chain = args.chain.lower().strip() if args.chain else None
    chain = ALIAS.get(chain, chain)

    hasil = {
        "symbol": ticker,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "peringatan": [
            "Alamat BURSA & KONTRAK/PROTOKOL bukan whale perorangan — jangan dihitung "
            "sebagai konsentrasi di satu tangan.",
            "Alamat 'TIDAK DIKENALI' yang porsinya besar WAJIB dicek lewat WebSearch "
            "sebelum disebut whale — data label tidak mencakup semua alamat.",
            "Porsi besar di kontrak staking/treasury/bridge BUKAN tanda konsentrasi berbahaya.",
        ],
    }

    address = args.address
    # Resolusi alamat + (kalau perlu) auto-deteksi chain lewat CoinGecko.
    if not address or not chain:
        plats, nama, err = cg_platforms(ticker)
        if err:
            hasil["error"] = err
            hasil["saran"] = ("Koin L1 sendiri (BTC, dsb.) atau tak terdaftar: cari kepemilikan "
                              "lewat WebSearch di explorer terkait, sebutkan keterbatasannya.")
            print(json.dumps(hasil, indent=2, ensure_ascii=False))
            return
        hasil["nama"] = nama
        if not chain:
            chain, alamat_auto = deteksi_chain(plats)
            if not chain:
                hasil["error"] = (f"{ticker} tidak ada di chain yang didukung. "
                                  f"Platform terdeteksi: {alamat_auto or 'tidak ada'}.")
                hasil["chain_didukung"] = list(CHAINS.keys())
                print(json.dumps(hasil, indent=2, ensure_ascii=False))
                return
            if not address:
                address = alamat_auto
        if not address:  # chain dipaksa user, ambil alamat untuk chain itu
            if chain not in CHAINS:
                hasil["error"] = f"Chain '{chain}' tidak dikenal. Pilihan: {list(CHAINS.keys())}"
                print(json.dumps(hasil, indent=2, ensure_ascii=False))
                return
            address = plats.get(CHAINS[chain]["cg"])
            if not address:
                hasil["error"] = (f"{ticker} tidak punya kontrak di chain '{chain}' menurut CoinGecko. "
                                  f"Platform yang ada: {', '.join(plats.keys()) or 'tidak ada'}.")
                print(json.dumps(hasil, indent=2, ensure_ascii=False))
                return

    if chain not in CHAINS:
        hasil["error"] = f"Chain '{chain}' tidak dikenal. Pilihan: {list(CHAINS.keys())}"
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return

    tipe = CHAINS[chain]["tipe"]
    if tipe == "evm" and not is_valid_evm(address):
        hasil["error"] = f"Alamat '{str(address)[:24]}' bukan format EVM (0x + 40 hex) untuk chain {chain}."
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return

    hasil["chain"] = chain
    hasil["kontrak"] = address

    # Rute ke sumber sesuai chain.
    if chain == "ethereum":
        daftar, token, err = ethplorer_holders(address, limit)
        hasil["sumber"] = "Ethplorer (gratis) + label lokal etherscan-labels + CoinGecko (resolusi)"
    elif tipe == "solana":
        daftar, token, err = moralis_solana_holders(address, limit)
        hasil["sumber"] = "Moralis Solana Gateway (gratis) + CoinGecko (resolusi)"
    else:
        daftar, token, err = moralis_evm_holders(address, CHAINS[chain]["moralis"], limit)
        hasil["sumber"] = f"Moralis ({chain}) (gratis) + CoinGecko (resolusi)"

    if token:
        hasil["token"] = token
    if err:
        hasil["error"] = err
        if "MORALIS_API_KEY" in err:
            hasil["saran"] = ("Daftar gratis di moralis.com, salin API key, simpan sebagai GitHub "
                              "Secret MORALIS_API_KEY. Chain Ethereum tetap jalan tanpa key ini.")
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return

    hasil["holder_teratas"] = daftar
    persen = [d["persen_supply"] for d in daftar if d["persen_supply"] is not None]
    if persen:
        non_entitas = sum(d["persen_supply"] for d in daftar
                          if d["persen_supply"] is not None
                          and d["kategori"] not in ("BURSA", "KONTRAK/PROTOKOL"))
        hasil["konsentrasi"] = {
            "top10_persen": round(sum(persen[:10]), 2),
            "terbesar_persen": persen[0],
            "top10_non_bursa_kontrak_persen": round(non_entitas, 2),
            "acuan_penilaian": ("Pakai angka non-bursa/kontrak untuk konsentrasi RIIL: "
                                "<20% sangat tersebar · 20-35% sehat · 35-50% sedang · "
                                "50-70% terkonsentrasi · >70% sangat terkonsentrasi. "
                                "Alamat 'TIDAK DIKENALI' yang besar tetap cek lewat WebSearch."),
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

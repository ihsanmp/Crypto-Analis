"""Penarik data kepemilikan on-chain (konsentrasi holder / whale) — MULTI-CHAIN.

Menjawab bagian "siapa yang memegang koin ini dan seberapa besar" dari sisi ANGKA.

SUMBER per chain:
  - Ethereum  -> Ethplorer (gratis, apiKey=freekey) + pelabelan lokal eth_labels.json.
  - Base, Arbitrum, Optimism, Polygon -> Blockscout `/api/v2/tokens/{addr}/holders`
                 (tanpa key; label dari nama kontrak & Open Labels Initiative).
  - Avalanche -> Routescan `/erc20/{addr}/holders` (tanpa key, tanpa label).
  - BSC, Solana -> GoPlus Security `token_security` (tanpa key). Ditemukan 20 Sep 2026
                 saat memeriksa bot pemindai token: GoPlus memuat daftar pemegang, porsi,
                 penanda kontrak/terkunci, dan tag bursa. Kesimpulan sehari sebelumnya
                 ("tidak ada sumber gratis") keliru.

Alamat kontrak per chain diresolusi dari CoinGecko (`platforms`), keyless.

BATASAN YANG HARUS DISAMPAIKAN APA ADANYA:
  1. Pelabelan paling kaya hanya di Ethereum (eth_labels.json, 29 rb alamat). Di chain
     lain label bergantung pada Blockscout (nama kontrak/tag) — lebih terbatas,
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
import gzip
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
import cgkunci  # noqa: E402  kunci Demo CoinGecko, dikirim lewat header

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
TIMEOUT = 25
ETHPLORER = "https://api.ethplorer.io"
GOPLUS = "https://api.gopluslabs.io/api/v1"
CG = "https://api.coingecko.com/api/v3"
ROUTESCAN = "https://api.routescan.io/v2/network/mainnet/evm"
# Semua sumber di bawah ini TANPA KEY. Token dengan jutaan holder (USDC) membuat Blockscout
# timeout; token altcoin biasa di bawah 3 detik.
BLOCKSCOUT = {
    "ethereum": "eth.blockscout.com",   # cadangan kalau Ethplorer gagal
    "base": "base.blockscout.com",
    "arbitrum": "arbitrum.blockscout.com",
    "optimism": "optimism.blockscout.com",
    "polygon": "polygon.blockscout.com",
}
ROUTESCAN_CHAIN = {"avalanche": 43114}
GOPLUS_CHAIN = {"bsc": 56}
SUMBER_CHAIN = {
    "ethereum": "Ethplorer (gratis) + label lokal etherscan-labels, cadangan Blockscout",
    "base": "Blockscout (gratis, tanpa key)",
    "arbitrum": "Blockscout (gratis, tanpa key)",
    "optimism": "Blockscout (gratis, tanpa key)",
    "polygon": "Blockscout (gratis, tanpa key)",
    "avalanche": "Routescan (gratis, tanpa key)",
    "bsc": "GoPlus Security (gratis, tanpa key)",
    "solana": "GoPlus Security Solana (gratis, tanpa key)",
}
# Registry chain: nama internal -> kunci platform CoinGecko, tipe.
CHAINS = {
    "ethereum":  {"cg": "ethereum",            "tipe": "evm"},
    "bsc":       {"cg": "binance-smart-chain", "tipe": "evm"},
    "polygon":   {"cg": "polygon-pos",         "tipe": "evm"},
    "arbitrum":  {"cg": "arbitrum-one",        "tipe": "evm"},
    "base":      {"cg": "base",                "tipe": "evm"},
    "optimism":  {"cg": "optimistic-ethereum", "tipe": "evm"},
    "avalanche": {"cg": "avalanche",           "tipe": "evm"},
    "solana":    {"cg": "solana",              "tipe": "solana"},
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
    """Baca label alamat. Diutamakan versi terkompresi.

    Berkas mentahnya 1,94 MB dan merupakan berkas TERBESAR di repo — ikut ditarik setiap
    clone, termasuk checkout di TIAP run GitHub Actions, padahal isinya nyaris tidak pernah
    berubah. Versi .gz separuhnya. Versi .json tetap dibaca kalau ada, supaya checkout lama
    tidak mendadak kehilangan pelabelan.
    """
    for jalur, buka in ((_LABELS_PATH + ".gz", lambda p: gzip.open(p, "rt", encoding="utf-8")),
                        (_LABELS_PATH, lambda p: open(p, encoding="utf-8"))):
        try:
            with buka(jalur) as f:
                return json.load(f)
        except OSError:
            continue
        except Exception:
            return {}
    return {}


def kategori_label(teks):
    low = (teks or "").lower()
    if any(k in low for k in _BURSA):
        return "BURSA"
    if any(k in low for k in _KONTRAK):
        return "KONTRAK/PROTOKOL"
    return "TERLABELI"


def klasifikasi_alamat(entity, label, is_contract):
    """Beri label + kategori untuk holder di chain selain Ethereum."""
    teks = (entity or label or "").strip()
    if teks:
        kat = kategori_label(teks)
        # Nama yang tidak memuat kata kunci ("Aave Matic Market AAVE") tetap sebuah KONTRAK
        # kalau sumbernya bilang begitu — bukan entitas yang memegang koin untuk dirinya.
        if kat == "TERLABELI" and is_contract:
            kat = "KONTRAK/PROTOKOL"
        return teks, kat
    if is_contract:
        return "kontrak (tak bernama)", "KONTRAK/PROTOKOL"
    return "belum dikenali", "TIDAK DIKENALI — cek lewat WebSearch"


def try_json(url, headers=None):
    h = {**UA, **cgkunci.header_untuk(url)}
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
    """Kembalikan (platforms_dict, nama_koin, error, natif) dari CoinGecko — keyless.

    natif=True bila koin ini aset asli chain-nya sendiri (asset_platform_id kosong). Kontrak
    yang tercantum untuk koin natif adalah versi bridge/wrapped di chain lain."""
    s = try_json(f"{CG}/search?query={urllib.parse.quote(ticker)}")
    coins = s.get("coins") if isinstance(s, dict) else None
    if not coins:
        return None, None, f"Koin '{ticker}' tidak ditemukan di CoinGecko.", False
    exact = [c for c in coins if (c.get("symbol") or "").upper() == ticker.upper()]
    pick = (exact or coins)[0]
    cid = pick.get("id")
    d = try_json(f"{CG}/coins/{cid}?localization=false&tickers=false"
                 "&market_data=false&community_data=false&developer_data=false")
    if not isinstance(d, dict) or "__err" in d:
        return None, None, "Gagal mengambil detail koin dari CoinGecko.", False
    plats = {k: v for k, v in (d.get("platforms") or {}).items() if v}
    return plats, d.get("name"), None, not d.get("asset_platform_id")


def deteksi_chain(platforms):
    """Pilih chain default: utamakan Ethereum, lalu urutan di CHAINS yang punya alamat."""
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


def _nama_blockscout(alamat):
    """Nama alamat dari Blockscout: nama kontrak, lalu tag bertipe 'name' (Open Labels)."""
    if alamat.get("name"):
        return alamat["name"]
    for tag in ((alamat.get("metadata") or {}).get("tags") or []):
        if tag.get("tagType") == "name" and tag.get("name"):
            return tag["name"]
    return None


def blockscout_holders(address, chain, limit):
    host = BLOCKSCOUT[chain]
    info = try_json(f"https://{host}/api/v2/tokens/{address}")
    token, supply = {}, None
    if "__err" not in info:
        token = {"nama": info.get("name"), "symbol": info.get("symbol"),
                 "jumlah_holder": info.get("holders_count") or info.get("holders")}
        try:
            supply = float(info.get("total_supply") or 0) or None
        except (TypeError, ValueError):
            supply = None
    data = try_json(f"https://{host}/api/v2/tokens/{address}/holders")
    if "__err" in data:
        return None, token, f"Blockscout ({chain}) gagal: {data['__err']}"
    daftar = []
    for h in (data.get("items") or [])[:limit]:
        alamat = h.get("address") or {}
        try:
            pct = round(float(h.get("value")) / supply * 100, 2) if supply else None
        except (TypeError, ValueError):
            pct = None
        nm, kat = klasifikasi_alamat(None, _nama_blockscout(alamat),
                                      bool(alamat.get("is_contract")))
        daftar.append({"alamat": alamat.get("hash"), "persen_supply": pct,
                       "label": nm, "kategori": kat})
    return daftar, token, None


def routescan_holders(address, limit, chain_id=43114):
    data = try_json(f"{ROUTESCAN}/{chain_id}/erc20/{address}/holders?limit={min(limit, 100)}")
    if "__err" in data:
        return None, {}, f"Routescan gagal: {data['__err']}"
    items = data.get("items") or []
    # "percentage" berupa PECAHAN (0,209 = 20,9%): saldo/porsi USDC Avalanche teratas cocok
    # dengan pasokan ~391 jt. Dijaga seandainya suatu hari berubah jadi persen.
    faktor = 1 if any(float(i.get("percentage") or 0) > 1 for i in items) else 100
    daftar = []
    for h in items[:limit]:
        p = h.get("percentage")
        daftar.append({"alamat": h.get("address"),
                       "persen_supply": round(float(p) * faktor, 2) if p is not None else None,
                       "label": "belum dikenali",
                       "kategori": "TIDAK DIKENALI — cek lewat WebSearch"})
    return daftar, {}, None


def _label_goplus(alamat, tag, is_contract, terkunci):
    """Label + kategori satu pemegang versi GoPlus.

    Alamat burn dibedakan: token yang DIBAKAR bukan konsentrasi di satu tangan. CAKE
    memarkir 92,85% supply di 0x...dead — dibaca mentah, itu tampak seperti satu whale
    yang bisa menjatuhkan pasar kapan saja, padahal token itu justru sudah lenyap.
    """
    rendah = (alamat or "").lower()
    if rendah in ("0x000000000000000000000000000000000000dead",
                  "0x0000000000000000000000000000000000000000") or rendah.endswith("dead"):
        return "alamat burn (token dimusnahkan)", "BURN/HANGUS"
    if tag:
        return tag, kategori_label(tag)
    if terkunci:
        return "terkunci (locker/vesting)", "KONTRAK/PROTOKOL"
    if is_contract:
        return "kontrak (tak bernama)", "KONTRAK/PROTOKOL"
    return "belum dikenali", "TIDAK DIKENALI — cek lewat WebSearch"


def _persen_goplus(nilai):
    try:
        return round(float(nilai) * 100, 2)   # GoPlus memberi PECAHAN (0,9285 = 92,85%)
    except (TypeError, ValueError):
        return None


def goplus_holders(address, chain_id, limit):
    """Pemegang teratas dari GoPlus Security (EVM). Dipakai untuk BSC."""
    data = try_json(f"{GOPLUS}/token_security/{chain_id}?contract_addresses={address}")
    if "__err" in data:
        return None, {}, f"GoPlus gagal: {data['__err']}"
    r = (data.get("result") or {}).get(address.lower()) or (data.get("result") or {}).get(address)
    if not r:
        return None, {}, f"GoPlus tidak punya data untuk {address[:12]} di chain {chain_id}."
    token = {"nama": r.get("token_name"), "symbol": r.get("token_symbol"),
             "jumlah_holder": _int(r.get("holder_count"))}
    daftar = []
    for h in (r.get("holders") or [])[:limit]:
        nm, kat = _label_goplus(h.get("address"), (h.get("tag") or "").strip(),
                                str(h.get("is_contract")) == "1", str(h.get("is_locked")) == "1")
        daftar.append({"alamat": h.get("address"), "persen_supply": _persen_goplus(h.get("percent")),
                       "label": nm, "kategori": kat})
    return daftar, token, None


def goplus_solana_holders(mint, limit):
    data = try_json(f"{GOPLUS}/solana/token_security?contract_addresses={mint}")
    if "__err" in data:
        return None, {}, f"GoPlus Solana gagal: {data['__err']}"
    r = (data.get("result") or {}).get(mint)
    if not r:
        return None, {}, f"GoPlus Solana tidak punya data untuk {mint[:12]}."
    meta = r.get("metadata") or {}
    token = {"nama": meta.get("name"), "symbol": meta.get("symbol"),
             "jumlah_holder": _int(r.get("holder_count"))}
    daftar = []
    for h in (r.get("holders") or [])[:limit]:
        nm, kat = _label_goplus(h.get("account"), (h.get("tag") or "").strip(),
                                False, str(h.get("is_locked")) == "1")
        daftar.append({"alamat": h.get("account"), "persen_supply": _persen_goplus(h.get("percent")),
                       "label": nm, "kategori": kat})
    return daftar, token, None


def _int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def main():
    if "--periksa" in sys.argv[1:]:
        ok, lap = periksa_kunci()
        print("\n".join(lap))
        sys.exit(0 if ok else 1)
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
            "Porsi di alamat burn (0x...dead) berarti token itu DIMUSNAHKAN — bukan whale.",
            # Run 35289835742: kegagalan sumber ini ditulis sebagai "data investor gagal
            # ditarik" dan dijadikan alasan Tim & VC tak bisa dinilai.
            "Ini data HOLDER on-chain, BUKAN data VC/investor. Berhasil atau gagalnya script "
            "ini tidak ada hubungannya dengan penilaian Tim & VC — jangan dijadikan alasannya.",
        ],
    }

    address = args.address
    # Resolusi alamat + (kalau perlu) auto-deteksi chain lewat CoinGecko.
    if not address or not chain:
        plats, nama, err, natif = cg_platforms(ticker)
        if err:
            hasil["error"] = err
            hasil["saran"] = ("Koin L1 sendiri (BTC, dsb.) atau tak terdaftar: cari kepemilikan "
                              "lewat WebSearch di explorer terkait, sebutkan keterbatasannya.")
            print(json.dumps(hasil, indent=2, ensure_ascii=False))
            return
        hasil["nama"] = nama
        # Koin natif (TAO, dsb.): kontrak yang tercantum hanyalah versi bridge. Holder-nya
        # bukan pemegang koin itu — di run 35289835742 TAO dibaca lewat kontrak Base.
        if natif and not chain and not address:
            hasil["error"] = (f"{ticker} koin natif chain sendiri; kontrak di "
                              f"{', '.join(sorted(plats)) or 'chain lain'} hanyalah versi "
                              "bridge/wrapped, holder-nya bukan kepemilikan koin ini.")
            hasil["saran"] = ("Cari distribusi holder lewat WebSearch di explorer chain aslinya, "
                              "sebutkan keterbatasannya.")
            print(json.dumps(hasil, indent=2, ensure_ascii=False))
            return
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
    hasil["sumber"] = SUMBER_CHAIN[chain] + " + CoinGecko (resolusi)"
    if chain == "ethereum":
        daftar, token, err = ethplorer_holders(address, limit)
        if err:
            daftar, token, err = blockscout_holders(address, chain, limit)
    elif chain in BLOCKSCOUT:
        daftar, token, err = blockscout_holders(address, chain, limit)
    elif chain in ROUTESCAN_CHAIN:
        daftar, token, err = routescan_holders(address, limit, ROUTESCAN_CHAIN[chain])
    elif tipe == "solana":
        daftar, token, err = goplus_solana_holders(address, limit)
    else:
        daftar, token, err = goplus_holders(address, GOPLUS_CHAIN[chain], limit)

    if token:
        hasil["token"] = token
    if err:
        hasil["error"] = err
        hasil["saran"] = ("Cari distribusi holder lewat WebSearch di explorer chain itu, "
                          "sebutkan keterbatasannya.")
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return

    hasil["holder_teratas"] = daftar
    persen = [d["persen_supply"] for d in daftar if d["persen_supply"] is not None]
    if persen:
        non_entitas = sum(d["persen_supply"] for d in daftar
                          if d["persen_supply"] is not None
                          and d["kategori"] not in ("BURSA", "KONTRAK/PROTOKOL",
                                                   "BURN/HANGUS"))
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

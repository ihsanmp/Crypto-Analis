"""Pelacak WALLET ADDRESS — isi dompet + nilai USD, multi-chain (ala Arkham, versi gratis).

Beda dengan investors.py (yang melihat holder sebuah TOKEN), script ini melihat SATU
ALAMAT DOMPET: apa saja yang dipegang, berapa nilainya, dan (kalau dikenal) siapa dia.

SUMBER (semua tanpa key; Moralis ditinggalkan 19 Sep 2026 — akunnya habis masa uji coba):
  - Ethereum, Base, Arbitrum, Optimism, Polygon -> Blockscout `/api/v2/addresses/{addr}`
    (saldo native + harga) dan `/token-balances` (token + harga + reputasi).
  - Avalanche -> Routescan `/address/{addr}/erc20-holdings` (token + nilai USD).
  - Solana -> RPC publik `getBalance` (saldo SOL SAJA; daftar token SPL ditolak RPC publik).
  - BSC -> tidak ada sumber gratis; Moralis dipakai hanya kalau paketnya berbayar.
  - Label alamat Ethereum diperkaya dari eth_labels.json lokal (bursa/kontrak/dll).

BATASAN:
  - Alamat EVM sama bentuknya di semua chain — default Ethereum; pakai --chain untuk chain lain.
  - Token berreputasi scam TIDAK dihitung; token tanpa harga ditulis usd=None, bukan 0.

Pemakaian:
    python cloud/wallet.py 0xF977814e90dA44bFA03b6295A0616a897441aceC          # ETH (default)
    python cloud/wallet.py 0xF977...aceC --chain bsc
    python cloud/wallet.py 5xoBq7f7CDg...  --chain solana
"""

import argparse
import gzip
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
TIMEOUT = 25
MORALIS_EVM = "https://deep-index.moralis.io/api/v2.2"
MORALIS_SOL = "https://solana-gateway.moralis.io"
MORALIS_KEY = os.environ.get("MORALIS_API_KEY", "").strip()
BLOCKSCOUT = {"ethereum": "eth.blockscout.com", "base": "base.blockscout.com",
              "arbitrum": "arbitrum.blockscout.com", "optimism": "optimism.blockscout.com",
              "polygon": "polygon.blockscout.com"}
NATIVE = {"ethereum": "ETH", "base": "ETH", "arbitrum": "ETH", "optimism": "ETH",
          "polygon": "POL"}
ROUTESCAN = "https://api.routescan.io/v2/network/mainnet/evm"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
SUMBER = {**{c: "Blockscout (gratis, tanpa key)" for c in BLOCKSCOUT},
          "avalanche": "Routescan (gratis, tanpa key)",
          "solana": "RPC publik Solana (gratis, saldo SOL saja)",
          "bsc": "Moralis (butuh paket berbayar)"}

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


def try_json(url, headers=None, data=None):
    h = dict(UA)
    if headers:
        h.update(headers)
    if data is not None:
        h["content-type"] = "application/json"
        data = json.dumps(data).encode()
    try:
        req = urllib.request.Request(url, data=data, headers=h)
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


def _angka(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _rangkum(holdings, catatan=None):
    """Urutkan per nilai, hitung nilai bersih & porsi dari aset yang BERHARGA saja."""
    total = sum(h["usd"] for h in holdings if h["usd"])
    for h in holdings:
        h["persen_portofolio"] = round(h["usd"] / total * 100, 2) if total and h["usd"] else None
    holdings.sort(key=lambda x: -(x["usd"] or 0))
    hasil = {"nilai_bersih_usd": round(total, 2), "jumlah_aset": len(holdings),
             "holdings": holdings[:25]}
    if catatan:
        hasil["catatan"] = catatan
    return hasil


def blockscout_wallet(addr, chain):
    host = BLOCKSCOUT[chain]
    info = try_json(f"https://{host}/api/v2/addresses/{addr}")
    token = try_json(f"https://{host}/api/v2/addresses/{addr}/token-balances")
    if isinstance(info, dict) and "__err" in info and isinstance(token, dict):
        return {"error": f"Blockscout ({chain}) gagal: {info['__err']}"}
    holdings = []
    if isinstance(info, dict) and "__err" not in info:
        jml, kurs = _angka(info.get("coin_balance")), _angka(info.get("exchange_rate"))
        if jml:
            jml /= 1e18
            holdings.append({"symbol": NATIVE[chain], "nama": f"{NATIVE[chain]} (native)",
                             "jumlah": round(jml, 6),
                             "usd": round(jml * kurs, 2) if kurs is not None else None,
                             "native": True})
    for t in (token if isinstance(token, list) else []):
        tk = t.get("token") or {}
        if (tk.get("reputation") or "ok") != "ok":
            continue                    # scam/spam: jangan ikut menggelembungkan nilai
        des = _angka(tk.get("decimals")) or 0
        jml = _angka(t.get("value"))
        if jml is None:
            continue
        jml /= 10 ** des
        kurs = _angka(tk.get("exchange_rate"))
        holdings.append({"symbol": tk.get("symbol"), "nama": tk.get("name"),
                         "jumlah": round(jml, 6),
                         "usd": round(jml * kurs, 2) if kurs is not None else None,
                         "native": False})
    return _rangkum(holdings)


def routescan_wallet(addr, chain_id=43114):
    data = try_json(f"{ROUTESCAN}/{chain_id}/address/{addr}/erc20-holdings?limit=100")
    if "__err" in data:
        return {"error": f"Routescan gagal: {data['__err']}"}
    holdings = []
    for t in (data.get("items") or []):
        jml = _angka(t.get("tokenQuantity"))
        des = _angka(t.get("tokenDecimals")) or 0
        usd = _angka(t.get("tokenValueInUsd"))
        holdings.append({"symbol": t.get("tokenSymbol"), "nama": t.get("tokenName"),
                         "jumlah": round(jml / 10 ** des, 6) if jml is not None else None,
                         "usd": round(usd, 2) if usd is not None else None,
                         "native": False})
    return _rangkum(holdings, "Saldo AVAX native tidak termasuk (Routescan hanya token ERC-20).")


def evm_wallet(addr, chain):
    """Jalur Moralis — kini hanya untuk BSC, dan hanya berguna dengan paket berbayar."""
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
    data = try_json(SOLANA_RPC, data={"jsonrpc": "2.0", "id": 1, "method": "getBalance",
                                      "params": [addr]})
    if "__err" in data or "error" in data:
        return {"error": f"RPC Solana gagal: {data.get('__err') or data.get('error')}"}
    lamports = (data.get("result") or {}).get("value")
    if lamports is None:
        return {"error": "RPC Solana tidak mengembalikan saldo."}
    return {"jumlah_aset": 1,
            "holdings": [{"symbol": "SOL", "nama": "Solana (native)",
                          "jumlah": lamports / 1e9, "usd": None, "native": True}],
            "catatan": ("Hanya saldo SOL. Daftar token SPL tidak tersedia gratis (RPC publik "
                        "menolak getTokenAccountsByOwner); cek Solscan lewat WebSearch.")}


# USDC di Base: token yang pasti ada, jadi galat apa pun datang dari kuncinya, bukan tokennya.
_USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


def _galat_moralis(err, label="Moralis"):
    """Moralis memakai 401 untuk DUA hal berbeda: kunci tidak sah, dan kuota paket gratis
    yang dihentikan. Menyuruh user memperbarui kunci yang sebenarnya sah membuang waktunya
    (periksa 19 Sep 2026: kuncinya sah, akunnya yang habis masa uji coba)."""
    teks = str(err)
    if teks.startswith("HTTP 401") and ("paused" in teks or "usage" in teks.lower()):
        return (f"{label} menghentikan pemakaian paket gratis akun ini (HTTP 401) — key-nya "
                "sah; pemakaian harus dipulihkan dari dashboard moralis.com.")
    if teks.startswith("HTTP 401"):
        return (f"{label} menolak API key (HTTP 401) — secret MORALIS_API_KEY tidak valid atau "
                "kedaluwarsa; perbarui di GitHub Secrets.")
    return f"{label} gagal: {teks}"


def periksa_kunci(kunci=None):
    """Diagnosis MORALIS_API_KEY tanpa pernah mencetak isinya (log Actions repo ini publik).

    Return (ok, baris_laporan). Bentuk diperiksa dulu: kunci Moralis berupa JWT (tiga bagian
    dipisah titik, diawali "eyJ"). Galat "Token is invalid format" hampir selalu berarti yang
    tersimpan bukan kuncinya — terpotong, tertukar, atau ikut tanda kutip.

    Pindah ke sini 20 Sep 2026: investors.py tidak lagi memakai Moralis sama sekali (BSC &
    Solana pindah ke GoPlus), jadi satu-satunya pemakai yang tersisa adalah isi dompet BSC.
    """
    kunci = MORALIS_KEY if kunci is None else kunci.strip()
    lap = []
    if not kunci:
        return False, ["MORALIS_API_KEY: TIDAK ADA (secret kosong/belum dibuat)."]
    bagian = kunci.split(".")
    lap.append(f"MORALIS_API_KEY: ada, panjang {len(kunci)} karakter, "
               f"{len(bagian)} bagian bertitik.")
    masalah = []
    if len(bagian) != 3 or not kunci.startswith("eyJ"):
        masalah.append("bentuknya BUKAN JWT (kunci Moralis diawali 'eyJ' dan "
                       "punya 3 bagian bertitik)")
    if any(c in kunci for c in "\"' <>"):
        masalah.append("mengandung tanda kutip/spasi/kurung sudut — kemungkinan ikut tersalin")
    lap.append("Bentuk: " + ("; ".join(masalah) if masalah else "wajar (JWT)."))
    data = try_json(f"{MORALIS_EVM}/erc20/{_USDC_BASE}/owners?chain=base&limit=1",
                    headers={"X-API-Key": kunci, "accept": "application/json"})
    if isinstance(data, dict) and "__err" in data:
        # Badan galat Moralis tidak memuat kunci, tapi disaring juga untuk berjaga-jaga.
        lap.append("Moralis: DITOLAK — " + str(data["__err"]).replace(kunci, "***")[:160])
        return False, lap
    lap.append("Moralis: DITERIMA — endpoint holder ERC-20 (Base) menjawab normal.")
    return True, lap


def main():
    if "--periksa" in sys.argv[1:]:
        ok, lap = periksa_kunci()
        print("\n".join(lap))
        sys.exit(0 if ok else 1)
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
        "sumber": SUMBER.get(chain, "?") + " + label lokal etherscan-labels (khusus Ethereum)",
        "peringatan": [
            "Alamat bursa memegang dana banyak nasabah — bukan kekayaan satu orang.",
            "Token berreputasi scam sudah dibuang dari nilai bersih; token tanpa harga bernilai usd=None.",
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
        if chain in BLOCKSCOUT:
            hasil["portofolio"] = blockscout_wallet(addr, chain)
        elif chain == "avalanche":
            hasil["portofolio"] = routescan_wallet(addr)
        else:
            port = evm_wallet(addr, chain)
            if "error" in port:
                port["error"] = (f"{chain}: tidak ada sumber gratis tanpa key untuk isi dompet "
                                 f"chain ini. Moralis: {port['error']}")
            hasil["portofolio"] = port
    else:
        hasil["error"] = f"Chain '{chain}' tidak dikenal. Pilihan: {list(EVM_SLUG) + ['solana']}"
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return

    port = hasil.get("portofolio") or {}
    if isinstance(port, dict) and str(port.get("error", "")).startswith("Moralis gagal: "):
        port["error"] = _galat_moralis(str(port["error"]).replace("Moralis gagal: ", ""))
    if isinstance(port, dict) and port.get("error"):
        hasil["saran"] = "Cek isi dompet lewat WebSearch di explorer chain itu, sebutkan keterbatasannya."

    print(json.dumps(hasil, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

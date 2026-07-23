"""Sinyal aliran whale pasar (market-wide) — Deep Blue Alpha, gratis tanpa API key.

Sumber: https://deepbluealpha.io (API publik, lisensi CC-BY-4.0 → WAJIB atribusi).

Menghasilkan:
  - Whale Sentiment Index (0-100) + komponennya → dipakai sebagai market filter,
    sejajar dengan Fear & Greed dan dominasi BTC.
  - Top-token by volume whale 24h dengan buy vs sell USD → sinyal AKUMULASI /
    DISTRIBUSI whale per koin (untuk mode SCAN & konfirmasi mode KOIN).

BATASAN (sampaikan apa adanya):
  - Hanya ekosistem ETHEREUM (token ERC-20). Koin di chain lain tidak tercakup.
  - Hanya TOP-10 token. Flow whale per-koin sembarang butuh tier berbayar Deep Blue
    Alpha (Leviathan) — di sini hanya yang masuk daftar teratas.

Pemakaian:  python cloud/whaleflow.py
"""

import json
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
BASE = "https://deepbluealpha.io/api/v1/public"
TIMEOUT = 20


def get(path):
    try:
        req = urllib.request.Request(f"{BASE}/{path}", headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"__err": f"{type(e).__name__}: {str(e)[:90]}"}


def main():
    hasil = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": "Deep Blue Alpha (deepbluealpha.io) — data whale Ethereum, gratis",
        "atribusi_wajib": "Sumber whale flow: Deep Blue Alpha (CC-BY-4.0)",
        "cakupan": "Hanya ekosistem Ethereum, hanya top-10 token by volume whale 24h",
    }

    wi = get("whale-index")
    if "__err" not in wi:
        hasil["whale_index"] = {
            "skor_0_100": wi.get("score"),
            "label": wi.get("label"),
            "sentimen_trade": wi.get("trade_sentiment"),
            "sentimen_volume": wi.get("volume_sentiment"),
            "acuan": "0-30 whale bearish · 30-45 lemah · 45-55 mixed · 55-70 bullish · >70 sangat bullish",
        }
    else:
        hasil["whale_index"] = {"error": wi["__err"]}

    tt = get("top-tokens")
    if "__err" not in tt:
        out = []
        for t in (tt.get("tokens") or [])[:10]:
            buy = float(t.get("buy_volume_usd") or 0)
            sell = float(t.get("sell_volume_usd") or 0)
            net = buy - sell
            vol = buy + sell
            rasio = round(net / vol, 3) if vol else None
            if rasio is None:
                arah = "n/a"
            elif rasio > 0.15:
                arah = "AKUMULASI"        # whale beli bersih signifikan
            elif rasio < -0.15:
                arah = "DISTRIBUSI"       # whale jual bersih signifikan
            else:
                arah = "seimbang"
            out.append({
                "symbol": t.get("symbol"),
                "volume_usd": round(float(t.get("volume_usd") or 0)),
                "buy_usd": round(buy),
                "sell_usd": round(sell),
                "net_usd": round(net),
                "arah_whale": arah,
                "trades": t.get("trades"),
            })
        hasil["top_tokens_whale_24h"] = out
        hasil["window"] = tt.get("window")
    else:
        hasil["top_tokens_whale_24h"] = {"error": tt["__err"]}

    print(json.dumps(hasil, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Sentimen sosial & pasar — GRATIS, tanpa API key.

Pengganti hemat untuk LunarCrush (yang API-nya kini berbayar). Menggabungkan:
  - Fear & Greed Index (alternative.me) -> sentimen PASAR keseluruhan + arahnya.
  - CoinGecko (per-koin, keyless) -> sentiment votes komunitas, ukuran audiens
    (Twitter/X, Reddit, Telegram), jumlah watchlist, dan aktivitas developer.

BATASAN YANG HARUS DISAMPAIKAN APA ADANYA:
  - Ini BUKAN Galaxy Score / analisis NLP cuitan real-time. "sentiment votes" adalah
    hasil voting komunitas CoinGecko (bisa bias), dan jumlah follower = UKURAN audiens,
    bukan mood sekarang. Pakai sebagai konteks tambahan, jangan jadi sinyal utama.
  - Untuk narasi/hype terbaru yang spesifik, tetap lengkapi dengan WebSearch.

Pemakaian:  python cloud/sentiment.py SOL
"""

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
TIMEOUT = 25
CG = "https://api.coingecko.com/api/v3"
FNG = "https://api.alternative.me/fng/?limit=2"


def try_json(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"__err": f"HTTP {e.code}"}
    except Exception as e:
        return {"__err": f"{type(e).__name__}: {str(e)[:90]}"}


def fear_greed():
    d = try_json(FNG)
    data = d.get("data") if isinstance(d, dict) else None
    if not data:
        return {"error": d.get("__err") if isinstance(d, dict) else "gagal"}
    now = data[0]
    hasil = {
        "skor_0_100": int(now.get("value")) if now.get("value") else None,
        "label": now.get("value_classification"),
        "acuan": "0-24 extreme fear · 25-44 fear · 45-55 netral · 56-75 greed · 76-100 extreme greed",
    }
    if len(data) > 1 and data[1].get("value"):
        kemarin = int(data[1]["value"])
        hasil["kemarin"] = kemarin
        if hasil["skor_0_100"] is not None:
            delta = hasil["skor_0_100"] - kemarin
            hasil["arah"] = "naik" if delta > 2 else "turun" if delta < -2 else "stabil"
    return hasil


def coin_social(ticker):
    s = try_json(f"{CG}/search?query={urllib.parse.quote(ticker)}")
    coins = s.get("coins") if isinstance(s, dict) else None
    if not coins:
        return {"error": f"Koin '{ticker}' tidak ditemukan di CoinGecko."}
    exact = [c for c in coins if (c.get("symbol") or "").upper() == ticker.upper()]
    pick = (exact or coins)[0]
    cid = pick.get("id")
    d = try_json(f"{CG}/coins/{cid}?localization=false&tickers=false"
                 "&market_data=false&community_data=true&developer_data=true")
    if not isinstance(d, dict) or "__err" in d:
        return {"error": "Gagal mengambil data komunitas dari CoinGecko."}

    cd = d.get("community_data") or {}
    dev = d.get("developer_data") or {}

    def num(x):
        return x if isinstance(x, (int, float)) else None

    return {
        "nama": d.get("name"),
        "coingecko_id": cid,
        "sentiment_naik_persen": num(d.get("sentiment_votes_up_percentage")),
        "sentiment_turun_persen": num(d.get("sentiment_votes_down_percentage")),
        "watchlist_users": num(d.get("watchlist_portfolio_users")),
        "twitter_followers": num(cd.get("twitter_followers")),
        "reddit_subscribers": num(cd.get("reddit_subscribers")),
        "reddit_aktif_48j": num(cd.get("reddit_accounts_active_48h")),
        "reddit_posts_48j": num(cd.get("reddit_average_posts_48h")),
        "telegram_users": num(cd.get("telegram_channel_user_count")),
        "dev": {
            "stars": num(dev.get("stars")),
            "forks": num(dev.get("forks")),
            "commit_4_pekan": num(dev.get("commit_count_4_weeks")),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    args = ap.parse_args()
    ticker = args.ticker.upper().replace("$", "")

    hasil = {
        "symbol": ticker,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": "Fear & Greed (alternative.me) + CoinGecko community (gratis, keyless)",
        "fear_greed_pasar": fear_greed(),
        "sosial_koin": coin_social(ticker),
        "cara_pakai": [
            "sentiment_votes = voting komunitas CoinGecko (bisa bias) — konteks, bukan sinyal utama.",
            "twitter/reddit/telegram = UKURAN audiens, bukan mood real-time; naik pesat = perhatian tumbuh.",
            "commit_4_pekan tinggi = tim aktif membangun; nol dalam waktu lama = waspada proyek pasif.",
            "Untuk hype/narasi terbaru yang spesifik, LENGKAPI dengan WebSearch.",
        ],
    }
    print(json.dumps(hasil, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

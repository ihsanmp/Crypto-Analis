"""Penarik OHLC + kalkulator indikator deterministik.

Kenapa ada file ini:
  - Candle mingguan ASLI tidak bisa didapat dari CoinGecko tier gratis (untuk rentang
    panjang granularitasnya jadi 4-harian). Padahal Weekly = penentu bias di metodologi ini.
  - Menghitung EMA/RSI/Stoch di dalam prompt rawan salah. Di sini dihitung dengan kode.

Sumber OHLC dicoba berurutan sampai ada yang berhasil (lingkungan berbeda memblokir
bursa yang berbeda: ISP Indonesia memblokir sebagian besar bursa; datacenter AS diblokir
oleh Binance/Bybit/OKX). Sumber yang terpakai selalu dilaporkan di output.

Candle Weekly dibangun dengan mengagregasi candle harian (open pertama, high maks,
low min, close terakhir) -> hasilnya persis sama dengan weekly asli.

Pemakaian:
    python indicators.py TRX
    python indicators.py BTC --cg-id bitcoin

Output: JSON ringkas berisi EMA13/21, RSI14, Stoch(5,3,3), swing+Fibonacci,
struktur pasar, dan volume untuk timeframe 1w / 1d / 4h.
Hanya memakai pustaka standar Python (tanpa numpy/pandas) agar jalan di mana saja.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
TIMEOUT = 8          # pendek: sumber yang diblokir harus cepat menyerah
_DEAD = set()        # sumber yang sudah terbukti gagal -> jangan dicoba lagi run ini


# ---------------------------------------------------------------- util jaringan

def http_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def resolve_cg_id(ticker):
    """Cari id CoinGecko dari ticker (mis. TRX -> tron) supaya fallback tetap jalan
    walau pemanggil lupa memberi --cg-id."""
    try:
        data = http_json("https://api.coingecko.com/api/v3/search?query="
                         + urllib.parse.quote(ticker))
        for c in data.get("coins", []):
            if c.get("symbol", "").upper() == ticker.upper():
                return c.get("id")
        coins = data.get("coins", [])
        return coins[0].get("id") if coins else None
    except Exception:
        return None


# ------------------------------------------------------------- adapter sumber
# Setiap adapter mengembalikan list candle terurut lama->baru:
#   [ts_ms, open, high, low, close, volume]

def src_binance(ticker, interval):
    imap = {"1d": "1d", "4h": "4h"}
    url = ("https://api.binance.com/api/v3/klines?symbol="
           f"{ticker}USDT&interval={imap[interval]}&limit=1000")
    rows = http_json(url)
    return [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
            for r in rows]


def src_kraken(ticker, interval):
    imap = {"1d": 1440, "4h": 240}
    pair = ("XBT" if ticker == "BTC" else ticker) + "USD"
    url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={imap[interval]}"
    data = http_json(url)
    if data.get("error"):
        raise RuntimeError(f"kraken error: {data['error']}")
    key = next(k for k in data["result"] if k != "last")
    # Kraken: [time, open, high, low, close, vwap, volume, count]
    return [[int(r[0]) * 1000, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[6])]
            for r in data["result"][key]]


def src_coinbase(ticker, interval):
    gmap = {"1d": 86400, "4h": 14400}
    url = (f"https://api.exchange.coinbase.com/products/{ticker}-USD/candles"
           f"?granularity={gmap[interval]}")
    rows = http_json(url)
    # Coinbase: [time, low, high, open, close, volume] (terbaru dulu)
    out = [[int(r[0]) * 1000, float(r[3]), float(r[2]), float(r[1]), float(r[4]), float(r[5])]
           for r in rows]
    return sorted(out, key=lambda c: c[0])


def src_okx(ticker, interval):
    imap = {"1d": "1Dutc", "4h": "4H"}
    url = (f"https://www.okx.com/api/v5/market/candles?instId={ticker}-USDT"
           f"&bar={imap[interval]}&limit=300")
    data = http_json(url)
    if data.get("code") not in ("0", 0):
        raise RuntimeError(f"okx error: {data.get('msg')}")
    out = [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
           for r in data["data"]]
    return sorted(out, key=lambda c: c[0])


def src_coingecko_ohlc(cg_id, interval):
    """Candle 4 jam asli dari CoinGecko (days=30 -> granularitas 4 jam)."""
    if interval != "4h":
        raise RuntimeError("coingecko ohlc: candle harian asli tidak ada di tier gratis")
    url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/ohlc?vs_currency=usd&days=30"
    rows = http_json(url)
    # CoinGecko: [ts, o, h, l, c] (tanpa volume)
    return [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), 0.0] for r in rows]


def src_coingecko_chart(cg_id, interval):
    """Fallback TERAKHIR untuk candle harian saat semua bursa terblokir.

    market_chart days=365 memberi granularitas harian, TAPI hanya harga penutupan —
    tidak ada high/low intraday. Jadi O=H=L=C. Konsekuensinya Stochastic jadi versi
    berbasis close (range dihitung dari close, bukan high/low asli). EMA & RSI tetap
    akurat karena memang hanya butuh close. Kualitas ditandai 'approx_close_only'."""
    if interval != "1d":
        raise RuntimeError("coingecko chart: hanya untuk candle harian")
    url = (f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart"
           f"?vs_currency=usd&days=365")
    data = http_json(url)
    prices = data.get("prices", [])
    vols = data.get("total_volumes", [])
    vol_by_i = {i: float(v[1]) for i, v in enumerate(vols)}
    out = []
    for i, (ts, p) in enumerate(prices):
        p = float(p)
        out.append([int(ts), p, p, p, p, vol_by_i.get(i, 0.0)])
    return out


EXCHANGES = [
    ("binance", src_binance),
    ("kraken", src_kraken),
    ("coinbase", src_coinbase),
    ("okx", src_okx),
]


def fetch_base(ticker, cg_id, interval):
    """Ambil candle dari sumber pertama yang berhasil.
    Return: (candles, nama_sumber, kualitas, pesan_error)"""
    errors = []
    for name, fn in EXCHANGES:
        if name in _DEAD:               # sudah gagal di timeframe sebelumnya
            errors.append(f"{name}: dilewati (sudah gagal)")
            continue
        try:
            rows = fn(ticker, interval)
            if rows and len(rows) >= 30:
                return rows, name, "native", None
            errors.append(f"{name}: data terlalu sedikit ({len(rows)})")
        except Exception as e:
            _DEAD.add(name)
            errors.append(f"{name}: {type(e).__name__}")
    if cg_id:
        for fn, qual in ((src_coingecko_ohlc, "native"), (src_coingecko_chart, "approx_close_only")):
            try:
                rows = fn(cg_id, interval)
                if rows and len(rows) >= 30:
                    return rows, "coingecko", qual, None
            except Exception as e:
                errors.append(f"coingecko/{fn.__name__}: {type(e).__name__}")
    return None, None, None, "; ".join(errors)


def aggregate_weekly(daily):
    """Gabung candle harian jadi mingguan (pekan mulai Senin UTC).
    Hasilnya identik dengan candle weekly asli."""
    buckets = {}
    order = []
    for ts, o, h, l, c, v in daily:
        d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        # kunci pekan: tanggal Senin dari pekan tersebut
        monday = d.toordinal() - d.weekday()
        if monday not in buckets:
            buckets[monday] = [ts, o, h, l, c, v]
            order.append(monday)
        else:
            b = buckets[monday]
            b[2] = max(b[2], h)
            b[3] = min(b[3], l)
            b[4] = c
            b[5] += v
    return [buckets[k] for k in sorted(order)]


# ------------------------------------------------------------------ indikator

def ema(values, n):
    if len(values) < n:
        return []
    k = 2 / (n + 1)
    out = [sum(values[:n]) / n]
    for v in values[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi_wilder(closes, n=14):
    if len(closes) < n + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    out = []
    for i in range(n, len(gains) + 1):
        if i > n:
            avg_g = (avg_g * (n - 1) + gains[i - 1]) / n
            avg_l = (avg_l * (n - 1) + losses[i - 1]) / n
        if avg_l == 0:
            out.append(100.0)
        else:
            rs = avg_g / avg_l
            out.append(100 - 100 / (1 + rs))
    return out


def sma(values, n):
    return [sum(values[i - n + 1:i + 1]) / n for i in range(n - 1, len(values))]


def stochastic(highs, lows, closes, k_len=5, k_smooth=3, d_smooth=3):
    """Setting user: %K length 5, K smoothing 3, D smoothing 3."""
    raw = []
    for i in range(k_len - 1, len(closes)):
        hh = max(highs[i - k_len + 1:i + 1])
        ll = min(lows[i - k_len + 1:i + 1])
        raw.append(100.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100)
    k = sma(raw, k_smooth)
    d = sma(k, d_smooth)
    return k, d


def pivots(values, window=5, kind="low"):
    """Indeks pivot lokal (low atau high) dengan konfirmasi `window` bar di kedua sisi."""
    out = []
    for i in range(window, len(values) - window):
        seg = values[i - window:i + window + 1]
        if kind == "low" and values[i] == min(seg):
            out.append(i)
        if kind == "high" and values[i] == max(seg):
            out.append(i)
    return out


def detect_divergence(closes, rsi_vals, offset):
    """Bandingkan 2 pivot terakhir harga vs RSI. Valid jika jarak 5-50 bar."""
    if len(rsi_vals) < 20:
        return "none"
    p = closes[offset:]
    n = min(len(p), len(rsi_vals))
    p, r = p[-n:], rsi_vals[-n:]

    lows = pivots(p, 4, "low")
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if 5 <= b - a <= 50 and p[b] < p[a] and r[b] > r[a]:
            return "bullish"
    highs = pivots(p, 4, "high")
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if 5 <= b - a <= 50 and p[b] > p[a] and r[b] < r[a]:
            return "bearish"
    return "none"


def stoch_cycle_bottom(k_series):
    """Pola W (double bottom) pada Stochastic — penanda zona akumulasi siklus."""
    if len(k_series) < 12:
        return False
    lows = pivots(k_series, 4, "low")
    if len(lows) < 2:
        return False
    i1, i2 = lows[-2], lows[-1]
    v1, v2 = k_series[i1], k_series[i2]
    return (v1 < 25 and v2 < 35 and v2 >= v1
            and 4 <= (i2 - i1) <= 20
            and k_series[-1] > v2 + 10)


def fib_from_swing(highs, lows, closes, lookback=80):
    """Tarik Fibonacci dari swing besar terakhir.
    Uptrend: low -> high (cari support koreksi). Downtrend: high -> low."""
    seg_h = highs[-lookback:]
    seg_l = lows[-lookback:]
    base = len(highs) - len(seg_h)
    hi_i = base + seg_h.index(max(seg_h))
    lo_i = base + seg_l.index(min(seg_l))
    hi, lo = highs[hi_i], lows[lo_i]
    rng = hi - lo
    if rng <= 0:
        return None

    up = hi_i > lo_i  # extreme terakhir = high -> leg naik
    levels = {}
    for f in [0, 0.236, 0.382, 0.5, 0.618, 0.786]:
        levels[str(f)] = hi - rng * f if up else lo + rng * f
    for f in [1.618, 2.618]:
        levels[str(f)] = lo + rng * f if up else hi - rng * f

    price = closes[-1]
    if up:
        gp_lo, gp_hi = levels["0.618"], levels["0.5"]
        if gp_lo <= price <= gp_hi:
            zone = "GOLDEN_POCKET"
        elif price > levels["0.236"]:
            zone = "SHALLOW_PULLBACK"
        elif price < levels["0.786"]:
            zone = "TREND_INVALID"
        else:
            zone = "MID_RETRACE"
    else:
        gp_lo, gp_hi = levels["0.5"], levels["0.618"]
        if gp_lo <= price <= gp_hi:
            zone = "GOLDEN_POCKET"
        elif price < levels["0.236"]:
            zone = "SHALLOW_PULLBACK"
        elif price > levels["0.786"]:
            zone = "TREND_INVALID"
        else:
            zone = "MID_RETRACE"

    return {
        "direction": "up" if up else "down",
        "swing_high": round(hi, 8), "swing_high_utc": None,
        "swing_low": round(lo, 8), "swing_low_utc": None,
        "levels": {k: round(v, 8) for k, v in levels.items()},
        "zone": zone,
        "_hi_i": hi_i, "_lo_i": lo_i,
    }


def market_structure(highs, lows, window=5):
    ph = pivots(highs, window, "high")
    pl = pivots(lows, window, "low")
    if len(ph) < 2 or len(pl) < 2:
        return "UNDEFINED"
    hh = highs[ph[-1]] > highs[ph[-2]]
    hl = lows[pl[-1]] > lows[pl[-2]]
    if hh and hl:
        return "UPTREND_HH_HL"
    if not hh and not hl:
        return "DOWNTREND_LH_LL"
    if not hh and hl:
        return "LOWER_HIGH_(possible_CHoCH)"
    return "HIGHER_HIGH_but_LOWER_LOW_(expanding)"


def ema_signal(price, e13, e21, e13p, e21p):
    if e13p <= e21p and e13 > e21:
        return "GOLDEN_CROSS"
    if e13p >= e21p and e13 < e21:
        return "DEATH_CROSS"
    if price > e13 > e21:
        return "UPTREND"
    if price < e13 < e21:
        return "DOWNTREND"
    return "NEUTRAL"


def stoch_signal(k, d, kp, dp):
    cross_up = kp <= dp and k > d
    cross_down = kp >= dp and k < d
    if cross_up and k < 20:
        return "CROSS_UP_OVERSOLD"
    if cross_up and k < 50:
        return "CROSS_UP_MID"
    if cross_up:
        return "CROSS_UP_HIGH"
    if cross_down and k > 80:
        return "CROSS_DOWN_OVERBOUGHT"
    if cross_down and k > 50:
        return "CROSS_DOWN_MID"
    if cross_down:
        return "CROSS_DOWN_LOW"
    if k > 80:
        return "OVERBOUGHT_HOLDING"
    if k < 20:
        return "OVERSOLD_HOLDING"
    return "NEUTRAL"


def analyze(candles, drop_unclosed=True):
    """Hitung semua indikator untuk satu timeframe."""
    if drop_unclosed and len(candles) > 1:
        candles = candles[:-1]   # buang candle berjalan -> hindari look-ahead
    if len(candles) < 40:
        return {"error": f"candle tidak cukup ({len(candles)})"}

    ts = [c[0] for c in candles]
    o = [c[1] for c in candles]
    h = [c[2] for c in candles]
    l = [c[3] for c in candles]
    c_ = [c[4] for c in candles]
    v = [c[5] for c in candles]

    e13 = ema(c_, 13)
    e21 = ema(c_, 21)
    r = rsi_wilder(c_, 14)
    k, d = stochastic(h, l, c_)
    fib = fib_from_swing(h, l, c_)

    if len(e13) < 2 or len(e21) < 2 or len(k) < 2 or len(d) < 2 or not r:
        return {"error": "data tidak cukup untuk indikator"}

    price = c_[-1]
    vol_sma20 = sma(v, 20)[-1] if len(v) >= 20 and any(v) else 0.0

    out = {
        "candles_used": len(candles),
        "last_candle_utc": datetime.fromtimestamp(ts[-1] / 1000, tz=timezone.utc)
                                   .strftime("%Y-%m-%d %H:%M"),
        "close": round(price, 8),
        "ema13": round(e13[-1], 8),
        "ema21": round(e21[-1], 8),
        "ema_signal": ema_signal(price, e13[-1], e21[-1], e13[-2], e21[-2]),
        "ema_gap_pct": round(abs(e13[-1] - e21[-1]) / price * 100, 3),
        "ema_cross_valid": abs(e13[-1] - e21[-1]) / price > 0.005,
        "rsi14": round(r[-1], 2),
        "rsi_divergence": detect_divergence(c_, r, len(c_) - len(r)),
        "stoch": {
            "k": round(k[-1], 2), "d": round(d[-1], 2),
            "k_prev": round(k[-2], 2), "d_prev": round(d[-2], 2),
            "signal": stoch_signal(k[-1], d[-1], k[-2], d[-2]),
            "cycle_bottom": stoch_cycle_bottom(k),
        },
        "structure": market_structure(h, l),
        "volume": {
            "last": round(v[-1], 2), "sma20": round(vol_sma20, 2),
            "ratio": round(v[-1] / vol_sma20, 2) if vol_sma20 else None,
            "breakout_valid": (v[-1] / vol_sma20 > 1.5) if vol_sma20 else None,
        },
    }

    if fib:
        fib["swing_high_utc"] = datetime.fromtimestamp(ts[fib.pop("_hi_i")] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        fib["swing_low_utc"] = datetime.fromtimestamp(ts[fib.pop("_lo_i")] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        out["fib"] = fib
    return out


# ----------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker", help="simbol koin, mis. TRX / BTC / SOL")
    ap.add_argument("--cg-id", default=None,
                    help="id CoinGecko (mis. tron) untuk fallback terakhir")
    args = ap.parse_args()
    ticker = args.ticker.upper().replace("$", "")
    cg_id = args.cg_id or resolve_cg_id(ticker)   # fallback tetap hidup walau lupa --cg-id

    result = {
        "symbol": ticker,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "indicator_settings": "EMA 13/21, RSI 14 (Wilder), Stoch 5-3-3, Fib 0/.236/.382/.5/.618/.786/1.618/2.618",
        "note": "candle berjalan dibuang (hanya candle tertutup) untuk hindari look-ahead",
        "timeframes": {},
    }

    daily, src_d, qual_d, err_d = fetch_base(ticker, cg_id, "1d")
    if daily:
        result["timeframes"]["1d"] = dict(analyze(daily), source=src_d, quality=qual_d)
        weekly = aggregate_weekly(daily)
        # agregasi harian->mingguan itu eksak; kualitas mengikuti kualitas data hariannya
        result["timeframes"]["1w"] = dict(
            analyze(weekly),
            source=f"{src_d} (agregasi harian->mingguan)",
            quality="exact" if qual_d == "native" else qual_d)
    else:
        result["timeframes"]["1d"] = {"error": f"gagal ambil candle harian: {err_d}"}
        result["timeframes"]["1w"] = {"error": "tidak bisa dihitung tanpa candle harian"}

    h4, src_4, qual_4, err_4 = fetch_base(ticker, cg_id, "4h")
    if h4:
        result["timeframes"]["4h"] = dict(analyze(h4), source=src_4, quality=qual_4)
    else:
        result["timeframes"]["4h"] = {"error": f"gagal ambil candle 4 jam: {err_4}"}

    if any(tf.get("quality") == "approx_close_only" for tf in result["timeframes"].values()):
        result["quality_warning"] = (
            "Sebagian timeframe memakai data close-only (semua API bursa tidak dapat "
            "dijangkau dari lingkungan ini). EMA & RSI tetap akurat; Stochastic memakai "
            "range close (bukan high/low asli) sehingga kurang presisi. WAJIB disebutkan "
            "di output analisa.")

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

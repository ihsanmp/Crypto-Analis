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

Output: JSON ringkas berisi EMA 13/21/33/50/100/200, RSI14, Stoch(5,3,3),
        BB+MidBand(EMA20), ATR14, SuperTrend, Pivot standar, swing+Fibonacci,
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


def stdev(values, n):
    """Standar deviasi POPULASI n periode terakhir (sama seperti TradingView)."""
    if len(values) < n:
        return None
    seg = values[-n:]
    m = sum(seg) / n
    return (sum((x - m) ** 2 for x in seg) / n) ** 0.5


def bollinger(closes, n=20, mult=2.0, mult2=1.0):
    """Bollinger Band + Mid Band pakai EMA — sesuai indikator 'BB + MB' milik user
    (Panjang 20, Sumber Penutupan, Mult 2, Mult2 1). Basis memakai EMA, bukan SMA."""
    if len(closes) < n:
        return None
    e = ema(closes, n)
    sd = stdev(closes, n)
    if not e or sd is None or not e[-1]:
        return None
    basis, price = e[-1], closes[-1]
    atas, bawah = basis + mult * sd, basis - mult * sd
    atas2, bawah2 = basis + mult2 * sd, basis - mult2 * sd
    lebar = (atas - bawah)
    if price > atas:
        posisi = "DI ATAS band atas (overextended)"
    elif price < bawah:
        posisi = "DI BAWAH band bawah (oversold ekstrem)"
    elif price > basis:
        posisi = "antara basis dan band atas"
    else:
        posisi = "antara band bawah dan basis"
    return {
        "basis_ema20": round(basis, 8),
        "atas_2sd": round(atas, 8), "bawah_2sd": round(bawah, 8),
        "atas_1sd": round(atas2, 8), "bawah_1sd": round(bawah2, 8),
        "posisi_harga": posisi,
        "persen_b": round((price - bawah) / lebar, 3) if lebar else None,
        "bandwidth_pct": round(lebar / basis * 100, 2),
        "squeeze": (lebar / basis * 100) < 10,   # band sempit -> sering mendahului ledakan
    }


def atr_series(highs, lows, closes, n=14):
    """ATR dengan pemulusan Wilder. Return list (sejajar indeks mulai dari n)."""
    if len(closes) < n + 1:
        return []
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    if len(trs) < n:
        return []
    nilai = sum(trs[:n]) / n
    keluar = [nilai]
    for t in trs[n:]:
        nilai = (nilai * (n - 1) + t) / n
        keluar.append(nilai)
    return keluar


def supertrend(highs, lows, closes, n=10, mult=3.0):
    """SuperTrend klasik (ATR n, pengali mult). Dipakai sebagai trailing stop tren."""
    a = atr_series(highs, lows, closes, n)
    if not a:
        return None
    mulai = len(closes) - len(a)
    arah, st = None, None
    ub_prev = lb_prev = None
    for idx, atr in enumerate(a):
        i = mulai + idx
        mid = (highs[i] + lows[i]) / 2
        ub, lb = mid + mult * atr, mid - mult * atr
        if ub_prev is not None:
            ub = ub if (ub < ub_prev or closes[i - 1] > ub_prev) else ub_prev
            lb = lb if (lb > lb_prev or closes[i - 1] < lb_prev) else lb_prev
        if arah is None:
            arah = "naik" if closes[i] > ub else "turun"
        elif arah == "naik" and closes[i] < lb:
            arah = "turun"
        elif arah == "turun" and closes[i] > ub:
            arah = "naik"
        st = lb if arah == "naik" else ub
        ub_prev, lb_prev = ub, lb
    price = closes[-1]
    return {
        "arah": arah,
        "level": round(st, 8),
        "jarak_pct": round(abs(price - st) / price * 100, 2),
        "acuan": "arah naik = level jadi trailing stop di bawah harga; turun = resistensi di atas",
    }


def pivot_standard(highs, lows, closes):
    """Pivot Point standar/klasik dari candle SEBELUMNYA (bukan yang berjalan)."""
    if len(closes) < 2:
        return None
    h, l, c = highs[-2], lows[-2], closes[-2]
    p = (h + l + c) / 3
    return {
        "P": round(p, 8),
        "R1": round(2 * p - l, 8), "S1": round(2 * p - h, 8),
        "R2": round(p + (h - l), 8), "S2": round(p - (h - l), 8),
        "R3": round(h + 2 * (p - l), 8), "S3": round(l - 2 * (h - p), 8),
    }


# Set EMA sesuai konfigurasi TradingView user.
EMA_SET = (13, 21, 33, 50, 100, 200)
SMA_SET = (20, 50, 200)


def ema_stack(price, emas):
    """Nilai keselarasan tren dari susunan EMA. Makin selaras, makin kuat trennya."""
    ada = [emas[f"ema{n}"] for n in EMA_SET if emas.get(f"ema{n}") is not None]
    if len(ada) < 3:
        return {"status": "data tidak cukup", "selaras": None}
    naik = all(ada[i] >= ada[i + 1] for i in range(len(ada) - 1))   # cepat > lambat
    turun = all(ada[i] <= ada[i + 1] for i in range(len(ada) - 1))
    if naik and price > ada[0]:
        status = "BULLISH PENUH — semua EMA tersusun naik & harga di atasnya"
    elif turun and price < ada[0]:
        status = "BEARISH PENUH — semua EMA tersusun turun & harga di bawahnya"
    elif naik:
        status = "susunan bullish, tapi harga di bawah EMA tercepat (koreksi)"
    elif turun:
        status = "susunan bearish, tapi harga di atas EMA tercepat (pantulan)"
    else:
        status = "campur aduk — tren belum jelas (EMA saling silang)"
    di_atas = sum(1 for x in ada if price > x)
    return {
        "status": status,
        "selaras": naik or turun,
        "harga_di_atas": f"{di_atas} dari {len(ada)} EMA",
    }


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

    # EMA cepat (13/21) tetap jadi pemicu cross; sisanya konteks tren besar.
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

    # --- EMA set lengkap (13/21/33/50/100/200) ---------------------------------
    # EMA panjang butuh banyak candle; kalau data kurang diberi None (bukan diarang),
    # supaya tidak ada angka palsu. Weekly sering tidak punya 200 periode.
    emas = {}
    for n in EMA_SET:
        seri = ema(c_, n) if len(c_) >= n else []
        emas[f"ema{n}"] = round(seri[-1], 8) if seri else None
    out["ema"] = emas
    out["ema_kurang_data"] = [f"ema{n}" for n in EMA_SET if emas[f"ema{n}"] is None]
    out["ema_stack"] = ema_stack(price, emas)

    smas = {}
    for n in SMA_SET:
        seri = sma(c_, n) if len(c_) >= n else []
        smas[f"sma{n}"] = round(seri[-1], 8) if seri else None
    out["sma"] = smas

    bb = bollinger(c_)
    if bb:
        out["bollinger"] = bb

    # Indikator berbasis RENTANG (ATR/SuperTrend/Pivot) hanya sahih kalau high & low
    # asli tersedia. Pada fallback close-only (O=H=L=C) hasilnya menyesatkan — mis.
    # pivot jadi R1=S1=P. Deteksi dan tandai, jangan disajikan seolah valid.
    sampel = min(30, len(c_))
    punya_range = any(h[i] > l[i] for i in range(-sampel, 0))
    if punya_range:
        a = atr_series(h, l, c_, 14)
        if a:
            out["atr14"] = round(a[-1], 8)
            out["atr_pct"] = round(a[-1] / price * 100, 2)
            # Trailing stop berbasis ATR (setara ATR Trailing Stop): 3x ATR dari harga.
            out["atr_trailing_stop"] = round(price - 3 * a[-1], 8)
        st = supertrend(h, l, c_)
        if st:
            out["supertrend"] = st
        pv = pivot_standard(h, l, c_)
        if pv:
            out["pivot_standar"] = pv
    else:
        out["indikator_rentang"] = (
            "TIDAK TERSEDIA — sumber hanya memberi harga penutupan (tanpa high/low asli), "
            "sehingga ATR, SuperTrend, dan Pivot tidak bisa dihitung dengan benar. "
            "JANGAN memakai level rentang untuk timeframe ini.")

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
        "indicator_settings": ("EMA 13/21/33/50/100/200 (cross 13x21), RSI 14 (Wilder), Stoch 5-3-3, BB+MidBand EMA 20 (mult 2 & 1), ATR 14 + trailing 3x, SuperTrend 10x3, Pivot standar, Fib 0/.236/.382/.5/.618/.786/1.618/2.618"),
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

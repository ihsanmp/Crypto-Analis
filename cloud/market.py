"""OHLC + indikator untuk SAHAM dan FOREX — memakai mesin indikator yang sama dengan crypto.

Kenapa cukup satu file kecil: cloud/indicators.py sebenarnya AGNOSTIK ASET — ia hanya butuh
deret candle [ts_ms, open, high, low, close, volume]. Jadi seluruh perhitungan (EMA
13/21/33/50/100/200, RSI14, Stoch 5-3-3, Bollinger+MidBand, ATR, SuperTrend, Pivot,
Fibonacci, struktur, volume) dipakai ulang apa adanya. Yang ditambahkan di sini hanya
penarik datanya.

SUMBER: Yahoo Finance chart API — gratis, tanpa API key, mencakup saham global dan pasangan
forex. Sudah diuji hidup untuk AAPL dan EURUSD=X.

BATASAN YANG HARUS DISAMPAIKAN APA ADANYA:
  - Yahoo Finance adalah API TIDAK RESMI. Bisa berubah, membatasi laju, atau memblokir IP
    datacenter sewaktu-waktu. Kalau gagal, katakan datanya tidak tersedia — jangan mengarang.
  - Saham & forex TIDAK buka 24 jam. Di luar sesi, candle terakhir adalah penutupan sesi
    sebelumnya — itu wajar, bukan data basi. Akhir pekan & libur bursa juga kosong.
  - Yahoo tidak menyediakan candle 4 jam; 4H di sini DIBANGUN dari candle 1 jam.
  - Volume forex dari Yahoo umumnya nol/tidak bermakna — jangan menilai breakout dari volume
    pada pasangan mata uang.

Pemakaian:
    python cloud/market.py AAPL              # saham
    python cloud/market.py EURUSD --forex    # forex (otomatis jadi EURUSD=X)
    python cloud/market.py BBCA.JK           # bursa non-AS pakai akhiran Yahoo
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from indicators import aggregate_weekly, analyze  # noqa: E402  (mesin indikator dipakai ulang)

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-pasar/1.0)"}
YF = "https://query1.finance.yahoo.com/v8/finance/chart/"
TIMEOUT = 20


def tarik(simbol, rentang, interval):
    """Ambil candle dari Yahoo. Return (candles, meta, error)."""
    url = f"{YF}{urllib.parse.quote(simbol)}?range={rentang}&interval={interval}"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return None, None, f"HTTP {e.code}"
    except Exception as e:
        return None, None, f"{type(e).__name__}"

    hasil = ((d.get("chart") or {}).get("result") or [None])[0]
    if not hasil:
        err = ((d.get("chart") or {}).get("error") or {}).get("description")
        return None, None, err or "simbol tidak ditemukan"

    ts = hasil.get("timestamp") or []
    q = ((hasil.get("indicators") or {}).get("quote") or [{}])[0]
    o, h, l, c, v = (q.get("open") or [], q.get("high") or [], q.get("low") or [],
                     q.get("close") or [], q.get("volume") or [])
    candles = []
    for i, t in enumerate(ts):
        try:
            # Candle yang belum lengkap (nilai None) dibuang — bukan ditambal, supaya
            # indikator tidak dihitung dari angka karangan.
            if None in (o[i], h[i], l[i], c[i]):
                continue
            candles.append([int(t) * 1000, float(o[i]), float(h[i]), float(l[i]),
                            float(c[i]), float((v[i] if i < len(v) and v[i] else 0) or 0)])
        except (IndexError, TypeError):
            continue
    # Buang HANYA candle yang masih berjalan (bertanggal hari ini), bukan candle terakhir
    # secara membabi buta. Yahoo mengirim hari perdagangan yang belum settle dengan close
    # None — itu sudah tersaring di atas. Kalau setelah itu candle terakhir dibuang lagi
    # (drop_unclosed), satu hari perdagangan yang SAH ikut hilang: pernah membuat analisa
    # NVDA memakai candle 30 Juli padahal 31 Juli sudah tutup dan tersedia.
    hari_ini = datetime.now(timezone.utc).date()
    candles = [c for c in candles
               if datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc).date() < hari_ini]
    if len(candles) < 40:
        return None, hasil.get("meta"), f"candle terlalu sedikit ({len(candles)})"
    return candles, hasil.get("meta"), None


def ke_4jam(satu_jam):
    """Yahoo tidak punya candle 4 jam — dibangun dari 1 jam (4 batang per kelompok)."""
    keluar = []
    for i in range(0, len(satu_jam) - 3, 4):
        grup = satu_jam[i:i + 4]
        keluar.append([grup[0][0], grup[0][1], max(g[2] for g in grup),
                       min(g[3] for g in grup), grup[-1][4], sum(g[5] for g in grup)])
    return keluar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("simbol", help="AAPL, MSFT, NVDA, EURUSD, XAUUSD (fokus: saham luar negeri)")
    ap.add_argument("--forex", action="store_true", help="tambahkan akhiran =X untuk pasangan mata uang")
    args = ap.parse_args()

    simbol = args.simbol.upper().replace("$", "")
    # Komoditas dipetakan ke kontrak berjangka; "XAUUSD=X" tidak ada di Yahoo (404).
    # "GOLD" di NYSE adalah Barrick Gold Corp (saham tambang), BUKAN logamnya.
    KOMODITAS = {"GOLD": "GC=F", "EMAS": "GC=F", "XAUUSD": "GC=F", "XAU": "GC=F",
                 "SILVER": "SI=F", "PERAK": "SI=F", "XAGUSD": "SI=F", "XAG": "SI=F",
                 "OIL": "CL=F", "MINYAK": "CL=F", "WTI": "CL=F"}
    if simbol in KOMODITAS:
        simbol = KOMODITAS[simbol]
    elif args.forex and not simbol.endswith(("=X", "=F")):
        simbol += "=X"
    jenis = "komoditas" if simbol.endswith("=F") else ("forex" if simbol.endswith("=X") else "saham")

    hasil = {
        "simbol": simbol,
        "jenis": jenis,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": "Yahoo Finance (gratis, tanpa API key, API TIDAK RESMI)",
        "peringatan": [
            "Yahoo Finance API tidak resmi — bisa berubah/memblokir sewaktu-waktu.",
            "Pasar TIDAK 24 jam: di luar sesi, candle terakhir = penutupan sesi sebelumnya "
            "(wajar, bukan data basi). Akhir pekan & libur bursa kosong.",
            "4H dibangun dari candle 1 jam (Yahoo tidak menyediakan 4H).",
        ],
    }
    if jenis in ("forex", "komoditas"):
        hasil["peringatan"].append(
            "Volume forex dari Yahoo umumnya nol — JANGAN menilai breakout dari volume.")

    # Harian: 2 tahun supaya EMA200 terisi. Weekly dibangun dari harian (identik weekly asli).
    harian, meta, err = tarik(simbol, "2y", "1d")
    if err:
        hasil["error"] = f"Gagal mengambil data harian: {err}"
        hasil["saran"] = ("Cek penulisan simbol. Bursa non-AS perlu akhiran Yahoo "
                          "(mis. BBCA.JK, VOD.L). Forex pakai --forex (EURUSD -> EURUSD=X).")
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return

    if meta:
        hasil["profil"] = {
            "nama_bursa": meta.get("fullExchangeName"),
            "mata_uang": meta.get("currency"),
            "harga_terakhir": meta.get("regularMarketPrice"),
            "penutupan_sebelumnya": meta.get("chartPreviousClose") or meta.get("previousClose"),
            "zona_waktu": meta.get("exchangeTimezoneName"),
        }

    tf = {}
    tf["1d"] = analyze(harian, drop_unclosed=False)
    tf["1d"]["source"] = "yahoo finance"
    tf["1d"]["quality"] = "native"

    mingguan = aggregate_weekly(harian)
    if len(mingguan) >= 40:
        tf["1w"] = analyze(mingguan, drop_unclosed=False)
        tf["1w"]["source"] = "yahoo finance (agregasi harian->mingguan)"
        tf["1w"]["quality"] = "exact"
    else:
        tf["1w"] = {"error": f"candle mingguan tidak cukup ({len(mingguan)})"}

    satu_jam, _, err_h = tarik(simbol, "60d", "1h")
    if err_h or not satu_jam:
        tf["4h"] = {"error": f"data 1 jam tidak tersedia ({err_h or 'kosong'})"}
    else:
        empat = ke_4jam(satu_jam)
        tf["4h"] = analyze(empat, drop_unclosed=False) if len(empat) >= 40 else {
            "error": f"candle 4 jam tidak cukup ({len(empat)})"}
        if "error" not in tf["4h"]:
            tf["4h"]["source"] = "yahoo finance (agregasi 1 jam->4 jam)"
            tf["4h"]["quality"] = "exact"

    hasil["timeframes"] = tf
    hasil["indicator_settings"] = ("EMA 13/21/33/50/100/200 (cross 13x21), RSI 14 (Wilder), "
                                   "Stoch 5-3-3, BB+MidBand EMA 20 (mult 2 & 1), ATR 14 + "
                                   "trailing 3x, SuperTrend 10x3, Pivot standar, Fibonacci")
    print(json.dumps(hasil, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

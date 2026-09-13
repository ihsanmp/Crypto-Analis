"""Uji ekspektansi setup "Deviation" (deviasi.py) pada OHLC ASLI banyak koin.

KENAPA BERKAS INI ADA. Pengujian gaya #Kalimasada sebelumnya hanya bisa mengukur peluang
menang tanpa stop maupun target, pada BTC saja. Setup deviation punya stop dan target
eksplisit, jadi yang diukur di sini EKSPEKTANSI dalam R, dan pada altcoin yang memang
diperdagangkan mentornya.

SUMBER: data.binance.vision — arsip publik candle Binance, OHLC asli, gratis. Sumber yang
dipakai bot di tempat lain (CoinGecko) cuma close-only di harian, dan sapuan di bawah zona
adalah sapuan SUMBU: tanpa high/low asli ia tidak pernah terlihat.

PEMBANDING YANG MENENTUKAN. Setup ini punya geometri yang menguntungkan dengan sendirinya
(target lebih jauh dari stop). Jadi ia dibandingkan dengan ENTRI TANPA PEMICU yang memakai
GEOMETRI YANG SAMA: range yang sama, zona yang disentuh minimal dua kali, stop di bawah low
lima candle terakhir, target di swing high range, R:R minimal 1. Kalau keduanya sama, yang
menghasilkan uang adalah bentuk R:R-nya, bukan deviasinya.

BATAS YANG WAJIB DISEBUT:
  - Chart mentor adalah contoh yang berhasil. Yang gagal tidak diposting. Justru karena itu
    pengujian ini ada.
  - Spot Binance, bukan perpetual: funding tidak dihitung.
  - Semua koin bergerak bersama pasar, jadi transaksi di tanggal yang sama tidak independen.
  - OI (panel CoinGlass di chart TAO) tidak ada di arsip candle — konfirmasi itu belum diuji.

Pemakaian:
    python cloud/uji_deviasi.py                    # harian + H4 + H1, 20 koin
    python cloud/uji_deviasi.py --tf 1d --koin NEAR,TAO
"""

import argparse
import concurrent.futures
import csv
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import date, datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
import deviasi as dv  # noqa: E402

KOIN_BAWAAN = ("BTC ETH SOL NEAR TAO LINK AVAX DOT ATOM INJ FET ARB OP SUI ZEC CFX ZRO "
               "MEME DOGE ADA").split()
RENTANG = {"1d": ((2020, 1), (2026, 8)), "4h": ((2022, 1), (2026, 8)),
           "1h": ((2024, 9), (2026, 8))}
LABEL_TF = {"1d": "daily", "4h": "H4", "1h": "H1"}


def _bulan(awal, akhir):
    th, bl = awal
    while (th, bl) <= akhir:
        yield th, bl
        bl += 1
        if bl > 12:
            th, bl = th + 1, 1


def _unduh_bulan(simbol, tf, th, bl, cache):
    nama = f"{simbol}USDT-{tf}-{th}-{bl:02d}"
    jalur = os.path.join(cache, nama + ".zip")
    if not os.path.exists(jalur):
        url = (f"https://data.binance.vision/data/spot/monthly/klines/{simbol}USDT/{tf}/"
               f"{nama}.zip")
        p = subprocess.run(["curl", "-s", "-f", "--max-time", "60", "-o", jalur, url],
                           capture_output=True, timeout=90)
        if p.returncode != 0:
            try:
                os.remove(jalur)
            except OSError:
                pass
            return []
    try:
        with zipfile.ZipFile(jalur) as z:
            teks = z.read(z.namelist()[0]).decode()
    except Exception:
        return []
    keluar = []
    for r in csv.reader(io.StringIO(teks)):
        if not r or not r[0].isdigit():
            continue                     # baris judul (sebagian arsip memuatnya)
        ts = int(r[0])
        if ts > 10 ** 14:                # sejak 2025 arsip spot memakai mikrodetik
            ts //= 1000
        keluar.append([ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
    return keluar


def muat(simbol, tf, cache):
    awal, akhir = RENTANG[tf]
    semua = []
    for th, bl in _bulan(awal, akhir):
        semua.extend(_unduh_bulan(simbol, tf, th, bl, cache))
    semua.sort(key=lambda c: c[0])
    # Buang duplikat stempel waktu di sambungan antar-bulan.
    bersih, lalu = [], None
    for c in semua:
        if c[0] != lalu:
            bersih.append(c)
            lalu = c[0]
    return bersih


def sma(nilai, n):
    keluar, jumlah = [None] * len(nilai), 0.0
    for i, v in enumerate(nilai):
        jumlah += v
        if i >= n:
            jumlah -= nilai[i - n]
        if i >= n - 1:
            keluar[i] = jumlah / n
    return keluar


def pembanding(candles, a, i):
    """Entri TANPA pemicu dengan geometri yang sama. None kalau geometrinya tak sah."""
    if i < dv.PANJANG_RANGE + dv.JENDELA_DEVIASI or a[i] is None or a[i] <= 0:
        return None
    awal, akhir = i - dv.PANJANG_RANGE - dv.JENDELA_DEVIASI + 1, i - dv.JENDELA_DEVIASI + 1
    rng = candles[awal:akhir]
    support = min(c[3] for c in rng)
    if sum(1 for c in rng if c[3] <= support + dv.TOLERANSI_SENTUH_ATR * a[i]) < dv.SENTUH_MIN:
        return None
    masuk = candles[i][4]
    stop = min(c[3] for c in candles[i - dv.JENDELA_DEVIASI + 1:i + 1]) \
        - dv.PENYANGGA_STOP_ATR * a[i]
    target = max(c[2] for c in rng)
    if not (stop < masuk < target) or (target - masuk) / (masuk - stop) < dv.RR_MIN:
        return None
    return {"indeks": i, "masuk": masuk, "stop": stop, "target": target}


def uji_koin(simbol, tf, cache):
    candles = muat(simbol, tf, cache)
    if len(candles) < 300:
        return {"simbol": simbol, "tf": tf, "n_candle": len(candles), "transaksi": [],
                "pembanding": []}
    prep = dv.siapkan(candles)
    a = prep["atr"]
    close = [c[4] for c in candles]
    s200 = sma(close, 200)
    ck = {}
    transaksi, i, bebas_sejak = [], 0, 0
    while i < len(candles):
        if i >= bebas_sejak:
            s = dv.cek_candle(candles, i, prep)
            if s:
                r, alasan, keluar = dv.hasil_perdagangan(candles, s)
                if r is not None:
                    kf = dv.konfirmasi(candles, i, ck)
                    transaksi.append({
                        "tanggal": datetime.fromtimestamp(candles[i][0] / 1000,
                                                          tz=timezone.utc).date().isoformat(),
                        "r": r, "alasan": alasan, "rr": s["rr"],
                        "rezim": (None if s200[i] is None
                                  else ("naik" if close[i] > s200[i] else "turun")),
                        **kf})
                    # Satu posisi per koin: setup baru tidak diambil selagi posisi terbuka.
                    bebas_sejak = keluar + 1
        i += 1
    # Pembanding: tiap candle ketiga yang geometrinya sah tapi BUKAN pemicu deviasi.
    pemicu = {t["tanggal"] for t in transaksi}
    banding = []
    for i in range(dv.PANJANG_RANGE + dv.JENDELA_DEVIASI, len(candles), 3):
        if dv.cek_candle(candles, i, prep):
            continue
        b = pembanding(candles, a, i)
        if not b:
            continue
        r, alasan, _ = dv.hasil_perdagangan(candles, b)
        if r is None or alasan == "belum_selesai":
            continue
        banding.append({"r": r, "rezim": (None if s200[i] is None
                                          else ("naik" if close[i] > s200[i] else "turun"))})
    del pemicu
    return {"simbol": simbol, "tf": tf, "n_candle": len(candles), "transaksi": transaksi,
            "pembanding": banding}


def ringkas(rs):
    if not rs:
        return {"n": 0}
    n = len(rs)
    rata = sum(rs) / n
    sd = math.sqrt(sum((x - rata) ** 2 for x in rs) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "menang_persen": round(sum(1 for x in rs if x > 0) / n * 100, 1),
            "ekspektansi_r": round(rata, 3), "se_r": round(sd / math.sqrt(n), 3),
            "median_r": round(sorted(rs)[n // 2], 3)}


def laporan(hasil_koin, tf):
    tr = [t for h in hasil_koin for t in h["transaksi"]]
    bd = [b for h in hasil_koin for b in h["pembanding"]]
    lap = {"timeframe": LABEL_TF[tf], "koin": len([h for h in hasil_koin if h["n_candle"]]),
           "setup_deviation": ringkas([t["r"] for t in tr]),
           "pembanding_geometri_sama": ringkas([b["r"] for b in bd])}
    for rz in ("naik", "turun"):
        lap[f"rezim_{rz}"] = {
            "setup": ringkas([t["r"] for t in tr if t["rezim"] == rz]),
            "pembanding": ringkas([b["r"] for b in bd if b["rezim"] == rz])}
    for k in ("rebut_ema", "stoch_rsi_dari_oversold", "volume_di_atas_median"):
        lap[f"dengan_{k}"] = ringkas([t["r"] for t in tr if t[k]])
        lap[f"tanpa_{k}"] = ringkas([t["r"] for t in tr if not t[k]])
    per_koin = {}
    for h in hasil_koin:
        rs = [t["r"] for t in h["transaksi"]]
        if len(rs) >= 5:
            per_koin[h["simbol"]] = round(sum(rs) / len(rs), 3)
    lap["ekspektansi_per_koin_n5"] = per_koin
    per_tahun = {}
    for t in tr:
        per_tahun.setdefault(t["tanggal"][:4], []).append(t["r"])
    lap["per_tahun"] = {th: ringkas(rs) for th, rs in sorted(per_tahun.items())}
    return lap


def main():
    ap = argparse.ArgumentParser(description="Uji ekspektansi setup deviation")
    ap.add_argument("--tf", default="1d,4h,1h")
    ap.add_argument("--koin", default=",".join(KOIN_BAWAAN))
    ap.add_argument("--cache", default=os.path.join(tempfile.gettempdir(), "klines_binance"))
    args = ap.parse_args()
    os.makedirs(args.cache, exist_ok=True)
    koin = [k.strip().upper() for k in args.koin.split(",") if k.strip()]
    keluar = {"parameter": {k: getattr(dv, k) for k in (
        "PANJANG_RANGE", "JENDELA_DEVIASI", "SENTUH_MIN", "TOLERANSI_SENTUH_ATR",
        "KEDALAMAN_DEVIASI_ATR", "PENYANGGA_STOP_ATR", "RR_MIN", "TAHAN_MAKS",
        "BIAYA_PERSEN")}, "hasil": []}
    for tf in [t.strip() for t in args.tf.split(",")]:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            hasil = list(ex.map(lambda s: uji_koin(s, tf, args.cache), koin))
        keluar["hasil"].append(laporan(hasil, tf))
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

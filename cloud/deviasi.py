"""Setup "Deviation" gaya #Kalimasada — dideteksi KODE, dengan aturan yang bisa diuji.

Dari 10 chart mentor user (TAO, NEAR, CHIP, DXY; 13 Sep 2026). Bentuknya berulang:

  1. RANGE: harga bolak-balik di atas satu zona support yang disentuh berkali-kali.
  2. DEVIASI: harga menembus ke BAWAH zona itu — menyapu stop & likuiditas di bawahnya
     (NEAR Agustus, TAO 2-3 Sep berbentuk mangkuk, DXY Juni).
  3. REBUT KEMBALI: harga close lagi di ATAS zona. Itu titik masuknya.
  4. STOP di bawah low deviasi (kotak merah DXY di 87,110).
  5. TARGET di swing high / likuiditas di atas range (NEAR 2,562 lalu 3,085; DXY 92,379
     dan 93,120; CHIP 0,04421).
  Konfirmasi yang terlihat di chartnya: harga merebut EMA 13/21 lagi, Stoch RSI berbalik
  dari oversold (TAO), dan OI + volume ikut naik (panel CoinGlass TAO).

KENAPA BENTUK INI PENTING. Pengujian gaya ini sebelumnya (gaya_kalimasada.md) hanya bisa
mengukur PELUANG MENANG tanpa stop maupun target, dan dokumen itu sendiri mencatat itulah
celah terbesarnya. Setup deviation punya stop dan target yang eksplisit, jadi yang bisa
diukur sekarang adalah EKSPEKTANSI dalam R — satuan yang menentukan untung-rugi.

SATU ATURAN UNTUK DUA PEMAKAIAN. deteksi() di sini dipakai analisa langsung DAN
uji_deviasi.py. Kalau dipisah, yang dipakai bot pelan-pelan menyimpang dari yang teruji
tanpa ada yang tahu.

PARAMETER DITETAPKAN SEBELUM MELIHAT HASIL. Mengubahnya sesudah melihat backtest lalu
melaporkan hasil terbaik adalah cara paling mudah membuat sinyal apa pun terlihat bagus.

Pemakaian:
    python cloud/deviasi.py NEAR              # daily + H4
    python cloud/deviasi.py TAO --tf 4h --json
"""

import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Parameter a priori (lihat docstring) ---------------------------------------------
PANJANG_RANGE = 40        # candle yang membentuk range sebelum deviasi
JENDELA_DEVIASI = 5       # hanya untuk pembanding & konfirmasi
DEVIASI_MAKS = 30         # deviasi boleh berlangsung sampai N candle (NEAR: ~3 minggu)
SENTUH_MIN = 2            # zona support harus disentuh minimal sekian kali
TOLERANSI_SENTUH_ATR = 0.5
KEDALAMAN_DEVIASI_ATR = 0.25   # sapuan di bawah zona harus berarti, bukan selisih satu tick
PENYANGGA_STOP_ATR = 0.1
RR_MIN = 1.0              # target lebih dekat dari stop tidak akan diambil mentor
TAHAN_MAKS = 60           # candle; lebih dari ini posisi ditutup di harga close
BIAYA_PERSEN = 0.10       # pulang-pergi


def atr(candles, n=14):
    """ATR Wilder. candles: [ts, o, h, l, c, v]. Return list sepanjang candles (None awal)."""
    keluar = [None] * len(candles)
    tr = []
    for i, c in enumerate(candles):
        h, l = c[2], c[3]
        if i == 0:
            tr.append(h - l)
        else:
            pc = candles[i - 1][4]
            tr.append(max(h - l, abs(h - pc), abs(l - pc)))
        if i == n - 1:
            keluar[i] = sum(tr) / n
        elif i >= n:
            keluar[i] = (keluar[i - 1] * (n - 1) + tr[i]) / n
    return keluar


def ema(nilai, n):
    k = 2 / (n + 1)
    keluar, e = [], None
    for v in nilai:
        e = v if e is None else v * k + e * (1 - k)
        keluar.append(e)
    return keluar


def stoch_rsi_k(close, n_rsi=14, n_st=14, halus=3):
    """%K Stochastic RSI (0-100). None di awal."""
    rsi = [None] * len(close)
    naik = turun = 0.0
    for i in range(1, len(close)):
        d = close[i] - close[i - 1]
        u, t = max(d, 0), max(-d, 0)
        if i <= n_rsi:
            naik += u / n_rsi
            turun += t / n_rsi
            if i < n_rsi:
                continue
        else:
            naik = (naik * (n_rsi - 1) + u) / n_rsi
            turun = (turun * (n_rsi - 1) + t) / n_rsi
        rsi[i] = 100.0 if turun == 0 else 100 - 100 / (1 + naik / turun)
    mentah = [None] * len(close)
    for i in range(len(close)):
        jendela = [r for r in rsi[max(0, i - n_st + 1):i + 1] if r is not None]
        if len(jendela) == n_st:
            lo, hi = min(jendela), max(jendela)
            mentah[i] = 50.0 if hi == lo else (rsi[i] - lo) / (hi - lo) * 100
    k = [None] * len(close)
    for i in range(len(close)):
        j = [m for m in mentah[max(0, i - halus + 1):i + 1] if m is not None]
        if len(j) == halus:
            k[i] = sum(j) / halus
    return k


def siapkan(candles):
    """Hitung sekali untuk banyak candle: ATR dan min/max bergulir range. Mengulang minimum
    di atas irisan untuk tiap panjang deviasi pada ribuan candle H1 membuat backtest
    berjalan berjam-jam; nilainya sendiri identik."""
    n, L = len(candles), PANJANG_RANGE
    lo = [None] * n
    hi = [None] * n
    for e in range(L - 1, n):
        jendela = candles[e - L + 1:e + 1]
        lo[e] = min(c[3] for c in jendela)
        hi[e] = max(c[2] for c in jendela)
    return {"atr": atr(candles), "min_low": lo, "max_high": hi}


def cek_candle(candles, i, prep=None):
    """Setup deviation yang TERPICU di candle i (close-nya). Return dict atau None.

    Hanya memakai data sampai candle i — tidak melihat ke depan.

    ZONA DIAMBIL DARI RANGE SEBELUM DEVIASI DIMULAI, dan deviasinya boleh berlangsung sampai
    DEVIASI_MAKS candle. Versi pertama hanya mengenali sapuan dalam 5 candle terakhir.
    Divalidasi pada chart mentor sendiri, itu gagal: NEAR harian memakai zona 1,839 (lantai
    range Juni-Juli) dengan deviasi ~3 minggu sepanjang Agustus, sedangkan versi 5-candle
    menangkap lantai kecil 1,571 di DALAM mangkuk Agustus — setup yang berbeda sama sekali.
    Disesuaikan SEBELUM satu pun angka backtest dilihat, supaya yang diuji memang setup
    mentornya, bukan setup yang kebetulan menguntungkan.
    """
    if i >= len(candles) or i < PANJANG_RANGE + 2:
        return None
    prep = prep or siapkan(candles)
    a = prep["atr"][i]
    if a is None or a <= 0:
        return None
    toleransi = TOLERANSI_SENTUH_ATR * a
    close_i = candles[i][4]
    maks_close = float("-inf")
    min_low = candles[i][3]
    for m in range(0, DEVIASI_MAKS + 1):
        if m >= 1:
            k = i - m
            maks_close = max(maks_close, candles[k][4])
            min_low = min(min_low, candles[k][3])
        ujung_range = i - m - 1
        if ujung_range - PANJANG_RANGE + 1 < 0 or prep["min_low"][ujung_range] is None:
            break
        support = prep["min_low"][ujung_range]
        batas_zona = support + toleransi
        # Selama deviasi harga TIDAK close di atas zona; begitu ada, deviasinya tidak bisa
        # dimundurkan lebih jauh dengan zona ini.
        if m >= 1 and maks_close > batas_zona:
            continue
        if close_i <= batas_zona:
            continue                                  # belum direbut kembali
        if min_low >= support - KEDALAMAN_DEVIASI_ATR * a:
            continue                                  # tidak ada sapuan yang berarti
        awal = ujung_range - PANJANG_RANGE + 1
        rng = candles[awal:ujung_range + 1]
        sentuhan = sum(1 for c in rng if c[3] <= batas_zona)
        if sentuhan < SENTUH_MIN:
            continue
        stop = min_low - PENYANGGA_STOP_ATR * a
        target = prep["max_high"][ujung_range]
        if not (stop < close_i < target):
            continue
        rr = (target - close_i) / (close_i - stop)
        if rr < RR_MIN:
            continue
        return {"indeks": i, "support": support, "low_deviasi": min_low, "masuk": close_i,
                "stop": stop, "target": target, "rr": rr, "sentuhan": sentuhan,
                "lama_deviasi": m}
    return None


def konfirmasi(candles, i, cache=None):
    """Konfirmasi yang terlihat di chart mentor, dihitung terpisah supaya bisa diuji
    sendiri-sendiri: apakah masing-masing MENAMBAH ekspektansi, bukan sekadar terlihat."""
    cache = cache if cache is not None else {}
    close = [c[4] for c in candles]
    if "e13" not in cache:
        cache["e13"], cache["e21"] = ema(close, 13), ema(close, 21)
        cache["srsi"] = stoch_rsi_k(close)
        cache["vol"] = [c[5] for c in candles]
    e13, e21, s = cache["e13"], cache["e21"], cache["srsi"]
    lalu = [v for v in s[max(0, i - JENDELA_DEVIASI):i + 1] if v is not None]
    vol = cache["vol"][max(0, i - 20):i]
    return {
        "rebut_ema": close[i] > e13[i] and close[i] > e21[i],
        "stoch_rsi_dari_oversold": bool(lalu) and min(lalu) < 20 and s[i] is not None
        and s[i] > min(lalu),
        "volume_di_atas_median": bool(vol) and candles[i][5] > sorted(vol)[len(vol) // 2],
    }


def hasil_perdagangan(candles, sinyal, biaya_persen=BIAYA_PERSEN):
    """Jalankan satu setup ke depan. Return (R, alasan, candle_keluar).

    Stop dan target di candle yang SAMA dianggap kena stop. Dari OHLC tidak bisa diketahui
    mana yang tersentuh duluan, dan menganggap target duluan adalah cara paling sunyi untuk
    membuat backtest terlihat lebih bagus daripada kenyataan.
    """
    i, masuk, stop, target = (sinyal["indeks"], sinyal["masuk"], sinyal["stop"],
                              sinyal["target"])
    risiko = masuk - stop
    biaya_r = masuk * biaya_persen / 100 / risiko
    for j in range(i + 1, min(i + 1 + TAHAN_MAKS, len(candles))):
        h, l = candles[j][2], candles[j][3]
        if l <= stop:
            return -1.0 - biaya_r, "stop", j
        if h >= target:
            return (target - masuk) / risiko - biaya_r, "target", j
    j = min(i + TAHAN_MAKS, len(candles) - 1)
    if j <= i:
        return None, "belum_selesai", i
    return (candles[j][4] - masuk) / risiko - biaya_r, "waktu_habis", j


def ambil_candles(simbol, tf):
    """OHLC NATIVE lewat indicators.fetch_base. Close-only DITOLAK: deviasi adalah sapuan
    SUMBU di bawah zona, dan tanpa high/low asli sapuan itu tidak pernah terlihat."""
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    import indicators as ind
    c, sumber, kualitas, err = ind.fetch_base(simbol.upper(), ind.resolve_cg_id(simbol), tf)
    if err or not c:
        return None, sumber, f"candle tidak tersedia: {err}"
    if kualitas != "native":
        return None, sumber, ("sumbernya close-only — sapuan di bawah zona tidak terlihat "
                              "tanpa high/low asli, jadi setup deviation TIDAK bisa dinilai")
    return c, sumber, None


def analisa(simbol, tf="1d"):
    candles, sumber, err = ambil_candles(simbol, tf)
    label_tf = {"1d": "daily", "4h": "H4"}.get(tf, tf)
    if err:
        return {"simbol": simbol.upper(), "timeframe": label_tf, "tidak_tersedia": err}
    prep = siapkan(candles)
    i = len(candles) - 1
    terpicu = None
    # Setup yang terpicu dalam beberapa candle terakhir masih relevan, asal belum kena
    # stop maupun target.
    for k in range(i, max(i - JENDELA_DEVIASI, 0), -1):
        s = cek_candle(candles, k, prep)
        if not s:
            continue
        r, alasan, _ = hasil_perdagangan(candles[:i + 1], s)
        if alasan in ("stop", "target"):
            continue
        terpicu = s
        terpicu["candle_lalu"] = i - k
        terpicu["konfirmasi"] = konfirmasi(candles, k)
        break
    keluar = {"simbol": simbol.upper(), "timeframe": label_tf, "sumber": sumber,
              "harga_terakhir": candles[-1][4]}
    if terpicu:
        keluar["setup_aktif"] = {
            "zona_support": round(terpicu["support"], 8),
            "low_deviasi": round(terpicu["low_deviasi"], 8),
            "masuk_referensi": round(terpicu["masuk"], 8),
            "invalidasi_stop": round(terpicu["stop"], 8),
            "target_swing_high": round(terpicu["target"], 8),
            "rr": round(terpicu["rr"], 2),
            "terpicu_candle_lalu": terpicu["candle_lalu"],
            "konfirmasi": terpicu["konfirmasi"],
        }
    else:
        keluar["setup_aktif"] = None
    keluar["wajib_dibaca"] = WAJIB_DIBACA
    return keluar


# Hasil uji ekspektansi (uji_deviasi.py, 20 koin, OHLC asli Binance, biaya 0,1% pp).
# Angkanya ditaruh DI SINI, satu tempat, dan ikut ke mana pun data ini dipakai. Menaruhnya
# hanya di dokumen berarti ia cuma sampai kalau blok dokumennya kebetulan ikut termuat.
HASIL_UJI = {
    "daily": {"n": 516, "menang_persen": 33.3, "ekspektansi_r": 0.150, "se_r": 0.083,
              "pembanding_r": 0.014, "vonis": "lemah positif, BELUM meyakinkan"},
    "H4": {"n": 2884, "menang_persen": 30.7, "ekspektansi_r": -0.006, "se_r": 0.031,
           "pembanding_r": -0.118, "vonis": "impas setelah biaya"},
    "H1": {"n": 5968, "menang_persen": 29.2, "ekspektansi_r": -0.112, "se_r": 0.021,
           "pembanding_r": -0.131, "vonis": "RUGI — 19 dari 20 koin negatif, tiap tahun negatif"},
}

WAJIB_DIBACA = (
    "Setup deviation dideteksi KODE dengan aturan tetap (zona dari range 40 candle SEBELUM "
    "deviasi, deviasi sampai 30 candle dengan sapuan >= 0,25 ATR di bawah zona yang "
    "disentuh minimal 2x, close kembali di atas zona, stop di bawah low deviasi, target di "
    "swing high range). Kalau setup_aktif null, JANGAN menggambar setup deviation sendiri "
    "dari chart. "
    "SUDAH DIUJI pada 20 koin dengan OHLC asli, biaya 0,1% pulang-pergi: "
    "daily n=516 menang 33,3% ekspektansi +0,150R (galat baku 0,083; pembanding entri tanpa "
    "pemicu +0,014R) — lemah positif tapi BELUM meyakinkan, dan 2022 & 2025 negatif. "
    "H4 n=2884 menang 30,7% ekspektansi -0,006R — impas setelah biaya. "
    "H1 RUGI: n=5968 ekspektansi -0,112R (tanpa biaya pun -0,062R), 19 dari 20 koin "
    "negatif, tiap tahun negatif — JANGAN menyarankan setup ini di H1. "
    "Menang 1 dari 3: dua dari tiga setup kena stop, itu normal dan sudah termasuk di angka "
    "di atas. Chart yang dibagikan mentor adalah contoh yang BERHASIL; yang gagal tidak "
    "diposting, jadi chart-chart itu tidak bisa dipakai menilai seberapa sering setup ini "
    "jalan. Rinciannya di cloud/data/gaya_kalimasada.md.")


def main():
    ap = argparse.ArgumentParser(description="Deteksi setup deviation gaya #Kalimasada")
    ap.add_argument("simbol")
    ap.add_argument("--tf", default="1d,4h",
                    help="satu atau beberapa: 1d,4h (dipisah koma)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    # Beberapa timeframe dalam SATU keluaran: catatan wajib-bacanya cukup sekali. Dua
    # panggilan terpisah membayar paragraf yang sama dua kali di setiap prompt crypto.
    per_tf = []
    for tf in [t.strip() for t in args.tf.split(",") if t.strip()]:
        if tf not in ("1d", "4h"):
            continue
        h = analisa(args.simbol, tf)
        h.pop("wajib_dibaca", None)
        per_tf.append(h)
    hasil = {"setup": "deviation #Kalimasada", "per_timeframe": per_tf,
             "wajib_dibaca": WAJIB_DIBACA}
    print(json.dumps(hasil, indent=None if args.json else 2, ensure_ascii=False))
    return 0 if any(not h.get("tidak_tersedia") for h in per_tf) else 1


if __name__ == "__main__":
    sys.exit(main())

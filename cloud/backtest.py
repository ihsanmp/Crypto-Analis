"""Uji balik (backtest) sinyal terhadap RIWAYAT aset itu sendiri.

Tujuannya menjawab satu pertanyaan yang biasanya tidak pernah ditanyakan:
"sinyal ini kalau dipakai di masa lalu pada aset ini, hasilnya bagaimana?"

Dua jenis uji:

1. TEKNIKAL — tiap kemunculan sinyal di masa lalu dilacak N candle ke depan, lalu diukur:
   berapa kali berakhir untung, rata-rata & median hasilnya, dan seberapa dalam harga
   sempat turun lebih dulu (MAE — nyeri maksimum sebelum untung). Angka terakhir ini
   penting: sinyal dengan win-rate bagus tapi MAE dalam tetap sulit ditahan.

2. MAKRO (untuk emas/forex) — membandingkan besar pergerakan pada HARI RILIS TERJADWAL
   (Jumat pertama = NFP, tgl 10-15 = jendela CPI, Kamis = Unemployment Claims) terhadap
   hari biasa. Tidak memerlukan data konsensus: yang diukur BESAR gerakannya, bukan arahnya.

BATASAN YANG WAJIB DISAMPAIKAN — ini bukan bukti, hanya konteks:
  - Riwayat terbatas (ratusan candle). Jumlah kejadian sering kecil; di bawah 10 kejadian
    angkanya TIDAK bermakna secara statistik dan ditandai sebagai sampel kecil.
  - Biaya pulang-pergi per kelas aset SUDAH dikurangi (BIAYA_PULANG_PERGI); pajak belum.
  - Keunggulan dibandingkan dengan 'masuk kapan saja' dan diuji per paruh waktu: sinyal
    hanya divonis BERTAHAN bila unggul (setelah biaya) di kedua paruh.
  - Masa lalu BUKAN jaminan masa depan. Rezim pasar berubah.
  - Hanya menguji sinyal tunggal, bukan keseluruhan metodologi berskor.

Pemakaian:
    python cloud/backtest.py BTC                  # crypto
    python cloud/backtest.py NVDA --pasar         # saham/forex/komoditas (lewat market.py)
    python cloud/backtest.py GOLD --pasar --makro # sekaligus uji hari rilis
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from statistics import median

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from indicators import ema, rsi_wilder  # noqa: E402


def ambil_candle(simbol, pasar, tf="1d"):
    """Pinjam penarik data yang sudah ada supaya sumbernya persis sama dengan analisa.

    `tf` penting, bukan kenyamanan. Untuk crypto, candle HARIAN dari CoinGecko tidak punya
    high/low sungguhan sama sekali (open=high=low=close di 366/366 candle, mutu
    'approx_close_only'), sementara candle 4 JAM justru 'native' dengan high/low asli
    180/180. Sinyal yang menuntut sentuhan level — pullback ke EMA21, misalnya — hanya bisa
    diukur apa adanya di 4h. Tukarannya: 4h cuma menyimpan ~30 hari riwayat.
    """
    if pasar:
        from market import tarik
        KOM = {"GOLD": "GC=F", "EMAS": "GC=F", "XAUUSD": "GC=F", "SILVER": "SI=F",
               "PERAK": "SI=F", "XAGUSD": "SI=F", "OIL": "CL=F", "WTI": "CL=F",
               "MINYAK": "CL=F", "CRUDE": "CL=F", "USOIL": "CL=F"}
        s = KOM.get(simbol, simbol)
        c, _, err = tarik(s, "2y", tf)
        return c, s, err
    from indicators import fetch_base, resolve_cg_id
    c, sumber, _, err = fetch_base(simbol, resolve_cg_id(simbol), tf)
    if tf == "1d" and c and not err:
        panjang = _yahoo_panjang(simbol, c[-1][4])
        if panjang and len(panjang) > len(c):
            return panjang, f"{simbol} (Yahoo {simbol}-USD, riwayat panjang)", None
    return c, simbol, err


# Riwayat harian sumber analisa (CoinGecko) cuma ~1 tahun dan TANPA high/low asli: BTC 350
# candle -> tiap sinyal 3-22 kejadian, terlalu sedikit untuk uji paruh waktu (16 Okt 2026).
# Yahoo <SIMBOL>-USD punya OHLC asli bertahun-tahun (BTC sejak 2014). Ticker Yahoo bisa
# milik koin LAIN dengan simbol sama, jadi dipakai HANYA bila harga terakhirnya cocok
# dengan sumber analisa (selisih <= 3%); selain itu kembali ke riwayat pendek.
COCOK_HARGA = 0.03


def _yahoo_panjang(simbol, harga_acuan):
    import time
    import urllib.request
    try:
        import makro
        url = (makro.YAHOO + f"{simbol}-USD?period1=0&period2={int(time.time())}&interval=1d")
        req = urllib.request.Request(url, headers=makro.UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode())["chart"]["result"][0]
        q = d["indicators"]["quote"][0]
        c = [[t * 1000, o, h, lo, cl, v or 0] for t, o, h, lo, cl, v in
             zip(d["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"])
             if None not in (o, h, lo, cl)]
    except Exception:
        return None
    if not c or not harga_acuan or abs(c[-1][4] / harga_acuan - 1) > COCOK_HARGA:
        return None
    return c


def ringkas(hasil_depan):
    """Ubah daftar hasil forward-return jadi ringkasan yang jujur."""
    if not hasil_depan:
        return None
    untung = [h for h in hasil_depan if h["return_persen"] > 0]
    n = len(hasil_depan)
    r = {
        "kejadian": n,
        "menang_persen": round(len(untung) / n * 100, 1),
        "return_rata2_persen": round(sum(h["return_persen"] for h in hasil_depan) / n, 2),
        "return_median_persen": round(median(h["return_persen"] for h in hasil_depan), 2),
        "nyeri_maks_rata2_persen": round(sum(h["mae_persen"] for h in hasil_depan) / n, 2),
        "terbaik_persen": round(max(h["return_persen"] for h in hasil_depan), 2),
        "terburuk_persen": round(min(h["return_persen"] for h in hasil_depan), 2),
    }
    # Win-rate sendirian menyesatkan (lihat peran Portfolio Manager): sistem 40% menang
    # dengan R:R 3:1 unggul atas 70% menang dengan R:R 1:2. Karena itu profit factor dan
    # expectancy disediakan langsung supaya tidak dihitung manual oleh model.
    rugi = [h for h in hasil_depan if h["return_persen"] <= 0]
    tot_u = sum(h["return_persen"] for h in untung)
    tot_r = abs(sum(h["return_persen"] for h in rugi))
    r["profit_factor"] = round(tot_u / tot_r, 2) if tot_r else None
    r["expectancy_persen"] = r["return_rata2_persen"]
    r["rata2_untung_persen"] = round(tot_u / len(untung), 2) if untung else None
    r["rata2_rugi_persen"] = round(-tot_r / len(rugi), 2) if rugi else None
    if r["rata2_rugi_persen"] and r["rata2_untung_persen"]:
        r["rasio_untung_rugi"] = round(
            abs(r["rata2_untung_persen"] / r["rata2_rugi_persen"]), 2)
    if n < 10:
        r["peringatan"] = (f"SAMPEL KECIL ({n} kejadian) — angka ini TIDAK bermakna secara "
                           "statistik. Sebut sebagai catatan, jangan sebagai bukti.")
    return r


# Biaya PULANG-PERGI (beli + jual) dalam persen: komisi taker kedua sisi + spread/slippage.
# Asumsi konservatif untuk spot ritel, ditulis terang supaya bisa ditimpa (--biaya):
#   kripto besar 0,10% x2 + slippage 0,05% x2 = 0,30% ; kripto kecil spread lebih lebar 0,60%
#   saham AS 0,10% ; forex/komoditas (spread) 0,05%.
BIAYA_PULANG_PERGI = {"kripto_besar": 0.30, "kripto_kecil": 0.60, "saham": 0.10,
                      "forex_komoditas": 0.05}
KRIPTO_BESAR = {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "TRX", "AVAX", "LINK",
                "DOT", "LTC", "BCH", "TON", "SUI"}
# Sinyal yang dibaca sebagai HINDARI/KURANGI (bot spot-only): keunggulannya adalah bila
# return SESUDAHNYA lebih buruk dari acak. Membaca death cross sebagai "beli" dan menilainya
# kalah adalah salah arah.
ARAH_SINYAL = {"golden_cross_13x21": "beli", "pullback_ke_ema21_saat_uptrend": "beli",
               "pullback_ke_ema21_PROKSI_CLOSE": "beli", "rsi_turun_bawah_30": "beli",
               "death_cross_13x21": "hindari", "rsi_naik_atas_70": "hindari"}
KEJADIAN_MINIMUM_PARUH = 10


MATA_UANG = {"USD", "EUR", "JPY", "GBP", "AUD", "NZD", "CAD", "CHF", "XAU", "XAG", "SGD",
             "HKD", "CNH", "CNY", "IDR", "MXN", "ZAR", "TRY", "SEK", "NOK"}


def biaya_untuk(simbol, pasar):
    """simbol = yang DIPAKAI (GC=F, USDJPY), bukan masukan mentah (GOLD/EMAS).
    Versi pertama mengenali forex hanya dari akhiran USD -> USDJPY/GBPJPY tergolong saham."""
    if pasar:
        s = (simbol or "").upper()
        forex = (len(s) == 6 and s.isalpha() and s[:3] in MATA_UANG and s[3:] in MATA_UANG)
        return BIAYA_PULANG_PERGI["forex_komoditas" if "=" in s or forex else "saham"]
    return BIAYA_PULANG_PERGI["kripto_besar" if simbol in KRIPTO_BESAR else "kripto_kecil"]


def return_acak(candles, n_depan):
    """Return n_depan candle dari SETIAP candle — pembanding 'masuk kapan saja'."""
    c = [x[4] for x in candles]
    return [(c[i + n_depan] - c[i]) / c[i] * 100 for i in range(len(c) - n_depan) if c[i]]


def nilai_oos(kejadian, acak_per_tanggal, arah, biaya):
    """Keunggulan bersih vs acak, di keseluruhan dan per PARUH WAKTU (awal/akhir).

    Pembanding = rata-rata return 'masuk kapan saja' di SELURUH hari paruh yang sama (versi
    pertama membandingkan dengan return di tanggal sinyal itu sendiri — selalu nol).
    Paruh dibagi menurut WAKTU (tengah rentang tanggal), walk-forward paling sederhana yang
    jujur: sinyal yang hanya bekerja di satu rezim tidak layak disebut keunggulan."""
    if not kejadian or not acak_per_tanggal:
        return None
    tanda = 1 if arah == "beli" else -1
    tanggal = sorted(acak_per_tanggal)
    tengah = tanggal[len(tanggal) // 2]

    def kel(ev, hari):
        if not ev:
            return None
        rata = sum(e["return_persen"] for e in ev) / len(ev)
        dasar = [acak_per_tanggal[t] for t in hari]
        return {"n": len(ev), "keunggulan": round(tanda * (rata - sum(dasar) / len(dasar)), 2)}

    awal = kel([e for e in kejadian if e["tanggal"] < tengah],
               [t for t in tanggal if t < tengah])
    akhir = kel([e for e in kejadian if e["tanggal"] >= tengah],
                [t for t in tanggal if t >= tengah])
    total = kel(kejadian, tanggal)
    bersih = [e["return_persen"] - biaya for e in kejadian]
    keluar = {
        "arah": arah,
        "expectancy_bersih_persen": round(sum(bersih) / len(bersih), 2),
        "menang_bersih_persen": round(sum(1 for b in bersih if b > 0) / len(bersih) * 100, 1),
        "keunggulan_vs_acak_persen": total["keunggulan"],
        "paruh_awal_akhir": [awal and awal["keunggulan"], akhir and akhir["keunggulan"]],
        "paruh_dibelah": tengah,
    }
    if awal and akhir and min(awal["n"], akhir["n"]) >= KEJADIAN_MINIMUM_PARUH:
        # 'beli': keunggulan harus melampaui BIAYA di kedua paruh — unggul 0,1% pada sinyal
        # yang membayar 0,3% per transaksi adalah kerugian. 'hindari': menghindar tidak
        # membayar biaya tambahan, cukup positif di kedua paruh.
        ambang = biaya if arah == "beli" else 0.0
        bertahan = awal["keunggulan"] > ambang and akhir["keunggulan"] > ambang
        keluar["vonis"] = ("BERTAHAN (unggul di kedua paruh setelah biaya)" if bertahan
                           else "TIDAK BERTAHAN — jangan dipakai sebagai alasan")
    else:
        keluar["vonis"] = (f"SAMPEL KECIL (< {KEJADIAN_MINIMUM_PARUH} kejadian per paruh) — "
                           "hanya catatan")
    return keluar


def uji_sinyal(candles, pemicu, n_depan=20):
    """Untuk tiap indeks yang memenuhi `pemicu`, ukur hasil n_depan candle berikutnya."""
    c = [x[4] for x in candles]
    l = [x[3] for x in candles]
    keluar = []
    for i in pemicu:
        if i + n_depan >= len(c):
            continue
        masuk = c[i]
        if not masuk:
            continue
        jendela_l = l[i + 1:i + 1 + n_depan]
        akhir = c[i + n_depan]
        mae = (min(jendela_l) - masuk) / masuk * 100 if jendela_l else 0.0
        keluar.append({
            "tanggal": datetime.fromtimestamp(candles[i][0] / 1000, tz=timezone.utc)
                                .strftime("%Y-%m-%d"),
            "return_persen": round((akhir - masuk) / masuk * 100, 2),
            "mae_persen": round(mae, 2),
        })
    return keluar


def cari_pemicu(candles):
    """Tentukan indeks kemunculan tiap jenis sinyal sepanjang riwayat."""
    c = [x[4] for x in candles]
    e13, e21 = ema(c, 13), ema(c, 21)
    r = rsi_wilder(c, 14)
    off13, off21, offr = len(c) - len(e13), len(c) - len(e21), len(c) - len(r)

    def E13(i):
        j = i - off13
        return e13[j] if 0 <= j < len(e13) else None

    def E21(i):
        j = i - off21
        return e21[j] if 0 <= j < len(e21) else None

    def R(i):
        j = i - offr
        return r[j] if 0 <= j < len(r) else None

    l = [x[3] for x in candles]
    # DATA CRYPTO DARI COINGECKO TIDAK PUNYA HIGH/LOW SUNGGUHAN: open=high=low=close di
    # SELURUH candle (diverifikasi 366/366 pada ZEC, NEAR, dan BTC; indicators.py menandai
    # mutunya 'approx_close_only'). Akibatnya syarat sentuhan `low <= EMA21 < close`
    # MUSTAHIL terpenuhi — pullback dilaporkan "0 kejadian" seolah memang tidak pernah
    # terjadi, padahal ia tidak pernah bisa DIUKUR. Nol yang berarti "tidak terukur" jauh
    # lebih menyesatkan daripada nol yang berarti "tidak ada".
    # MAYORITAS, bukan all(): satu candle nyasar yang kebetulan punya rentang sudah
    # cukup untuk melempar seluruh deret ke jalur "high/low asli", dan di situ sinyalnya
    # kembali nol diam-diam — bug yang sama persis, cuma lebih sulit terlihat.
    datar = sum(1 for x in candles
                if abs(x[3] - x[4]) < 1e-12 and abs(x[2] - x[4]) < 1e-12)
    tanpa_rentang = bool(candles) and datar >= len(candles) * 0.9
    gc, dc, os_, ob, pullback = [], [], [], [], []
    for i in range(1, len(c)):
        a13, a21, b13, b21 = E13(i), E21(i), E13(i - 1), E21(i - 1)
        if None not in (a13, a21, b13, b21):
            # Filter anti-whipsaw = KONFIRMASI SETELAH cross, bukan syarat saat cross.
            # Di titik persilangan EMA13 == EMA21 sehingga selisihnya ~0 — menuntut >0,5%
            # tepat di candle itu membuat SEMUA cross tertolak (terbukti: 9 cross BTC,
            # selisih 0,01-0,23%, lolos 0). Jadi: deteksi cross, lalu cari candle pertama
            # dalam 5 candle berikutnya yang selisihnya sudah melebar >0,5% dengan arah
            # yang sama. Itulah saat sinyal benar-benar layak ditindaklanjuti.
            def konfirmasi(mulai, naik):
                for k in range(mulai, min(mulai + 6, len(c))):
                    k13, k21 = E13(k), E21(k)
                    if None in (k13, k21):
                        continue
                    if abs(k13 - k21) / c[k] > 0.005 and ((k13 > k21) == naik):
                        return k
                return None

            if b13 <= b21 and a13 > a21:
                k = konfirmasi(i, True)
                if k is not None:
                    gc.append(k)
            if b13 >= b21 and a13 < a21:
                k = konfirmasi(i, False)
                if k is not None:
                    dc.append(k)
            # Pullback: dalam tren naik (EMA13 di atas EMA21), harga menyentuh EMA21
            # lalu ditutup kembali di atasnya — pola "beli di diskon" yang lazim dipakai.
            if a13 > a21:
                if tanpa_rentang:
                    # Tanpa low sungguhan, "menyentuh" diganti "mendekat": close turun ke
                    # dalam 1,5% di atas EMA21 padahal candle sebelumnya lebih jauh.
                    # PROKSI, dan dinamai proksi supaya tidak dikira hasil yang sama.
                    dekat = 0 <= (c[i] - a21) / a21 <= 0.015
                    jauh = b21 and (c[i - 1] - b21) / b21 > 0.015
                    if dekat and jauh:
                        pullback.append(i)
                elif l[i] <= a21 < c[i]:
                    pullback.append(i)
        rv, rp = R(i), R(i - 1)
        if None not in (rv, rp):
            if rp >= 30 > rv:
                os_.append(i)
            if rp <= 70 < rv:
                ob.append(i)

    nama_pullback = ("pullback_ke_ema21_PROKSI_CLOSE" if tanpa_rentang
                     else "pullback_ke_ema21_saat_uptrend")
    return {"golden_cross_13x21": gc, "death_cross_13x21": dc,
            "rsi_turun_bawah_30": os_, "rsi_naik_atas_70": ob,
            nama_pullback: pullback}



def metrik_risiko(candles, setahun):
    """Metrik risiko dari riwayat harga aset itu sendiri — bahan peran Risk Manager.

    Dihitung dari distribusi return HARIAN yang sebenarnya terjadi, bukan dari asumsi
    distribusi normal. Itu penting: return pasar punya fat tails, sehingga VaR bergaya
    Monte-Carlo-normal hampir selalu terlalu optimistis soal ekor kirinya.

    setahun: 365 untuk crypto (dagang tiap hari), 252 untuk saham/forex (hari bursa).
    """
    tutup = [x[4] for x in candles if x[4]]   # indeks 4 = harga penutupan (sama dengan uji_sinyal)
    if len(tutup) < 30:
        return {"tidak_tersedia": f"butuh minimal 30 candle, tersedia {len(tutup)}"}

    ret = [(tutup[i] - tutup[i - 1]) / tutup[i - 1] for i in range(1, len(tutup))]
    n = len(ret)
    rata = sum(ret) / n
    var_ = sum((x - rata) ** 2 for x in ret) / n
    sd = var_ ** 0.5

    turun = [x for x in ret if x < 0]
    sd_turun = ((sum(x * x for x in turun) / len(turun)) ** 0.5) if turun else 0.0

    # Penurunan terdalam dari puncak (peak-to-trough) sepanjang rentang data.
    puncak, dd_maks = tutup[0], 0.0
    for h in tutup:
        puncak = max(puncak, h)
        dd_maks = min(dd_maks, (h - puncak) / puncak)

    akar = setahun ** 0.5
    total = tutup[-1] / tutup[0] - 1
    tahunan = (1 + total) ** (setahun / n) - 1 if n else 0.0

    urut = sorted(ret)
    i5 = max(0, int(0.05 * len(urut)) - 1)
    var95 = urut[i5]
    ekor = urut[:i5 + 1]
    cvar95 = sum(ekor) / len(ekor) if ekor else var95

    m = {
        "rentang_candle": n + 1,
        "hari_setahun_dipakai": setahun,
        "return_total_persen": round(total * 100, 2),
        "return_tahunan_persen": round(tahunan * 100, 2),
        "volatilitas_tahunan_persen": round(sd * akar * 100, 2),
        "drawdown_maks_persen": round(dd_maks * 100, 2),
        "pemulihan_dibutuhkan_persen": (round((1 / (1 + dd_maks) - 1) * 100, 1)
                                        if dd_maks > -1 else None),
        "sharpe": round(rata / sd * akar, 2) if sd else None,
        "sortino": round(rata / sd_turun * akar, 2) if sd_turun else None,
        "calmar": round(tahunan / abs(dd_maks), 2) if dd_maks else None,
        "var95_harian_persen": round(var95 * 100, 2),
        "cvar95_harian_persen": round(cvar95 * 100, 2),
    }
    m["arti_singkat"] = (
        "drawdown_maks = penurunan terdalam dari puncak yang PERNAH terjadi di rentang ini; "
        "pemulihan_dibutuhkan = kenaikan yang diperlukan untuk balik modal dari situ. "
        "var95 = kerugian harian yang hanya dilampaui 1 dari 20 hari; cvar95 = RATA-RATA "
        "kerugian pada hari-hari terburuk itu — selalu lebih dalam dari var95, dan itulah "
        "angka yang jujur. Sortino lebih relevan dari Sharpe untuk spot karena hanya "
        "menghukum gejolak TURUN. Calmar rendah = returnnya ada tapi jalannya menyakitkan."
    )
    if n < 120:
        m["peringatan"] = (f"rentang hanya {n + 1} candle — metrik risiko dari sampel "
                           "sependek ini belum stabil, perlakukan sebagai indikasi kasar.")
    return m


def uji_makro(candles):
    """Bandingkan BESAR gerakan harian pada hari rilis terjadwal vs hari biasa.

    Tidak butuh data konsensus — yang diukur besar gerakannya, bukan arahnya. Jadwal
    mengikuti cloud/data/gold_drivers.md: NFP Jumat pertama, jendela CPI tgl 10-15,
    Unemployment Claims tiap Kamis.
    """
    kelompok = {"NFP (Jumat pertama)": [], "jendela CPI (tgl 10-15)": [],
                "Kamis (Unemployment Claims)": [], "hari biasa": []}
    for ts, o, h, l, c, v in candles:
        if not o:
            continue
        d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        rentang = (h - l) / o * 100
        if d.weekday() == 4 and d.day <= 7:
            kelompok["NFP (Jumat pertama)"].append(rentang)
        elif 10 <= d.day <= 15:
            kelompok["jendela CPI (tgl 10-15)"].append(rentang)
        elif d.weekday() == 3:
            kelompok["Kamis (Unemployment Claims)"].append(rentang)
        else:
            kelompok["hari biasa"].append(rentang)

    dasar = kelompok["hari biasa"]
    rata_dasar = sum(dasar) / len(dasar) if dasar else None
    keluar = {}
    for nama, v in kelompok.items():
        if not v:
            continue
        rata = sum(v) / len(v)
        item = {"hari": len(v), "rentang_harian_rata2_persen": round(rata, 2)}
        if rata_dasar and nama != "hari biasa":
            item["dibanding_hari_biasa"] = f"{round(rata / rata_dasar, 2)}x"
        if len(v) < 10:
            item["peringatan"] = "sampel kecil"
        keluar[nama] = item
    keluar["cara_baca"] = ("Yang diukur BESAR gerakan (high-low), bukan arahnya. Rasio >1,3x "
                           "berarti hari itu memang lebih bergejolak — perlakukan sebagai "
                           "peringatan risiko, bukan sinyal arah.")
    return keluar


# Field yang isinya PANDUAN STATIS, bukan angka. Dibuang saat --ringkas karena ikut
# ditempel ke DATA BRIEF lalu dikirim ULANG ke model penganalisa — dibayar dua kali.
# Peringatan AKTIF (sampel kecil, tidak tersedia, close-only) SENGAJA tidak termasuk:
# itu pengaman mutu, bukan hiasan.
_PANDUAN_STATIS = ("acuan", "cara_pakai", "arti", "cara_baca", "acuan_penilaian",
                   # arti_singkat menjelaskan VaR/CVaR/Sortino/Calmar — penjelasan yang sama
                   # sudah ada di seed peran risk.md, jadi tidak perlu dibayar dua kali.
                   "arti_singkat")


def buang_panduan(obj):
    """Buang panduan statis secara rekursif. Peringatan aktif tetap dipertahankan."""
    if isinstance(obj, dict):
        return {k: buang_panduan(v) for k, v in obj.items() if k not in _PANDUAN_STATIS}
    if isinstance(obj, list):
        return [buang_panduan(v) for v in obj]
    return obj


# Notasi yang dipakai user: H1/H4 untuk jam, "daily"/"weekly" dieja penuh.
_NAMA_TF = {"1d": "daily", "4h": "H4", "1h": "H1", "1w": "weekly"}
_JAM_TF = {"1d": 24, "4h": 4}


def _setara(tf, n):
    """Horizon dalam satuan manusia. "20 candle" berarti hal yang sangat berbeda di 4h."""
    jam = _JAM_TF.get(tf, 24) * n
    return f"{jam / 24:.1f} hari" if jam >= 24 else f"{jam} jam"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("simbol")
    ap.add_argument("--pasar", action="store_true", help="saham/forex/komoditas (via market.py)")
    ap.add_argument("--makro", action="store_true", help="uji juga hari rilis terjadwal")
    ap.add_argument("--depan", type=int, default=20, help="berapa candle ke depan diukur")
    ap.add_argument("--tf", default="1d", choices=["4h", "1d"],
                    help="timeframe candle. 4h punya high/low asli (crypto), 1d tidak")
    ap.add_argument("--ringkas", action="store_true",
                    help="buang panduan statis (hemat token saat dipakai bot)")
    ap.add_argument("--biaya", type=float, default=None,
                    help="biaya pulang-pergi %% (bawaan per kelas aset)")
    args = ap.parse_args()
    simbol = args.simbol.upper().replace("$", "")

    hasil = {
        "simbol": simbol,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        # Label ini SEBELUMNYA dipatok "timeframe harian" apa pun --tf-nya. Dengan
        # --tf 4h, horizon 20 candle berarti 3,3 hari — bukan 20 hari — dan model
        # membaca label itu apa adanya lalu salah menafsirkan seluruh angkanya.
        "jenis": ("uji balik sinyal terhadap riwayat aset ini sendiri (timeframe "
                  + _NAMA_TF.get(args.tf, args.tf) + ")"),
        "timeframe": args.tf,
        "horizon_candle": args.depan,
        "horizon_setara": _setara(args.tf, args.depan),
        "peringatan": [
            "BUKAN bukti, hanya konteks. Masa lalu tidak menjamin masa depan.",
            "SUDAH dikurangi biaya pulang-pergi (lihat biaya_pulang_pergi_persen); "
            "belum termasuk pajak.",
            "Kejadian di bawah 10 kali TIDAK bermakna secara statistik.",
            "Menguji sinyal TUNGGAL, bukan keseluruhan metodologi berskor.",
        ],
    }

    candles, dipakai, err = ambil_candle(simbol, args.pasar, args.tf)
    if err or not candles:
        hasil["error"] = f"Gagal mengambil riwayat harga: {err or 'kosong'}"
        print(json.dumps(buang_panduan(hasil) if args.ringkas else hasil, indent=2, ensure_ascii=False))
        return

    hasil["simbol_dipakai"] = dipakai
    hasil["candle_dipakai"] = len(candles)
    hasil["periode"] = {
        "dari": datetime.fromtimestamp(candles[0][0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
        "sampai": datetime.fromtimestamp(candles[-1][0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
    }

    # TOLOK UKUR — tanpa ini angka sinyal gampang disalahtafsirkan. Kalau sepanjang periode
    # asetnya turun 40%, sinyal yang rugi 6% sebenarnya JAUH lebih baik daripada diam
    # memegang. Sebaliknya di pasar naik kencang, sinyal untung 5% justru kalah dari diam.
    c_awal, c_akhir = candles[0][4], candles[-1][4]
    tutup = [x[4] for x in candles]
    langkah = [(tutup[i] - tutup[i - 1]) / tutup[i - 1] * 100
               for i in range(1, len(tutup)) if tutup[i - 1]]
    acak = sum(1 for g in langkah if g > 0) / len(langkah) * 100 if langkah else None
    hasil["tolok_ukur"] = {
        "beli_dan_tahan_persen": round((c_akhir - c_awal) / c_awal * 100, 2) if c_awal else None,
        "hari_naik_persen": round(acak, 1) if acak else None,
        "cara_baca": ("Bandingkan menang_persen tiap sinyal dengan 'hari_naik_persen' (peluang "
                      "dasar harga naik). Sinyal yang menang_persen-nya TIDAK jauh di atas "
                      "angka itu berarti tidak memberi keunggulan nyata. Dan nilai hasil "
                      "sinyal terhadap 'beli_dan_tahan': di pasar turun, rugi kecil bisa "
                      "berarti unggul; di pasar naik kencang, untung kecil bisa berarti kalah."),
    }

    hasil["metrik_risiko"] = metrik_risiko(candles, 252 if args.pasar else 365)

    biaya = (args.biaya if args.biaya is not None
             else biaya_untuk(dipakai if args.pasar else simbol, args.pasar))
    hasil["biaya_pulang_pergi_persen"] = biaya
    acak = return_acak(candles, args.depan)
    acak_per_tanggal = {
        datetime.fromtimestamp(candles[i][0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"): r
        for i, r in enumerate(acak)}
    hasil["tolok_ukur"]["return_acak_rata2_persen"] = (
        round(sum(acak) / len(acak), 2) if acak else None)
    pemicu = cari_pemicu(candles)
    uji = {}
    for nama, idx in pemicu.items():
        kejadian = uji_sinyal(candles, idx, args.depan)
        r = ringkas(kejadian)
        if not r:
            uji[nama] = {"kejadian": 0, "catatan": "tidak pernah terjadi di rentang ini"}
            continue
        r.update(nilai_oos(kejadian, acak_per_tanggal, ARAH_SINYAL.get(nama, "beli"), biaya))
        if args.ringkas:
            # Brief: yang menentukan keputusan saja. Rincian kotor tetap ada tanpa --ringkas.
            r = {k: r[k] for k in ("kejadian", "arah", "menang_bersih_persen",
                                   "expectancy_bersih_persen", "keunggulan_vs_acak_persen",
                                   "paruh_awal_akhir", "nyeri_maks_rata2_persen", "vonis")
                 if k in r}
        uji[nama] = r
    hasil["uji_teknikal"] = uji
    hasil["cara_baca_vonis"] = (
        "Pakai sinyal sebagai alasan HANYA bila vonisnya BERTAHAN. keunggulan_vs_acak = "
        "selisih return sesudah sinyal dengan return masuk kapan saja (untuk 'hindari': "
        "positif = sesudahnya memang lebih buruk). Semua sudah setelah biaya. Lima sinyal "
        "diuji sekaligus, jadi satu BERTAHAN bisa kebetulan — lebih kuat bila sinyal yang "
        "sama juga bertahan di aset lain. Uji 16 Okt 2026 (BTC/ETH/SOL): RSI>70 sebagai "
        "'hindari' TERBALIK di ketiganya — sesudahnya return justru lebih tinggi (momentum).")

    if args.makro:
        hasil["uji_makro"] = uji_makro(candles)

    hasil["cara_pakai"] = [
        "menang_persen tinggi + nyeri_maks kecil = sinyal itu historisnya nyaman ditahan.",
        "menang_persen tinggi tapi nyeri_maks DALAM = sering benar, tapi berat dijalani — "
        "perkecil ukuran posisi atau tunggu konfirmasi tambahan.",
        "Kalau menang_persen di bawah 50%, sinyal itu TIDAK unggul di aset ini — katakan "
        "apa adanya, jangan dipoles.",
        "Selalu sebut jumlah kejadian saat mengutip angka ini.",
    ]
    print(json.dumps(buang_panduan(hasil) if args.ringkas else hasil, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

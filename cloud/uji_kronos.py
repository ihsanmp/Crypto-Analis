"""Uji Kronos (model fondasi candlestick) vs metode bot sekarang — DIDAFTARKAN SEBELUM DIJALANKAN
(8 Nov 2026). Kriteria di bawah tidak boleh diubah sesudah hasil akurasi terlihat.

Kronos (github.com/shiyu-coder/Kronos, MIT, AAAI 2026): tokenizer K-line + Transformer
autoregresif, pra-latih 12 miliar candle dari 45 bursa termasuk crypto Binance. Paper:
data pra-latih s/d Juni 2024, uji mereka mulai Juli 2024.

KEBOCORAN DATA = jebakan utama. Menguji di periode yang sudah dilihat saat pra-latih hanya
mengukur hafalan. Maka:
  PERIODE UTAMA (penentu vonis): titik asal 1 Sep 2025 s/d 31 Okt 2026 — sesudah bobot
                                 dirilis publik (Agu 2025), pasti tidak terlihat.
  PERIODE KEDUA (dilaporkan saja): 1 Jul 2024 s/d 31 Agu 2025.

MODEL      : Kronos-small (24,7 jt parameter) + Kronos-Tokenizer-base, kode di commit
             67b630e67f6a18c9e9be918d9b4337c960db1e9a. T = 0,6, top_p = 0,9 (setelan paper
             untuk ramalan harga). 20 jalur independen per titik asal (predict_batch dengan
             deret yang sama diulang; predict() biasa merata-ratakan sampel sehingga sebaran
             hilang). Kuantil = kuantil empiris 20 jalur.
DATA       : Binance spot BTCUSDT, ETHUSDT, SOLUSDT (data.binance.vision), OHLCV + quote volume.
TITIK ASAL : 00:00 UTC, tiap LANGKAH hari (LANGKAH ditetapkan dari uji WAKTU saja, sebelum
             akurasi apa pun dihitung — lihat --probe).
SETELAN (3 perbandingan, tiap aset):
  H24 : konteks 512 candle 1 jam -> close 24 jam ke depan   vs EWMA 0,94 harian x 1 hari
  D1  : konteks 512 candle harian -> close 1 hari ke depan  vs EWMA 0,94 harian x 1 hari
  D7  : konteks 512 candle harian -> close 7 hari ke depan  vs sigma 90 hari x akar(7)
  Pembanding = persis metode prediksi_harga di proyeksi.py (jalan acak, tanpa arah,
  kuantil lognormal z yang sama).

ADDENDUM 8 Nov 2026 — dari probe WAKTU saja (tanpa akurasi), sebelum uji dijalankan:
  Runner GitHub 4 vCPU: 197 dtk per titik asal (H24) dan 66 dtk (jalan harian). Maka:
  H24  utama: tiap 2 hari (~213 titik/aset)   · kedua: tiap 7 hari
  D1/D7 utama: tiap hari  (~426 titik/aset)   · kedua: tiap 7 hari
  Periode utama dipecah 3 segmen per aset (job paralel); kriteria tidak berubah.

UKURAN (pada log-return close)
  Kisaran : pinball rata-rata kuantil {0,10; 0,25; 0,50; 0,75; 0,90}; cakupan p10-p90.
  Arah    : IC Spearman median ramalan Kronos vs return nyata (pembanding tidak punya arah).

KRITERIA, per setelan (Bonferroni 3 setelan -> p < 0,0167)
  KISARAN lolos bila: pinball Kronos < pembanding di >= 2 dari 3 aset, DAN uji Diebold-
    Mariano satu sisi pada selisih pinball RELATIF (dinormalkan dengan pinball pembanding
    tiap aset, dirata-rata lintas aset per tanggal; HAC Newey-West, lag = max(h, aturan
    4(n/100)^(2/9))) p < 0,0167, DAN galat cakupan 80% rata-rata tidak > pembanding + 3 pp.
  ARAH lolos bila: IC > 0 di >= 2 dari 3 aset, DAN IC gabungan (rata-rata 3 aset) > 0 dengan
    p placebo circular-shift (2000x, per aset, digabung) < 0,0167.
  Lolos -> boleh diusulkan masuk bot sebagai uji maju dulu; gagal -> tidak dipakai.

    python cloud/uji_kronos.py --probe --aset BTC --jalan H24        # waktu saja
    python cloud/uji_kronos.py --aset BTC --jalan D --segmen utama:2025-09-01:2026-01-20:1
    python cloud/uji_kronos.py --gabung DIR                        # vonis dari semua JSON
"""
import argparse
import csv
import glob
import io
import json
import math
import os
import random
import statistics
import sys
import time
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ASET = ("BTC", "ETH", "SOL")
SETELAN = {"H24": ("1h", 24, 1), "D1": ("1d", 1, 1), "D7": ("1d", 7, 7)}  # tf, langkah, hari
JALAN = {"H24": ("H24",), "D": ("D1", "D7")}     # satu set jalur harian dipakai D1 & D7
WAKTU_MODEL = [0.0, 0]
KUANTIL = (0.10, 0.25, 0.50, 0.75, 0.90)
Z = {0.10: -1.2816, 0.25: -0.6745, 0.50: 0.0, 0.75: 0.6745, 0.90: 1.2816}
LOOKBACK = 512
JALUR = 20
SUHU, TOP_P = 0.6, 0.9
UTAMA = ("2025-09-01", "2026-10-31")
KEDUA = ("2024-07-01", "2025-08-31")
P_MAKS = 0.05 / 3
BENIH = 20261108
UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-kronos/1.0)"}


# ------------------------------------------------------------------ data
def _bulan(awal, akhir):
    th, bl = awal
    while (th, bl) <= akhir:
        yield th, bl
        bl += 1
        if bl > 12:
            th, bl = th + 1, 1


def muat(simbol, tf, awal, akhir, cache):
    """[[ts_ms_buka, o, h, l, c, v, quote_v]] dari arsip bulanan data.binance.vision."""
    os.makedirs(cache, exist_ok=True)
    semua = {}
    for th, bl in _bulan(awal, akhir):
        nama = f"{simbol}USDT-{tf}-{th}-{bl:02d}"
        jalur = os.path.join(cache, nama + ".zip")
        if not os.path.exists(jalur):
            url = (f"https://data.binance.vision/data/spot/monthly/klines/{simbol}USDT/{tf}/"
                   f"{nama}.zip")
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                            timeout=60) as r, open(jalur, "wb") as f:
                    f.write(r.read())
            except Exception as e:
                print(f"  lewati {nama}: {type(e).__name__}", file=sys.stderr)
                continue
        with zipfile.ZipFile(jalur) as z:
            teks = z.read(z.namelist()[0]).decode()
        for b in csv.reader(io.StringIO(teks)):
            if not b or not b[0].isdigit():
                continue
            ts = int(b[0])
            if ts > 10 ** 14:                  # sejak 2025 arsip spot memakai mikrodetik
                ts //= 1000
            semua[ts] = [ts] + [float(x) for x in b[1:6]] + [float(b[7])]
    return [semua[k] for k in sorted(semua)]


def _ts(tgl):
    return int(datetime.fromisoformat(tgl).replace(tzinfo=timezone.utc).timestamp() * 1000)


def titik_asal(dari, sampai, langkah):
    d = datetime.fromisoformat(dari)
    akhir = datetime.fromisoformat(sampai)
    while d <= akhir:
        yield d.strftime("%Y-%m-%d")
        d += timedelta(days=langkah)


# ------------------------------------------------------------------ pembanding
def sigma_pembanding(harian, i_asal, hari):
    """Persis prediksi_harga: EWMA 0,94 (1 hari) atau sigma 90 hari, dari close SEBELUM asal."""
    tutup = [c[4] for c in harian[:i_asal]]
    r = [math.log(tutup[j] / tutup[j - 1]) for j in range(1, len(tutup))]
    if hari == 1:
        v = statistics.pvariance(r[:90])
        for x in r:
            v = 0.94 * v + 0.06 * x * x
        return math.sqrt(v)
    return statistics.pstdev(r[-90:]) * math.sqrt(hari)


# ------------------------------------------------------------------ ukuran
def pinball(aktual, q_nilai):
    return sum(max(q * (aktual - v), (q - 1) * (aktual - v)) for q, v in q_nilai.items()) / len(q_nilai)


def kuantil_empiris(x, q):
    s = sorted(x)
    pos = q * (len(s) - 1)
    a = int(pos)
    b = min(a + 1, len(s) - 1)
    return s[a] + (s[b] - s[a]) * (pos - a)


def spearman(a, b):
    def peringkat(v):
        urut = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(urut):
            j = i
            while j + 1 < len(urut) and v[urut[j + 1]] == v[urut[i]]:
                j += 1
            for k in range(i, j + 1):
                r[urut[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = peringkat(a), peringkat(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    sa = math.sqrt(sum((x - ma) ** 2 for x in ra))
    sb = math.sqrt(sum((x - mb) ** 2 for x in rb))
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (sa * sb) if sa and sb else 0.0


def diebold_mariano(d, lag):
    n = len(d)
    m = sum(d) / n
    e = [x - m for x in d]
    s = sum(x * x for x in e) / n
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * sum(e[t] * e[t - k] for t in range(k, n)) / n
    if s <= 0:
        return None, None
    dm = m / math.sqrt(s / n)
    return dm, 1 - 0.5 * (1 + math.erf(dm / math.sqrt(2)))


# ------------------------------------------------------------------ Kronos
def muat_kronos():
    sumber = os.environ.get("KRONOS_SRC", "kronos_src")
    sys.path.insert(0, sumber)
    import torch
    from model import Kronos, KronosPredictor, KronosTokenizer
    torch.manual_seed(BENIH)
    tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    mdl = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    return KronosPredictor(mdl, tok, device="cpu", max_context=512)


def ramal_jalur(prediktor, konteks, tf, pred_len):
    """JALUR jalur close untuk satu titik asal -> list[list[float]] (jalur x langkah)."""
    import pandas as pd
    df = pd.DataFrame([c[1:] for c in konteks],
                      columns=["open", "high", "low", "close", "volume", "amount"])
    ts = pd.to_datetime([c[0] for c in konteks], unit="ms", utc=True).tz_localize(None)
    x_ts = pd.Series(ts)
    langkah = pd.Timedelta(hours=1) if tf == "1h" else pd.Timedelta(days=1)
    y_ts = pd.Series([ts[-1] + langkah * (k + 1) for k in range(pred_len)])
    hasil = prediktor.predict_batch(df_list=[df] * JALUR, x_timestamp_list=[x_ts] * JALUR,
                                    y_timestamp_list=[y_ts] * JALUR, pred_len=pred_len,
                                    T=SUHU, top_p=TOP_P, sample_count=1, verbose=False)
    return [list(p["close"].values) for p in hasil]


# ------------------------------------------------------------------ satu aset x setelan
def jalankan(aset, jalan, segmen, cache, batas=None):
    """-> {setelan: [baris]} untuk satu aset. jalan 'H24' atau 'D' (D1 & D7 sekaligus)."""
    tf = SETELAN[JALAN[jalan][0]][0]
    pred_len = max(SETELAN[st][1] for st in JALAN[jalan])
    harian = muat(aset, "1d", (2022, 12), (2026, 10), cache)
    deret = harian if tf == "1d" else muat(aset, "1h", (2024, 5), (2026, 11), cache)
    buka = [c[0] for c in deret]
    buka_h = [c[0] for c in harian]
    prediktor = muat_kronos()
    keluar = {st: [] for st in JALAN[jalan]}
    n = 0
    for periode, dari, sampai, langkah in segmen:
        for tgl in titik_asal(dari, sampai, langkah):
            t0 = _ts(tgl)
            i = next((k for k, b in enumerate(buka) if b >= t0), None)
            ih = next((k for k, b in enumerate(buka_h) if b >= t0), None)
            if i is None or ih is None or i < LOOKBACK or i + pred_len > len(deret):
                continue
            konteks = deret[i - LOOKBACK:i]
            if konteks[-1][0] + (3600000 if tf == "1h" else 86400000) != t0:
                continue                                    # ada lubang data sebelum asal
            awal = konteks[-1][4]
            w0 = time.time()
            jalur = ramal_jalur(prediktor, konteks, tf, pred_len)
            WAKTU_MODEL[0] += time.time() - w0
            WAKTU_MODEL[1] += 1
            for st in JALAN[jalan]:
                _, langkah_st, hari = SETELAN[st]
                nyata = math.log(deret[i + langkah_st - 1][4] / awal)
                r_k = [math.log(j[langkah_st - 1] / awal) for j in jalur if j[langkah_st - 1] > 0]
                qk = {q: kuantil_empiris(r_k, q) for q in KUANTIL}
                s = sigma_pembanding(harian, ih, hari)
                qb = {q: Z[q] * s for q in KUANTIL}
                keluar[st].append({"tgl": tgl, "periode": periode, "nyata": nyata,
                                   "pin_k": pinball(nyata, qk), "pin_b": pinball(nyata, qb),
                                   "cak_k": qk[0.10] <= nyata <= qk[0.90],
                                   "cak_b": qb[0.10] <= nyata <= qb[0.90],
                                   "median_k": qk[0.50]})
            n += 1
            if batas and n >= batas:
                return keluar
            if n % 25 == 0:
                print(f"  {aset} {jalan}: {n} titik asal", file=sys.stderr)
    return keluar


# ------------------------------------------------------------------ vonis
def placebo_ic(x, y, n, rng):
    ic = spearman(x, y)
    lebih = 0
    for _ in range(n):
        g = rng.randrange(1, len(y))
        if spearman(x, y[g:] + y[:g]) >= ic:
            lebih += 1
    return ic, (lebih + 1) / (n + 1)


def gabung(folder):
    rng = random.Random(BENIH)
    data = {}
    for f in sorted(glob.glob(os.path.join(folder, "**", "hasil_*.json"), recursive=True)):
        isi = json.load(open(f, encoding="utf-8"))
        data.setdefault((isi["aset"], isi["setelan"]), []).extend(isi["baris"])
    for k in data:                               # urut tanggal, buang duplikat antar-segmen
        unik = {(x["periode"], x["tgl"]): x for x in data[k]}
        data[k] = [unik[u] for u in sorted(unik)]
    keluar = {"didaftarkan": "2026-11-08", "setelan": {}}
    for st in SETELAN:
        hari = SETELAN[st][2]
        per = {}
        for periode in ("utama", "kedua"):
            ring = {}
            for a in ASET:
                b = [x for x in data.get((a, st), []) if x["periode"] == periode]
                if len(b) < 20:
                    continue
                pk = statistics.fmean(x["pin_k"] for x in b)
                pb = statistics.fmean(x["pin_b"] for x in b)
                ic, p = placebo_ic([x["median_k"] for x in b], [x["nyata"] for x in b], 2000, rng)
                ring[a] = {"n": len(b), "pinball_kronos": round(pk, 6), "pinball_bot": round(pb, 6),
                           "pinball_relatif": round(pk / pb, 3),
                           "cakupan80_kronos": round(100 * statistics.fmean(x["cak_k"] for x in b), 1),
                           "cakupan80_bot": round(100 * statistics.fmean(x["cak_b"] for x in b), 1),
                           "ic_arah": round(ic, 3), "p_ic": round(p, 4)}
            if not ring:
                continue
            # Selisih relatif per tanggal, dirata-rata lintas aset yang punya tanggal itu.
            per_tgl = {}
            for a in ring:
                skala = ring[a]["pinball_bot"]
                for x in data[(a, st)]:
                    if x["periode"] == periode:
                        per_tgl.setdefault(x["tgl"], []).append((x["pin_b"] - x["pin_k"]) / skala)
            d = [statistics.fmean(v) for _, v in sorted(per_tgl.items())]
            langkah = max(1, round((datetime.fromisoformat(sorted(per_tgl)[1])
                                    - datetime.fromisoformat(sorted(per_tgl)[0])).days))
            lag = max(math.ceil(hari / langkah), math.floor(4 * (len(d) / 100) ** (2 / 9)))
            dm, p_dm = diebold_mariano(d, lag)
            ic_gab = statistics.fmean(r["ic_arah"] for r in ring.values())
            # p gabungan: Fisher atas p placebo tiap aset (uji independen per aset).
            chi = -2 * sum(math.log(r["p_ic"]) for r in ring.values())
            k = len(ring)
            p_gab = math.exp(-chi / 2) * sum((chi / 2) ** j / math.factorial(j) for j in range(k))
            menang = sum(1 for r in ring.values() if r["pinball_kronos"] < r["pinball_bot"])
            galat = lambda kunci: statistics.fmean(abs(r[kunci] - 80) for r in ring.values())
            ic_pos = sum(1 for r in ring.values() if r["ic_arah"] > 0)
            hasil = {"aset": ring, "dm": round(dm, 2) if dm is not None else None,
                     "p_dm": round(p_dm, 5) if p_dm is not None else None, "lag_hac": lag,
                     "menang_kisaran": f"{menang}/{k}",
                     "galat_cakupan80": [round(galat("cakupan80_kronos"), 1),
                                         round(galat("cakupan80_bot"), 1)],
                     "ic_gabungan": round(ic_gab, 3), "p_ic_gabungan": round(p_gab, 4),
                     "ic_positif": f"{ic_pos}/{k}"}
            if periode == "utama":
                hasil["lolos_kisaran"] = (menang >= 2 and p_dm is not None and p_dm < P_MAKS
                                          and galat("cakupan80_kronos")
                                          <= galat("cakupan80_bot") + 3)
                hasil["lolos_arah"] = ic_pos >= 2 and ic_gab > 0 and p_gab < P_MAKS
            per[periode] = hasil
        keluar["setelan"][st] = per
        u = per.get("utama", {})
        print(f"{st}: kisaran {'LOLOS' if u.get('lolos_kisaran') else 'TIDAK LOLOS'} "
              f"(menang {u.get('menang_kisaran')}, p DM {u.get('p_dm')}, galat cakupan "
              f"{u.get('galat_cakupan80')}) · arah {'LOLOS' if u.get('lolos_arah') else 'TIDAK LOLOS'}"
              f" (IC {u.get('ic_gabungan')}, p {u.get('p_ic_gabungan')})")
        for a, r in (u.get("aset") or {}).items():
            print(f"    {a}: {r}")
    return keluar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aset", default="BTC")
    ap.add_argument("--jalan", default="H24", choices=list(JALAN))
    ap.add_argument("--segmen", default=None,
                    help="periode:dari:sampai:langkah (mis. utama:2025-09-01:2026-01-20:2)")
    ap.add_argument("--cache", default="cache_binance")
    ap.add_argument("--probe", action="store_true", help="ukur WAKTU per titik asal saja")
    ap.add_argument("--gabung", default=None)
    a = ap.parse_args()
    if a.gabung:
        hasil = gabung(a.gabung)
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                               "uji_kronos.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(hasil, f, ensure_ascii=False, indent=1)
        return
    if a.probe:
        # Hanya WAKTU: tidak ada akurasi yang dicetak, supaya LANGKAH dipilih buta hasil.
        jalankan(a.aset, a.jalan, [("utama",) + UTAMA + (30,)], a.cache, batas=4)
        print(f"PROBE {a.aset} {a.jalan}: {WAKTU_MODEL[0] / max(WAKTU_MODEL[1], 1):.1f} detik "
              f"model per titik asal ({JALUR} jalur, rata-rata {WAKTU_MODEL[1]} titik)")
        return
    periode, dari, sampai, langkah = a.segmen.split(":")
    hasil = jalankan(a.aset, a.jalan, [(periode, dari, sampai, int(langkah))], a.cache)
    for st, baris in hasil.items():
        with open(f"hasil_{a.aset}_{st}_{periode}_{dari}.json", "w", encoding="utf-8") as f:
            json.dump({"aset": a.aset, "setelan": st, "segmen": a.segmen, "baris": baris}, f)
        print(f"{a.aset} {st} {a.segmen}: {len(baris)} titik", file=sys.stderr)

if __name__ == "__main__":
    main()

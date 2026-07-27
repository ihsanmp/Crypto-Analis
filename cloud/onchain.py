"""Metrik on-chain — CoinMetrics Community API. GRATIS, TANPA API key.

Alternatif CryptoQuant (yang akses API-nya butuh paket Professional ~$99/bulan).
Metrik inti yang dipakai untuk menilai valuasi on-chain tersedia gratis di sini.

METRIK & CARA BACANYA:
  - CapMVRVCur (MVRV) : nilai pasar / nilai realisasi. <1 = pasar di bawah harga modal
    rata-rata pemegang (zona akumulasi historis) · 1-2 wajar · >3 mulai panas ·
    >3,7 secara historis dekat puncak siklus.
  - NVTAdj (NVT)      : "P/E"-nya jaringan. Tinggi = harga mahal relatif aktivitas.
  - AdrActCnt         : alamat aktif harian — proxy pemakaian nyata. Tren naik bersama
    harga = sehat; harga naik sementara alamat aktif turun = rapuh.
  - CapRealUSD        : realized cap (modal riil yang masuk).
  - FeeTotUSD, TxCnt  : biaya & jumlah transaksi (permintaan blokspace).
  - SplyAct1yr        : supply yang bergerak dalam 1 tahun (sisanya = HODLer).

BATASAN (sampaikan apa adanya):
  - Tier Community tidak memuat SEMUA metrik CryptoQuant (mis. SOPR & exchange flow
    per-bursa detail). Metrik yang tidak tersedia dilaporkan kosong, TIDAK dikarang.
  - Cakupan aset paling lengkap untuk BTC & ETH; altcoin kecil sering tidak ada.

Pemakaian:  python cloud/onchain.py BTC
"""

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
BASE = "https://community-api.coinmetrics.io/v4"
TIMEOUT = 25

# Metrik yang dicoba. Yang tidak tersedia untuk aset itu akan hilang sendiri dari respons.
METRIK = ["CapMVRVCur", "NVTAdj", "AdrActCnt", "CapRealUSD", "TxCnt", "FeeTotUSD", "SplyAct1yr"]

ARTI = {
    "CapMVRVCur": "MVRV — <1 zona akumulasi historis · 1-2 wajar · >3 panas · >3,7 dekat puncak",
    "NVTAdj": "NVT — makin tinggi makin mahal relatif aktivitas jaringan",
    "AdrActCnt": "alamat aktif harian — proxy pemakaian nyata",
    "CapRealUSD": "realized cap — modal riil yang sudah masuk (USD)",
    "TxCnt": "jumlah transaksi harian",
    "FeeTotUSD": "total biaya jaringan harian (USD) — permintaan blokspace",
    "SplyAct1yr": "supply yang bergerak dalam 1 tahun (sisanya dipegang HODLer)",
}


def get(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:120]
        except Exception:
            detail = ""
        return {"__err": f"HTTP {e.code} {detail}".strip()}
    except Exception as e:
        return {"__err": f"{type(e).__name__}: {str(e)[:90]}"}


def angka(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def tren(seri):
    """Bandingkan nilai terbaru dengan ~30 hari lalu."""
    nilai = [a for a in seri if a is not None]
    if len(nilai) < 5:
        return None
    awal, akhir = nilai[0], nilai[-1]
    if not awal:
        return None
    delta = (akhir - awal) / abs(awal) * 100
    arah = "naik" if delta > 3 else "turun" if delta < -3 else "datar"
    return {"perubahan_persen": round(delta, 1), "arah": arah,
            "dari": round(awal, 4), "ke": round(akhir, 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--hari", type=int, default=35, help="rentang riwayat (default 35 hari)")
    args = ap.parse_args()
    aset = args.ticker.lower().replace("$", "")

    mulai = (datetime.now(timezone.utc) - timedelta(days=args.hari)).strftime("%Y-%m-%d")
    url = (f"{BASE}/timeseries/asset-metrics?assets={urllib.parse.quote(aset)}"
           f"&metrics={','.join(METRIK)}&frequency=1d&start_time={mulai}&page_size=10000")

    hasil = {
        "symbol": aset.upper(),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": "CoinMetrics Community API (gratis, tanpa API key)",
        "catatan": ("Tier Community tidak memuat semua metrik CryptoQuant (mis. SOPR & "
                    "exchange flow per-bursa). Yang tidak tersedia dibiarkan kosong."),
    }

    # CoinMetrics menolak SELURUH permintaan kalau ada SATU metrik yang tidak tersedia
    # untuk aset itu (mis. NVTAdj tidak ada di tier Community untuk BTC). Jadi: coba
    # sekaligus dulu (1 permintaan, cepat); kalau ditolak, ambil per metrik dan simpan
    # yang berhasil saja — lebih lambat tapi tidak kehilangan metrik yang sebenarnya ada.
    d = get(url)
    tak_didukung = []
    if "__err" in d:
        gabung = {}
        for m in METRIK:
            satu = get(f"{BASE}/timeseries/asset-metrics?assets={urllib.parse.quote(aset)}"
                       f"&metrics={m}&frequency=1d&start_time={mulai}&page_size=10000")
            if "__err" in satu:
                tak_didukung.append(m)
                continue
            for b in (satu.get("data") or []):
                gabung.setdefault(b.get("time"), {"time": b.get("time")})[m] = b.get(m)
        if not gabung:
            hasil["error"] = f"Tidak ada metrik on-chain untuk '{aset}' di tier Community."
            hasil["saran"] = ("Cakupan paling lengkap untuk BTC & ETH; banyak altcoin kecil "
                              "tidak tercakup. Untuk altcoin pakai fundamentals.py & investors.py.")
            print(json.dumps(hasil, indent=2, ensure_ascii=False))
            return
        d = {"data": [gabung[k] for k in sorted(gabung)]}

    baris = d.get("data") or []
    if not baris:
        hasil["error"] = f"Tidak ada data on-chain untuk '{aset}' di CoinMetrics Community."
        hasil["saran"] = "Coba BTC atau ETH; altcoin kecil sering tidak tercakup."
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return

    hasil["periode"] = {"dari": baris[0].get("time", "")[:10], "sampai": baris[-1].get("time", "")[:10]}
    hasil["hari_terpakai"] = len(baris)

    metrik_keluar = {}
    tidak_tersedia = []
    for m in METRIK:
        seri = [angka(b.get(m)) for b in baris]
        nilai = [x for x in seri if x is not None]
        if not nilai:
            tidak_tersedia.append(m)
            continue
        item = {"terbaru": round(nilai[-1], 6), "arti": ARTI.get(m, "")}
        t = tren(seri)
        if t:
            item["tren_30h"] = t
        metrik_keluar[m] = item

    hasil["metrik"] = metrik_keluar
    semua_kosong = sorted(set(tidak_tersedia) | set(tak_didukung))
    if semua_kosong:
        hasil["tidak_tersedia"] = semua_kosong
        hasil["kenapa_kosong"] = ("Metrik ini tidak ada di tier Community CoinMetrics untuk aset "
                                  "ini. Perlakukan sebagai TIDAK TERSEDIA — jangan dikarang.")

    # Penilaian MVRV otomatis — bagian paling sering dipakai untuk keputusan spot.
    mv = (metrik_keluar.get("CapMVRVCur") or {}).get("terbaru")
    if mv is not None:
        if mv < 1:
            zona = "DI BAWAH 1 — rata-rata pemegang sedang rugi; historisnya zona akumulasi"
        elif mv < 2:
            zona = "1-2 — wajar, belum panas"
        elif mv < 3:
            zona = "2-3 — mulai mahal, hati-hati mengejar"
        elif mv < 3.7:
            zona = "3-3,7 — panas, historisnya area distribusi bertahap"
        else:
            zona = ">3,7 — historisnya dekat puncak siklus; prioritaskan ambil profit"
        hasil["penilaian_mvrv"] = {"nilai": mv, "zona": zona,
                                   "peringatan": "Acuan historis, BUKAN jaminan. Selalu gabungkan "
                                                 "dengan teknikal & kondisi makro."}

    print(json.dumps(hasil, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

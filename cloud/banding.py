"""Perbandingan dua sampai empat aset dalam metrik yang DIJAMIN setara.

Kenapa ini script sendiri, bukan menempelkan dua brief penuh: perbandingan hanya bermakna
kalau tiap aset diukur dengan cara yang PERSIS SAMA. Menempel dua brief lengkap tidak
menjamin itu — brief crypto dan brief saham punya isi berbeda, dan bahkan dua brief crypto
bisa berbeda bagian karena daftar lewat (`_KOIN_NATIF`, `_ONCHAIN_ADA`) berbeda per koin.
Yang keluar dari situ tabel dengan sel kosong di tempat yang tidak beraturan.

Di sini tiap aset dilewatkan jalur yang sama persis, dan kolom yang tidak tersedia untuk
sebuah aset ditulis "tidak tersedia" — bukan dihilangkan diam-diam.

Ukurannya juga sengaja jauh lebih kecil daripada brief penuh: perbandingan butuh SATU baris
per metrik per aset, bukan seluruh isi indicators.py untuk masing-masing.

BATAS YANG WAJIB DISEBUT: aset dengan riwayat harga pendek (koin di luar BTC/ETH lewat
CoinGecko gratis) punya sebaran proyeksi yang tidak sebanding dengan saham beriwayat 15
tahun. Setiap baris membawa jendela riwayatnya sendiri supaya itu terlihat.

Pemakaian:
    python cloud/banding.py BTC ETH
    python cloud/banding.py NVDA AMD --pasar
    python cloud/banding.py SOL AVAX SUI --hari 60 --ringkas
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MAKS_ASET = 4


def _persen(baru, lama):
    if not baru or not lama:
        return None
    return round((baru - lama) / lama * 100, 2)


def _ambil(simbol, pasar):
    """Satu jalur untuk semua aset. Return (candles, sumber, kualitas, error)."""
    if pasar:
        from market import tarik
        KOM = {"GOLD": "GC=F", "EMAS": "GC=F", "XAUUSD": "GC=F", "SILVER": "SI=F",
               "PERAK": "SI=F", "XAGUSD": "SI=F", "OIL": "CL=F", "WTI": "CL=F"}
        s = KOM.get(simbol.upper(), simbol.upper())
        c, _, err = tarik(s, "2y", "1d")
        return c, s, "native", err
    from indicators import fetch_base, resolve_cg_id
    s = simbol.upper()
    c, sumber, kualitas, err = fetch_base(s, resolve_cg_id(s), "1d")
    return c, f"{s} ({sumber})", kualitas, err


def satu_aset(simbol, pasar, hari):
    """Metrik pembanding untuk SATU aset. Bentuknya identik untuk semua aset."""
    baris = {"aset": simbol.upper()}
    candles, sumber, kualitas, err = _ambil(simbol, pasar)
    if err or not candles or len(candles) < 30:
        baris["tidak_tersedia"] = err or "riwayat harga terlalu pendek"
        return baris

    from indicators import analyze, atr_series
    tinggi = [c[2] for c in candles]
    rendah = [c[3] for c in candles]
    tutup = [c[4] for c in candles]
    harga = tutup[-1]

    a = analyze(candles)
    atr = (atr_series(tinggi, rendah, tutup, 14) or [None])[-1]

    def tgl(c):
        return datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc).date().isoformat()

    baris.update({
        "sumber": sumber,
        "kualitas": kualitas,
        "jendela_riwayat": f"{tgl(candles[0])} s/d {tgl(candles[-1])}",
        "candle_harian": len(candles),
        "harga": round(harga, 8),
        "perubahan_7h_persen": _persen(harga, tutup[-8]) if len(tutup) > 8 else None,
        "perubahan_30h_persen": _persen(harga, tutup[-31]) if len(tutup) > 31 else None,
        "tren_ema": a.get("ema_signal"),
        "susunan_ema": a.get("ema_stack"),
        "rsi14": a.get("rsi14"),
        "struktur": a.get("structure"),
        "volatilitas_atr_persen": round(atr / harga * 100, 2) if atr and harga else None,
    })

    # Proyeksi & level dipinjam dari proyeksi.py supaya angkanya SATU definisi, bukan
    # dihitung ulang dengan cara berbeda di sini.
    try:
        from proyeksi import sebaran_gerakan, level_struktural, _persentil
        pakai_high = kualitas != "approx_close_only"
        tercapai, terdalam, tertutup = sebaran_gerakan(candles, hari, pakai_high)
        if tertutup:
            baris[f"proyeksi_{hari}h_p25_p75"] = [
                round(harga * (1 + _persentil(tertutup, 25) / 100), 8),
                round(harga * (1 + _persentil(tertutup, 75) / 100), 8)]
            baris["jendela_proyeksi_diuji"] = len(tertutup)
        atas, bawah = level_struktural(candles, harga, pakai_high)
        baris["resisten_terdekat"] = atas[0] if atas else None
        baris["support_terdekat"] = bawah[0] if bawah else None
        if atas:
            baris["jarak_ke_resisten_persen"] = _persen(atas[0], harga)
        if bawah:
            baris["jarak_ke_support_persen"] = _persen(bawah[0], harga)
    except Exception as e:
        baris["proyeksi"] = f"tidak tersedia: {type(e).__name__}"
    return baris


def banding(daftar, pasar, hari):
    aset = []
    for s in daftar[:MAKS_ASET]:
        aset.append(satu_aset(s, pasar, hari))

    hasil = {"aset": aset, "horizon_proyeksi_hari": hari}

    # Riwayat yang panjangnya jauh berbeda membuat sebaran proyeksi TIDAK sebanding.
    panjang = [b.get("candle_harian") for b in aset if b.get("candle_harian")]
    if len(panjang) >= 2 and max(panjang) > 2 * min(panjang):
        hasil["peringatan_riwayat_timpang"] = (
            f"Panjang riwayat antar-aset berbeda jauh ({min(panjang)} vs {max(panjang)} "
            "candle). Kolom proyeksi TIDAK sebanding — sebutkan ketimpangan ini, jangan "
            "membandingkan p25-p75 seolah diukur dari basis yang sama.")

    kualitas = {b.get("kualitas") for b in aset if b.get("kualitas")}
    if "approx_close_only" in kualitas and len(kualitas) > 1:
        hasil["peringatan_kualitas_campur"] = (
            "Sebagian aset memakai sumber close-only (high/low bukan angka asli) dan "
            "sebagian tidak. Volatilitas dan level strukturalnya tidak setara — sebutkan.")

    gagal = [b["aset"] for b in aset if "tidak_tersedia" in b]
    if gagal:
        hasil["gagal_diambil"] = gagal

    hasil["wajib_dibaca"] = (
        "Sajikan sebagai TABEL dengan kolom pertama berisi nama metrik dan satu kolom per "
        "aset. Isi sel yang datanya tidak ada dengan 'tidak tersedia' — JANGAN dikosongkan "
        "dan jangan diisi angka aset lain. Perbandingan hanya sah kalau tiap baris diukur "
        "dengan cara yang sama; itu sebabnya semua angka di sini datang dari satu jalur. "
        "Setelah tabel, beri kesimpulan yang menyebut PADA DIMENSI APA satu aset unggul, "
        "bukan vonis 'A lebih baik dari B' tanpa syarat.")
    return hasil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("simbol", nargs="+", help="dua sampai empat aset")
    ap.add_argument("--pasar", action="store_true", help="saham/forex/komoditas")
    ap.add_argument("--hari", type=int, default=60, help="horizon proyeksi")
    ap.add_argument("--ringkas", action="store_true", help="buang panduan statis")
    args = ap.parse_args()

    keluar = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "jumlah_aset": len(args.simbol[:MAKS_ASET]),
    }
    keluar.update(banding(args.simbol, args.pasar, args.hari))
    if args.ringkas:
        from backtest import buang_panduan
        keluar = buang_panduan(keluar)
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

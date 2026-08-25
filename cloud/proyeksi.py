"""Proyeksi target harga yang DITURUNKAN dari data, plus penguji target yang diajukan user.

Dua kebutuhan berbeda, dan yang kedua justru lebih penting:

1. "Sejauh apa harga masuk akal bergerak dalam N hari?" -> sebaran dari sejarahnya sendiri,
   bukan angka bulat yang enak didengar.
2. "Solana berpotensi naik sampai $200, betul?" -> ini HIPOTESIS yang harus DIUJI. Tanpa
   alat, model cenderung mencari level yang kebetulan dekat $200 lalu menyebutnya
   konfluensi. Dengan --target, angka itu diukur: berapa ATR jauhnya, persentil berapa dari
   gerakan historis, dan berapa sering harga benar-benar mencapainya dalam jendela sepanjang
   itu. Kalau jawabannya 4% dari kejadian, itu yang dilaporkan.

SEMUA angka di sini turunan HARGA. Itu SATU kategori sinyal, bukan konfluensi — lihat
aturan konfluensi di seed peran. Proyeksi ini tidak tahu apa-apa soal on-chain, makro, arus
dana, atau posisi, dan tidak boleh disajikan seolah tahu.

Pemakaian:
    python cloud/proyeksi.py SOL --hari 60
    python cloud/proyeksi.py SOL --hari 60 --target 200
    python cloud/proyeksi.py GOLD --pasar --hari 30 --target 4000
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PERSENTIL = (10, 25, 50, 75, 90)


def _persentil(nilai, p):
    """Persentil linier. Ditulis sendiri supaya tidak menambah ketergantungan."""
    if not nilai:
        return None
    s = sorted(nilai)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100
    bawah, atas = int(k), min(int(k) + 1, len(s) - 1)
    return s[bawah] + (s[atas] - s[bawah]) * (k - bawah)


def _rentang_tanggal(candles):
    """Rentang tanggal candle — wajib menyertai setiap klaim frekuensi historis."""
    if not candles:
        return None
    def t(c):
        return datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc).date().isoformat()
    return f"{t(candles[0])} s/d {t(candles[-1])}"


def ambil(simbol, pasar, rentang="2y"):
    """Pinjam penarik data yang dipakai analisa supaya angkanya konsisten."""
    if pasar:
        from market import tarik
        KOM = {"GOLD": "GC=F", "EMAS": "GC=F", "XAUUSD": "GC=F", "SILVER": "SI=F",
               "PERAK": "SI=F", "XAGUSD": "SI=F", "OIL": "CL=F", "WTI": "CL=F"}
        s = KOM.get(simbol.upper(), simbol.upper())
        c, _, err = tarik(s, rentang, "1d")
        return c, s, "native", err
    from indicators import fetch_base, resolve_cg_id
    s = simbol.upper()
    c, sumber, kualitas, err = fetch_base(s, resolve_cg_id(s), "1d")
    return c, f"{s} ({sumber})", kualitas, err


def sebaran_gerakan(candles, n_hari, pakai_high):
    """Sebaran gerakan N hari ke depan: yang TERCAPAI dan yang TERTUTUP.

    Dua-duanya perlu. "Tercapai" (high tertinggi dalam jendela) menjawab "apakah harganya
    pernah sampai" — itu yang relevan untuk target. "Tertutup" (close di akhir jendela)
    menjawab "apakah bertahan di sana". Target yang tercapai lalu balik lagi bukan hal sama.
    """
    tercapai, tertutup, terdalam = [], [], []
    for i in range(len(candles) - n_hari):
        acuan = candles[i][4]
        if not acuan:
            continue
        jendela = candles[i + 1:i + 1 + n_hari]
        if not jendela:
            continue
        puncak = max((c[2] if pakai_high else c[4]) for c in jendela)
        dasar = min((c[3] if pakai_high else c[4]) for c in jendela)
        akhir = jendela[-1][4]
        if not (puncak and dasar and akhir):
            continue
        tercapai.append((puncak - acuan) / acuan * 100)
        terdalam.append((dasar - acuan) / acuan * 100)
        tertutup.append((akhir - acuan) / acuan * 100)
    return tercapai, terdalam, tertutup


def level_struktural(candles, harga, pakai_high):
    """Swing high/low sebelumnya — level yang benar-benar pernah diuji pasar."""
    from indicators import pivots
    tinggi = [c[2] if pakai_high else c[4] for c in candles]
    rendah = [c[3] if pakai_high else c[4] for c in candles]
    atas = sorted({round(tinggi[i], 8) for i in pivots(tinggi, 5, "high")
                   if tinggi[i] and tinggi[i] > harga})
    bawah = sorted({round(rendah[i], 8) for i in pivots(rendah, 5, "low")
                    if rendah[i] and rendah[i] < harga}, reverse=True)
    return atas[:4], bawah[:4]


# Jarak invalidasi yang lazim dipakai, dari yang rapat sampai yang selebar swing low.
JARAK_STOP = (5, 10, 15, 20, 30)
RASIO_DIWAJIBKAN = 2.0        # analisa.md meminta minimal 1:2


def kelayakan(candles, harga, n_hari, pakai_high, rasio=RASIO_DIWAJIBKAN):
    """Untuk tiap jarak invalidasi: target apa yang DIBUTUHKAN, dan seberapa sering
    gerakan sebesar itu benar-benar terjadi.

    Kenapa ini ada. analisa.md sudah lama mewajibkan R:R minimal 1:2 dan tetap dilewati —
    delapan dari sepuluh panggilan pertama di bawah 1. Menambah kalimat lagi ke prompt
    tidak akan menolong; aturannya sudah ada.

    Yang berubah kalau tabel ini hadir: aturan R:R berhenti jadi imbauan dan jadi FAKTA
    YANG BISA DIPERIKSA. Dengan invalidasi 30% di bawah harga, target untuk R:R 2 adalah
    +60% — dan sebaran historis bisa bilang gerakan sebesar itu terjadi di berapa persen
    jendela. Kalau jawabannya 3%, setupnya memang tidak layak diambil, dan yang harus
    diperbaiki adalah invalidasinya, bukan targetnya dipaksa mendekat.

    Ini juga menutup jalan pintas yang paling menggoda: memasang target dekat supaya
    terlihat mudah tercapai. Target dekat memperkecil imbalan tanpa memperkecil risiko.
    """
    if not harga or not candles:
        return None
    baris = []
    for stop in JARAK_STOP:
        butuh = harga * (1 + stop * rasio / 100.0)
        u = uji_target(candles, harga, butuh, n_hari, None, pakai_high)
        if "tidak_tersedia" in u:
            continue
        baris.append({
            "invalidasi_persen": -stop,
            "invalidasi_harga": round(harga * (1 - stop / 100.0), 8),
            "target_dibutuhkan_persen": round(stop * rasio, 1),
            "target_dibutuhkan_harga": round(butuh, 8),
            "peluang_historis_persen": u.get("peluang_historis_persen"),
        })
    if not baris:
        return None
    layak = [b for b in baris if (b["peluang_historis_persen"] or 0) >= 25]
    return {
        "rasio_diwajibkan": rasio,
        "horizon_hari": n_hari,
        # Riwayat kripto gratis cuma ~1 tahun. "0%" di sini berarti TIDAK PERNAH DALAM
        # RENTANG INI, bukan mustahil — dan bedanya besar. Rentangnya wajib ikut supaya
        # angka nol tidak dikutip sebagai hukum alam.
        "jendela_riwayat": _rentang_tanggal(candles),
        "baris": baris,
        "stop_terlebar_yang_masih_layak_persen": (
            min(b["invalidasi_persen"] for b in layak) if layak else None),
        "wajib_dibaca": (
            "Baca dari BAWAH ke atas: makin lebar invalidasi, makin besar target yang "
            "dibutuhkan, dan makin jarang gerakan sebesar itu terjadi. Pilih jarak "
            "invalidasi yang peluang historisnya masih masuk akal, JANGAN memaksakan "
            "target mendekat supaya terlihat mudah — target dekat memperkecil imbalan "
            "tanpa memperkecil risiko, dan itulah yang membuat delapan dari sepuluh "
            "panggilan pertama bot ini punya rasio di bawah 1. Kalau tidak ada satu baris "
            "pun yang peluangnya memadai, setup ini memang TIDAK LAYAK DIAMBIL — katakan "
            "begitu, jangan diperhalus jadi target yang lebih dekat. Peluang 0% berarti "
            "TIDAK PERNAH TERJADI dalam `jendela_riwayat` yang tertulis — bukan mustahil; "
            "sebut rentangnya saat mengutipnya."),
    }


def uji_target(candles, harga, target, n_hari, atr, pakai_high):
    """Ukur target yang DIAJUKAN. Ini penawar utama terhadap penjangkaran angka user."""
    if not harga or not target or target <= 0:
        return {"tidak_tersedia": "harga atau target tidak sah"}

    jarak = (target - harga) / harga * 100
    arah = "naik" if target > harga else "turun"
    tercapai, terdalam, _ = sebaran_gerakan(candles, n_hari, pakai_high)
    relevan = tercapai if target > harga else terdalam
    if not relevan:
        return {"tidak_tersedia": f"riwayat kurang dari {n_hari} hari"}

    if target > harga:
        kena = [x for x in relevan if x >= jarak]
    else:
        kena = [x for x in relevan if x <= jarak]

    hasil = {
        "target": target,
        "harga_saat_ini": round(harga, 8),
        "arah": arah,
        "jarak_persen": round(jarak, 2),
        "horizon_hari": n_hari,
        "jarak_dalam_atr": round(abs(target - harga) / atr, 1) if atr else None,
        "peluang_historis_persen": round(len(kena) / len(relevan) * 100, 1),
        "jendela_diuji": len(relevan),
        "gerakan_terekstrem_yang_pernah_terjadi_persen": round(
            max(relevan) if target > harga else min(relevan), 1),
    }
    hasil["jendela_riwayat"] = _rentang_tanggal(candles)
    if hasil["peluang_historis_persen"] == 0:
        # "Tidak pernah" WAJIB disertai rentangnya. Data crypto gratis cuma ~1 tahun; tanpa
        # tanggalnya, kalimat ini terbaca seperti klaim sepanjang sejarah aset.
        hasil["catatan"] = (f"Dalam riwayat yang tersedia ({hasil['jendela_riwayat']}), harga "
                            f"TIDAK PERNAH bergerak sejauh itu dalam {n_hari} hari. Sebutkan "
                            f"apa adanya BESERTA rentang tanggalnya — bukan 'tidak pernah "
                            f"dalam sejarah'.")
    hasil["peringatan_metode"] = (
        "Jendela saling tumpang tindih, jadi kejadiannya TIDAK independen — peluang di atas "
        "adalah frekuensi historis kasar, bukan probabilitas. Riwayatnya juga terbatas pada "
        "rentang data yang ada, dan rezim pasar bisa berbeda.")
    return hasil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("simbol")
    ap.add_argument("--pasar", action="store_true", help="saham/forex/komoditas via market.py")
    ap.add_argument("--hari", type=int, default=30, help="horizon proyeksi (hari perdagangan)")
    ap.add_argument("--target", type=float, help="uji target harga yang diajukan")
    ap.add_argument("--ringkas", action="store_true", help="buang panduan statis")
    args = ap.parse_args()

    keluar = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "simbol": args.simbol.upper(),
        "horizon_hari": args.hari,
        "lingkup": ("SEMUA angka di sini turunan HARGA — satu kategori sinyal. Bukan "
                    "konfluensi, dan tidak memuat on-chain, makro, arus dana, atau posisi."),
    }

    candles, sumber, kualitas, err = ambil(args.simbol, args.pasar)
    if err or not candles:
        keluar["tidak_tersedia"] = err or "candle kosong"
        print(json.dumps(keluar, indent=2, ensure_ascii=False))
        return

    pakai_high = kualitas != "approx_close_only"
    keluar["sumber"] = sumber
    keluar["kualitas"] = kualitas
    keluar["candle_harian"] = len(candles)
    if not pakai_high:
        keluar["peringatan_kualitas"] = (
            "Sumbernya close-only: high/low harian bukan angka asli. Sebaran 'tercapai' "
            "dihitung dari CLOSE, sehingga cenderung MEREMEHKAN jangkauan sebenarnya. "
            "Sebutkan batas ini saat mengutip.")

    from indicators import atr_series
    tinggi = [c[2] for c in candles]
    rendah = [c[3] for c in candles]
    tutup = [c[4] for c in candles]
    harga = tutup[-1]
    atr_list = atr_series(tinggi, rendah, tutup, 14)
    atr = atr_list[-1] if atr_list else None

    keluar["harga_terkini"] = round(harga, 8)
    keluar["atr14"] = round(atr, 8) if atr else None
    keluar["atr14_persen_dari_harga"] = round(atr / harga * 100, 2) if atr and harga else None

    tercapai, terdalam, tertutup = sebaran_gerakan(candles, args.hari, pakai_high)
    if tercapai:
        def ke_harga(nilai):
            return {f"p{p}": {"persen": round(_persentil(nilai, p), 2),
                              "harga": round(harga * (1 + _persentil(nilai, p) / 100), 8)}
                    for p in PERSENTIL}
        keluar["sebaran_historis"] = {
            "jendela_diuji": len(tercapai),
            "jendela_riwayat": _rentang_tanggal(candles),
            "puncak_tercapai": ke_harga(tercapai),
            "dasar_tercapai": ke_harga(terdalam),
            "harga_penutup": ke_harga(tertutup),
            # Bukan "cara_baca" — dibuang --ringkas. Peringatan "ini BUKAN ramalan" dan
            # "frekuensi, bukan probabilitas" harus sampai ke model.
            "wajib_dibaca": (f"Sebaran gerakan {args.hari} hari sepanjang riwayat yang ada. Ini "
                          "BUKAN ramalan — ini rentang yang wajar secara historis. p90 "
                          "puncak berarti hanya 10% jendela yang mencapai lebih tinggi. "
                          "Jendela tumpang tindih, jadi ini frekuensi, bukan probabilitas."),
        }
    else:
        keluar["sebaran_historis"] = {
            "tidak_tersedia": f"riwayat kurang dari {args.hari} hari perdagangan"}

    try:
        k = kelayakan(candles, harga, args.hari, pakai_high)
        if k:
            keluar["kelayakan_imbalan_risiko"] = k
        else:
            # HILANG DIAM-DIAM adalah kegagalan tersendiri. Tabel ini tidak bisa dihitung
            # kalau riwayatnya lebih pendek daripada horizonnya — dan itu berubah-ubah
            # antar-run karena sumber OHLC dicoba berurutan sampai ada yang berhasil.
            # Tanpa baris ini, blok yang absen tak bisa dibedakan dari blok yang lupa.
            keluar["kelayakan_tidak_tersedia"] = (
                f"riwayat {len(candles)} candle tidak cukup untuk jendela {args.hari} hari "
                f"(sumber: {sumber}). Aturan R:R 1:2 tetap berlaku, tapi peluang historis "
                "targetnya TIDAK bisa diperiksa — katakan begitu, jangan menebak.")
    except Exception as e:
        keluar["kelayakan_tidak_tersedia"] = f"{type(e).__name__}: {e}"

    # KALIBRASI TERUKUR, bukan asumsi. Diuji walk-forward di uji_sebaran.py atas BTC, ETH,
    # dan SOL (1.068 titik asal, horizon 60): interval p10-p90 dari metode ini secara
    # historis memuat hasil sebenarnya hanya ~72-80% kali, bukan 80% sebagaimana namanya
    # menyiratkan — dan sisi BAWAH yang paling sering meleset. Menyebut "p10" tanpa
    # menyebut ini membuat pembacanya mengira risikonya sudah terhitung penuh.
    keluar["kalibrasi_terukur"] = {
        "cakupan_p10_p90_sebenarnya_persen": "72-80 (puncak) · 72-74 (dasar)",
        "target_nominal_persen": 80,
        "diuji_pada": "BTC/ETH/SOL, 1.068 titik asal, horizon 60 hari",
        # BUKAN "arti" — kata itu ada di _PANDUAN_STATIS dan dibuang --ringkas, padahal
        # justru kalimat inilah aturan kerasnya.
        "wajib_dibaca": ("Interval ini lebih SEMPIT daripada kenyataan, terutama di sisi bawah. "
                 "Perlakukan p10 dasar sebagai batas yang masih bisa ditembus lebih sering "
                 "daripada 1 dari 10 kali. JANGAN menyajikannya sebagai batas risiko yang "
                 "sudah terhitung penuh."),
    }

    atas, bawah = level_struktural(candles, harga, pakai_high)
    keluar["level_struktural"] = {
        "resisten_di_atas": atas, "support_di_bawah": bawah,
        "cara_pakai": ("Level ini pernah DIUJI pasar, jadi lebih bermakna daripada angka "
                       "bulat. Target di atas resisten terdekat harus melewatinya dulu — "
                       "sebutkan urutannya, jangan melompat langsung ke target."),
    }

    try:
        from indicators import fib_from_swing
        keluar["fib_ekstensi"] = fib_from_swing(tinggi, rendah, tutup)
    except Exception as e:
        keluar["fib_ekstensi"] = {"tidak_tersedia": f"{type(e).__name__}"}

    if args.target is not None:
        keluar["uji_target"] = uji_target(candles, harga, args.target, args.hari, atr, pakai_high)

    if args.ringkas:
        from backtest import buang_panduan
        keluar = buang_panduan(keluar)
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Arus dana ETF spot — kategori sinyal INSTITUSIONAL yang belum dipunyai sumber lain.

Kenapa ini penting untuk analisa crypto di repo ini: seluruh sumber yang ada bersifat
teknikal (indicators.py), on-chain (onchain.py), atau sentimen (sentiment.py). Aturan
konfluensi di seed peran menuntut sinyal dari KATEGORI BERBEDA, dan arus dana adalah
kategori yang selama ini kosong. Satu koin dengan struktur harga bagus TAPI arus ETF keluar
beruntun menceritakan hal yang sama sekali berbeda dari yang chart-nya saja tunjukkan.

Angka mentah tidak dipakai langsung. Arus $98 juta terdengar besar, tapi tanpa tahu itu
persentil berapa dari riwayatnya sendiri, angkanya tidak bisa dinilai. Karena itu yang
dilaporkan adalah posisi relatif terhadap sejarahnya, beserta jendela yang dipakai.

Yang paling bernilai justru DIVERGENSI: harga naik sementara arus keluar adalah tanda
distribusi, dan itu tidak terlihat dari chart maupun on-chain.

BATAS YANG WAJIB DISEBUT: data ETF tertinggal beberapa hari dari harga (hanya hari bursa,
plus jeda pelaporan). Umur datanya selalu dicetak — sebutkan saat mengutip, jangan
diperlakukan seolah real-time.

Pemakaian:
    python cloud/etf.py BTC
    python cloud/etf.py ETH --ringkas
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Hanya dua aset yang punya ETF spot AS. Koin lain TIDAK punya, dan itu harus dikatakan
# apa adanya alih-alih mengembalikan bagian kosong yang membingungkan.
JENIS = {"BTC": "us-btc-spot", "ETH": "us-eth-spot"}

JENDELA = (5, 20)


def _persentil_dari(nilai, deret):
    """Posisi `nilai` di dalam `deret`, dalam persen. Konteks sejarah, bukan level telanjang."""
    if not deret:
        return None
    lebih_kecil = sum(1 for x in deret if x < nilai)
    return round(lebih_kecil / len(deret) * 100, 1)


def _beruntun(arus):
    """Berapa hari berturut-turut arahnya sama, dihitung dari yang terbaru."""
    if not arus:
        return 0, None
    arah = 1 if arus[-1] > 0 else (-1 if arus[-1] < 0 else 0)
    if arah == 0:
        return 0, None
    n = 0
    for x in reversed(arus):
        if (x > 0 and arah > 0) or (x < 0 and arah < 0):
            n += 1
        else:
            break
    return n, "masuk" if arah > 0 else "keluar"


def _gerak_harga(simbol, hari):
    """Perubahan harga N hari, untuk menguji divergensi. None kalau harga tidak tersedia."""
    try:
        from indicators import fetch_base, resolve_cg_id
        candles, _, _, err = fetch_base(simbol, resolve_cg_id(simbol), "1d")
        if err or not candles or len(candles) <= hari:
            return None
        awal, akhir = candles[-hari - 1][4], candles[-1][4]
        if not awal or not akhir:
            return None
        return round((akhir - awal) / awal * 100, 2)
    except Exception:
        return None


def analisa(simbol):
    simbol = simbol.upper()
    if simbol not in JENIS:
        return {"tidak_tersedia": f"{simbol} tidak punya ETF spot AS. Yang ada hanya "
                                  f"{', '.join(JENIS)}. Katakan apa adanya — JANGAN "
                                  f"meminjam angka arus BTC untuk koin lain."}
    import sosovalue
    baris, err = sosovalue.historis_etf(JENIS[simbol])
    if err:
        return {"tidak_tersedia": err}
    if not baris:
        return {"tidak_tersedia": "riwayat arus ETF kosong"}

    arus = [b.get("totalNetInflow") for b in baris if b.get("totalNetInflow") is not None]
    tanggal = [b.get("date") for b in baris]
    terbaru = baris[-1]
    hari_ini = datetime.now(timezone.utc).date()
    try:
        umur = (hari_ini - datetime.strptime(terbaru["date"], "%Y-%m-%d").date()).days
    except (ValueError, KeyError):
        umur = None

    hasil = {
        "simbol": simbol,
        "jenis": JENIS[simbol],
        "tanggal_data_terakhir": terbaru.get("date"),
        "umur_data_hari": umur,
        "jendela_riwayat": f"{tanggal[0]} s/d {tanggal[-1]}" if tanggal else None,
        "hari_terekam": len(baris),
        "arus_harian_terakhir_usd": terbaru.get("totalNetInflow"),
        "total_aset_usd": terbaru.get("totalNetAssets"),
        "kumulatif_sejak_awal_usd": terbaru.get("cumNetInflow"),
    }
    if umur is not None and umur >= 3:
        hasil["peringatan_kesegaran"] = (
            f"Data ETF berumur {umur} hari (hanya hari bursa, plus jeda pelaporan). "
            "Sebutkan tanggalnya saat mengutip; JANGAN disajikan sebagai arus hari ini.")

    n, arah = _beruntun(arus)
    if n >= 2:
        hasil["beruntun"] = {"hari": n, "arah": arah}

    for j in JENDELA:
        if len(arus) < j + 20:
            continue
        jumlah = sum(arus[-j:])
        # Dibandingkan dengan SEMUA jendela sepanjang j hari di riwayatnya sendiri.
        sejarah = [sum(arus[i:i + j]) for i in range(len(arus) - j)]
        hasil[f"arus_{j}_hari"] = {
            "jumlah_usd": round(jumlah),
            "persentil": _persentil_dari(jumlah, sejarah),
            "arti_persentil": (f"persentil dari {len(sejarah)} jendela {j}-hari dalam "
                               f"riwayat yang sama. Di atas 80 = arus masuk kuat secara "
                               f"historis; di bawah 20 = arus keluar kuat."),
        }

    # DIVERGENSI — bagian paling bernilai. Harga dan arus dana berpisah adalah sinyal yang
    # tidak muncul di chart maupun on-chain.
    gerak = _gerak_harga(simbol, 20)
    if gerak is not None and len(arus) >= 20:
        arus20 = sum(arus[-20:])
        hasil["divergensi_20_hari"] = {
            "perubahan_harga_persen": gerak,
            "arus_bersih_usd": round(arus20),
        }
        if gerak > 2 and arus20 < 0:
            hasil["divergensi_20_hari"]["pola"] = (
                "HARGA NAIK + ARUS KELUAR — pola distribusi. Kenaikan tidak didukung uang "
                "institusi; turunkan keyakinan pada kelanjutan tren.")
        elif gerak < -2 and arus20 > 0:
            hasil["divergensi_20_hari"]["pola"] = (
                "HARGA TURUN + ARUS MASUK — pola akumulasi. Institusi menyerap penurunan.")
        else:
            hasil["divergensi_20_hari"]["pola"] = (
                "Harga dan arus SEJALAN — tidak ada divergensi. Ini konfirmasi biasa, "
                "bukan sinyal tambahan.")

    hasil["cara_pakai"] = (
        "Arus ETF adalah KATEGORI SINYAL TERSENDIRI (arus dana institusional), terpisah dari "
        "teknikal, on-chain, dan sentimen. Inilah yang menaikkan konfluensi dari satu "
        "kategori jadi dua — sebutkan secara eksplisit saat menghitung kategori. Angkanya "
        "USD, bukan jumlah koin. Jangan menyimpulkan arah dari satu hari: satu hari arus "
        "keluar di tengah beruntun masuk itu derau.")
    return hasil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("simbol", help="BTC atau ETH")
    ap.add_argument("--ringkas", action="store_true", help="buang panduan statis")
    args = ap.parse_args()

    keluar = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": "SoSoValue OpenAPI — arus dana ETF spot AS",
    }
    keluar.update(analisa(args.simbol))
    if args.ringkas:
        from backtest import buang_panduan
        keluar = buang_panduan(keluar)
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

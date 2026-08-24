"""Denyut pasar crypto secara keseluruhan — untuk MEMISAHKAN gerakan koin dari gerakan pasar.

Tanpa ini, "SOL naik 18% minggu ini" terdengar seperti prestasi koinnya. Padahal kalau
seluruh pasar naik 23% di periode yang sama, SOL sebenarnya TERTINGGAL — dan kesimpulan
yang benar berbalik arah. Rapor sudah lama memakai alpha untuk menilai panggilan lama;
ini membawa pemisahan yang sama ke jawaban yang sedang disusun.

Seluruhnya dari CoinGecko tanpa API key: /global untuk dominasi & mcap total, /coins/markets
untuk gerakan BTC sebagai pembanding.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kategori import ambil, _bulat, data_koin           # noqa: E402

GLOBAL = "/global"


def denyut():
    """Dominasi, mcap total, dan gerakan BTC. Field yang gagal diisi None, bukan dihilangkan."""
    hasil = {}
    data, _cache, err = ambil(GLOBAL)
    if err or not isinstance(data, dict):
        hasil["global_tidak_tersedia"] = err or "bentuk balasan tak dikenal"
    else:
        d = data.get("data", data)
        dom = d.get("market_cap_percentage") or {}
        hasil.update({
            "dominasi_btc_persen": _bulat(dom.get("btc")),
            "dominasi_eth_persen": _bulat(dom.get("eth")),
            "mcap_total_usd": (d.get("total_market_cap") or {}).get("usd"),
            "mcap_total_ubah_24j_persen": _bulat(d.get("market_cap_change_percentage_24h_usd")),
        })

    try:
        btc = data_koin("bitcoin")
        hasil["btc"] = {k: btc.get(k) for k in ("harga_usd", "ubah_24j", "ubah_7h", "ubah_30h")}
    except Exception as e:
        hasil["btc_tidak_tersedia"] = f"{type(e).__name__}"

    try:
        hasil["sisa_pasar"] = sisa_pasar()
    except Exception as e:
        hasil["sisa_pasar_tidak_tersedia"] = f"{type(e).__name__}"

    hasil["wajib_dibaca"] = (
        "Untuk BTC SENDIRI pakai `sisa_pasar` sebagai pembanding, BUKAN `btc` — BTC vs BTC "
        "selalu nol dan itu tautologi, bukan temuan. "
        "Dipakai untuk MEMISAHKAN gerakan koin dari gerakan pasar. Koin yang naik 5% saat "
        "BTC naik 20% adalah koin yang TERTINGGAL, bukan koin yang menguat. Sebut selisihnya, "
        "jangan hanya angka koinnya. Dominasi BTC yang NAIK berarti dana mengumpul ke BTC "
        "(altcoin melemah relatif); dominasi TURUN berarti sebaliknya.")
    return hasil


def sisa_pasar(n=100):
    """Gerakan pasar DI LUAR BTC, ditimbang mcap. Pembanding untuk BTC itu sendiri.

    BTC tidak bisa dibandingkan dengan dirinya sendiri — selisihnya selalu nol dan
    "sejalan dengan pasar" jadi tautologi, bukan temuan. rapor.py sudah lama mengecualikan
    aset yang menjadi tolok ukurnya sendiri; ini padanannya di sisi jawaban.

    Ditimbang mcap, bukan rata-rata sederhana: rata-rata sederhana membuat koin peringkat
    90 sama beratnya dengan ETH, sehingga angkanya lebih menggambarkan ekor daftar
    daripada pasarnya.
    """
    data, _cache, err = ambil("/coins/markets", {
        "vs_currency": "usd", "order": "market_cap_desc", "per_page": n, "page": 1,
        "price_change_percentage": "7d,30d"})
    if err and not data:
        return {"tidak_tersedia": err}
    if not data:
        return {"tidak_tersedia": "daftar pasar kosong"}

    hasil = {"koin_dipakai": 0, "dari": f"top {n} CoinGecko, BTC dikeluarkan"}
    for jangka, kunci in (("24j", "price_change_percentage_24h"),
                          ("7h", "price_change_percentage_7d_in_currency"),
                          ("30h", "price_change_percentage_30d_in_currency")):
        bobot = nilai = 0.0
        for c in data:
            if (c.get("symbol") or "").upper() == "BTC":
                continue
            mc, ubah = c.get("market_cap"), c.get(kunci)
            if not mc or ubah is None:
                continue
            bobot += mc
            nilai += mc * ubah
        hasil[f"ubah_{jangka}"] = _bulat(nilai / bobot) if bobot else None
    hasil["koin_dipakai"] = sum(
        1 for c in data if (c.get("symbol") or "").upper() != "BTC" and c.get("market_cap"))
    return hasil


def isolasi(ubah_koin, ubah_pasar):
    """Selisih gerakan koin terhadap pembandingnya, dalam poin persen.

    Pembandingnya BTC untuk altcoin, tapi SISA PASAR untuk BTC sendiri — karena itu
    namanya `pasar`, bukan `btc`. Nama yang salah di sini akan terbaca sebagai
    "dibandingkan BTC" pada satu-satunya kasus di mana itu justru tidak benar.
    """
    if ubah_koin is None or ubah_pasar is None:
        return None
    selisih = round(ubah_koin - ubah_pasar, 2)
    if selisih > 2:
        arti = "MENGUNGGULI pasar"
    elif selisih < -2:
        arti = "TERTINGGAL dari pasar"
    else:
        arti = "sejalan dengan pasar"
    return {"koin_persen": ubah_koin, "pasar_persen": ubah_pasar,
            "selisih_pp": selisih, "arti": arti}


def main():
    p = argparse.ArgumentParser(description="Denyut pasar crypto keseluruhan")
    p.add_argument("--koin", help="bandingkan satu koin terhadap pasar (id atau simbol)")
    a = p.parse_args()

    hasil = denyut()
    if a.koin:
        try:
            k = data_koin(a.koin)
            btc = hasil.get("btc") or {}
            hasil["isolasi"] = {
                jangka: isolasi(k.get(f"ubah_{jangka}"), btc.get(f"ubah_{jangka}"))
                for jangka in ("24j", "7h", "30h")
            }
            hasil["isolasi"]["simbol"] = k.get("simbol")
        except Exception as e:
            hasil["isolasi_tidak_tersedia"] = f"{type(e).__name__}: {e}"
    print(json.dumps(hasil, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

"""Dekomposisi SEBAB: kenapa sebuah aset bergerak — dan berapa banyak yang sebenarnya miliknya.

Pertanyaan "kenapa BTC naik minggu ini" paling sering dijawab dengan daftar berita yang
kebetulan terbit di pekan itu. Itu bukan sebab, itu koinsidensi yang disusun rapi. Jawaban
yang berguna harus lebih dulu memisahkan tiga lapis:

  1. Berapa yang berasal dari SELURUH PASAR (semua aset sejenis naik bersama)?
  2. Berapa dari SELERA RISIKO LEBIH LUAS (saham teknologi, emas, dolar bergerak searah)?
  3. Sisanya — hanya sisanya — yang benar-benar khas aset ini.

Tanpa langkah 1 dan 2, "BTC naik karena arus ETF" bisa saja salah total: kalau seluruh
pasar naik dengan besaran yang sama, ETF hanya penumpang, bukan penggerak.

Seluruh sumber gratis tanpa API key: CoinGecko (dominasi & gerakan), Yahoo (QQQ, emas,
dolar, imbal hasil), FRED lewat makro.py.
"""

import argparse
import json
import os
import sys

from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Pembanding lintas aset. Empat ini dipilih karena masing-masing menjawab pertanyaan
# berbeda, bukan karena tersedia: QQQ = selera risiko, emas = pencarian aset lindung,
# dolar = harga likuiditas global, imbal hasil 10 tahun = biaya modal.
LINTAS_ASET = (
    ("QQQ", "Nasdaq 100", "selera risiko aset pertumbuhan"),
    ("GC=F", "Emas", "pencarian aset lindung nilai"),
    ("DX-Y.NYB", "Indeks Dolar", "harga likuiditas global — menguat = pengetatan"),
    ("^TNX", "Imbal hasil 10 tahun AS", "biaya modal"),
)

HORIZON = (7, 30)


def lintas_aset():
    """Gerakan empat pembanding makro. Yang gagal dilaporkan, bukan dihilangkan."""
    from konteks import kinerja
    keluar, gagal = {}, {}
    for sim, nama, arti in LINTAS_ASET:
        k, err = kinerja(sim, hari=HORIZON)
        if err or not k:
            gagal[nama] = err or "kosong"
            continue
        k["nama"] = nama
        k["kenapa_dilihat"] = arti
        keluar[sim] = k
    hasil = {"pembanding": keluar}
    if gagal:
        hasil["gagal_diambil"] = gagal
    return hasil


def lapisan(ubah_aset, ubah_pasar):
    """Pecah gerakan aset jadi bagian PASAR dan bagian KHAS ASET, dalam poin persen."""
    if ubah_aset is None or ubah_pasar is None:
        return None
    khas = round(ubah_aset - ubah_pasar, 2)
    porsi = abs(ubah_pasar) / abs(ubah_aset) * 100 if ubah_aset else None
    return {
        "gerakan_aset_persen": ubah_aset,
        "gerakan_pasar_persen": ubah_pasar,
        "khas_aset_pp": khas,
        "porsi_dari_pasar_persen": round(porsi, 1) if porsi is not None else None,
        "arti": ("sebagian besar gerakan ini milik PASAR, bukan aset ini"
                 if porsi is not None and porsi >= 70 else
                 "sebagian besar gerakan ini KHAS aset ini"
                 if porsi is not None and porsi <= 30 else
                 "gerakan pasar dan gerakan khas aset sama-sama berperan"),
    }


def _deret_penutupan(simbol, jenis):
    """{tanggal: harga penutup} harian. Satu sumber untuk semua supaya tanggalnya sepadan.

    Sengaja lewat Yahoo juga untuk kripto (BTC-USD), bukan sumber kripto biasa: korelasi
    dihitung dengan MENYELARASKAN tanggal, dan dua sumber dengan batas hari berbeda akan
    menghasilkan pasangan yang bergeser beberapa jam. Pergeseran itu menurunkan korelasi
    tanpa ada yang berubah di pasarnya. Kalau Yahoo tidak punya asetnya, baru jatuh ke
    sumber kripto — dan kejadian itu dilaporkan, bukan disembunyikan.
    """
    from market import tarik
    kandidat = [simbol] if jenis != "crypto" else [f"{simbol.upper()}-USD", simbol.upper()]
    for s in kandidat:
        c, _, err = tarik(s, "1y", "1d")
        if not err and c:
            return ({datetime.fromtimestamp(b[0] / 1000, timezone.utc).strftime("%Y-%m-%d"):
                     b[4] for b in c if b[4]}, s, None)
    return {}, None, f"tidak ada deret harian untuk {simbol}"


def _imbal(deret):
    """Ubah harga jadi imbal hasil harian.

    Korelasi dihitung dari IMBAL HASIL, bukan harga. Dua aset yang sama-sama menanjak
    akan menunjukkan korelasi harga mendekati 1 walau gerak hariannya tidak berhubungan
    sama sekali — itu korelasi tren, bukan korelasi pasar.
    """
    tgl = sorted(deret)
    keluar = {}
    for i in range(1, len(tgl)):
        a, b = deret[tgl[i - 1]], deret[tgl[i]]
        if a:
            keluar[tgl[i]] = (b - a) / a
    return keluar


def pearson(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    atas = sum((a - mx) * (b - my) for a, b in zip(x, y))
    bx = sum((a - mx) ** 2 for a in x) ** 0.5
    by = sum((b - my) ** 2 for b in y) ** 0.5
    return round(atas / (bx * by), 4) if bx and by else None


def korelasi(simbol, jenis, horizon=(30, 90)):
    """Korelasi imbal hasil terhadap empat pembanding makro, DENGAN jumlah hari sepadannya.

    Angka tumpang tindih itu bukan hiasan. QQQ dan emas tidak diperdagangkan akhir pekan
    sementara kripto jalan terus, jadi korelasi 30 hari kalender sebenarnya berdiri di atas
    ~21 hari yang benar-benar berpasangan. Tanpa menyebutnya, koefisien terdengar seperti
    fakta padahal separuh datanya tidak pernah ada. CMC AI melaporkan `overlap` 0,4806 untuk
    QQQ dan itu praktik yang benar — ini padanannya di sini.
    """
    aset, sumber, err = _deret_penutupan(simbol, jenis)
    if err:
        return {"tidak_tersedia": err}
    r_aset = _imbal(aset)

    hasil = {"simbol": simbol.upper(), "sumber_deret": sumber,
             "dasar": "imbal hasil harian (bukan harga)", "pembanding": {}}
    from market import tarik
    for sim, nama, _arti in LINTAS_ASET:
        c, _, e = tarik(sim, "1y", "1d")
        if e or not c:
            hasil["pembanding"][nama] = {"tidak_tersedia": e or "kosong"}
            continue
        r_lain = _imbal({datetime.fromtimestamp(b[0] / 1000, timezone.utc).strftime("%Y-%m-%d"):
                         b[4] for b in c if b[4]})
        sama = sorted(set(r_aset) & set(r_lain))
        baris = {}
        for h in horizon:
            # Jendelanya HARI KALENDER, bukan "h observasi berpasangan terakhir". Mengambil
            # h pasangan terakhir untuk QQQ akan membentang ~6 minggu — lalu melaporkannya
            # sebagai "korelasi 30 hari" dengan 30 dari 30 hari cocok, padahal QQQ tidak
            # diperdagangkan akhir pekan sehingga angka itu mustahil. Yang dibandingkan
            # harus rentang waktu yang sama, dan kepadatannya dilaporkan apa adanya.
            akhir = datetime.strptime(sama[-1], "%Y-%m-%d")
            mulai = (akhir - timedelta(days=h)).strftime("%Y-%m-%d")
            batas = [t for t in sama if t >= mulai]
            x = [r_aset[t] for t in batas]
            y = [r_lain[t] for t in batas]
            k = pearson(x, y)
            baris[f"{h}h"] = {
                "korelasi": k,
                "hari_sepadan": len(batas),
                "hari_kalender": h,
                "kepadatan": round(len(batas) / h, 2),
                "rentang": f"{batas[0]} s/d {batas[-1]}" if batas else None,
            }
            if k is None:
                baris[f"{h}h"]["catatan"] = "terlalu sedikit hari berpasangan untuk dihitung"
            elif len(batas) < h * 0.5:
                baris[f"{h}h"]["catatan"] = (
                    f"hanya {len(batas)} hari berpasangan dalam {h} hari kalender — baca "
                    "sebagai petunjuk arah, bukan hubungan yang mapan")
        hasil["pembanding"][nama] = baris

    hasil["arti"] = (
        "Mendekati +1 = bergerak searah; mendekati 0 = tidak berhubungan; negatif = "
        "berlawanan. Korelasi RENDAH terhadap QQQ berarti gerakan ini BUKAN sekadar selera "
        "risiko saham teknologi. Korelasi TINGGI terhadap emas dengan dolar melemah "
        "mengarah ke cerita likuiditas. Selalu sebut `hari_sepadan` saat mengutip "
        "koefisiennya — angka di atas sedikit hari bukan temuan.")
    return hasil


def rakit(simbol, jenis):
    """Bahan lengkap untuk menjawab 'kenapa bergerak'. Tidak menyimpulkan — itu tugas model."""
    hasil = {"simbol": simbol, "jenis": jenis, "horizon_hari": list(HORIZON)}

    if jenis == "crypto":
        try:
            from pasarglobal import denyut, isolasi
            from kategori import data_koin
            d = denyut()
            k = data_koin(simbol)
            hasil["pasar_crypto"] = {x: d.get(x) for x in
                                     ("dominasi_btc_persen", "mcap_total_usd",
                                      "mcap_total_ubah_24j_persen")}
            # BTC tidak bisa jadi pembanding bagi dirinya sendiri: selisihnya selalu nol
            # dan "sejalan dengan pasar" berubah jadi tautologi. Untuk BTC, pembandingnya
            # adalah sisa pasar (top 100 tanpa BTC, ditimbang mcap).
            ini_btc = (k.get("simbol") or "").upper() == "BTC"
            acuan = (d.get("sisa_pasar") or {}) if ini_btc else (d.get("btc") or {})
            hasil["pembanding_pasar"] = ("sisa pasar (top 100 tanpa BTC)" if ini_btc
                                         else "BTC")
            hasil["vs_pasar"] = {j: isolasi(k.get(f"ubah_{j}"), acuan.get(f"ubah_{j}"))
                                 for j in ("24j", "7h", "30h")}
            hasil["lapisan_7h"] = lapisan(k.get("ubah_7h"), acuan.get("ubah_7h"))
        except Exception as e:
            hasil["pasar_crypto_tidak_tersedia"] = f"{type(e).__name__}: {e}"
    else:
        try:
            from konteks import kinerja
            aset, e1 = kinerja(simbol, hari=HORIZON)
            spy, e2 = kinerja("SPY", hari=HORIZON)
            if aset and spy:
                hasil["vs_spy"] = {f"{h}h": lapisan(aset.get(f"perubahan_{h}h_persen"),
                                                    spy.get(f"perubahan_{h}h_persen"))
                                   for h in HORIZON}
            else:
                hasil["vs_spy_tidak_tersedia"] = e1 or e2
        except Exception as e:
            hasil["vs_spy_tidak_tersedia"] = f"{type(e).__name__}: {e}"

    hasil.update(lintas_aset())

    try:
        hasil["korelasi"] = korelasi(simbol, jenis)
    except Exception as e:
        hasil["korelasi_tidak_tersedia"] = f"{type(e).__name__}: {e}"

    try:
        from makro import rezim_pasar
        hasil["rezim_makro"] = rezim_pasar()
    except Exception as e:
        hasil["rezim_makro_tidak_tersedia"] = f"{type(e).__name__}"

    hasil["wajib_dibaca"] = (
        "URUTAN MENJAWAB, jangan dibalik: (1) berapa bagian gerakan ini yang milik SELURUH "
        "PASAR — pakai lapisan/vs_pasar/vs_spy; (2) apakah aset lain bergerak searah (QQQ, "
        "emas, dolar, imbal hasil) sehingga ini soal selera risiko luas, bukan aset ini; "
        "(3) BARU sebab khas aset. Berita yang terbit di pekan yang sama BUKAN bukti sebab "
        "— kalau seluruh pasar naik dengan besaran serupa, berita itu penumpang, bukan "
        "penggerak. Sebut besaran tiap lapis dalam angka, dan sebut mana yang TIDAK bisa "
        "dijelaskan datanya.")
    return hasil


def main():
    p = argparse.ArgumentParser(description="Dekomposisi sebab gerakan harga")
    p.add_argument("simbol")
    p.add_argument("--jenis", default="crypto", choices=("crypto", "saham", "forex"))
    a = p.parse_args()
    print(json.dumps(rakit(a.simbol, a.jenis), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

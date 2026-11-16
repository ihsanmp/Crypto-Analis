"""Riwayat REAKSI HARGA saham saat rilis earnings — dari tanggal rilis RESMI SEC (8-K item 2.02).

Diambil dari kerangka earnings-preview (anthropics/financial-services, Apache-2.0): ekspektasi
reaksi dikalibrasi dari "bagaimana saham ini bergerak pada rilis-rilis sebelumnya". Tanpa
angka ini bot hanya bisa menulis "earnings = risiko" tanpa ukuran seberapa besar.

Cara ukur: rilis earnings bisa sebelum pasar buka atau sesudah tutup, dan waktu itu tidak
selalu jelas. Maka jendelanya DUA hari: penutupan hari bursa terakhir SEBELUM tanggal 8-K ->
penutupan hari bursa pertama SESUDAHNYA (mencakup kedua kemungkinan). Pembanding = jendela dua
hari yang sama pada SEMUA hari biasa, supaya terlihat apakah earnings memang memperbesar gerak.

Ini DESKRIPSI masa lalu (besar gerak), BUKAN ramalan arah. Arah reaksi historis campuran dan
tidak dipakai sebagai sinyal.

    python cloud/reaksi_earnings.py NVDA
"""
import argparse
import json
import os
import statistics
import sys
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seckontak  # noqa: E402

MAKS_KEJADIAN = 20


def _ambil_json(url):
    req = urllib.request.Request(url, headers=seckontak.header())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _dari_blok(rec):
    return [tgl for form, tgl, items in zip(rec.get("form", []), rec.get("filingDate", []),
                                            rec.get("items", []))
            if form in ("8-K", "8-K/A") and "2.02" in (items or "")]


def tanggal_rilis(cik, minimal=MAKS_KEJADIAN, maks_arsip=4):
    """Tanggal 8-K berisi item 2.02 (Results of Operations) dari submissions SEC.

    'recent' hanya ~1.000 filing terakhir. Emiten yang sangat sering mengajukan (bank: 8-K &
    424B tiap pekan) cuma tercakup ~1 tahun — JPM hanya 4 rilis (cek runner 16 Nov 2026).
    Berkas arsip lama (filings.files) dibaca sampai cukup."""
    d = _ambil_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
    tanggal = set(_dari_blok((d.get("filings") or {}).get("recent") or {}))
    for berkas in ((d.get("filings") or {}).get("files") or [])[:maks_arsip]:
        if len(tanggal) >= minimal:
            break
        try:
            tanggal |= set(_dari_blok(_ambil_json(
                f"https://data.sec.gov/submissions/{berkas['name']}")))
        except Exception:
            break
    return sorted(tanggal)


def reaksi(tutup_per_tgl, tgl_rilis):
    """{tgl: close} urut -> list (tgl_rilis, gerak_persen) jendela 2 hari di sekitar rilis."""
    hari = sorted(tutup_per_tgl)
    keluar = []
    for t in tgl_rilis:
        sebelum = [h for h in hari if h < t]
        sesudah = [h for h in hari if h > t]
        if not sebelum or not sesudah:
            continue
        a, b = tutup_per_tgl[sebelum[-1]], tutup_per_tgl[sesudah[0]]
        keluar.append((t, round((b / a - 1) * 100, 2)))
    return keluar


def gerak_biasa(tutup_per_tgl):
    """|gerak| jendela 2 hari (close t-1 -> close t+1) pada semua hari — pembanding."""
    hari = sorted(tutup_per_tgl)
    return [abs(tutup_per_tgl[hari[i + 1]] / tutup_per_tgl[hari[i - 1]] - 1) * 100
            for i in range(1, len(hari) - 1)]


def ringkas(kejadian, biasa):
    g = [abs(x) for _, x in kejadian]
    med = statistics.median(g)
    med_biasa = statistics.median(biasa) if biasa else None
    urut = sorted(g)
    return {
        "jumlah_rilis": len(g),
        "median_gerak_mutlak_persen": round(med, 2),
        "gerak_mutlak_persen_80": round(urut[min(len(urut) - 1, int(0.8 * len(urut)))], 2),
        "terbesar_persen": max(kejadian, key=lambda x: abs(x[1])),
        "median_gerak_2_hari_biasa_persen": round(med_biasa, 2) if med_biasa else None,
        "kelipatan_vs_hari_biasa": round(med / med_biasa, 1) if med_biasa else None,
        "naik_dari": f"{sum(1 for _, x in kejadian if x > 0)} dari {len(g)}",
        "terakhir": [{"tgl": t, "gerak_persen": x} for t, x in kejadian[-6:]],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    a = ap.parse_args()
    t = a.ticker.upper().replace("$", "")
    hasil = {"ticker": t, "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
             "sumber": "tanggal rilis: SEC 8-K item 2.02; harga: Yahoo harian",
             "cara_ukur": ("jendela 2 hari: close sebelum tanggal 8-K -> close sesudahnya "
                           "(rilis pra-buka maupun pasca-tutup tercakup)")}
    alasan = seckontak.alasan_kosong()
    if alasan:
        hasil["tidak_tersedia"] = alasan
        print(json.dumps(hasil, ensure_ascii=False))
        return
    try:
        import stockfund
        import market
        cik, _nama, err = stockfund.cari_cik(t)
        if err:
            raise RuntimeError(err)
        rilis = tanggal_rilis(cik)
        candles, _meta, err = market.tarik(t, "10y", "1d")
        if err or not candles:
            raise RuntimeError(f"harga: {err or 'kosong'}")
    except Exception as e:
        hasil["tidak_tersedia"] = f"{type(e).__name__}: {str(e)[:120]}"
        print(json.dumps(hasil, ensure_ascii=False))
        return
    tutup = {datetime.fromtimestamp(c[0] / 1000, timezone.utc).strftime("%Y-%m-%d"): c[4]
             for c in candles if c[4]}
    kejadian = reaksi(tutup, rilis)[-MAKS_KEJADIAN:]
    if len(kejadian) < 4:
        hasil["tidak_tersedia"] = f"hanya {len(kejadian)} rilis earnings terukur"
    else:
        hasil.update(ringkas(kejadian, gerak_biasa(tutup)))
        hasil["cara_pakai"] = (
            "Ukuran BESAR gerak, bukan arah. Bila earnings dekat (lihat jadwal_berikutnya), "
            "sebut 'secara historis bergerak ±median% (80% rilis di bawah ±p80%)' di RISIKO "
            "dan kecilkan posisi baru sebelum rilis. Arah reaksi historis bukan sinyal.")
    print(json.dumps(hasil, ensure_ascii=False))


if __name__ == "__main__":
    main()

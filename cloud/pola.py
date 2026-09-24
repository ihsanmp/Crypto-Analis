"""Pola DOUBLE BOTTOM / DOUBLE TOP — bagian "Pattern" di outlook gaya Astronacci, dideteksi KODE.

Asalnya gambar ketiga yang dikirim user (BTC Weekly, 21 Sep 2026): "Bitcoin membentuk
pola Double Bottom dan telah menembus neckline di area 83.000 ... target pertama 98.000
dan target kedua 127.000 ... support utama 57.500". Goal user: outlook seperti itu.

Yang dibuat kode di sini — dan HANYA ini yang boleh disebut agent:
  - dua lembah (atau dua puncak) fraktal yang tingginya berdekatan;
  - NECKLINE = puncak tertinggi di antara dua lembah itu (terendah untuk double top);
  - TARGET UKUR (measured move) = neckline + (neckline − lembah terdalam) — cara baku
    buku teks. Target 98.000/127.000 di gambar TIDAK dihasilkan cara ini (dengan lembah
    di kisaran 60 rb, target ukurnya ~106 rb), jadi sumber angka-angka itu tidak bisa
    direproduksi dan tidak dikutip sebagai milik kode;
  - INVALID = lembah terdalam (puncak tertinggi untuk double top);
  - status: MENUNGGU TEMBUS neckline, atau SUDAH TEMBUS.

BERAPA SERING TARGETNYA TERCAPAI — diuji, bukan dianggap (uji_pola(), BTC harian
2012–2026). Setelah close menembus neckline, target ukur dan dasar pola berjarak SAMA
dari neckline, jadi pembandingnya adalah peluang dasar BTC mencapai +x% sebelum −x%
pada jarak yang sama, dari hari mana pun. Pola yang tidak lebih baik dari pembanding itu
tidak memberi informasi apa pun, sebagus apa pun bentuknya di chart.

PARAMETER DITETAPKAN SEKALI, sebelum melihat hasil uji (di bawah).

Pemakaian:
    python cloud/pola.py BTC --ringkas
    python cloud/pola.py --uji                # uji balik pada BTC harian repo
"""

import argparse
import csv
import datetime as dt
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Parameter a priori -------------------------------------------------------------------
PARAM = {
    "harian": {"fraktal": 3, "jeda_min": 10, "jeda_maks": 120, "tembus_maks": 60},
    "mingguan": {"fraktal": 2, "jeda_min": 4, "jeda_maks": 40, "tembus_maks": 16},
}
TOLERANSI = 0.05          # dua lembah berbeda maks 5%
KEDALAMAN_MIN = 0.08      # neckline minimal 8% di atas lembah — di bawah itu cuma derau
HORIZON_UJI = {"harian": 180, "mingguan": 52}


def _pivot(k, i, n, tinggi):
    kol = 2 if tinggi else 3
    v = k[i][kol]
    sisi = k[i - n:i] + k[i + 1:i + 1 + n]
    return all(v > c[kol] for c in sisi) if tinggi else all(v < c[kol] for c in sisi)


def mingguan(harian):
    """Resample candle harian [ts_ms,o,h,l,c,v] ke mingguan (ISO, Senin–Minggu)."""
    kelompok = {}
    for c in harian:
        d = dt.datetime.fromtimestamp(c[0] / 1000, dt.timezone.utc).date()
        kunci = d - dt.timedelta(days=d.weekday())
        kelompok.setdefault(kunci, []).append(c)
    out = []
    for kunci in sorted(kelompok):
        g = kelompok[kunci]
        out.append([g[0][0], g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4],
                    sum(x[5] for x in g)])
    return out


def _pivot_semua(k, n):
    """{False: [indeks lembah], True: [indeks puncak]} — dihitung sekali."""
    return {t: [i for i in range(n, len(k) - n) if _pivot(k, i, n, t)] for t in (False, True)}


def _pola_untuk(k, piv, b, skala, tinggi, akhir):
    """Pola dengan pivot KEDUA di b, dilihat pada candle `akhir`, atau None.

    Satu fungsi untuk deteksi live DAN uji balik — kalau dipisah, yang dipakai bot pelan-
    pelan menyimpang dari yang teruji tanpa ada yang tahu.
    """
    p = PARAM[skala]
    n = p["fraktal"]
    kol = 2 if tinggi else 3
    for a in reversed([i for i in piv[tinggi] if i < b]):
        jeda = b - a
        if jeda < p["jeda_min"]:
            continue
        if jeda > p["jeda_maks"]:
            return None
        v1, v2 = k[a][kol], k[b][kol]
        if abs(v1 - v2) / min(v1, v2) > TOLERANSI:
            continue
        antara = k[a + 1:b]
        if tinggi:
            leher, ekstrem = min(c[3] for c in antara), max(v1, v2)
            dalam = (ekstrem - leher) / ekstrem
        else:
            leher, ekstrem = max(c[2] for c in antara), min(v1, v2)
            dalam = (leher - ekstrem) / ekstrem
        if dalam < KEDALAMAN_MIN:
            continue
        tembus = None
        for j in range(b + n, min(akhir, b + p["tembus_maks"]) + 1):
            if (not tinggi and k[j][4] > leher) or (tinggi and k[j][4] < leher):
                tembus = j
                break
            if (not tinggi and k[j][3] < ekstrem) or (tinggi and k[j][2] > ekstrem):
                break           # dasar pola jebol sebelum tembus
        jarak = abs(leher - ekstrem)
        return {"jenis": "DOUBLE TOP" if tinggi else "DOUBLE BOTTOM", "skala": skala,
                "i_1": a, "i_2": b, "lembah_puncak": [v1, v2], "neckline": leher,
                "invalid": ekstrem, "target_ukur": leher - jarak if tinggi else leher + jarak,
                "tembus": tembus,
                "status": "SUDAH TEMBUS" if tembus is not None else "MENUNGGU TEMBUS"}
    return None


def cari(k, skala="harian"):
    """Pola terbaru yang MASIH HIDUP (belum jebol, target belum tercapai) di tiap arah.
    Pivot baru sah setelah n candle sesudahnya tertutup — tidak mengintip masa depan."""
    n = PARAM[skala]["fraktal"]
    akhir = len(k) - 1
    piv = _pivot_semua(k, n)
    hidup = []
    for tinggi in (False, True):
        for b in reversed([i for i in piv[tinggi] if i <= akhir - n]):
            h = _pola_untuk(k, piv, b, skala, tinggi, akhir)
            if not h:
                continue
            sesudah = k[b + 1:]
            if tinggi:
                mati = any(c[2] > h["invalid"] or c[3] <= h["target_ukur"] for c in sesudah)
            else:
                mati = any(c[3] < h["invalid"] or c[2] >= h["target_ukur"] for c in sesudah)
            if not mati:
                hidup.append(h)
            break               # hanya struktur TERBARU per arah
    return hidup


# --- Uji balik ----------------------------------------------------------------------------

def _muat_btc():
    k = []
    with gzip.open(os.path.join(BASE_DIR, "data", "btc_daily_bitstamp.csv.gz"), "rt",
                   encoding="utf-8") as f:
        for b in csv.DictReader(f):
            try:
                o, h, l, c = (float(b[x]) for x in ("open", "high", "low", "close"))
            except (TypeError, ValueError):
                continue
            if c > 0:
                t = dt.datetime.fromisoformat(b["dt"][:10]).replace(tzinfo=dt.timezone.utc)
                k.append([int(t.timestamp() * 1000), o, h, l, c, 0.0])
    return k


def _hasil_penghalang(k, j, naik_ke, turun_ke, horizon):
    """1 kalau naik_ke tersentuh dulu, 0 kalau turun_ke dulu, None kalau keduanya belum.
    Candle yang menyentuh keduanya dihitung GAGAL (tak bisa tahu urutannya)."""
    for c in k[j + 1:j + 1 + horizon]:
        if c[3] <= turun_ke:
            return 0
        if c[2] >= naik_ke:
            return 1
    return None


def uji_pola(k, skala):
    """Setiap tembus neckline: target ukur dulu, atau dasar pola dulu? + pembanding.

    Tiap pivot kedua b dinilai persis seperti deteksi live: _pola_untuk() yang sama,
    dengan tembus dicari hanya sampai batas yang sama. Tidak ada informasi sesudah hari
    tembus yang dipakai untuk memutuskan apakah polanya ada.
    """
    hor = HORIZON_UJI[skala]
    n = PARAM[skala]["fraktal"]
    piv = _pivot_semua(k, n)
    kasus = []
    for tinggi in (False, True):
        for b in piv[tinggi]:
            h = _pola_untuk(k, piv, b, skala, tinggi, len(k) - 1)
            if not h or h["tembus"] is None or h["tembus"] >= len(k) - 1:
                continue
            t = h["tembus"]
            harga = k[t][4]
            if h["jenis"] == "DOUBLE BOTTOM":
                r = _hasil_penghalang(k, t, h["target_ukur"], h["invalid"], hor)
                jarak_naik = h["target_ukur"] / harga - 1
                jarak_turun = 1 - h["invalid"] / harga
            else:
                r0 = _hasil_penghalang(k, t, h["invalid"], h["target_ukur"], hor)
                r = None if r0 is None else 1 - r0
                jarak_naik = h["invalid"] / harga - 1
                jarak_turun = 1 - h["target_ukur"] / harga
            kasus.append({"jenis": h["jenis"], "t": t, "hasil": r,
                          "jarak_naik": jarak_naik, "jarak_turun": jarak_turun})
    # Pembanding: dari SETIAP hari, penghalang dengan jarak persis sama seperti kasusnya.
    for kas in kasus:
        cocok = tot = 0
        for j in range(60, len(k) - hor, 3):
            harga = k[j][4]
            atas, bawah = harga * (1 + kas["jarak_naik"]), harga * (1 - kas["jarak_turun"])
            r = _hasil_penghalang(k, j, atas, bawah, hor)
            if r is None:
                continue
            tot += 1
            benar = r if kas["jenis"] == "DOUBLE BOTTOM" else 1 - r
            cocok += benar
        kas["dasar"] = cocok / tot if tot else None
    ringkas = {}
    for jenis in ("DOUBLE BOTTOM", "DOUBLE TOP"):
        x = [c for c in kasus if c["jenis"] == jenis and c["hasil"] is not None
             and c["dasar"] is not None]
        if not x:
            ringkas[jenis] = {"n": 0}
            continue
        ringkas[jenis] = {
            "n": len(x), "target_dulu_persen": round(100 * sum(c["hasil"] for c in x) / len(x), 1),
            "pembanding_persen": round(100 * sum(c["dasar"] for c in x) / len(x), 1),
            "belum_selesai": sum(1 for c in kasus if c["jenis"] == jenis and c["hasil"] is None)}
    return ringkas


# Hasil uji yang dipaku — `python cloud/pola.py --uji` + potongan periode (pola_btc.md).
# Angka gabungan (double bottom harian 77,4% vs pembanding 66,9%, p=0,008) MENYESATKAN:
# seluruh selisihnya milik 2012-2018. Dipotong kronologis, 2019-2026 memberi 67,1% vs
# 67,0% (p=0,99) — persis jebakan yang diperingatkan prinsip 3 README.
HASIL_UJI = (
    "  UJI (BTC harian 2012–2026, pola.py --uji): setelah tembus neckline, target ukur "
    "tercapai sebelum dasar pola di 77,4% dari 133 double bottom vs 66,9% pembanding "
    "(jarak sama, hari mana pun) — TAPI seluruh selisih itu milik 2012–2018 (94,1% vs "
    "66,7%). 2019–2026: 67,1% vs 67,0% (p=0,99); 2022–2026: 61,1% vs 64,6%. Double top: "
    "50,0% vs 49,9%. ARTINYA: di era sekarang pola ini TIDAK menambah informasi — peluang "
    "target tercapai lebih dulu ≈ peluang dasar (~2 dari 3 untuk double bottom, ~1 dari 2 "
    "untuk double top). Sebut polanya sebagai deskripsi struktur; jangan sebut polanya "
    "sebagai alasan peluang lebih tinggi. Diuji pada BTC saja.")


def _usd(x):
    return "$" + f"{x:,.0f}".replace(",", ".") if x >= 100 else f"${x:,.4f}"


def _persen(x):
    return f"{x:+.1f}%".replace(".", ",")


def _tgl(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date()


def data_btc():
    """Riwayat repo 2012–2026 disambung candle harian terbaru — data yang SAMA dengan yang
    diuji. Candle bursa saja terlalu pendek untuk skala mingguan: di run 35994887380 pola
    mingguan (neckline $82.833, sama dengan klaim Astronacci 83.000) hilang dari blok
    live karena itu."""
    k = _muat_btc()
    sumber = "riwayat repo (Bitstamp)"
    try:
        from indicators import fetch_base, resolve_cg_id
        baru, src, _q, _e = fetch_base("BTC", resolve_cg_id("BTC"), "1d")
    except Exception:
        baru, src = None, None
    if baru:
        akhir = k[-1][0]
        tambah = [c for c in baru if c[0] > akhir + 3600 * 1000]
        if tambah:
            k += tambah
            sumber += f" + {src}"
    return k, sumber


def ringkas(simbol, harian, sumber=None):
    b = [f"POLA DOUBLE BOTTOM/TOP {simbol} (dideteksi kode, pola.py)",
         f"  Data harian {_tgl(harian[0][0])} s.d. {_tgl(harian[-1][0])}"
         + (f" ({sumber})" if sumber else "")]
    ada = False
    for skala, k in (("mingguan", mingguan(harian)), ("harian", harian)):
        for h in cari(k, skala):
            ada = True
            harga = k[-1][4]
            b.append(f"  {skala.upper()}: {h['jenis']} — {h['status']}")
            b.append(f"    lembah/puncak {_usd(h['lembah_puncak'][0])} & "
                     f"{_usd(h['lembah_puncak'][1])} · neckline {_usd(h['neckline'])} · "
                     f"target ukur {_usd(h['target_ukur'])} "
                     f"({_persen(100 * (h['target_ukur'] / harga - 1))} dari harga kini) · "
                     f"invalid {_usd(h['invalid'])}")
    if not ada:
        b.append("  Tidak ada double bottom/top yang masih hidup di skala harian maupun "
                 "mingguan — jangan menamai pola yang tidak dideteksi kode.")
    if HASIL_UJI:
        b.append(HASIL_UJI)
    else:
        b.append("  Seberapa sering target ukur tercapai: BELUM diuji — jangan menyebut "
                 "peluangnya.")
    return "\n".join(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("simbol", nargs="?", default="BTC")
    ap.add_argument("--ringkas", action="store_true")
    ap.add_argument("--uji", action="store_true")
    a = ap.parse_args()
    if a.uji:
        k = _muat_btc()
        print(json.dumps({"harian": uji_pola(k, "harian"),
                          "mingguan": uji_pola(mingguan(k), "mingguan")},
                         indent=2, ensure_ascii=False))
        return
    s = a.simbol.upper()
    if s == "BTC":
        harian, sumber = data_btc()
    else:
        from indicators import fetch_base, resolve_cg_id
        harian, sumber, _kual, err = fetch_base(s, resolve_cg_id(s), "1d")
        if not harian:
            print(f"POLA DOUBLE BOTTOM/TOP {s}: candle harian tidak tersedia ({err}) — "
                  "jangan menamai pola apa pun.")
            return
    print(ringkas(s, harian, sumber))


if __name__ == "__main__":
    main()

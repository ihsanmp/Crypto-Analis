"""Apakah PPI memprediksi KEJUTAN CPI — diukur, bukan dikira-kira.

Bot ini pernah menjawab pertanyaan "PPI hari ini bilang apa soal CPI besok?" dengan
mengaku tidak punya model teruji, lalu menyebutnya murni dugaan makro. Jawaban itu benar
dan jujur. Berkas ini yang mengubahnya jadi angka.

APA YANG DIUKUR. Bukan "PPI naik -> CPI naik" (itu hampir tautologi: keduanya inflasi),
melainkan apakah PPI memprediksi BAGIAN CPI YANG MENGEJUTKAN — selisih aktual terhadap
ramalan. Itu yang menggerakkan harga; angka mentah CPI yang sudah diantisipasi tidak.

DUA PERTANYAAN YANG SAMA SEKALI BERBEDA, DAN GAMPANG TERTUKAR:

  1. PPI bulan SEBELUMNYA -> kejutan CPI bulan ini.
     Selalu sah dipakai meramal: PPI bulan M-1 terbit pertengahan bulan M, sedangkan
     CPI bulan M baru terbit pertengahan bulan M+1. Jadi angkanya PASTI sudah diketahui.

  2. PPI bulan SAMA -> kejutan CPI bulan itu.
     Korelasinya lebih tinggi, dan itu menggoda. Tapi ia hanya sah kalau PPI benar-benar
     terbit LEBIH DULU dari CPI pada siklus tersebut. Kalau PPI terbit sesudahnya, angka
     itu hubungan SEZAMAN, bukan ramalan — memakainya seolah ramalan berarti melihat
     jawaban sebelum menebak. Urutan rilis berubah-ubah antar-tahun, jadi tingkat ini
     WAJIB disebut beserta syaratnya, tidak boleh dikutip telanjang.

KENAPA HASILNYA MEMANG TIDAK BOLEH TERLALU KUAT. Porsi terbesar CPI adalah sewa/OER, dan
komponen itu sama sekali tidak ada di PPI. Jadi secara konsep PPI bukan pemandu mekanis
untuk CPI. Kalau berkas ini suatu saat melaporkan korelasi sangat tinggi, curigai datanya
lebih dulu — bukan rayakan.

SUMBER (gratis, tanpa kunci API):
  - Kejutan CPI: kejutan.py (nowcast Cleveland Fed + aktual + tanggal rilis sebenarnya).
    Kejutannya terhadap MODEL Cleveland Fed, bukan median survei Wall Street.
  - PPI: FRED (PPIFIS = final demand, WPSFD4131 = headline).

Pemakaian:
    python cloud/ppi_cpi.py
    python cloud/ppi_cpi.py --json
"""

import argparse
import csv
import io
import json
import os
import random
import statistics as st
import subprocess
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "data", "ppi_cache.json")
CACHE_UMUR = 12 * 3600

SERI_PPI = {
    "ppi_final_demand": "PPIFIS",
    "ppi_headline": "WPSFD4131",
}
# Di bawah ini sampelnya terlalu kecil untuk dipercaya apa pun hasilnya.
MINIMUM_SAMPEL = 24
# Ambang "layak dipakai". Bukan angka keramat — dipilih supaya sesuatu yang cuma sedikit
# di atas lemparan koin tidak lolos jadi "sinyal".
AMBANG_KORELASI = 0.25
AMBANG_ARAH = 55.0


def _unduh(seri):
    """Ambil satu seri FRED lewat curl. Return {'2026-8': 157.411} atau {}.

    Memakai curl, bukan urllib: di sebagian jaringan urllib kena proxy yang membuat
    pembacaannya menggantung sampai timeout, sedangkan curl lewat.
    """
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={seri}"
    try:
        p = subprocess.run(["curl", "-s", "--max-time", "45", "-A", "riset-koin/1.0", url],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if p.returncode != 0 or not p.stdout.strip():
            return {}
        keluar = {}
        for r in list(csv.reader(io.StringIO(p.stdout)))[1:]:
            if len(r) < 2 or r[1] in (".", ""):
                continue
            bagian = r[0].split("-")
            if len(bagian) < 2:
                continue
            try:
                keluar[f"{int(bagian[0])}-{int(bagian[1])}"] = float(r[1])
            except ValueError:
                continue
        return keluar
    except Exception:
        return {}


def ambil_ppi(paksa=False):
    """Seri PPI, dari cache kalau masih segar. Return (data, dari_cache, err)."""
    if not paksa and os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                c = json.load(f)
            umur = datetime.now(timezone.utc).timestamp() - c.get("waktu", 0)
            if umur < CACHE_UMUR and c.get("seri"):
                return c["seri"], True, None
        except Exception:
            pass
    seri = {nama: _unduh(kode) for nama, kode in SERI_PPI.items()}
    if not any(seri.values()):
        return {}, False, "seluruh seri PPI gagal diambil dari FRED"
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"waktu": datetime.now(timezone.utc).timestamp(), "seri": seri}, f)
    except OSError as e:
        print(f"[ppi] cache gagal ditulis ({type(e).__name__})", file=sys.stderr)
    return seri, False, None


def geser_bulan(kunci, n):
    th, bl = map(int, kunci.split("-"))
    bl += n
    th += (bl - 1) // 12
    bl = (bl - 1) % 12 + 1
    return f"{th}-{bl}"


def mom(seri, kunci):
    """Perubahan persen bulan-ke-bulan. None kalau bulan sebelumnya tidak ada."""
    sebelum = geser_bulan(kunci, -1)
    a, b = seri.get(kunci), seri.get(sebelum)
    if a is None or not b:
        return None
    return (a - b) / b * 100


def korelasi(x, y):
    if len(x) < MINIMUM_SAMPEL:
        return None
    mx, my = st.mean(x), st.mean(y)
    pembilang = sum((a - mx) * (b - my) for a, b in zip(x, y))
    penyebut = (sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5
    return pembilang / penyebut if penyebut else None


def _arah_cocok(x, y):
    """Berapa persen bulan yang TANDA-nya sama. Ini yang benar-benar dipakai user:
    ia tidak butuh besarnya, ia butuh tahu 'condong ke atas atau ke bawah'."""
    if not x:
        return None
    return sum(1 for a, b in zip(x, y) if (a > 0) == (b > 0)) / len(x) * 100


def pasangkan(riwayat, seri_ppi, geser):
    """(x_ppi, y_kejutan, bulan) untuk satu lag. Bulan tanpa data dilewati."""
    x, y, bulan = [], [], []
    for e in riwayat:
        if e.get("kejutan_pp") is None or not e.get("bulan_target"):
            continue
        p = mom(seri_ppi, geser_bulan(e["bulan_target"], geser))
        if p is None:
            continue
        x.append(p)
        y.append(e["kejutan_pp"])
        bulan.append(e["bulan_target"])
    return x, y, bulan


def uji_luar_sampel(x, y, bagian=0.6):
    """Latih di bagian AWAL, uji di sisanya. Return dict atau None.

    Korelasi dalam-sampel selalu terlihat lebih baik daripada kenyataan karena diukur
    pada data yang sama yang membentuknya. Yang menentukan layak-tidaknya dipakai adalah
    apakah hubungan itu BERTAHAN di bagian yang belum pernah dilihat.
    """
    n = len(x)
    if n < MINIMUM_SAMPEL * 2:
        return None
    potong = int(n * bagian)
    xl, yl = x[:potong], y[:potong]
    xu, yu = x[potong:], y[potong:]
    r_latih = korelasi(xl, yl)
    if r_latih is None:
        return None
    # Regresi linier sederhana dari bagian latih.
    mx, my = st.mean(xl), st.mean(yl)
    var = sum((a - mx) ** 2 for a in xl)
    kemiringan = sum((a - mx) * (b - my) for a, b in zip(xl, yl)) / var if var else 0.0
    potongan = my - kemiringan * mx
    ramal = [kemiringan * a + potongan for a in xu]
    return {
        "n_latih": len(xl),
        "n_uji": len(xu),
        "korelasi_latih": round(r_latih, 3),
        "korelasi_uji": round(korelasi(xu, yu), 3) if korelasi(xu, yu) is not None else None,
        "arah_cocok_uji_persen": round(_arah_cocok(ramal, yu), 1) if yu else None,
        "kemiringan": round(kemiringan, 4),
    }


BLOK_ACAK = 12      # bulan per blok saat mengacak


def uji_acak(x, y, putaran=2000, benih=12345, blok=BLOK_ACAK):
    """Seberapa sering korelasi sekuat ini muncul dari data yang DIACAK — PER BLOK.

    Tanpa ini, "r = 0,3" tidak bisa dibedakan dari kebetulan pada sampel sekecil ini.
    Benihnya tetap supaya hasilnya bisa diulang orang lain.

    KENAPA PER BLOK, BUKAN PER BULAN. Inflasi berautokorelasi: terukur PPI 0,47 dan
    kejutan CPI 0,42 pada lag satu bulan. Mengocok bulan satu per satu menghancurkan
    autokorelasi itu, sehingga data acaknya jauh lebih "berantakan" daripada data asli —
    dan korelasi sungguhan jadi terlihat jauh lebih langka daripada kenyataannya.
    Versi pertama berkas ini melaporkan p=0,000 dengan cara itu. Dikocok per blok 12
    bulan, lag bulan-sebelumnya naik ke p=0,0135: masih signifikan, tapi sekitar 13 kali
    lebih lemah dari yang sempat diklaim.
    """
    r_asli = korelasi(x, y)
    if r_asli is None:
        return None
    rng = random.Random(benih)
    potongan = [y[i:i + blok] for i in range(0, len(y), blok)]
    lebih = 0
    for _ in range(putaran):
        rng.shuffle(potongan)
        acak = [v for b in potongan for v in b][:len(x)]
        r = korelasi(x, acak)
        if r is not None and abs(r) >= abs(r_asli):
            lebih += 1
    return {"putaran": putaran, "blok_bulan": blok, "p_acak": round(lebih / putaran, 4)}


def rezim(bulan):
    """Bagi sampel per era. Hubungan makro sering hanya hidup di satu rezim, dan
    rata-rata seluruh periode menyembunyikan itu."""
    th = int(bulan.split("-")[0])
    if th <= 2019:
        return "2013-2019 (inflasi rendah)"
    if th <= 2022:
        return "2020-2022 (pandemi & lonjakan)"
    return "2023-sekarang (pendinginan)"


def analisa(riwayat, seri_ppi, nama_ppi, geser, label):
    x, y, bulan = pasangkan(riwayat, seri_ppi, geser)
    if len(x) < MINIMUM_SAMPEL:
        return {"prediktor": nama_ppi, "lag": label, "tidak_tersedia":
                f"sampel cuma {len(x)}, minimum {MINIMUM_SAMPEL}"}
    r = korelasi(x, y)
    hasil = {
        "prediktor": nama_ppi,
        "lag": label,
        "n": len(x),
        "periode": f"{bulan[0]} s/d {bulan[-1]}",
        "korelasi": round(r, 3) if r is not None else None,
        "arah_cocok_persen": round(_arah_cocok(x, y), 1),
        "luar_sampel": uji_luar_sampel(x, y),
        "acak": uji_acak(x, y),
        "per_rezim": {},
    }
    for nama_rz in sorted({rezim(b) for b in bulan}):
        xi = [a for a, b in zip(x, bulan) if rezim(b) == nama_rz]
        yi = [a for a, b in zip(y, bulan) if rezim(b) == nama_rz]
        ri = korelasi(xi, yi)
        hasil["per_rezim"][nama_rz] = {
            "n": len(xi),
            "korelasi": round(ri, 3) if ri is not None else None,
            "arah_cocok_persen": round(_arah_cocok(xi, yi), 1) if xi else None,
        }
    return hasil


def vonis(h):
    """Kesimpulan yang bisa dikutip apa adanya. Sengaja keras: alat ini dibuat justru
    supaya bot berhenti menebak, jadi meloloskan hubungan lemah sebagai 'sinyal'
    mengalahkan seluruh tujuannya."""
    if h.get("tidak_tersedia"):
        return "TIDAK BISA DINILAI — " + h["tidak_tersedia"]
    r = abs(h.get("korelasi") or 0)
    arah = h.get("arah_cocok_persen") or 0
    ls = h.get("luar_sampel") or {}
    r_uji = abs(ls.get("korelasi_uji") or 0)
    p = (h.get("acak") or {}).get("p_acak", 1)
    rz = {k: v.get("korelasi") for k, v in h.get("per_rezim", {}).items()
          if v.get("korelasi") is not None}
    tanda_konsisten = len({x > 0 for x in rz.values()}) == 1 if rz else False
    # Tanda saja TIDAK cukup. Versi pertama pemeriksa ini meloloskan hubungan yang di
    # era 2013-2019 korelasinya 0,022 — praktis nol — sebagai "konsisten", cuma karena
    # angkanya kebetulan positif. Padahal justru itu peringatan terpentingnya: hubungan
    # ini hidup di rezim inflasi tinggi dan mati di rezim tenang, dan rata-rata seluruh
    # periode menyembunyikannya.
    mati = [k for k, v in rz.items() if abs(v) < 0.1]

    if r < AMBANG_KORELASI or arah < AMBANG_ARAH:
        return "TIDAK ADA EDGE — terlalu lemah untuk dipakai"
    if p > 0.05:
        return f"TIDAK MEYAKINKAN — kekuatan sebesar ini muncul dari data acak {p:.1%}"
    if r_uji < AMBANG_KORELASI * 0.6:
        return "GUGUR DI LUAR SAMPEL — hanya bertahan di data yang membentuknya"
    if not tanda_konsisten:
        return "TIDAK STABIL — arahnya berbalik antar-rezim"
    if mati:
        return ("BERGANTUNG REZIM — nyata di rezim inflasi tinggi, tapi praktis NOL di "
                + "; ".join(f"{k} (r={rz[k]})" for k in mati)
                + ". Jangan dipakai sebagai aturan tetap.")
    return "LEMAH TAPI NYATA — condong, bukan kepastian"


def jalankan(paksa=False):
    sys.path.insert(0, BASE_DIR) if BASE_DIR not in sys.path else None
    import kejutan
    data, _, err = kejutan.deret_kejutan("CPI", paksa=paksa)
    riwayat = (data or {}).get("riwayat") or []
    if err or not riwayat:
        return {"tidak_tersedia": f"kejutan CPI tidak tersedia: {err or 'kosong'}"}
    seri, dari_cache, err_ppi = ambil_ppi(paksa=paksa)
    if err_ppi:
        return {"tidak_tersedia": err_ppi}

    keluar = {
        "pertanyaan": "Apakah PPI memprediksi KEJUTAN CPI (aktual - ramalan)?",
        "sumber": {
            "kejutan_cpi": "Cleveland Fed nowcast (kejutan terhadap MODEL, bukan "
                           "median survei Wall Street)",
            "ppi": "FRED " + ", ".join(SERI_PPI.values()),
        },
        "dari_cache": dari_cache,
        "hasil": [],
    }
    for nama, s in seri.items():
        if not s:
            continue
        for geser, label in [(-1, "PPI bulan SEBELUMNYA (selalu sah untuk meramal)"),
                             (0, "PPI bulan SAMA (sah HANYA bila PPI terbit lebih dulu)")]:
            h = analisa(riwayat, s, nama, geser, label)
            h["vonis"] = vonis(h)
            keluar["hasil"].append(h)
    keluar["wajib_dibaca"] = (
        "Lag 'bulan SAMA' korelasinya lebih tinggi dan itu menggoda, tapi ia hanya sah "
        "kalau PPI benar-benar terbit LEBIH DULU dari CPI pada siklus itu. Urutan rilis "
        "berubah-ubah antar-tahun. Kalau PPI terbit SESUDAH CPI, angka itu hubungan "
        "sezaman — bukan ramalan. "
        "Porsi terbesar CPI adalah sewa/OER yang sama sekali tidak ada di PPI, jadi PPI "
        "memang bukan pemandu mekanis untuk CPI; hubungan apa pun di sini condong, bukan "
        "kepastian. Kejutannya juga terhadap model Cleveland Fed, bukan konsensus pasar. "
        # Tidak bisa diukur dari sumber gratis, jadi WAJIB diakui, bukan didiamkan.
        "Angka PPI dari FRED adalah versi REVISI TERAKHIR, bukan angka yang tersedia saat "
        "rilis — PPI memang direvisi. Artinya uji historis ini sedikit lebih optimistis "
        "daripada yang bisa dicapai secara nyata di waktu itu.")
    return keluar


def cetak(hasil):
    if hasil.get("tidak_tersedia"):
        print("TIDAK TERSEDIA:", hasil["tidak_tersedia"])
        return 1
    print("PERTANYAAN:", hasil["pertanyaan"])
    print()
    for h in hasil["hasil"]:
        if h.get("tidak_tersedia"):
            print(f"{h['prediktor']} | {h['lag']}: {h['tidak_tersedia']}")
            continue
        print(f"{h['prediktor']} — {h['lag']}")
        print(f"  n={h['n']} ({h['periode']}) korelasi={h['korelasi']} "
              f"arah cocok={h['arah_cocok_persen']}%")
        ls = h.get("luar_sampel")
        if ls:
            print(f"  luar sampel: latih {ls['n_latih']} (r={ls['korelasi_latih']}) -> "
                  f"uji {ls['n_uji']} (r={ls['korelasi_uji']}, "
                  f"arah {ls['arah_cocok_uji_persen']}%)")
        ac = h.get("acak")
        if ac:
            print(f"  uji acak: p={ac['p_acak']} dari {ac['putaran']} pengacakan")
        for nama, v in h["per_rezim"].items():
            print(f"    {nama}: n={v['n']} r={v['korelasi']} arah={v['arah_cocok_persen']}%")
        print(f"  VONIS: {h['vonis']}")
        print()
    print("WAJIB DIBACA:", hasil["wajib_dibaca"])
    return 0


def main():
    ap = argparse.ArgumentParser(description="Apakah PPI memprediksi kejutan CPI")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--paksa", action="store_true", help="abaikan cache")
    args = ap.parse_args()
    hasil = jalankan(paksa=args.paksa)
    if args.json:
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return 0 if not hasil.get("tidak_tersedia") else 1
    return cetak(hasil)


if __name__ == "__main__":
    sys.exit(main())

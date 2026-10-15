"""A3 Adoption Clock — pemegang 13F ETF spot BTC AS per kuartal, dari Form 13F Data Sets SEC.

SEC menerbitkan seluruh isi 13F sebagai berkas zip per rentang TANGGAL FILING (tabel
SUBMISSION, COVERPAGE, INFOTABLE). Skrip ini memindai INFOTABLE untuk baris ETF spot BTC,
lalu menjumlah per PERIODOFREPORT: jumlah filer dan nilai (USD — sejak 2023 kolom VALUE
dalam dolar, bukan ribuan). Hanya 13F-HR asli; amandemen (13F-HR/A) diabaikan supaya satu
filer tidak terhitung dua kali.

Tiap filer menyerahkan satu 13F-HR per kuartal, jadi hasil per data set bisa DIJUMLAH lintas
data set tanpa menyimpan daftar filer — itu yang membuat pembaruan inkremental murah.

BATAS JUJUR: jenis pemegang (penasihat vs hedge fund basis-trade) TIDAK dipisah. 13F tidak
punya kolom jenis, dan menebak dari nama filer tidak bisa diaudit. Sebagian kepemilikan hedge
fund adalah long ETF + short futures (netral arah) — sebut itu saat mengutip.

Butuh secret SEC_CONTACT (lihat seckontak.py); dari jaringan pengembang SEC membalas 403,
jadi dijalankan di workflow jam-mingguan.

    python cloud/etf_13f.py            # proses data set yang belum diproses
    python cloud/etf_13f.py --semua    # ulang dari nol
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seckontak  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HALAMAN = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
SEC = "https://www.sec.gov"
F13_PATH = os.path.join(BASE_DIR, "data", "etf_13f.json")
MULAI = "2024"          # ETF spot BTC mulai diperdagangkan 11 Jan 2024

# Nama penerbit di 13F berupa singkatan huruf besar ("ISHARES BITCOIN TR", "FIDELITY WISE
# ORIGIN BITCOIN", "ARK 21SHARES BITCOIN ETF"). Semua yang memuat BITCOIN, KECUALI produk
# futures/leverage/opsi/penambang — itu bukan permintaan BTC spot.
_BTC = re.compile(r"BITCOIN|\bBTC\b")
_BUKAN = re.compile(r"STRATEGY|FUTURE|MINING|MINER|DEPOT|2X|ULTRA|SHORT|INVERSE|INCOME|"
                    r"COVERED|OPTION|YIELD|LEVERAG|BUFFER|PREMIUM|TREASURY CO|ETHER|MSTR")


def cocok(nama):
    nama = (nama or "").upper()
    return bool(_BTC.search(nama)) and not _BUKAN.search(nama)


def _get(url, biner=False):
    if seckontak.alasan_kosong():
        raise RuntimeError(seckontak.alasan_kosong())
    req = urllib.request.Request(url, headers=seckontak.header())
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read() if biner else r.read().decode("utf-8", errors="replace")


def daftar_data_set():
    html = _get(HALAMAN)
    tautan = sorted(set(re.findall(r'href="([^"]*form13f[^"]*\.zip)"', html, re.I)))
    # Nama berkas memuat tahun filing, mis. 01dec2023-29feb2024_form13f.zip
    return [t for t in tautan if any(str(y) in t for y in range(int(MULAI), 2100))]


def _baca(z, nama):
    cari = [n for n in z.namelist() if n.upper().endswith(nama)]
    if not cari:
        raise ValueError(f"{nama} tidak ada di zip")
    return csv.DictReader(io.TextIOWrapper(z.open(cari[0]), encoding="utf-8",
                                           errors="replace"), delimiter="\t")


def proses_zip(path):
    """{periode ISO: {"filer": n, "nilai_usd": x}}, {penerbit: jumlah baris}."""
    with zipfile.ZipFile(path) as z:
        asli = {}
        for b in _baca(z, "SUBMISSION.TSV"):
            if (b.get("SUBMISSIONTYPE") or "").strip() == "13F-HR":
                try:
                    asli[b["ACCESSION_NUMBER"]] = datetime.strptime(
                        b["PERIODOFREPORT"].strip(), "%d-%b-%Y").date().isoformat()
                except (KeyError, ValueError):
                    continue
        per, filer, penerbit = {}, {}, {}
        for b in _baca(z, "INFOTABLE.TSV"):
            acc = b.get("ACCESSION_NUMBER")
            if acc not in asli or (b.get("PUTCALL") or "").strip():
                continue
            if not cocok(b.get("NAMEOFISSUER")):
                continue
            try:
                v = float(b.get("VALUE") or 0)
            except ValueError:
                continue
            p = asli[acc]
            per.setdefault(p, 0.0)
            per[p] += v
            filer.setdefault(p, set()).add(acc)
            n = (b.get("NAMEOFISSUER") or "").strip().upper()
            penerbit[n] = penerbit.get(n, 0) + 1
    return ({p: {"filer": len(filer[p]), "nilai_usd": per[p]} for p in per}, penerbit)


def perbarui(semua=False):
    try:
        with open(F13_PATH, encoding="utf-8") as f:
            simpan = json.load(f)
    except (OSError, ValueError):
        simpan = {}
    if semua:
        simpan = {}
    simpan.setdefault("per_data_set", {})
    simpan.setdefault("penerbit_cocok", {})
    baru = [t for t in daftar_data_set() if t.rsplit("/", 1)[-1] not in simpan["per_data_set"]]
    for t in baru:
        nama = t.rsplit("/", 1)[-1]
        url = t if t.startswith("http") else SEC + t
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, nama)
            with open(path, "wb") as f:
                f.write(_get(url, biner=True))
            hasil, penerbit = proses_zip(path)
        simpan["per_data_set"][nama] = hasil
        for k, v in penerbit.items():
            simpan["penerbit_cocok"][k] = simpan["penerbit_cocok"].get(k, 0) + v
        print(f"{nama}: {sum(h['filer'] for h in hasil.values())} filing ETF BTC", flush=True)
        time.sleep(1)          # fair access SEC: jauh di bawah 10 permintaan/detik
    total = {}
    for hasil in simpan["per_data_set"].values():
        for p, h in hasil.items():
            t = total.setdefault(p, {"filer": 0, "nilai_usd": 0.0})
            t["filer"] += h["filer"]
            t["nilai_usd"] += h["nilai_usd"]
    simpan["kuartal"] = [{"akhir_kuartal": p, "pemegang": t["filer"],
                          "nilai_usd": round(t["nilai_usd"])}
                         for p, t in sorted(total.items()) if p >= MULAI]
    simpan["diperbarui_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    simpan["catatan"] = ("13F-HR asli saja; jenis pemegang tidak dipisah (basis trade "
                         "hedge fund ikut terhitung). Kuartal terakhir bisa belum lengkap "
                         "kalau data set SEC untuk rentang filing-nya belum terbit.")
    os.makedirs(os.path.dirname(F13_PATH), exist_ok=True)
    with open(F13_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(simpan, f, ensure_ascii=False, indent=1, sort_keys=True)
    return simpan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semua", action="store_true")
    a = ap.parse_args()
    s = perbarui(a.semua)
    for q in s["kuartal"]:
        print(f"{q['akhir_kuartal']}  pemegang {q['pemegang']:>5}  nilai ${q['nilai_usd'] / 1e9:,.1f} M")


if __name__ == "__main__":
    main()

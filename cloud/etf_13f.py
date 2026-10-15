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

# Nama penerbit di 13F diketik bebas oleh tiap filer ("ISHARES BITCOIN TR", "ISHS BITCOIN
# TRUST", "RAYSCALE BITCOIN MINI TR ET"). Versi pertama mencocokkan SEMUA yang memuat
# "BITCOIN" lalu membuang pengecualian — run 38746731651 membuktikan itu bocor: saham
# penambang (American Bitcoin Corp), SPAC (BTC Dev Corp, Bitcoin Infrastructure Acqui),
# ETF futures (ProShares), covered call / protection / floor, Grayscale Bitcoin CASH, dan
# "BlackRock Institutional Trust ... BTC iShares MSCI". Sekarang DAFTAR PUTIH: keluarga
# penerbit ETF spot + kata Bitcoin, lalu pengecualian produk turunannya.
VERSI_COCOK = 2
_FAMILI = re.compile(r"I ?SHARES?|ISHS|ISHA|IBIT|FIDELITY|WISE ORIGIN|G?R[AE]YSCALE|\bARK\b|"
                     r"21 ?SHARES|BITWISE|ITWISE|INVESCO|GALAXY|VAN ?ECK|ANECK|FRANKLIN|"
                     r"VALKYRIE|COINSHARES|COINSHRS|WISDOMTREE|ISDOMTREE|HASHDEX|"
                     r"MORGAN STANLEY|BITCOIN INVESTMENT TR")
_BITCOIN = re.compile(r"BITC(?:OI|IO|O)N")
_BUKAN = re.compile(r"CASH|BCH|\bCOV|CALL|\bCC\b|PREM|FLOOR|STRUCT|PROTECT|STANDARD|CORP|"
                    r"EX-BTC|ACTIVE|FUT|MINER|MINING|\bAND\b|\bPUT\b|PROSHARES|STRAT|"
                    r"INCOME|\bINC\b|INSTITUTIONAL TRUST COMPANY|LEVERAG|2X|SHORT|INVERSE")


def cocok(nama):
    nama = re.sub(r"\s+", " ", (nama or "").upper())
    return bool(_FAMILI.search(nama) and _BITCOIN.search(nama)) and not _BUKAN.search(nama)


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
    if semua or simpan.get("versi_cocok") != VERSI_COCOK:
        simpan = {"versi_cocok": VERSI_COCOK}
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


ADV_HALAMAN = (
    "https://www.sec.gov/data-research/sec-markets-data/"
    "information-about-registered-investment-advisers-exempt-reporting-advisers",
    "https://www.sec.gov/foia-services/frequently-requested-documents/form-adv-data",
)


def periksa():
    """Bentuk data untuk memisahkan JENIS pemegang: kolom COVERPAGE 13F (adakah CRD /
    nomor berkas 801- penasihat?) dan berkas data Form ADV. Hanya nama kolom & hitungan
    yang dicetak — tidak ada nama atau alamat filer."""
    t = daftar_data_set()[-1]
    url = t if t.startswith("http") else SEC + t
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "x.zip")
        with open(path, "wb") as f:
            f.write(_get(url, biner=True))
        with zipfile.ZipFile(path) as z:
            print("isi zip:", z.namelist())
            baris = list(_baca(z, "COVERPAGE.TSV"))
    print("COVERPAGE kolom:", list(baris[0].keys()))
    for k in baris[0]:
        isi = [b[k] for b in baris if (b.get(k) or "").strip()]
        print(f"  {k}: terisi {len(isi)}/{len(baris)}"
              + (f" contoh awalan {sorted({x[:4] for x in isi})[:8]}"
                 if k.upper() in ("CRDNUMBER", "SECFILENUMBER", "FORM13FFILENUMBER") else ""))
    for h in ADV_HALAMAN:
        try:
            html = _get(h)
        except Exception as e:
            print(h, "gagal", type(e).__name__)
            continue
        z = sorted(set(re.findall(r'href="([^"]+\.zip)"', html, re.I)))
        print(h, "->", len(z), "zip;", z[:6], "...", z[-6:])
        ia = [x for x in z if re.search(r"/ia\d{6}\.zip$", x)]
        if ia:
            terbaru = max(ia, key=lambda x: (x[-6:-4], x[-10:-8], x[-8:-6]))
            print("berkas IA terbaru:", terbaru)
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "ia.zip")
                with open(path, "wb") as f:
                    f.write(_get(terbaru if terbaru.startswith("http") else SEC + terbaru,
                                 biner=True))
                with zipfile.ZipFile(path) as zz:
                    print("isi:", zz.namelist())
                    nama = zz.namelist()[0]
                    with zz.open(nama) as f:
                        kepala = f.readline().decode("latin-1").rstrip()
                        n = sum(1 for _ in f)
            kol = re.split(r"[,|	]", kepala)
            print(f"{len(kol)} kolom, {n} baris")
            for k in kol:
                if re.search(r"5D|5F|7B|Pool|Hedge|CRD|Organization CRD|SEC#|Legal Name|Primary",
                             k, re.I):
                    print("  kolom:", k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semua", action="store_true")
    ap.add_argument("--periksa", action="store_true")
    a = ap.parse_args()
    if a.periksa:
        periksa()
        return
    s = perbarui(a.semua)
    for q in s["kuartal"]:
        print(f"{q['akhir_kuartal']}  pemegang {q['pemegang']:>5}  "
              f"nilai ${q['nilai_usd'] / 1e9:,.1f} miliar")


if __name__ == "__main__":
    main()

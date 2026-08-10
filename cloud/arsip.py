"""Arsip konsensus & aktual rilis ekonomi — menumbuhkan data yang tidak dijual gratis.

MASALAH YANG DIPECAHKAN: kejutan.py bisa mengukur reaksi harga menurut arah kejutan untuk
CPI karena Cleveland Fed kebetulan menerbitkan nowcast beserta aktualnya sejak 2013. Untuk
NFP, PPI, dan FOMC tidak ada padanannya — tidak satu pun sumber gratis menyimpan KONSENSUS
HISTORIS. Feed Forex Factory memuat konsensus, tapi hanya untuk pekan berjalan; begitu
pekannya lewat, angkanya hilang selamanya.

Solusinya bukan mencari sumber baru, melainkan BERHENTI MEMBUANG yang sudah lewat. Tiap kali
kalender.py menarik feed, rilis berdampak tinggi dicatat ke sini. Satu acara muncul dua kali
dalam siklus hidupnya — sebelum rilis (aktual kosong) dan sesudah (aktual terisi) — jadi
pencatatannya UPSERT, dan aktual yang sudah terisi TIDAK BOLEH tertimpa kosong oleh cache
lama.

KAPAN INI BERGUNA: sekitar 570 acara berdampak tinggi per tahun, tapi yang relevan untuk
satu indikator hanya ~12 per tahun. Jadi arsipnya baru bermakna secara statistik setelah
belasan bulan. Sampai itu tercapai, `--status` melaporkan apa adanya dan analisa TIDAK BOLEH
memakai angkanya sebagai bukti. Ini investasi, bukan sumber siap pakai.

Pemakaian:
    python cloud/arsip.py --status
    python cloud/arsip.py --cari "Non-Farm" --mata-uang USD
"""

import argparse
import json
import os
import re
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARSIP_PATH = os.path.join(BASE_DIR, "data", "arsip_konsensus.jsonl")

# Hanya dampak tinggi. Yang berdampak rendah jumlahnya lima kali lipat dan tidak pernah
# dipakai untuk studi kejutan — mengarsipkannya cuma menggemukkan berkas yang di-commit
# ulang setiap run.
DAMPAK_DIARSIP = ("tinggi",)

# Akhiran satuan pada nilai Forex Factory. Kejutan hanya dihitung bila satuannya SAMA;
# "0.2%" dikurangi "150K" tidak berarti apa-apa.
_RE_NILAI = re.compile(r"^\s*(-?\d[\d.,]*)\s*([%KMBT]?)\s*$", re.I)


def _angka(v):
    """'0.2%' -> (0.2, '%') · '-23K' -> (-23.0, 'K') · '158858' -> (158858.0, '')."""
    if v is None:
        return None, None
    m = _RE_NILAI.match(str(v))
    if not m:
        return None, None
    teks = m.group(1).replace(",", "")
    try:
        return float(teks), m.group(2).upper()
    except ValueError:
        return None, None


def _kunci(r):
    return f"{r.get('waktu')}|{r.get('mata_uang')}|{r.get('nama')}"


def muat():
    """Baca arsip jadi dict kunci->catatan. Baris rusak dilewati, bukan mematikan proses."""
    catatan = {}
    try:
        with open(ARSIP_PATH, encoding="utf-8") as f:
            for baris in f:
                baris = baris.strip()
                if not baris:
                    continue
                try:
                    r = json.loads(baris)
                except ValueError:
                    continue
                if r.get("waktu") and r.get("nama"):
                    catatan[_kunci(r)] = r
    except OSError:
        pass
    return catatan


def _tulis(catatan):
    """Ditulis terurut waktu supaya diff antar-run kecil dan bisa dibaca manusia."""
    os.makedirs(os.path.dirname(ARSIP_PATH), exist_ok=True)
    baris = sorted(catatan.values(), key=lambda r: (r.get("waktu") or "", r.get("nama") or ""))
    with open(ARSIP_PATH, "w", encoding="utf-8", newline="\n") as f:
        for r in baris:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def catat(rilis):
    """Upsert rilis berdampak tinggi. Return (baru, diperbarui, total)."""
    catatan = muat()
    sekarang = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    baru = diperbarui = 0

    for r in rilis or []:
        if (r.get("dampak") or "").lower() not in DAMPAK_DIARSIP:
            continue
        if not (r.get("waktu") and r.get("nama")):
            continue
        k = _kunci(r)
        isi = {"waktu": r.get("waktu"), "mata_uang": r.get("mata_uang"),
               "nama": r.get("nama"), "dampak": r.get("dampak"),
               "konsensus": r.get("konsensus"), "sebelumnya": r.get("sebelumnya"),
               "aktual": r.get("aktual")}
        lama = catatan.get(k)
        if lama is None:
            isi["dicatat_utc"] = sekarang
            catatan[k] = isi
            baru += 1
            continue
        # Feed bisa datang dari cache 6 jam. Menimpa aktual yang sudah terisi dengan kosong
        # akan MENGHAPUS satu-satunya salinan angka itu — arsip ini tidak punya cadangan.
        berubah = False
        for kolom in ("konsensus", "sebelumnya", "aktual"):
            nilai = isi.get(kolom)
            if nilai is None:
                continue
            if lama.get(kolom) != nilai:
                lama[kolom] = nilai
                berubah = True
        if berubah:
            lama["diperbarui_utc"] = sekarang
            diperbarui += 1

    if baru or diperbarui:
        _tulis(catatan)
    return baru, diperbarui, len(catatan)


def kejutan(r):
    """aktual - konsensus, hanya bila keduanya angka dengan satuan yang sama."""
    a, sa = _angka(r.get("aktual"))
    k, sk = _angka(r.get("konsensus"))
    if a is None or k is None or sa != sk:
        return None
    return round(a - k, 4)


def deret(cari=None, mata_uang=None):
    """Catatan yang SUDAH lengkap (punya konsensus dan aktual), terurut waktu."""
    hasil = []
    for r in muat().values():
        if cari and cari.lower() not in (r.get("nama") or "").lower():
            continue
        if mata_uang and (r.get("mata_uang") or "").upper() != mata_uang.upper():
            continue
        s = kejutan(r)
        if s is None:
            continue
        hasil.append(dict(r, kejutan=s))
    hasil.sort(key=lambda r: r.get("waktu") or "")
    return hasil


def status():
    catatan = muat()
    lengkap = [r for r in catatan.values() if kejutan(r) is not None]
    waktu = sorted(r.get("waktu") or "" for r in catatan.values())
    per_nama = {}
    for r in lengkap:
        per_nama[r.get("nama")] = per_nama.get(r.get("nama"), 0) + 1
    siap = {n: j for n, j in per_nama.items() if j >= 10}
    return {
        "total_acara": len(catatan),
        "punya_kejutan_terhitung": len(lengkap),
        "rentang": f"{waktu[0][:10]} s/d {waktu[-1][:10]}" if waktu else None,
        "acara_terbanyak": dict(sorted(per_nama.items(), key=lambda x: -x[1])[:8]),
        "siap_dipakai": siap or "BELUM ADA",
        "aturan_pakai": (
            "Arsip ini TUMBUH dari nol dan hanya bertambah ~12 kejadian per indikator per "
            "tahun. Selama satu indikator punya kurang dari 10 kejadian, angkanya TIDAK "
            "BOLEH dipakai sebagai bukti — sebut sebagai catatan awal, atau jangan sebut "
            "sama sekali. Konsensus berasal dari kompilasi Forex Factory, bukan median "
            "survei ekonom resmi; sebutkan sumbernya saat mengutip."),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="ringkasan isi arsip")
    ap.add_argument("--cari", help="saring nama acara, mis. 'Non-Farm'")
    ap.add_argument("--mata-uang", dest="mata_uang", help="saring mata uang, mis. USD")
    args = ap.parse_args()

    if args.cari or args.mata_uang:
        d = deret(args.cari, args.mata_uang)
        keluar = {"jumlah": len(d), "catatan": d[-24:]}
        if len(d) < 10:
            keluar["peringatan"] = (
                f"SAMPEL KECIL ({len(d)} kejadian) — tidak bermakna secara statistik. "
                "Arsip ini baru dimulai; jangan dipakai sebagai bukti.")
    else:
        keluar = status()
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

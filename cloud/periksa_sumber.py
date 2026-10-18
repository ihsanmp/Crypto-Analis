"""Diagnostik sumber data bot — mana yang GAGAL, KOSONG, atau sebagian hilang, DI RUNNER.

Log Actions bot hanya mencatat script yang keluar dengan galat; sumber yang "jalan tapi
kosong" (CoinGecko 429, field tidak_tersedia di dalam JSON) tidak pernah tercatat, sehingga
bagian yang sering bermasalah tidak bisa ditentukan dari log. Script ini mengumpulkan brief
yang SAMA dengan bot (data_mentah_crypto / data_mentah_pasar) tanpa memanggil Claude dan
tanpa mengirim apa pun ke Telegram, lalu meringkas per blok.

Repo PUBLIK, jadi log workflow publik: yang dicetak hanya judul blok, status, dan potongan
pendek pesan galat yang sudah dibersihkan dari alamat dompet / URL ber-query.

    python cloud/periksa_sumber.py                       # daftar bawaan
    python cloud/periksa_sumber.py BTC AAVE --pasar NVDA:saham GC=F:forex
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

KOIN_BAWAAN = ["BTC", "ETH", "SOL", "AAVE", "HYPE", "PUMP", "ENA", "PEPE", "XLM", "TAO"]
PASAR_BAWAAN = ["NVDA:saham", "GC=F:forex", "EURUSD:forex", "CL=F:forex"]

_TANDA = re.compile(r'"(tidak_tersedia|error|gagal|galat|catatan_gagal)"\s*:\s*"([^"]{0,160})'
                    r'|(GAGAL DIAMBIL[^\n]{0,120})|(semua sumber gagal[^\n]{0,80})', re.I)
_RAHASIA = re.compile(r"0x[0-9a-fA-F]{8,}|[1-9A-HJ-NP-Za-km-z]{32,}|https?://\S+")


def _bersih(t):
    return _RAHASIA.sub("…", t).strip()[:110]


def pecah_blok(brief):
    """'[JUDUL]\\nisi' -> [(judul, isi)]. Judul = baris pertama dalam kurung siku."""
    keluar = []
    for bagian in re.split(r"\n\n(?=\[)", brief or ""):
        kepala, _, isi = bagian.partition("\n")
        if kepala.startswith("[") and kepala.endswith("]"):
            keluar.append((kepala.strip("[]"), isi))
    return keluar


def nilai_blok(judul, isi):
    """-> (status, [masalah]). GAGAL = script galat; KOSONG = jalan tanpa data;
    SEBAGIAN = ada field tidak_tersedia/error di dalamnya; OK."""
    if isi.startswith("GAGAL DIAMBIL"):
        return "GAGAL", [_bersih(isi.split("\n", 1)[0])]
    masalah = []
    for m in _TANDA.finditer(isi):
        teks = m.group(2) or m.group(3) or m.group(4) or ""
        kunci = m.group(1) or ""
        masalah.append(_bersih(f"{kunci}: {teks}" if kunci else teks))
    if not isi.strip() or re.fullmatch(r"\s*(\{\s*\}|null|\[\s*\])\s*", isi):
        return "KOSONG", masalah or ["isi kosong"]
    if masalah:
        return "SEBAGIAN", masalah
    return "OK", []


def periksa(nama, fungsi):
    t0 = time.time()
    try:
        brief = fungsi()
    except Exception as e:
        return {"aset": nama, "galat": type(e).__name__, "detik": round(time.time() - t0, 1)}
    blok = []
    for judul, isi in pecah_blok(brief):
        st, masalah = nilai_blok(judul, isi)
        blok.append({"blok": judul, "status": st, "masalah": masalah[:4]})
    return {"aset": nama, "detik": round(time.time() - t0, 1), "karakter": len(brief),
            "blok": blok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("koin", nargs="*")
    ap.add_argument("--pasar", nargs="*", default=None, help="SIMBOL:jenis (saham/forex)")
    ap.add_argument("--json", default=None, help="simpan hasil lengkap ke berkas ini")
    a = ap.parse_args()
    import bot_oneshot as bot
    bot._sisipkan_jejak = lambda bagian: None        # tanpa jejak pesan lama
    bot._sisipkan_pantau = lambda bagian, teks: None

    koin = a.koin or (KOIN_BAWAAN if a.pasar is None else [])
    pasar = PASAR_BAWAAN if a.pasar is None and not a.koin else (a.pasar or [])
    hasil = []
    for k in koin:
        hasil.append(periksa(k, lambda k=k: bot.data_mentah_crypto(k, proyeksi=True)))
        print(f"selesai {k} ({hasil[-1].get('detik')} dtk)", file=sys.stderr)
    for p in pasar:
        sim, _, jenis = p.partition(":")
        hasil.append(periksa(sim, lambda s=sim, j=jenis or "saham":
                             bot.data_mentah_pasar(s, j, proyeksi=True)))
        print(f"selesai {sim} ({hasil[-1].get('detik')} dtk)", file=sys.stderr)

    # Rekap: blok mana yang paling sering bermasalah, lintas aset.
    rekap = Counter()
    contoh = {}
    for h in hasil:
        for b in h.get("blok", []):
            nama = re.sub(r"\s+[A-Z0-9=.$-]{2,10}\s+\(", " (", b["blok"])   # buang ticker
            rekap[(nama, b["status"])] += 1
            if b["status"] != "OK":
                contoh.setdefault(nama, set()).update(f"{h['aset']}: {m}"
                                                      for m in b["masalah"][:2])
    print("\n== REKAP PER BLOK (status x jumlah aset) ==")
    nama_blok = sorted({n for n, _ in rekap})
    for n in sorted(nama_blok, key=lambda n: -sum(v for (m, s), v in rekap.items()
                                                 if m == n and s != "OK")):
        st = {s: v for (m, s), v in rekap.items() if m == n}
        buruk = sum(v for s, v in st.items() if s != "OK")
        print(f"{buruk:>2} bermasalah | {n} | {st}")
        for c in sorted(contoh.get(n, []))[:6]:
            print(f"      - {c}")
    galat = [h for h in hasil if "galat" in h]
    for h in galat:
        print(f"!! {h['aset']}: pengumpulan data galat {h['galat']}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(hasil, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

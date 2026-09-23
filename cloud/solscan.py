"""Solscan Pro API v2 — Solana. HANYA BACA.

KENAPA ADA: untuk Solana, daftar trader GMGN mentok di 100 teratas per token. Solscan
memberi SETIAP alamat yang pernah menyentuh satu token (`token/transfer`) dan seluruh
pemegangnya (`token/holders`, dengan `total` yang sebenarnya) — halaman demi halaman.
Itulah yang membuat dompet kecil masih terjangkau.

SOAL KUNCI DAN PAKET — dua hal yang sering dikira satu:
Solscan membagikan kunci begitu akun dibuat (API Management -> Generate Key), tapi kunci
itu "tied to your account and current plan". Tabel paket resminya (23 Sep 2026) dimulai
dari Lite $49/bulan, dan tidak ada baris gratis di sana. Jadi punya kunci belum tentu
punya akses.

Modul ini sengaja TIDAK memutuskan siapa yang benar. `--periksa` menembak endpoint publik
(gratis) dan endpoint pro satu per satu lalu mencetak jawaban apa adanya — kalau kunci
bawaan ternyata cukup, barisnya akan berbunyi "diterima", dan itu bukti yang mengalahkan
tabel harga mana pun. Kalau ditolak, pesan penolakannya ikut dicetak supaya sebabnya
terbaca, bukan muncul sebagai daftar alamat yang diam-diam kosong.

Kuncinya dikirim sebagai header `token` — bukan query, bukan bearer.

Pemakaian:
    python cloud/solscan.py --periksa
    python cloud/solscan.py <MINT>
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASIS = "https://pro-api.solscan.io/v2.0"
PUBLIK = f"{BASIS}/chaininfo"          # dokumennya menyebut ini "API Public"...
NAMA_ENV = "SOLSCAN_API_KEY"
TIMEOUT = 20
# Paket termurah yang terdaftar: 1.000 permintaan/60 detik. Jeda ini menahannya jauh di
# bawah itu — batas laju yang tertabrak muncul sebagai daftar yang lebih pendek, bentuk
# kegagalan yang paling mudah dibaca sebagai "alamatnya memang cuma segini".
JEDA_MIN = 0.2
_terakhir = [0.0]

HALAMAN_TRANSFER = 100   # nilai yang diizinkan: 10, 20, 30, 40, 60, 100
HALAMAN_PEMEGANG = 40    # nilai yang diizinkan: 10, 20, 30, 40
MAKS_HALAMAN = 10
TANDA_POTONG = "dipotong di batas"


def kunci():
    return (os.environ.get(NAMA_ENV) or "").strip()


def catatan_kunci():
    if kunci():
        return None
    return (f"{NAMA_ENV} belum dipasang, jadi Solscan tidak dipakai sama sekali. Ini bukan "
            f"'tidak ada datanya' — bagian itu memang belum diperiksa.")


def _tahan_laju():
    sisa = JEDA_MIN - (time.time() - _terakhir[0])
    if sisa > 0:
        time.sleep(sisa)
    _terakhir[0] = time.time()


def _url(jalur, param):
    return f"{BASIS}/{jalur}?{urllib.parse.urlencode(param)}"


def try_json(url, ulang=True):
    """{"__err": ...} kalau gagal. Kunci tidak pernah ikut tercetak di pesan galat."""
    d = _sekali(url)
    if ulang and "__err" in d and ("429" in d["__err"] or "rate" in d["__err"].lower()):
        time.sleep(1.5)
        d = _sekali(url)
    return d


def _sekali(url):
    _tahan_laju()
    kepala = {"accept": "application/json",
              "User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
    if kunci():
        kepala["token"] = kunci()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=kepala),
                                    timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # Badannya memuat sebabnya ("Token is missing", "not subscribed", ...) dan itulah
        # yang menjelaskan apakah masalahnya kunci atau paket.
        try:
            isi = json.loads(e.read().decode())
            pesan = (isi.get("errors") or {}).get("message") or isi.get("message")
        except Exception:
            pesan = None
        return {"__err": f"HTTP {e.code}" + (f": {str(pesan)[:120]}" if pesan else "")}
    except Exception as e:
        return {"__err": type(e).__name__}
    if isinstance(d, dict) and d.get("success") is False:
        pesan = (d.get("errors") or {}).get("message") or "ditolak"
        return {"__err": str(pesan)[:160]}
    return d


def _halaman(jalur, param, ambil, maks_halaman, ukuran):
    """Kerangka bersama untuk transfer & pemegang: (nilai, jumlah_baris, halaman, galat)."""
    nilai, baris_total, halaman = set(), 0, 0
    for h in range(1, max(1, maks_halaman) + 1):
        d = try_json(_url(jalur, dict(param, page=h, page_size=ukuran)))
        if "__err" in d:
            if baris_total:
                break
            return set(), 0, 0, d["__err"]
        isi = d.get("data")
        baris = isi.get("items") if isinstance(isi, dict) else isi
        if not isinstance(baris, list) or not baris:
            break
        halaman = h
        baris_total += len(baris)
        for b in baris:
            if isinstance(b, dict):
                nilai.update(ambil(b))
        if len(baris) < ukuran:
            break
    return nilai, baris_total, halaman, None


def alamat_token(mint, maks_halaman=MAKS_HALAMAN):
    """(alamat, catatan) — setiap alamat yang pernah menyentuh token ini."""
    if not kunci():
        return set(), catatan_kunci()

    def ambil(b):
        return [str(b.get(k) or "") for k in ("from_address", "to_address") if b.get(k)]

    alamat, transfer, halaman, err = _halaman(
        "token/transfer", {"address": mint, "sort_by": "block_time", "sort_order": "desc"},
        ambil, maks_halaman, HALAMAN_TRANSFER)
    if err:
        return set(), f"Solscan menolak permintaan transfer: {err}"
    catatan = (f"Solscan solana: {len(alamat)} alamat dari {transfer} transfer terakhir "
               f"({halaman} halaman)")
    if transfer >= HALAMAN_TRANSFER * maks_halaman:
        catatan += f" — {TANDA_POTONG}, transfer yang lebih lama belum disisir"
    return alamat, catatan + "."


def pemegang(mint, maks_halaman=MAKS_HALAMAN):
    """(pemilik, catatan) — PEMILIK dompetnya, bukan alamat akun tokennya.

    `address` di jawaban Solscan adalah akun token (turunan), sedangkan yang dikenali orang
    sebagai "dompet saya" adalah `owner`. Mencocokkan yang salah berarti mencari di ruang
    alamat yang tidak pernah dilihat siapa pun.
    """
    if not kunci():
        return set(), catatan_kunci()
    pemilik, baris, halaman, err = _halaman(
        "token/holders", {"address": mint},
        lambda b: [str(b.get("owner") or "")] if b.get("owner") else [],
        maks_halaman, HALAMAN_PEMEGANG)
    if err:
        return set(), f"Solscan menolak permintaan pemegang: {err}"
    catatan = f"Solscan solana: {len(pemilik)} pemegang ({halaman} halaman, {baris} baris)"
    if baris >= HALAMAN_PEMEGANG * maks_halaman:
        catatan += f" — {TANDA_POTONG}"
    return pemilik, catatan + "."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mint", nargs="?", help="alamat mint token Solana")
    ap.add_argument("--halaman", type=int, default=3)
    ap.add_argument("--pemegang", action="store_true")
    ap.add_argument("--periksa", action="store_true")
    a = ap.parse_args()

    if a.periksa:
        print(f"Kunci: {'ada' if kunci() else 'TIDAK ADA (' + NAMA_ENV + ')'}")
        # ...tapi tanpa kunci ia menjawab 401 "Token is missing or invalid"
        # (diuji 23 Sep 2026). Labelnya tidak dipercaya; hasil ujinya yang dicetak.
        d = try_json(PUBLIK)
        print("  chaininfo (dilabeli publik) -> "
              + ("DITOLAK: " + d["__err"] if "__err" in d else "diterima"))
        # Endpoint pro diuji satu per satu: pertanyaannya bukan "apakah kuncinya ada"
        # melainkan "apakah paketnya mengizinkan" — dan itu hanya bisa dijawab jawabannya
        # sendiri, bukan oleh tabel harga.
        contoh = "So11111111111111111111111111111111111111112"
        for nama, jalur, param in (
                ("token/transfer", "token/transfer", {"address": contoh, "page_size": 10}),
                ("token/holders", "token/holders", {"address": contoh, "page_size": 10})):
            d = try_json(_url(jalur, dict(param, page=1)))
            print(f"  {nama:16} (pro) -> "
                  + ("DITOLAK: " + d["__err"] if "__err" in d
                     else "DITERIMA — kunci bawaan ternyata cukup"))
        return

    if not a.mint:
        ap.error("butuh <MINT>, atau pakai --periksa")
    nilai, catatan = (pemegang(a.mint, a.halaman) if a.pemegang
                      else alamat_token(a.mint, a.halaman))
    # Alamat TIDAK dicetak: repo ini publik dan keluarannya ikut terbaca di log Actions.
    print(json.dumps({"mint_diperiksa": bool(a.mint), "jumlah": len(nilai),
                      "catatan": catatan}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

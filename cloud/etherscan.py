"""Etherscan V2 — SATU kunci untuk beberapa explorer. HANYA BACA.

APA YANG GRATIS DAN APA YANG TIDAK. Diuji langsung 23 Sep 2026 tanpa kunci sama sekali;
pesan penolakannya sudah membedakan keduanya, jadi ini bukan tebakan:

    chain 1    Ethereum        -> "Missing/Invalid API Key"          = gratis, perlu kunci
    chain 4663 Robinhood Chain -> "Missing/Invalid API Key"          = gratis, perlu kunci
    chain 42161 Arbitrum       -> "Missing/Invalid API Key"          = gratis, perlu kunci
    chain 56   BNB Smart Chain -> "Free API access is not supported for this chain"
    chain 8453 Base            -> "Free API access is not supported for this chain"

BscScan memang masih membagikan kunci gratis, tapi kunci itu kini kunci Etherscan V2 yang
sama: API V1 lamanya sudah mati (`api.bscscan.com` menjawab 301 ke situsnya, dan V1 mana
pun menjawab "You are using a deprecated V1 endpoint"). Jadi kunci gratisnya ada, aksesnya
yang tidak — dan pesan penolakan di atas tetap muncul walau kuncinya dikirim.

Klaim itu tidak dianggap final: `--periksa` IKUT menguji chain berbayar dengan kunci yang
sebenarnya, jadi kalau kebijakan mereka berubah kita akan melihatnya sebagai "DITERIMA",
bukan sebagai kekosongan yang tidak pernah ketahuan sebabnya.
BSC dan Base tetap terlayani lewat GoPlus (pemegang token, tanpa kunci) seperti sebelumnya.

KENAPA INI BERGUNA untuk mencari dompet: daftar trader GMGN hanya memuat 100 teratas per
token. `account&action=tokentx` memberi SETIAP alamat yang pernah menyentuh token itu,
halaman demi halaman — jadi dompet kecil yang tidak masuk 100 besar pun masih terjangkau.

Pemakaian:
    python cloud/etherscan.py --periksa
    python cloud/etherscan.py robinhood 0x492f71fb6cb10f923b0740436f5cd39c7c9a177a
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASIS = "https://api.etherscan.io/v2/api"
NAMA_ENV = "ETHERSCAN_API_KEY"
UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)", "accept": "application/json"}
TIMEOUT = 20

# Nama chain kita -> chainid Etherscan V2.
CHAIN = {"ethereum": 1, "robinhood": 4663, "arbitrum": 42161}
# Ada di V2, tapi paket gratis menolaknya. Disimpan supaya penolakannya bisa DIJELASKAN,
# bukan muncul sebagai kekosongan tanpa sebab.
CHAIN_BERBAYAR = {"bsc": 56, "base": 8453}
# Batas paket gratis: 3 panggilan/detik — angkanya dari mulut mereka sendiri di run
# 35814979407 ("Max calls per sec rate limit reached (3/sec)"), bukan dari dokumentasi.
# Tanpa penahan ini, permintaan halaman kedua dan seterusnya hampir pasti ditolak, dan
# penolakan itu muncul sebagai daftar alamat yang lebih pendek — bentuk kegagalan yang
# paling mudah disalahartikan sebagai "alamatnya memang cuma segini".
JEDA_MIN = 0.4
_terakhir = [0.0]
HALAMAN = 100            # maksimum baris per permintaan yang kita minta
# Dipakai juga oleh pemanggilnya untuk tahu daftarnya terpotong, jadi kalimatnya
# satu tempat saja — bukan dicocokkan ulang dengan tangan di modul lain.
TANDA_POTONG = "dipotong di batas"
MAKS_HALAMAN = 10        # 1.000 transfer per token; batasnya disebut ke user, tidak disembunyikan


def kunci():
    return (os.environ.get(NAMA_ENV) or "").strip()


def catatan_kunci():
    """Kenapa datanya tidak ada — dikatakan, bukan dibiarkan jadi hasil kosong."""
    if kunci():
        return None
    return (f"{NAMA_ENV} belum dipasang, jadi explorer (Etherscan/Robinscan) tidak "
            f"dipakai sama sekali. Ini bukan 'tidak ada datanya' — bagian itu memang "
            f"belum diperiksa.")


def _url(chain_id, param):
    p = dict(param, chainid=chain_id, apikey=kunci())
    return f"{BASIS}?{urllib.parse.urlencode(p)}"


def _tahan_laju():
    """Jarak antar permintaan dijaga di sisi kita, bukan diserahkan ke keberuntungan."""
    sisa = JEDA_MIN - (time.time() - _terakhir[0])
    if sisa > 0:
        time.sleep(sisa)
    _terakhir[0] = time.time()


def try_json(url, ulang=True):
    """{"__err": ...} kalau gagal. Kuncinya tidak pernah ikut tercetak di pesan galat.

    Sekali coba ulang untuk penolakan batas laju: itu keadaan sesaat, bukan jawaban.
    """
    d = _sekali(url)
    if ulang and "__err" in d and "rate limit" in d["__err"].lower():
        time.sleep(1.2)
        d = _sekali(url)
    return d


def _sekali(url):
    _tahan_laju()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                    timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"__err": f"HTTP {e.code}"}
    except Exception as e:
        return {"__err": f"{type(e).__name__}"}
    # Etherscan membalas 200 untuk penolakan; status "0" itulah galat yang sebenarnya.
    if str(d.get("status")) == "0" and not isinstance(d.get("result"), list):
        return {"__err": str(d.get("result") or d.get("message"))[:160]}
    return d


def alasan_chain(chain):
    """None kalau chain-nya terlayani. Kalau tidak, kalimat yang menyebut sebabnya."""
    c = (chain or "").lower()
    if c in CHAIN:
        return None
    if c in CHAIN_BERBAYAR:
        return (f"Explorer untuk {c} (chain {CHAIN_BERBAYAR[c]}) hanya terbuka untuk "
                f"paket Etherscan berbayar — jadi tidak dipakai. Pemegang token {c} tetap "
                f"diambil dari GoPlus.")
    return f"Chain {chain} tidak ada di Etherscan V2."


def alamat_token(chain, kontrak, maks_halaman=MAKS_HALAMAN):
    """(alamat, catatan) — setiap alamat yang pernah menyentuh token ini.

    Dibatasi `maks_halaman` halaman × 100 transfer, dari yang TERBARU. Batas itu selalu
    ikut di catatan: daftar yang terpotong dan daftar yang lengkap tidak boleh terlihat
    sama, kalau tidak "tidak ketemu" terbaca seperti kesimpulan.
    """
    if not kunci():
        return set(), catatan_kunci()
    alasan = alasan_chain(chain)
    if alasan:
        return set(), alasan

    alamat, transfer, halaman = set(), 0, 0
    for h in range(1, max(1, maks_halaman) + 1):
        d = try_json(_url(CHAIN[chain.lower()], {
            "module": "account", "action": "tokentx", "contractaddress": kontrak,
            "page": h, "offset": HALAMAN, "sort": "desc"}))
        if "__err" in d:
            if transfer:
                break          # sudah dapat sebagian; batasnya disebut di bawah
            return set(), (f"Explorer menolak permintaan untuk {chain}: {d['__err']}")
        baris = d.get("result") or []
        if not isinstance(baris, list) or not baris:
            break
        halaman = h
        transfer += len(baris)
        for b in baris:
            for medan in ("from", "to"):
                a = (b.get(medan) or "").lower()
                if a.startswith("0x") and len(a) == 42:
                    alamat.add(a)
        if len(baris) < HALAMAN:
            break

    catatan = (f"Explorer {chain}: {len(alamat)} alamat dari {transfer} transfer terakhir "
               f"({halaman} halaman)")
    if transfer >= HALAMAN * maks_halaman:
        catatan += f" — {TANDA_POTONG}, transfer yang lebih lama belum disisir"
    return alamat, catatan + "."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chain", nargs="?", help=" | ".join(sorted(CHAIN)))
    ap.add_argument("kontrak", nargs="?")
    ap.add_argument("--halaman", type=int, default=MAKS_HALAMAN)
    ap.add_argument("--periksa", action="store_true")
    a = ap.parse_args()

    if a.periksa:
        print(f"Kunci: {'ada' if kunci() else 'TIDAK ADA (' + NAMA_ENV + ')'}")
        for nama, cid in sorted(CHAIN.items()):
            d = try_json(_url(cid, {"module": "block", "action": "getblocknobytime",
                                    "timestamp": 1700000000, "closest": "before"}))
            print(f"  {nama:9} (chain {cid:5}) -> "
                  + ("DITOLAK: " + d["__err"] if "__err" in d else "diterima"))
        # Chain berbayar IKUT diuji dengan kunci yang sebenarnya. Tanpa ini, "BSC
        # berbayar" cuma klaim di komentar — dan kalau kebijakan mereka berubah, kita
        # tidak akan pernah tahu. Kalau baris di bawah menjawab "diterima", pindahkan
        # chain-nya ke CHAIN.
        for nama, cid in sorted(CHAIN_BERBAYAR.items()):
            d = try_json(_url(cid, {"module": "block", "action": "getblocknobytime",
                                    "timestamp": 1700000000, "closest": "before"}))
            print(f"  {nama:9} (chain {cid:5}) -> "
                  + ("DITOLAK: " + d["__err"] if "__err" in d
                     else "DITERIMA — pindahkan ke CHAIN, paket gratis ternyata cukup"))
        return

    if not a.chain or not a.kontrak:
        ap.error("butuh <chain> dan <kontrak>, atau pakai --periksa")
    alamat, catatan = alamat_token(a.chain, a.kontrak, a.halaman)
    # Alamat TIDAK dicetak: repo ini publik dan keluarannya ikut terbaca di log Actions.
    print(json.dumps({"chain": a.chain, "jumlah_alamat": len(alamat), "catatan": catatan},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

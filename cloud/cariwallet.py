"""Cari ALAMAT DOMPET dari potongan huruf/angka yang diingat.

APA YANG BISA DAN TIDAK BISA — ini menentukan seluruh bentuk modul ini:

Pencarian sebagian di SELURUH blockchain TIDAK MUNGKIN. Ruang alamat Ethereum 2^160
(sekitar 10^48 kemungkinan), dan tidak ada indeks global yang bisa ditanya "alamat apa
saja yang mengandung abc". Siapa pun yang menjanjikan itu sedang mengarang.

Yang BISA dicari: alamat yang sudah DIKENAL seseorang —
  1. 29.772 alamat berlabel di repo ini (bursa, protokol, treasury) — offline, instan
  2. indeks pencarian Blockscout per chain — cakupannya tidak merata: "0xf977" memberi
     6 alamat, "0x833589" nol. Berguna sebagai pelengkap, bukan tulang punggung
  3. daftar token GMGN (nama/simbol -> alamat kontrak) untuk Solana, BSC, Base

Karena itu "tidak ketemu" TIDAK BOLEH ditulis seolah "alamatnya tidak ada". Dompet pribadi
yang tidak pernah dilabeli siapa pun memang tidak akan muncul, dan itu normal — bedanya
harus dinyatakan, kalau tidak user menyimpulkan dompetnya lenyap.

Pemakaian:
    python cloud/cariwallet.py f977                # potongan hex, di mana pun letaknya
    python cloud/cariwallet.py binance             # lewat nama
    python cloud/cariwallet.py 0xf977... --json
"""

import argparse
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from investors import load_labels  # noqa: E402  29.772 alamat berlabel, dibaca offline

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)", "accept": "application/json"}
TIMEOUT = 15
MIN_FRAGMEN = 3          # di bawah ini hasilnya ribuan dan tak menolong siapa pun
BATAS_BAWAAN = 25
BLOCKSCOUT = {"ethereum": "eth.blockscout.com", "base": "base.blockscout.com",
              "arbitrum": "arbitrum.blockscout.com", "optimism": "optimism.blockscout.com",
              "polygon": "polygon.blockscout.com"}
_RE_HEX = re.compile(r"^(0x)?[0-9a-f]+$")
_RE_ALAMAT_PENUH = re.compile(r"^0x[0-9a-f]{40}$")
# Bentuk singkat yang DITAMPILKAN explorer & dompet: "0xda...099". Inilah bentuk yang paling
# sering diingat dan disalin orang — sampai 22 Sep 2026 ia dibaca sebagai nama dan hasilnya
# selalu nihil (run 35743975623).
_RE_SINGKAT = re.compile(r"^(?:0x)?([0-9a-f]+)\s*(?:\.{2,}|\u2026)\s*([0-9a-f]+)$")
# Urutan penting: yang paling dekat dengan yang diingat user muncul dulu. Cocok di DUA
# ujung sekaligus jauh lebih menentukan daripada cocok di satu sisi.
_URUTAN = {"persis": 0, "awalan+akhiran": 1, "awalan": 2, "mengandung": 3,
           "nama": 4, "mirip": 5}
# Wajib punya baris untuk SETIAP kunci di _URUTAN — diuji, karena yang hilang bukan satu
# baris melainkan seluruh balasan.
_LABEL_KECOCOKAN = {"persis": "sama persis", "awalan+akhiran": "awalan & akhiran cocok",
                    "awalan": "awalannya cocok", "mengandung": "mengandung",
                    "nama": "dari nama", "mirip": "nama mirip"}


def _bersih(fragmen):
    return re.sub(r"[\s,]+", "", (fragmen or "")).strip().lower()


def _try_json(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                    timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _pisah_singkat(fragmen):
    """(awalan, akhiran) untuk bentuk "0xda...099". (None, None) kalau bukan bentuk itu."""
    m = _RE_SINGKAT.match(fragmen or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def _blockscout(fragmen, chain):
    """Cari di indeks Blockscout. Cakupannya TIDAK merata — dipakai sebagai pelengkap."""
    host = BLOCKSCOUT.get(chain or "ethereum")
    if not host:
        return []
    q = fragmen if fragmen.startswith("0x") else "0x" + fragmen
    d = _try_json(f"https://{host}/api/v2/search?q={urllib.parse.quote(q)}")
    keluar = []
    for i in (d or {}).get("items") or []:
        alamat = (i.get("address_hash") or i.get("address") or "").lower()
        if not _RE_ALAMAT_PENUH.match(alamat):
            continue
        keluar.append({"alamat": alamat, "label": i.get("name"),
                       "sumber": f"Blockscout ({chain or 'ethereum'})",
                       "chain": chain or "ethereum",
                       "jenis": "token" if i.get("type") == "token" else "alamat"})
    return keluar


def _gmgn_token(fragmen):
    """Cari TOKEN lewat nama/simbol di GMGN (Solana, BSC, Base)."""
    try:
        import gmgn
    except Exception:
        return []
    keluar = []
    for chain, kode in (("solana", "sol"), ("bsc", "bsc"), ("base", "base")):
        d = gmgn.try_json(gmgn._url(f"{gmgn.BASIS}/market/search",
                                    {"chain": kode, "q": fragmen}))
        if not isinstance(d, dict) or "__err" in d:
            continue
        isi = (d.get("data") or {})
        for c in (isi.get("coins") or isi.get("data") or [])[:5]:
            alamat = (c.get("address") or "").strip()
            if not alamat:
                continue
            nama = c.get("name") or c.get("symbol")
            keluar.append({"alamat": alamat, "label": f"{nama} (token)",
                           "sumber": f"GMGN ({chain})", "chain": chain, "jenis": "token"})
    return keluar


# ---- pencarian di dalam KUMPULAN token --------------------------------------------------
#
# Pola sependek "0xda...09d9" mengenai sekitar 1 dari 65 ribu alamat: tak berguna di seluruh
# blockchain, tapi di dalam daftar trader SATU token biasanya tinggal satu. Inilah jawaban
# untuk "yang terlihat cuma sedikit karakter" — yang dipersempit tempatnya, bukan polanya.
#
# Asalnya perburuan nyata 22 Sep 2026: dompet dari kartu PNL GMGN ketemu di Levera Markets
# (Robinhood Chain), cocok sampai sen terakhir dengan angka di kartunya.

CHAIN_CARI = ["robinhood", "bsc", "base", "solana", "eth"]
MAKS_TOKEN = 25          # batas kandidat; tiap kandidat = 1 permintaan berbobot 5
JEDA_BOBOT5 = 1.3        # paket Free GMGN: 5/5, jadi endpoint bobot 5 = 1 permintaan/detik


def gmgn_cari(q, chain):
    """Kandidat token dari GMGN: [(alamat, nama)]."""
    try:
        import gmgn
    except Exception:
        return []
    d = gmgn.try_json(gmgn._url(f"{gmgn.BASIS}/market/search", {"chain": chain, "q": q}))
    if not isinstance(d, dict) or "__err" in d:
        return []
    coins = (d.get("data") or {}).get("coins") or []
    kunci = q.lower().split()[0]
    keluar = []
    for c in coins:
        nama = (c.get("name") or c.get("symbol") or "").strip()
        alamat = (c.get("address") or "").strip()
        if alamat and kunci in (nama + " " + (c.get("symbol") or "")).lower():
            keluar.append((alamat, nama))
    return keluar


def gmgn_trader(chain, alamat, limit=100):
    """Daftar trader token (maks 100), diurutkan dari profit terbesar."""
    try:
        import gmgn
    except Exception:
        return []
    d = gmgn.try_json(gmgn._url(f"{gmgn.BASIS}/market/token_top_traders",
                                {"chain": chain, "address": alamat, "limit": limit,
                                 "order_by": "profit", "direction": "desc"}))
    if not isinstance(d, dict) or "__err" in d:
        return []
    isi = d.get("data") or {}
    baris = isi.get("list") or isi.get("data") or []
    return [b for b in baris if isinstance(b, dict)]


def _angka(x):
    try:
        return round(float(x), 2)
    except (TypeError, ValueError):
        return None


def cari_di_token(fragmen, token_q, chain=None, maks_token=MAKS_TOKEN):
    """(hasil, catatan) — sisir daftar trader tiap token yang namanya cocok.

    Nama token TIDAK unik: "LEVERA" cocok dengan 94 token di tiga chain (22 Sep 2026).
    Karena itu kandidatnya disisir satu per satu, dan batasnya disebut apa adanya.
    """
    f = _bersih(fragmen)
    kandidat = []
    for c in ([chain] if chain else CHAIN_CARI):
        for alamat, nama in gmgn_cari(token_q, c) or []:
            kandidat.append((c, alamat, nama))
        time.sleep(0.3)
    if not kandidat:
        return [], (f"Tidak ada token bernama \"{token_q}\" yang ketemu di "
                    f"{', '.join([chain] if chain else CHAIN_CARI)}. Coba nama yang lebih "
                    f"persis, atau sebut chain-nya.")

    dipakai = kandidat[:maks_token]
    hasil = []
    for c, alamat, nama in dipakai:
        for b in gmgn_trader(c, alamat) or []:
            a = str(b.get("address") or "")
            if not a or not _kecocokan(f, a, None):
                continue
            hasil.append({
                "alamat": a.lower(), "token": nama, "kontrak": alamat, "chain": c,
                "profit_usd": _angka(b.get("realized_profit") or b.get("profit")),
                "beli_usd": _angka(b.get("buy_volume_cur")),
                "jual_usd": _angka(b.get("sell_volume_cur")),
                "saldo": _angka(b.get("balance")),
                "sumber": f"GMGN trader ({c})", "kecocokan": _kecocokan(f, a, None)})
        time.sleep(JEDA_BOBOT5)

    catatan = f"Disisir {len(dipakai)} token bernama \"{token_q}\""
    if len(kandidat) > len(dipakai):
        catatan += f" dari {len(kandidat)} yang ketemu — sebutkan chain-nya untuk mempersempit"
    catatan += "."
    if not hasil:
        catatan += (" Tidak ada alamat yang cocok di daftar trader mereka. Itu BUKAN berarti "
                    "dompetnya tidak ada: daftar trader hanya memuat 100 teratas per token, "
                    "dan tokennya bisa saja bukan salah satu dari yang disisir.")
    return hasil, catatan


def _uang(x):
    """Ribuan titik, desimal koma. Format lama menghasilkan "$1.234.56" — dua titik,
    dan desimalnya tidak terbaca lagi."""
    utuh, _, desimal = f"{float(x):,.2f}".partition(".")
    return "$" + utuh.replace(",", ".") + "," + desimal


def kartu_token(fragmen, token_q, hasil, catatan):
    """Kartu untuk hasil pencarian berkonteks. Angkanya ikut supaya user bisa MEMBANDINGKAN
    dengan yang ia lihat sendiri — itu yang mengubah "mirip" jadi "ini dia"."""
    if not hasil:
        return f"🔍 Cari \"{fragmen}\" di token \"{token_q}\"\n\n{catatan}"
    baris = [f"🔍 {len(hasil)} alamat cocok dengan \"{fragmen}\" di token \"{token_q}\"", ""]
    for h in hasil:
        baris.append(f"`{h['alamat']}`")
        baris.append(f"   {h['token']} · {h['chain']} · {h['sumber']}")
        angka = []
        for kunci, label in (("profit_usd", "profit"), ("beli_usd", "beli"),
                             ("jual_usd", "jual")):
            if h.get(kunci) is not None:
                angka.append(f"{label} {_uang(h[kunci])}")
        if angka:
            baris.append("   " + " · ".join(angka) + " — cocokkan dengan yang kamu lihat")
    baris.append("")
    baris.append(f"ℹ️ {catatan}")
    return "\n".join(baris)


def _kecocokan(fragmen, alamat, label):
    """Seberapa dekat satu calon dengan yang diingat user. None kalau tidak cocok."""
    a = (alamat or "").lower()
    l = (label or "").lower()
    if _RE_ALAMAT_PENUH.match(fragmen) and a == fragmen:
        return "persis"
    awal, akhir = _pisah_singkat(fragmen)
    if awal:
        return "awalan+akhiran" if (a.startswith("0x" + awal) and a.endswith(akhir)) else None
    if _RE_HEX.match(fragmen):
        tanpa0x = fragmen[2:] if fragmen.startswith("0x") else fragmen
        if a.startswith("0x" + tanpa0x):
            return "awalan"
        if tanpa0x in a:
            return "mengandung"
    if l and fragmen in l:
        return "nama"
    # Salah ketik pada NAMA: "bitfinx" untuk "Bitfinex". Hanya untuk fragmen yang bukan
    # hex murni — potongan hex yang meleset satu huruf adalah alamat yang berbeda, bukan
    # salah ketik yang boleh ditebak.
    if l and not _RE_HEX.match(fragmen):
        for kata in l.split():
            if difflib.SequenceMatcher(None, fragmen, kata).ratio() >= 0.8:
                return "mirip"
    return None


def cari(fragmen, chain=None, batas=BATAS_BAWAAN):
    """Daftar alamat yang cocok, terurut dari yang paling dekat."""
    return cari_dengan_catatan(fragmen, chain, batas)[0]


def cari_dengan_catatan(fragmen, chain=None, batas=BATAS_BAWAAN):
    """(hasil, catatan). Catatan menjelaskan batas pencarian — bukan basa-basi: tanpa itu
    "tidak ketemu" terbaca sebagai "alamatnya tidak ada"."""
    f = _bersih(fragmen)
    _a, _b = _pisah_singkat(f)
    panjang = len(_a) + len(_b) if _a else len(f.replace("0x", "", 1))
    if panjang < MIN_FRAGMEN:
        return [], (f"Potongannya terlalu pendek — butuh minimal {MIN_FRAGMEN} huruf/angka. "
                    f"Di bawah itu hasilnya ribuan dan tidak menolong siapa pun.")

    gabung = {}

    def tambah(calon):
        kec = _kecocokan(f, calon["alamat"], calon.get("label"))
        if not kec:
            return
        kunci = calon["alamat"].lower()
        lama = gabung.get(kunci)
        if lama:
            # Alamat sama dari dua sumber: satu baris, sumbernya digabung, label yang
            # sudah ada dipertahankan (label lokal lebih informatif daripada nama indeks).
            lama["sumber"] = " + ".join(dict.fromkeys(
                lama["sumber"].split(" + ") + [calon["sumber"]]))
            lama["label"] = lama.get("label") or calon.get("label")
            if _URUTAN[kec] < _URUTAN[lama["kecocokan"]]:
                lama["kecocokan"] = kec
            return
        rapi = " ".join((calon.get("label") or "").split()) or None
        gabung[kunci] = dict(calon, label=rapi, kecocokan=kec)

    for alamat, label in (load_labels() or {}).items():
        tambah({"alamat": alamat, "label": label, "sumber": "label lokal (Ethereum)",
                "chain": "ethereum", "jenis": "alamat"})
    awal, _akhir = _pisah_singkat(f)
    for calon in _blockscout("0x" + awal if awal else f, chain) or []:
        tambah(calon)
    if not _RE_HEX.match(f) and not awal:
        for calon in _gmgn_token(f) or []:
            tambah(calon)

    # Yang BERLABEL didahulukan di kelas kecocokan yang sama: tiga alamat tanpa nama
    # sempat muncul di atas "Binance 8" hanya karena urutan hex-nya lebih kecil, padahal
    # yang dicari orang hampir selalu yang dikenali.
    hasil = sorted(gabung.values(),
                   key=lambda x: (_URUTAN[x["kecocokan"]], 0 if x.get("label") else 1,
                                  x["alamat"]))
    total = len(hasil)
    if not total:
        return [], ("Tidak ada yang cocok. Itu BUKAN berarti alamatnya tidak ada — yang "
                    "bisa dicari hanya alamat yang sudah dikenal (29 rb label bursa & "
                    "protokol, indeks Blockscout, daftar token GMGN). Dompet pribadi yang "
                    "tidak pernah dilabeli siapa pun memang tidak akan muncul.")
    catatan = (f"{total} alamat dikenal cocok dengan \"{fragmen}\".")
    if total > batas:
        catatan += (f" Ditampilkan {batas} yang paling dekat — sebutkan lebih banyak "
                    f"huruf/angka untuk mempersempit.")
    catatan += (" Pencarian hanya menjangkau alamat yang sudah dikenal, bukan seluruh "
                "blockchain.")
    return hasil[:batas], catatan


def kartu(fragmen, hasil, catatan):
    """Blok teks siap kirim ke Telegram. Disusun KODE, bukan model."""
    if not hasil:
        return f"🔍 Cari alamat \"{fragmen}\"\n\n{catatan}"
    baris = [f"🔍 {len(hasil)} alamat cocok dengan \"{fragmen}\"", ""]
    for h in hasil:
        nama = h.get("label") or "belum dikenali"
        baris.append(f"`{h['alamat']}`")
        # .get dengan cadangan: menambah jenis kecocokan baru pernah membuat SELURUH
        # balasan hilang karena KeyError di satu baris (produksi 22 Sep 2026).
        kec = _LABEL_KECOCOKAN.get(h["kecocokan"], h["kecocokan"])
        baris.append(f"   {nama} · {kec} · {h['sumber']}")
    baris.append("")
    baris.append(f"ℹ️ {catatan}")
    return "\n".join(baris)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fragmen", help="potongan alamat atau nama, minimal 3 karakter")
    ap.add_argument("--chain", default=None, help="ethereum | base | arbitrum | optimism | polygon | robinhood | bsc | solana")
    ap.add_argument("--di", default=None, dest="di",
                    help="cari di dalam daftar trader token ini (nama/simbol)")
    ap.add_argument("--maks-token", type=int, default=MAKS_TOKEN)
    ap.add_argument("--batas", type=int, default=BATAS_BAWAAN)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.di:
        hasil, catatan = cari_di_token(a.fragmen, a.di, a.chain,
                                       max(1, min(a.maks_token, 60)))
        if a.json:
            print(json.dumps({"fragmen": a.fragmen, "token": a.di, "hasil": hasil,
                              "catatan": catatan}, indent=2, ensure_ascii=False))
            return
        print(kartu_token(a.fragmen, a.di, hasil, catatan))
        return

    hasil, catatan = cari_dengan_catatan(a.fragmen, a.chain, max(1, min(a.batas, 100)))
    if a.json:
        print(json.dumps({"fragmen": a.fragmen, "hasil": hasil, "catatan": catatan},
                         indent=2, ensure_ascii=False))
        return
    print(kartu(a.fragmen, hasil, catatan))


if __name__ == "__main__":
    main()

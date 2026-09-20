"""Pemindai TOKEN BARU di DEX — daftar pool yang baru dibuat + pemeriksaan kontraknya.

ASAL PERMINTAAN: user menunjukkan kartu dari bot pemindai token milik temannya. Kartu itu
memberi "Security Score 55 🟢 Low Risk" dan menandai "⚠️HasOwner" — padahal GoPlus
menyatakan kepemilikan kontrak token itu SUDAH dilepas, dan yang benar-benar berbahaya
(68% likuiditasnya BEBAS DITARIK) sama sekali tidak disebut. Skor sebaris tanpa dasar yang
bisa diperiksa itu lebih berbahaya daripada tidak ada skor: pembacanya merasa sudah
diperiksa orang lain.

Maka script ini TIDAK memberi skor keamanan. Yang diberikan:
  - daftar TEMUAN, tiap baris menyebut angkanya sendiri, sehingga bisa dibantah
  - vonis yang DIHITUNG KODE dari temuan itu (BAHAYA / HATI-HATI / BELUM ADA TANDA BAHAYA)

"BELUM ADA TANDA BAHAYA" sengaja bukan "AMAN". Yang bisa diperiksa dari luar hanyalah
perilaku kontrak dan sebaran pemegang; niat pembuatnya tidak.

SUMBER (dua-duanya gratis, tanpa API key — diuji 20 Sep 2026):
  - GeckoTerminal `/networks/{chain}/new_pools` -> pool baru, likuiditas, FDV, harga
  - GoPlus Security `/token_security/{chain_id}` -> pajak, honeypot, owner, mintable,
    LP terkunci/tidak, sebaran pemegang, alamat pembuat

BATASAN YANG HARUS DISAMPAIKAN APA ADANYA:
  1. Token baru = risiko tertinggi di pasar ini. Tidak adanya temuan BUKAN rekomendasi.
  2. GoPlus bisa belum punya data untuk token yang umurnya menit-menitan; itu dilaporkan
     sebagai "belum bisa diperiksa", bukan dianggap bersih.
  3. Likuiditas terkunci hari ini bisa dibuka besok kalau kuncinya berjangka.

Pemakaian:
    python cloud/tokenbaru.py                 # kartu siap kirim (BSC, 5 token)
    python cloud/tokenbaru.py --json --limit 8
    python cloud/tokenbaru.py --min-liq 20000 --umur-jam 24
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)", "accept": "application/json"}
TIMEOUT = 25
GECKO = "https://api.geckoterminal.com/api/v2"
GOPLUS = "https://api.gopluslabs.io/api/v1"
# Chain yang didukung. "tipe" menentukan pemeriksa mana yang dipakai: risiko Solana
# BERBEDA TOTAL dari EVM (tidak ada honeypot/pajak; yang menentukan mint & freeze
# authority), jadi aturannya tidak boleh disalin begitu saja.
CHAIN = {
    "bsc": {"gecko": "bsc", "goplus": 56, "tipe": "evm", "alias": ("bnb", "binance")},
    "base": {"gecko": "base", "goplus": 8453, "tipe": "evm", "alias": ()},
    "solana": {"gecko": "solana", "goplus": None, "tipe": "solana", "alias": ("sol", "sol.")},
}


def chain_dari(nama):
    """Nama chain dari kata yang ditulis user. None kalau tidak didukung."""
    n = (nama or "").strip().lower()
    if n in CHAIN:
        return n
    for kunci, c in CHAIN.items():
        if n in c["alias"]:
            return kunci
    return None
JEDA = 0.5          # GoPlus & GeckoTerminal sama-sama membatasi ~30 permintaan/menit

# Ambang, ditulis di satu tempat supaya angkanya bisa dibantah dan diubah sekaligus.
PAJAK_TINGGI = 0.10          # 10% ke atas: sudah memakan hasil, sering dipakai menjebak
LP_BEBAS_BERAT = 0.50        # >50% LP tidak terkunci: rug pull tinggal satu transaksi
LP_BEBAS_RINGAN = 0.20
KONSENTRASI_BERAT = 0.30     # satu dompet (bukan burn/kontrak/terkunci) memegang >30%
KONSENTRASI_RINGAN = 0.15
LIKUIDITAS_TIPIS = 10000.0   # di bawah ini, keluar dari posisi saja sudah menghancurkan harga
MATI = ("0x000000000000000000000000000000000000dead",
        "0x0000000000000000000000000000000000000000")


def try_json(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                    timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"__err": f"HTTP {e.code}"}
    except Exception as e:
        return {"__err": f"{type(e).__name__}: {str(e)[:80]}"}


def _angka(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _umur_jam(iso):
    try:
        t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return round((datetime.now(timezone.utc) - t).total_seconds() / 3600, 1)


def pool_baru(chain, limit):
    """Pool yang baru dibuat di chain itu. Return list (kosong kalau gagal)."""
    data = try_json(f"{GECKO}/networks/{CHAIN.get(chain, {}).get('gecko', chain)}"
                    f"/new_pools?page=1")
    if "__err" in data:
        return []
    keluar = []
    for p in (data.get("data") or [])[:limit]:
        a = p.get("attributes") or {}
        token = (((p.get("relationships") or {}).get("base_token") or {}).get("data") or {})
        alamat = (token.get("id") or "").split("_", 1)[-1]
        keluar.append({
            "nama_pool": a.get("name"),
            "alamat_token": alamat,
            "harga_usd": _angka(a.get("base_token_price_usd")),
            "likuiditas_usd": _angka(a.get("reserve_in_usd")),
            "fdv_usd": _angka(a.get("fdv_usd")),
            "volume_24j_usd": _angka((a.get("volume_usd") or {}).get("h24")),
            "perubahan_24j_persen": _angka(
                (a.get("price_change_percentage") or {}).get("h24")),
            "umur_jam": _umur_jam(a.get("pool_created_at")),
        })
    return keluar


def keamanan(alamat, chain):
    """Data keamanan dari GoPlus. Return (data, error). Endpoint Solana berbeda."""
    c = CHAIN[chain]
    if c["tipe"] == "solana":
        url = f"{GOPLUS}/solana/token_security?contract_addresses={alamat}"
    else:
        url = f"{GOPLUS}/token_security/{c['goplus']}?contract_addresses={alamat}"
    d = try_json(url)
    if "__err" in d:
        return None, f"GoPlus gagal: {d['__err']}"
    r = (d.get("result") or {}).get(alamat.lower()) or (d.get("result") or {}).get(alamat)
    if not r:
        # Token menit-menitan sering belum terindeks. Itu BUKAN tanda bersih.
        return None, "GoPlus belum punya data kontrak ini (token terlalu baru?)"
    return r, None


def _ya(r, kunci):
    return str(r.get(kunci, "0")) == "1"


def _lp_bebas(r):
    """Porsi LP yang TIDAK terkunci (pecahan 0-1). None kalau datanya tidak ada."""
    lp = r.get("lp_holders") or []
    if not lp:
        return None
    bebas = 0.0
    for h in lp:
        p = _angka(h.get("percent")) or 0.0
        if str(h.get("is_locked")) != "1" and (h.get("address") or "").lower() not in MATI:
            bebas += p
    return bebas


def _pemegang_terbesar(r):
    """Porsi dompet terbesar yang BUKAN burn/kontrak/terkunci. Aturannya sama dengan
    investors.py: token yang dibakar atau terkunci bukan konsentrasi di satu tangan."""
    besar = 0.0
    for h in (r.get("holders") or []):
        if (h.get("address") or "").lower() in MATI:
            continue
        if str(h.get("is_contract")) == "1" or str(h.get("is_locked")) == "1":
            continue
        besar = max(besar, _angka(h.get("percent")) or 0.0)
    return besar


def _persen(x, desimal=1):
    """Persen bergaya Indonesia. Keluaran produksi 20 Sep sempat mencampur "+62,3%" dengan
    "100.0%" dalam satu kartu."""
    return f"{x * 100:.{desimal}f}".replace(".", ",") + "%"


def temuan(r, pool):
    """Daftar temuan yang tiap barisnya menyebut angkanya. berat=True artinya menentukan."""
    out = []

    def catat(pesan, berat=False):
        out.append({"pesan": pesan, "berat": berat})

    if _ya(r, "is_honeypot"):
        catat("HONEYPOT: simulasi penjualan gagal — token bisa dibeli tapi tidak bisa dijual",
              True)
    if _ya(r, "cannot_sell_all"):
        catat("Tidak bisa menjual SELURUH saldo (cannot_sell_all)", True)
    if _ya(r, "transfer_pausable"):
        catat("Transfer bisa DIHENTIKAN sepihak oleh kontrak (transfer_pausable)", True)
    if _ya(r, "is_blacklisted"):
        catat("Kontrak punya fungsi blacklist — sebuah dompet bisa dilarang menjual", True)
    if _ya(r, "is_mintable"):
        catat("Suplai bisa DICETAK lagi (mintable) — porsimu bisa diencerkan kapan saja", True)
    if _ya(r, "can_take_back_ownership"):
        catat("Kepemilikan bisa DIAMBIL KEMBALI setelah dilepas (can_take_back_ownership)",
              True)
    if _ya(r, "hidden_owner"):
        catat("Ada pemilik TERSEMBUNYI (hidden_owner) — pelepasan kepemilikan jadi semu", True)
    if _ya(r, "slippage_modifiable"):
        catat("Pajak/slippage bisa diubah sewaktu-waktu oleh pemilik", True)
    if not _ya(r, "is_open_source"):
        catat("Kode kontrak tidak open source — perilakunya tidak bisa diperiksa siapa pun",
              True)

    pemilik = (r.get("owner_address") or "").lower()
    if pemilik and pemilik not in MATI:
        catat(f"Kepemilikan kontrak BELUM dilepas (owner {pemilik[:10]}…)")

    for arah in ("buy", "sell"):
        pajak = _angka(r.get(f"{arah}_tax"))
        kata = "beli" if arah == "buy" else "jual"
        if pajak is not None and pajak >= PAJAK_TINGGI:
            catat(f"Pajak {kata} {_persen(pajak, 0)} — memakan hasil sebelum harga bergerak",
                  pajak >= 0.20)

    bebas = _lp_bebas(r)
    if bebas is None:
        catat("Status kunci likuiditas tidak diketahui — belum bisa dipastikan aman")
    elif bebas >= LP_BEBAS_BERAT:
        catat(f"{_persen(bebas, 0)} likuiditas TIDAK terkunci — bisa ditarik kapan saja "
              f"(ini mekanisme rug pull paling lazim)", True)
    elif bebas >= LP_BEBAS_RINGAN:
        catat(f"{_persen(bebas, 0)} likuiditas tidak terkunci")

    besar = _pemegang_terbesar(r)
    if besar >= KONSENTRASI_BERAT:
        catat(f"Satu dompet memegang {_persen(besar)} suplai (di luar burn/kontrak) — "
              f"penjualannya sendirian bisa menjatuhkan harga", True)
    elif besar >= KONSENTRASI_RINGAN:
        catat(f"Konsentrasi: dompet terbesar {_persen(besar)} suplai")

    pembuat = _angka(r.get("creator_percent"))
    if pembuat and pembuat >= KONSENTRASI_BERAT:
        # Terlihat nyata di pemindaian 20 Sep: satu token baru dengan pembuat memegang
        # 100% suplai. Itu bukan "catatan ringan" — seluruh pasar ada di satu dompet.
        catat(f"Pembuat kontrak masih memegang {_persen(pembuat)} suplai — seluruh "
              f"suplai ada di satu tangan", pembuat >= 0.5)
    elif pembuat and pembuat >= KONSENTRASI_RINGAN:
        catat(f"Pembuat kontrak masih memegang {_persen(pembuat)} suplai")

    out.extend(_temuan_pasar(pool))
    return out


def _temuan_pasar(pool):
    """Temuan yang tidak bergantung pada jenis chain: likuiditas, kewajaran angka, umur."""
    out = []

    def catat(pesan, berat=False):
        out.append({"pesan": pesan, "berat": berat})

    likuid = (pool or {}).get("likuiditas_usd")
    if likuid is not None and likuid < LIKUIDITAS_TIPIS:
        catat(f"Likuiditas cuma {_uang(likuid)} — keluar dari posisi saja sudah "
              f"menggerakkan harganya sendiri", True)

    fdv = (pool or {}).get("fdv_usd")
    # Ambang 0,9: selisih beberapa persen cuma beda waktu pengambilan & pembulatan.
    if fdv and likuid and fdv < likuid * 0.9:
        # Nilai SELURUH token tidak mungkin di bawah isi kolamnya sendiri. Biasanya berarti
        # suplai atau harga acuannya keliru di sumber data.
        catat(f"Angka pasar tidak konsisten: FDV {_uang(fdv)} lebih kecil daripada "
              f"likuiditasnya sendiri {_uang(likuid)} — salah satu angka itu tidak bisa "
              f"dipercaya")

    umur = (pool or {}).get("umur_jam")
    if umur is not None and umur < 24:
        catat(f"Umur pool baru {umur:.0f} jam — belum ada rekam jejak apa pun")
    return out


def _status(r, kunci):
    """Field Solana berbentuk {"status": "1", "authority": [...]} — bukan "1"/"0" polos."""
    nilai = r.get(kunci)
    if isinstance(nilai, dict):
        return str(nilai.get("status", "0")) == "1"
    return str(nilai) == "1"


def temuan_solana(r, pool):
    """Pemeriksa khas Solana. Tidak ada honeypot/pajak di sini; yang menentukan adalah
    siapa yang masih memegang wewenang atas token (mint, freeze, saldo)."""
    out = []

    def catat(pesan, berat=False):
        out.append({"pesan": pesan, "berat": berat})

    if _status(r, "mintable"):
        catat("Wewenang cetak (mint authority) masih aktif — suplai bisa DICETAK lagi "
              "kapan saja dan porsimu ikut diencerkan", True)
    if _status(r, "freezable"):
        catat("Wewenang beku (freeze authority) masih aktif — dompetmu bisa DIBEKUKAN "
              "sehingga tokennya tidak bisa dijual", True)
    if _status(r, "balance_mutable_authority"):
        catat("Ada wewenang yang bisa MENGUBAH SALDO dompet orang lain", True)
    if _status(r, "closable"):
        catat("Akun token bisa DITUTUP sepihak oleh pemegang wewenang", True)
    if str(r.get("non_transferable")) == "1":
        catat("Token ini TIDAK BISA DIPINDAH (non-transferable) — dibeli pun tak bisa dijual",
              True)
    if r.get("transfer_hook"):
        catat("Ada transfer hook — kode pihak ketiga ikut berjalan setiap transfer dan "
              "bisa menolaknya", True)
    if _status(r, "transfer_hook_upgradable"):
        catat("Transfer hook masih bisa diubah sewaktu-waktu", True)
    biaya = r.get("transfer_fee")
    if isinstance(biaya, dict) and biaya:
        rate = _angka(biaya.get("fee_rate"))
        catat("Ada biaya transfer bawaan token"
              + (f" ({_persen(rate)})" if rate is not None else ""))
    if _status(r, "metadata_mutable"):
        catat("Metadata (nama/simbol/gambar) masih bisa diubah pembuatnya")
    # Yang TIDAK bisa diperiksa harus disebut: diam di sini mudah terbaca sebagai "aman".
    catat("Simulasi jual-beli (honeypot) tidak tersedia untuk Solana — bagian ini "
          "TIDAK diperiksa, bukan lolos")
    out.extend(_temuan_pasar(pool))
    return out


def vonis(daftar):
    if any(t["berat"] for t in daftar):
        return "BAHAYA"
    if daftar:
        return "HATI-HATI"
    return "BELUM ADA TANDA BAHAYA"


def _uang(x):
    """Harga token baru hampir selalu pecahan sen; dua desimal menghapus seluruh angkanya
    ("$0.00"). Di bawah satu dolar dipakai empat angka berarti."""
    if x is None:
        return "?"
    for batas, satuan in ((1e9, " M"), (1e6, " jt"), (1e3, " rb")):
        if abs(x) >= batas:
            return f"${x / batas:,.2f}{satuan}".replace(",", ".")
    if abs(x) >= 1:
        return f"${x:,.2f}".replace(",", ".")
    if x == 0:
        return "$0"
    # %g memberi notasi ilmiah untuk pecahan sangat kecil ("1.089e-05"); di token baru,
    # justru banyaknya nol itu yang dicari pembaca. Ditulis penuh, 4 angka berarti.
    tempat = min(12, max(2, 4 - 1 - __import__("math").floor(__import__("math").log10(abs(x)))))
    return f"${x:.{tempat}f}".rstrip("0").replace(".", ",")


def _nama(r):
    r = r or {}
    return r.get("token_name") or (r.get("metadata") or {}).get("name")


def _symbol(r):
    r = r or {}
    return r.get("token_symbol") or (r.get("metadata") or {}).get("symbol")


def kartu(pool, r, daftar):
    """Satu blok teks siap kirim ke Telegram. Disusun KODE, bukan model."""
    v = vonis(daftar)
    lencana = {"BAHAYA": "🛑", "HATI-HATI": "⚠️", "BELUM ADA TANDA BAHAYA": "🔍"}[v]
    nama = _symbol(r) or (pool.get("nama_pool") or "?").split("/")[0].strip()
    baris = [f"{lencana} {nama} — {v}",
             f"CA: {pool.get('alamat_token')}",
             f"Harga {_uang(pool.get('harga_usd'))} · FDV {_uang(pool.get('fdv_usd'))} · "
             f"Likuiditas {_uang(pool.get('likuiditas_usd'))}"]
    ubah = pool.get("perubahan_24j_persen")
    umur = pool.get("umur_jam")
    baris.append(
        f"24 jam {ubah:+.1f}%".replace(".", ",").replace("-", "−")
        if ubah is not None else "24 jam ?"
        + (f" · umur {umur:.0f} jam" if umur is not None else ""))
    pemegang = _angka((r or {}).get("holder_count"))
    if pemegang:
        baris.append(f"Pemegang {int(pemegang):,}".replace(",", "."))
    elif r:
        # 0 dari GoPlus berarti BELUM TERBACA, bukan "tidak ada pemegang".
        baris.append("Pemegang: belum terindeks")
    if daftar:
        baris.append("")
        baris.extend(("‼️ " if t["berat"] else "• ") + t["pesan"] for t in daftar)
    else:
        baris.append("")
        baris.append("Tidak ada temuan dari pemeriksaan kontrak & sebaran pemegang. "
                     "Itu BUKAN berarti aman — yang bisa diperiksa dari luar hanya "
                     "perilaku kontrak, bukan niat pembuatnya.")
    baris.append("")
    baris.append("⚠️ Token baru = risiko tertinggi. Ini pemeriksaan otomatis, "
                 "bukan saran beli.")
    return "\n".join(baris)


def pindai(chain="bsc", limit=5, min_liq=0.0, umur_maks=None):
    """Return (daftar_hasil, error). Tiap hasil: pool + keamanan + temuan + vonis."""
    chain = chain_dari(chain) or chain
    if chain not in CHAIN:
        return [], f"Chain '{chain}' belum didukung. Pilihan: {list(CHAIN)}"
    mentah = try_json(f"{GECKO}/networks/{CHAIN[chain]['gecko']}/new_pools?page=1")
    if "__err" in mentah:
        return [], f"GeckoTerminal gagal: {mentah['__err']}"
    pools = pool_baru(chain, 30)
    hasil = []
    for p in pools:
        if len(hasil) >= limit:
            break
        if not p.get("alamat_token"):
            continue
        if (p.get("likuiditas_usd") or 0) < min_liq:
            continue
        if umur_maks is not None and (p.get("umur_jam") is None or p["umur_jam"] > umur_maks):
            continue
        r, err = keamanan(p["alamat_token"], chain)
        time.sleep(JEDA)
        periksa = temuan_solana if CHAIN[chain]["tipe"] == "solana" else temuan
        t = periksa(r or {}, p) if r else list(_temuan_pasar(p))
        if err:
            t = [{"pesan": err + " — jangan dianggap bersih", "berat": False}] + t
        hasil.append({"alamat": p["alamat_token"], "pool": p,
                      "nama": _nama(r), "symbol": _symbol(r),
                      "jumlah_pemegang": (r or {}).get("holder_count"),
                      "temuan": t, "vonis": vonis(t), "kartu": kartu(p, r, t)})
    return hasil, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", default="bsc", help="bsc | base | solana")
    ap.add_argument("--limit", type=int, default=5, help="jumlah token yang diperiksa")
    ap.add_argument("--min-liq", type=float, default=5000.0,
                    help="likuiditas minimum USD (di bawah ini nyaris tak bisa dijual)")
    ap.add_argument("--umur-jam", type=float, default=None,
                    help="hanya pool yang lebih muda dari ini")
    ap.add_argument("--json", action="store_true", help="keluarkan JSON, bukan kartu")
    args = ap.parse_args()

    daftar, err = pindai(args.chain, max(1, min(args.limit, 15)), args.min_liq, args.umur_jam)
    if args.json:
        keluar = {"chain": args.chain,
                  "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                  "sumber": "GeckoTerminal new_pools + GoPlus Security (gratis, tanpa key)",
                  "ambang": {"pajak_tinggi": PAJAK_TINGGI, "lp_bebas_berat": LP_BEBAS_BERAT,
                             "konsentrasi_berat": KONSENTRASI_BERAT,
                             "likuiditas_tipis": LIKUIDITAS_TIPIS},
                  "token": daftar}
        if err:
            keluar["error"] = err
        print(json.dumps(keluar, indent=2, ensure_ascii=False))
        return
    if err:
        print(f"❌ {err}")
        return
    if not daftar:
        print("Tidak ada pool baru yang lolos saringan saat ini.")
        return
    print(f"🆕 {len(daftar)} token terbaru di {(chain_dari(args.chain) or args.chain).upper()} "
          f"(likuiditas ≥ {_uang(args.min_liq)})\n")
    print(("\n\n" + "─" * 28 + "\n\n").join(d["kartu"] for d in daftar))


if __name__ == "__main__":
    main()

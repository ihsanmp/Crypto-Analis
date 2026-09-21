"""Data GMGN OpenAPI untuk memperkaya pemindai token baru — HANYA BACA.

APA INI: GMGN menyediakan data yang tidak ada di sumber gratis lain untuk token meme baru —
riwayat pembuatnya, porsi dompet sniper/bundler/rat trader, status bonding curve launchpad,
dan apakah logonya menjiplak token lain.

KENAPA LEWAT KODE, BUKAN "SKILL": repo GMGNAI/gmgn-skills menyediakan 14 skill siap pasang
untuk agen AI. Dua alasan tidak dipakai begitu saja:
  1. Setengahnya MENGEKSEKUSI TRANSAKSI on-chain (swap, token-buy, order, cooking) dan
     menuntut GMGN_PRIVATE_KEY. Bot ini berjalan tanpa pengawasan — kemampuan mengirim
     order tidak boleh ada di dalamnya, gratis sekalipun.
  2. Skill = instruksi untuk model. Alat yang bergantung pada model mau memanggilnya sudah
     terbukti gagal diam-diam di proyek ini (MCP CoinGlass, dicabut 20 Sep 2026). Di sini
     datanya ditarik KODE, jadi ada atau tidaknya terlihat di brief, bukan bergantung selera.

Dokumen skill-nya tetap berguna — sebagai rujukan field mana yang penting, bukan sebagai
ketergantungan saat jalan.

KUNCI: `GMGN_API_KEY` dari GitHub Secrets. Tanpa itu dipakai kunci DEMO PUBLIK yang tertulis
di README GMGN — hanya untuk uji coba, dipakai bersama semua orang, dan bisa dicabut kapan
saja. Statusnya selalu ikut dilaporkan, supaya tidak ada yang mengira ini jalur produksi.

Pemakaian:
    python cloud/gmgn.py <CHAIN> <ALAMAT>      # solana | bsc | base
    python cloud/gmgn.py --periksa             # uji akses dari mesin ini
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BASIS = "https://openapi.gmgn.ai/v1"
TIMEOUT = 20
# Tertulis terbuka di README GMGN sebagai kunci uji coba. Bukan rahasia, jadi boleh ada di
# kode — tapi TIDAK boleh diandalkan: batasnya dipakai bersama seluruh pengguna publik.
KUNCI_DEMO = "gmgn_solbscbaseethmonadtron"
# Nama chain internal kita -> nama chain GMGN.
CHAIN = {"solana": "sol", "bsc": "bsc", "base": "base", "ethereum": "eth"}

# Ambang, di satu tempat supaya bisa dibantah dan diubah sekaligus.
DEV_BANYAK_TOKEN = 5       # pembuat serial: token ke-N dari dompet yang sama
DEV_PEGANG_BERAT = 0.20    # pembuat masih memegang >20% suplai
RAT_TRADER = 0.15          # porsi volume dari dompet "orang dalam"
BUNDLER = 0.15             # porsi volume dari pembelian yang dibundel bot
SNIPER_BANYAK = 10         # dompet yang membeli persis di detik peluncuran
FRESH_TINGGI = 0.50        # dompet baru dibuat: ciri pasar yang diisi sendiri


def kunci():
    return os.environ.get("GMGN_API_KEY", "").strip() or KUNCI_DEMO


def catatan_kunci():
    """Peringatan yang WAJIB ikut kalau yang dipakai kunci demo. None kalau kunci sendiri."""
    if os.environ.get("GMGN_API_KEY", "").strip():
        return None
    return ("GMGN memakai kunci demo publik (uji coba; batas dipakai bersama semua orang). "
            "Isi secret GMGN_API_KEY untuk jalur yang bisa diandalkan.")


def bentuk_kunci():
    """Diagnosis BENTUK kunci tanpa pernah mencetak isinya (log Actions repo ini publik).

    Dipakai saat GMGN membalas 401: memisahkan "nilainya salah tempel" dari "kuncinya sah
    tapi endpointnya menuntut tanda tangan". Tanpa ini, satu-satunya cara memeriksa adalah
    menempelkan kuncinya ke suatu tempat — persis yang tidak boleh dilakukan.
    """
    k = os.environ.get("GMGN_API_KEY", "")
    if not k.strip():
        return "GMGN_API_KEY: TIDAK ADA (secret kosong/belum dibuat)"
    catatan = [f"panjang {len(k)} karakter"]
    if "BEGIN PUBLIC KEY" in k or "BEGIN PRIVATE KEY" in k:
        catatan.append("BERISI BLOK PEM — sepertinya kunci PUBLIK/PRIVAT yang tertempel, "
                       "bukan kunci API")
    if k != k.strip():
        catatan.append("ada spasi/baris baru di awal atau akhir")
    if any(c in k.strip() for c in "\"' "):
        catatan.append("mengandung tanda kutip atau spasi di tengah")
    if "\n" in k.strip() or "\r" in k.strip():
        catatan.append("mengandung baris baru di tengah")
    if not k.strip().startswith("gmgn_"):
        catatan.append("tidak diawali 'gmgn_' (kunci demo GMGN diawali itu)")
    else:
        catatan.append("bentuknya wajar (diawali 'gmgn_')")
    return "GMGN_API_KEY: " + "; ".join(catatan)


def try_json(url, kunci_api=None):
    h = {"X-APIKEY": kunci_api or kunci(), "accept": "application/json",
         "User-Agent": "Mozilla/5.0 (compatible; riset-koin/1.0)"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h),
                                    timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"__err": f"HTTP {e.code}"}
    except Exception as e:
        return {"__err": f"{type(e).__name__}"}


def _angka(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _isi(d):
    """GMGN membungkus dua lapis: {"code":0,"data":{"data":{...}}}."""
    data = (d or {}).get("data")
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return data if isinstance(data, dict) else {}


def info(chain, alamat):
    """Ringkasan token dari GMGN. None kalau chain tidak didukung; {"error": ...} kalau gagal.

    Pesan galat SENGAJA tidak memuat isi respons: kunci bisa ikut terbawa di badan galat,
    dan log Actions repo ini publik.
    """
    c = CHAIN.get((chain or "").lower())
    if not c:
        return None
    d = try_json(f"{BASIS}/token/info?chain={c}&address={alamat}")
    if "__err" in d:
        # Kuncinya disaring juga di sini: try_json memang hanya mengembalikan kode HTTP,
        # tapi satu perubahan di sana tidak boleh diam-diam membocorkannya ke log publik.
        return {"error": "GMGN gagal: " + str(d["__err"]).replace(kunci(), "***")}
    r = _isi(d)
    if not r:
        return {"error": "GMGN tidak punya data token ini"}
    dev = r.get("dev") or {}
    tag = r.get("wallet_tags_stat") or {}
    st = r.get("stat") or {}
    return {
        "symbol": r.get("symbol"), "nama": r.get("name"),
        "holder": r.get("holder_count"),
        "launchpad": r.get("launchpad_platform") or r.get("launchpad") or None,
        "launchpad_progres": _angka(r.get("launchpad_progress")),
        "locked_ratio": _angka(r.get("locked_ratio")),
        "logo_duplikat": r.get("image_dup_count") or 0,
        "dev_alamat": dev.get("creator_address"),
        "dev_status": dev.get("creator_token_status"),
        "dev_ganti_nama_x": len(dev.get("twitter_name_change_history") or []),
        "dev_token_dibuat": st.get("creator_created_count"),
        "dev_pegang": _angka(st.get("creator_hold_rate")),
        "tim_pegang": _angka(st.get("dev_team_hold_rate")),
        "top10": _angka(st.get("top_10_holder_rate")),
        "rat_trader": _angka(st.get("top_rat_trader_percentage")),
        "bundler": _angka(st.get("top_bundler_trader_percentage")),
        "fresh_rate": _angka(st.get("fresh_wallet_rate")),
        "smart": tag.get("smart_wallets") or 0,
        "kol": tag.get("renowned_wallets") or 0,
        "sniper": tag.get("sniper_wallets") or 0,
        "fresh": tag.get("fresh_wallets") or 0,
        "whale": tag.get("whale_wallets") or 0,
    }


def _persen(x, desimal=0):
    return f"{x * 100:.{desimal}f}".replace(".", ",") + "%"


def temuan(d):
    """Temuan RISIKO dari data GMGN, bentuknya sama dengan tokenbaru.py.

    Sinyal positif (smart money, KOL) SENGAJA tidak masuk sini: mencampurnya membuat daftar
    risiko kehilangan arti, dan "ada smart money" bukan alasan membeli.
    """
    if not d or d.get("error"):
        return []
    out = []

    def catat(pesan, berat=False):
        out.append({"pesan": pesan, "berat": berat})

    n = d.get("dev_token_dibuat")
    if isinstance(n, (int, float)) and n >= DEV_BANYAK_TOKEN:
        catat(f"Pembuatnya sudah menerbitkan {int(n)} token dari dompet yang sama — "
              f"pola peluncur serial, bukan satu proyek", True)
    if (d.get("dev_status") or "").lower() in ("creator_sell", "sell", "creator_sold"):
        catat("Pembuatnya SUDAH MENJUAL token miliknya sendiri", True)
    pegang = d.get("dev_pegang")
    if pegang is not None and pegang >= DEV_PEGANG_BERAT:
        catat(f"Pembuat memegang {_persen(pegang)} suplai — penjualannya sendirian "
              f"bisa menjatuhkan harga", True)
    rat = d.get("rat_trader")
    if rat is not None and rat >= RAT_TRADER:
        catat(f"{_persen(rat)} volume datang dari dompet rat trader (orang dalam)")
    bund = d.get("bundler")
    if bund is not None and bund >= BUNDLER:
        catat(f"{_persen(bund)} volume dari pembelian yang dibundel bot (bundler)")
    sn = d.get("sniper")
    if isinstance(sn, (int, float)) and sn >= SNIPER_BANYAK:
        catat(f"{int(sn)} dompet sniper membeli persis saat peluncuran")
    fr = d.get("fresh_rate")
    if fr is not None and fr >= FRESH_TINGGI:
        catat(f"{_persen(fr)} pemegangnya dompet yang baru dibuat — ciri pasar yang "
              f"diramaikan sendiri")
    if (d.get("logo_duplikat") or 0) > 0:
        catat(f"Logonya dipakai {int(d['logo_duplikat'])} token lain — kemungkinan tiruan")
    if (d.get("dev_ganti_nama_x") or 0) > 0:
        catat(f"Akun X-nya pernah ganti nama {int(d['dev_ganti_nama_x'])} kali — "
              f"akun daur ulang dari proyek sebelumnya")
    return out


def ringkas(d):
    """Satu baris konteks (bukan risiko): siapa yang masuk, dari launchpad mana."""
    if not d or d.get("error"):
        return None
    bagian = []
    if d.get("launchpad"):
        p = d.get("launchpad_progres")
        bagian.append(f"{d['launchpad']}"
                      + (f" {_persen(p)} kurva" if p is not None and p < 1 else ""))
    if d.get("smart"):
        bagian.append(f"smart money {d['smart']}")
    if d.get("kol"):
        bagian.append(f"KOL {d['kol']}")
    if d.get("whale"):
        bagian.append(f"whale {d['whale']}")
    return " · ".join(bagian) if bagian else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chain", nargs="?", help="solana | bsc | base | ethereum")
    ap.add_argument("alamat", nargs="?")
    ap.add_argument("--periksa", action="store_true",
                    help="uji akses GMGN dari mesin ini (tanpa mencetak kunci)")
    args = ap.parse_args()

    if args.periksa:
        d = try_json(f"{BASIS}/market/rank?chain=sol&limit=1")
        catat = catatan_kunci()
        print("Kunci: " + ("demo publik (uji coba)" if catat else "GMGN_API_KEY dari secret"))
        if not catat:
            print(bentuk_kunci())
        if "__err" in d:
            print(f"GMGN: DITOLAK — {d['__err']}")
            if not catat:
                print("Kalau bentuknya wajar, 401 biasanya berarti endpoint ini menuntut "
                      "tanda tangan (X-Signature) dengan kunci privat, bukan kunci API saja.")
            sys.exit(1)
        n = len(((d.get("data") or {}).get("data") or {}).get("rank") or [])
        print(f"GMGN: DITERIMA — market/rank menjawab normal ({n} baris)")
        sys.exit(0)

    if not args.chain or not args.alamat:
        ap.error("butuh <chain> dan <alamat>, atau pakai --periksa")
    d = info(args.chain, args.alamat)
    if d is None:
        print(json.dumps({"error": f"chain '{args.chain}' tidak didukung GMGN di sini",
                          "pilihan": list(CHAIN)}, indent=2, ensure_ascii=False))
        return
    keluar = dict(d, temuan=temuan(d), ringkas=ringkas(d))
    catat = catatan_kunci()
    if catat:
        keluar["catatan_kunci"] = catat
    print(json.dumps(keluar, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

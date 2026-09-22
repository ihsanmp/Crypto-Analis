"""Tes tokenbaru.py — pemindai token yang baru diluncurkan (BSC).

ASALNYA: user menunjukkan kartu dari bot pemindai token milik temannya. Kartu itu menulis
"Security Score 55 🟢 Low Risk" dan menandai "⚠️HasOwner", padahal GoPlus menyatakan
kepemilikan kontrak SUDAH dilepas (owner = alamat nol) — dan yang benar-benar berbahaya,
likuiditasnya TIDAK terkunci sama sekali (38%, 18%, 12% LP bebas ditarik), justru tidak
disebut. Skor tanpa dasar yang bisa diperiksa lebih buruk daripada tidak ada skor.

Maka di sini: tidak ada "skor keamanan" karangan. Yang ada daftar TEMUAN yang tiap barisnya
menyebut angkanya, dan vonis dihitung KODE dari temuan itu — sama seperti bagian lain
proyek ini.
"""

import json
import os
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import tokenbaru as tb  # noqa: E402

CA = "0xb077ada375b5e416f15e8b8f6827dadfa53a7777"


def _pool(**ubah):
    d = {"id": "bsc_0xpair", "attributes": {
        "name": "NIUMA / BNB", "address": "0xpair",
        "pool_created_at": "2026-09-18T05:00:00Z",
        "reserve_in_usd": "209000.5", "fdv_usd": "3817547",
        "base_token_price_usd": "0.003823",
        "price_change_percentage": {"h1": "6.2", "h24": "50.4"},
        "volume_usd": {"h24": "1200000"},
        "transactions": {"h24": {"buys": 900, "sells": 700}}},
        "relationships": {"base_token": {"data": {"id": f"bsc_{CA}"}}}}
    d["attributes"].update(ubah)
    return d


def _aman(**ubah):
    d = {"token_name": "Niu Ma", "token_symbol": "NIUMA", "holder_count": "7914",
         "buy_tax": "0.01", "sell_tax": "0.0099", "is_honeypot": "0",
         "owner_address": "0x0000000000000000000000000000000000000000",
         "creator_address": "0xcreator", "creator_percent": "0",
         "is_mintable": "0", "transfer_pausable": "0", "is_blacklisted": "0",
         "can_take_back_ownership": "0", "hidden_owner": "0", "is_open_source": "1",
         "cannot_sell_all": "0", "slippage_modifiable": "0",
         "lp_holders": [{"address": "0xlp1", "percent": "0.9", "is_locked": 1}],
         "holders": [{"address": "0xh1", "percent": "0.03", "is_contract": 0,
                      "is_locked": 0, "tag": ""}]}
    d.update(ubah)
    return d


def test_umur_muda_selalu_dicatat():
    """Umur pendek bukan pelanggaran, tapi wajib disebut: tidak ada rekam jejak apa pun."""
    t = tb.temuan(_aman(), {"likuiditas_usd": 100000.0, "umur_jam": 3.0})
    assert any("umur" in x["pesan"].lower() and not x["berat"] for x in t)
    assert tb.vonis(t) == "HATI-HATI"


def test_pool_baru_diurai(monkeypatch):
    monkeypatch.setattr(tb, "try_json", lambda url: {"data": [_pool()]})
    pool = tb.pool_baru("bsc", 5)
    assert pool[0]["alamat_token"] == CA
    assert pool[0]["likuiditas_usd"] == 209000.5 and pool[0]["fdv_usd"] == 3817547.0
    assert pool[0]["perubahan_24j_persen"] == 50.4


def test_lp_tidak_terkunci_jadi_temuan_berat():
    """Rug pull paling lazim: LP ditarik. Kartu bot teman user tidak menyebutnya sama
    sekali, padahal 68% LP token itu bebas ditarik."""
    t = tb.temuan(_aman(lp_holders=[{"address": "0xa", "percent": "0.38", "is_locked": 0},
                                    {"address": "0xb", "percent": "0.18", "is_locked": 0},
                                    {"address": "0xc", "percent": "0.12", "is_locked": 1}]),
                  {"likuiditas_usd": 209000.0, "umur_jam": 40.0})
    berat = [x for x in t if x["berat"]]
    assert any("56" in x["pesan"] and "likuiditas" in x["pesan"].lower()
               for x in berat), t


def test_honeypot_langsung_vonis_bahaya():
    t = tb.temuan(_aman(is_honeypot="1"), {"likuiditas_usd": 50000.0, "umur_jam": 2.0})
    assert tb.vonis(t) == "BAHAYA"
    assert any("honeypot" in x["pesan"].lower() and x["berat"] for x in t)


@pytest.mark.parametrize("ubah,cuplikan", [
    ({"owner_address": "0xbos"}, "kepemilikan kontrak BELUM dilepas"),
    ({"is_mintable": "1"}, "bisa dicetak"),
    ({"transfer_pausable": "1"}, "dihentikan"),
    ({"can_take_back_ownership": "1"}, "diambil kembali"),
    ({"is_blacklisted": "1"}, "blacklist"),
    ({"is_open_source": "0"}, "tidak open source"),
    ({"buy_tax": "0.15"}, "pajak beli 15"),
    ({"sell_tax": "0.2"}, "pajak jual 20"),
])
def test_tiap_bendera_kontrak_punya_pesannya_sendiri(ubah, cuplikan):
    t = tb.temuan(_aman(**ubah), {"likuiditas_usd": 100000.0, "umur_jam": 5.0})
    assert any(cuplikan.lower() in x["pesan"].lower() for x in t), [x["pesan"] for x in t]


def test_konsentrasi_pemegang_memakai_aturan_yang_sama_dengan_investors():
    """Alamat burn bukan whale (lihat investors.py) — jangan dihitung sebagai konsentrasi."""
    t = tb.temuan(_aman(holders=[
        {"address": "0x000000000000000000000000000000000000dead", "percent": "0.9",
         "is_contract": 0, "is_locked": 0, "tag": ""},
        {"address": "0xh", "percent": "0.02", "is_contract": 0, "is_locked": 0, "tag": ""}]),
        {"likuiditas_usd": 100000.0, "umur_jam": 5.0})
    assert not any("konsentrasi" in x["pesan"].lower() for x in t), [x["pesan"] for x in t]


def test_vonis_dihitung_dari_temuan_bukan_skor_karangan():
    aman = tb.temuan(_aman(), {"likuiditas_usd": 209000.0, "umur_jam": 40.0})
    assert tb.vonis(aman) == "BELUM ADA TANDA BAHAYA"
    ragu = tb.temuan(_aman(owner_address="0xbos"), {"likuiditas_usd": 209000.0, "umur_jam": 40.0})
    assert tb.vonis(ragu) == "HATI-HATI"


def test_kartu_menyebut_dasar_tiap_temuan():
    p = {"nama_pool": "NIUMA / BNB", "alamat_token": CA, "likuiditas_usd": 209000.0,
         "fdv_usd": 3817547.0, "umur_jam": 40.0, "perubahan_24j_persen": 50.4,
         "harga_usd": 0.003823, "volume_24j_usd": 1200000.0}
    kartu = tb.kartu(p, _aman(owner_address="0xbos"), tb.temuan(_aman(owner_address="0xbos"), p))
    assert CA in kartu and "HATI-HATI" in kartu
    assert "$209" in kartu.replace(".", ",") or "209" in kartu
    # Tidak boleh ada skor keamanan buatan sendiri.
    assert "score" not in kartu.lower() and "skor" not in kartu.lower()
    assert "bukan saran" in kartu.lower()


def test_main_json(monkeypatch, capsys):
    monkeypatch.setattr(tb, "gmgn", _gmgn_palsu())     # pengaya dimatikan; jalur utama saja
    monkeypatch.setattr(tb, "try_json", lambda url: (
        {"data": [_pool()]} if "geckoterminal" in url else {"result": {CA: _aman()}}))
    monkeypatch.setattr(tb.time, "sleep", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["tokenbaru.py", "--json", "--limit", "1"])
    tb.main()
    h = json.loads(capsys.readouterr().out)
    assert h["chain"] == "bsc" and h["token"][0]["vonis"] == "BELUM ADA TANDA BAHAYA"
    assert h["token"][0]["alamat"] == CA


def test_sumber_gagal_dilaporkan_bukan_dikarang(monkeypatch, capsys):
    monkeypatch.setattr(tb, "try_json", lambda url: {"__err": "HTTP 429"})
    monkeypatch.setattr(sys, "argv", ["tokenbaru.py", "--json"])
    tb.main()
    h = json.loads(capsys.readouterr().out)
    assert "429" in h["error"] and not h.get("token")


def test_harga_kecil_tidak_jadi_nol():
    """Token baru hampir selalu berharga pecahan sen. "$0.00" menghapus satu-satunya
    angka yang dicari pembaca."""
    assert tb._uang(0.003823).startswith("$0,0038") or "3823" in tb._uang(0.003823)
    assert tb._uang(0.000000412) not in ("$0.00", "$0,00")
    assert tb._uang(3817547) == "$3.82 jt"


def test_pemegang_nol_tidak_ditulis_sebagai_angka():
    """GoPlus membalas holder_count 0 untuk token yang belum terindeks. "Pemegang 0"
    terbaca seperti fakta, padahal artinya belum terbaca."""
    p = {"nama_pool": "X / BNB", "alamat_token": CA, "likuiditas_usd": 19000.0,
         "fdv_usd": 85000.0, "umur_jam": 0.4, "perubahan_24j_persen": 241.0,
         "harga_usd": 0.0000412}
    k = tb.kartu(p, _aman(holder_count="0"), [])
    assert "Pemegang 0" not in k and "belum terindeks" in k.lower()


def test_pembuat_memegang_hampir_semua_suplai_itu_berat():
    t = tb.temuan(_aman(creator_percent="1"), {"likuiditas_usd": 50000.0, "umur_jam": 1.0})
    assert any("100" in x["pesan"] and x["berat"] for x in t), [x["pesan"] for x in t]
    assert tb.vonis(t) == "BAHAYA"


@pytest.mark.parametrize("nilai,harap", [
    (1.089e-05, "$0,00001089"),
    (0.0002296, "$0,0002296"),
    (0.003823, "$0,003823"),
])
def test_harga_sangat_kecil_ditulis_penuh_bukan_notasi_ilmiah(nilai, harap):
    """"$1,089e-05" memaksa pembaca menghitung nolnya sendiri — dan di token baru,
    justru banyaknya nol itu informasi yang dicari."""
    assert tb._uang(nilai) == harap


def test_persen_memakai_koma():
    p = {"nama_pool": "X / BNB", "alamat_token": CA, "likuiditas_usd": 20000.0,
         "fdv_usd": 85000.0, "umur_jam": 5.0, "perubahan_24j_persen": 38.2,
         "harga_usd": 0.0002296}
    k = tb.kartu(p, _aman(), [])
    assert "+38,2%" in k and "+38.2%" not in k


def test_persen_di_temuan_juga_memakai_koma():
    """Keluaran produksi 20 Sep: "+62,3%" di kepala kartu tapi "100.0%" di temuan —
    dua gaya angka dalam satu kartu membuat pembaca ragu mana yang benar."""
    t = tb.temuan(_aman(creator_percent="1"), {"likuiditas_usd": 50000.0, "umur_jam": 1.0})
    pesan = " ".join(x["pesan"] for x in t)
    assert "100,0%" in pesan and "100.0%" not in pesan


def test_fdv_jauh_di_bawah_likuiditas_ditandai():
    """Koreksi 21 Sep: kasus asli (LAST, FDV $9,32 rb vs likuiditas $16,90 rb = 0,55x)
    ternyata NORMAL — likuiditas menghitung kedua sisi kolam. Yang ditandai sekarang hanya
    yang di luar batas kolam seimbang."""
    t = tb.temuan(_aman(), {"likuiditas_usd": 16900.0, "fdv_usd": 9320.0, "umur_jam": 5.0})
    assert not any("janggal" in x["pesan"].lower() for x in t), [x["pesan"] for x in t]
    t = tb.temuan(_aman(), {"likuiditas_usd": 16900.0, "fdv_usd": 2000.0, "umur_jam": 5.0})
    assert any("janggal" in x["pesan"].lower() for x in t), [x["pesan"] for x in t]


def test_fdv_wajar_tidak_ditandai():
    t = tb.temuan(_aman(), {"likuiditas_usd": 20000.0, "fdv_usd": 230000.0, "umur_jam": 5.0})
    assert not any("janggal" in x["pesan"].lower() for x in t)


def test_likuiditas_tipis_memakai_format_yang_sama(monkeypatch):
    """Produksi sempat menulis "$6,052" (gaya Inggris) di temuan, sementara kepala kartu
    menulis "$6.05 rb" — angka yang sama tampil dua rupa."""
    t = tb.temuan(_aman(), {"likuiditas_usd": 6052.0, "fdv_usd": 50000.0, "umur_jam": 5.0})
    pesan = " ".join(x["pesan"] for x in t)
    assert "$6.05 rb" in pesan and "$6,052" not in pesan


@pytest.mark.parametrize("fdv,likuid,ditandai", [
    (6040.0, 6052.0, False),     # selisih 0,2%: derau pembulatan, bukan kejanggalan
    # Likuiditas menghitung KEDUA sisi kolam, FDV hanya sisi tokennya. Di pool baru yang
    # seimbang, likuiditas wajar mendekati 2x FDV — jadi rasio 0,5-0,6 itu NORMAL, bukan
    # data rusak. Ambang lama (0,9) menandai 43% token Base sebagai "tidak bisa dipercaya"
    # (diukur 21 Sep 2026): aturannya yang keliru, bukan datanya.
    (9320.0, 16900.0, False),    # 0,55x — peluncuran biasa
    (7496.0, 14947.0, False),    # 0,50x — persis batas kolam seimbang
    (3000.0, 15000.0, True),     # 0,20x — di luar batas kolam seimbang
    (0.0, 20498.0, True),        # FDV nol padahal kolamnya berisi: jelas data bolong
])
def test_ambang_kejanggalan_fdv(fdv, likuid, ditandai):
    t = tb.temuan(_aman(), {"likuiditas_usd": likuid, "fdv_usd": fdv, "umur_jam": 5.0})
    assert any("janggal" in x["pesan"].lower() for x in t) is ditandai


# ---- Base & Solana (20 Sep 2026) ----------------------------------------------------------
# Base memakai jalur EVM yang sama (GoPlus chain 8453). Solana TIDAK: skemanya berbeda
# total — tidak ada honeypot/pajak, yang menentukan justru mint authority, freeze authority,
# dan transfer hook. Menyalin aturan EVM ke Solana akan menghasilkan kartu yang diam soal
# risiko yang paling penting di sana.

SOL_MINT = "9iRbh6SiR3C7VLKcCZEFUTifmL3vRUwAB41xkuH1ULqX"


def _sol(**ubah):
    d = {"metadata": {"name": "Trader", "symbol": "TRADER"},
         "mintable": {"status": "0", "authority": []},
         "freezable": {"status": "0", "authority": []},
         "closable": {"status": "0", "authority": []},
         "balance_mutable_authority": {"status": "0", "authority": []},
         "transfer_hook": [], "transfer_hook_upgradable": {"status": "0"},
         "non_transferable": "0", "transfer_fee": {},
         "metadata_mutable": {"status": "0"}, "total_supply": "1000000001",
         "holder_count": None, "creators": []}
    d.update(ubah)
    return d


@pytest.mark.parametrize("ubah,cuplikan,berat", [
    ({"mintable": {"status": "1", "authority": [{"address": "0xa"}]}}, "dicetak", True),
    ({"freezable": {"status": "1", "authority": []}}, "dibekukan", True),
    ({"balance_mutable_authority": {"status": "1", "authority": []}}, "saldo", True),
    ({"non_transferable": "1"}, "tidak bisa dipindah", True),
    ({"closable": {"status": "1", "authority": []}}, "ditutup", True),
    ({"transfer_hook": [{"address": "0xh"}]}, "transfer hook", True),
    ({"transfer_fee": {"fee_rate": "0.05"}}, "biaya transfer", False),
    ({"metadata_mutable": {"status": "1"}}, "metadata", False),
])
def test_risiko_khas_solana_punya_pesannya_sendiri(ubah, cuplikan, berat):
    t = tb.temuan_solana(_sol(**ubah), {"likuiditas_usd": 50000.0, "umur_jam": 5.0})
    cocok = [x for x in t if cuplikan.lower() in x["pesan"].lower()]
    assert cocok, [x["pesan"] for x in t]
    assert cocok[0]["berat"] is berat


def test_solana_menyebut_yang_TIDAK_bisa_diperiksa():
    """Di Solana tidak ada simulasi jual-beli seperti EVM. Diamnya kartu soal honeypot
    jangan terbaca sebagai "sudah dicek dan aman".

    Sejak 21 Sep catatan ini ditulis SEKALI di kaki pemindaian, bukan diulang di tiap kartu:
    lima pengulangan dalam satu balasan membuat catatan yang benar pun dilewati mata."""
    catat = tb.catatan_chain("solana")
    assert "honeypot" in catat.lower() and "tidak" in catat.lower()
    t = tb.temuan_solana(_sol(), {"likuiditas_usd": 50000.0, "umur_jam": 5.0})
    assert not any("honeypot" in x["pesan"].lower() for x in t)


def test_solana_tetap_memeriksa_likuiditas_dan_umur():
    t = tb.temuan_solana(_sol(), {"likuiditas_usd": 2000.0, "umur_jam": 0.5})
    pesan = " ".join(x["pesan"] for x in t)
    assert "Likuiditas cuma" in pesan and "Umur pool" in pesan


@pytest.mark.parametrize("chain,tipe,goplus", [
    ("bsc", "evm", 56), ("base", "evm", 8453), ("solana", "solana", None)])
def test_registry_chain(chain, tipe, goplus):
    assert tb.CHAIN[chain]["tipe"] == tipe and tb.CHAIN[chain].get("goplus") == goplus


def test_alias_chain():
    assert tb.chain_dari("bnb") == "bsc" and tb.chain_dari("sol") == "solana"
    assert tb.chain_dari("base") == "base" and tb.chain_dari("ngawur") is None


def test_pindai_solana_memakai_endpoint_solana(monkeypatch):
    dipanggil = []

    def palsu(url):
        dipanggil.append(url)
        if "geckoterminal" in url:
            return {"data": [{"attributes": {
                "name": "trader / SOL", "pool_created_at": "2026-09-18T05:00:00Z",
                "reserve_in_usd": "18687.7", "fdv_usd": "50000",
                "base_token_price_usd": "0.00005"},
                "relationships": {"base_token": {"data": {"id": f"solana_{SOL_MINT}"}}}}]}
        return {"result": {SOL_MINT: _sol()}}

    monkeypatch.setattr(tb, "try_json", palsu)
    monkeypatch.setattr(tb.time, "sleep", lambda *_: None)
    hasil, err = tb.pindai("solana", 1, 0.0, None)
    assert err is None and hasil[0]["alamat"] == SOL_MINT
    assert any("solana/token_security" in u for u in dipanggil), dipanggil
    assert "networks/solana/new_pools" in dipanggil[0]


# ---- GMGN sebagai pengaya (21 Sep 2026) ---------------------------------------------------
# Data yang tidak ada di GoPlus/GeckoTerminal: riwayat pembuat token, porsi sniper/bundler/
# rat trader, status bonding curve. Ditarik KODE lewat cloud/gmgn.py, bukan lewat skill yang
# bergantung pada model mau memanggilnya.

def _gmgn_palsu(temuan=(), ringkas=None, gagal=False):
    class Palsu:
        CHAIN = {"solana": "sol", "bsc": "bsc", "base": "base"}

        @staticmethod
        def info(chain, alamat):
            return {"error": "GMGN gagal: HTTP 429"} if gagal else {"symbol": "X"}

        @staticmethod
        def temuan(d):
            return [] if gagal else [dict(t) for t in temuan]

        @staticmethod
        def ringkas(d):
            return None if gagal else ringkas

        @staticmethod
        def catatan_kunci():
            return None
    return Palsu


def test_temuan_gmgn_masuk_ke_kartu(monkeypatch):
    monkeypatch.setattr(tb, "gmgn", _gmgn_palsu(
        temuan=[{"pesan": "Pembuatnya sudah menerbitkan 12 token dari dompet yang sama",
                 "berat": True}],
        ringkas="Pump.fun 43% kurva · smart money 3"))
    monkeypatch.setattr(tb, "try_json", lambda url: (
        {"data": [{"attributes": {"name": "X / SOL", "pool_created_at": "2026-09-18T05:00:00Z",
                                  "reserve_in_usd": "50000", "fdv_usd": "100000",
                                  "base_token_price_usd": "0.001"},
                   "relationships": {"base_token": {"data": {"id": f"solana_{SOL_MINT}"}}}}]}
        if "geckoterminal" in url else {"result": {SOL_MINT: _sol()}}))
    monkeypatch.setattr(tb.time, "sleep", lambda *_: None)
    hasil, err = tb.pindai("solana", 1, 0.0, None)
    kartu = hasil[0]["kartu"]
    assert "12 token" in kartu and hasil[0]["vonis"] == "BAHAYA"
    assert "Pump.fun 43% kurva" in kartu and "smart money 3" in kartu


def test_gmgn_gagal_disebut_bukan_didiamkan(monkeypatch):
    """Kalau bagian dev/sniper tidak terperiksa, itu harus kelihatan — bukan hilang diam-diam
    sehingga kartunya tampak lebih bersih daripada yang sebenarnya diketahui."""
    monkeypatch.setattr(tb, "gmgn", _gmgn_palsu(gagal=True))
    monkeypatch.setattr(tb, "try_json", lambda url: (
        {"data": [{"attributes": {"name": "X / SOL", "pool_created_at": "2026-09-18T05:00:00Z",
                                  "reserve_in_usd": "50000", "fdv_usd": "100000",
                                  "base_token_price_usd": "0.001"},
                   "relationships": {"base_token": {"data": {"id": f"solana_{SOL_MINT}"}}}}]}
        if "geckoterminal" in url else {"result": {SOL_MINT: _sol()}}))
    monkeypatch.setattr(tb.time, "sleep", lambda *_: None)
    hasil, _ = tb.pindai("solana", 1, 0.0, None)
    pesan = " ".join(t["pesan"] for t in hasil[0]["temuan"])
    assert "GMGN" in pesan and "tidak diperiksa" in pesan.lower()


def test_gmgn_tidak_dipakai_untuk_chain_yang_tak_didukungnya(monkeypatch):
    dipanggil = []
    palsu = _gmgn_palsu()
    palsu.CHAIN = {"solana": "sol"}
    palsu.info = staticmethod(lambda c, a: dipanggil.append(c))
    monkeypatch.setattr(tb, "gmgn", palsu)
    EVM = "0x2f063b5c4fdb206e698078b29e01105cf593f5d2"
    monkeypatch.setattr(tb, "try_json", lambda url: (
        {"data": [{"attributes": {"name": "X / WETH", "pool_created_at": "2026-09-18T05:00:00Z",
                                  "reserve_in_usd": "50000", "fdv_usd": "100000",
                                  "base_token_price_usd": "0.001"},
                   "relationships": {"base_token": {"data": {"id": f"base_{EVM}"}}}}]}
        if "geckoterminal" in url else {"result": {EVM: _aman()}}))
    monkeypatch.setattr(tb.time, "sleep", lambda *_: None)
    tb.pindai("base", 1, 0.0, None)
    assert dipanggil == [], "chain di luar dukungan GMGN tidak boleh ditembak"


# ---- dari kartu produksi 21 Sep (run 35554977377) -----------------------------------------

def test_jumlah_pemegang_diambil_dari_gmgn_kalau_goplus_kosong(monkeypatch):
    """Kelima kartu menulis "belum terindeks" padahal GMGN mengirim holder_count. Datanya
    ada, cuma tidak dipakai — dan "belum terindeks" lalu terbaca sebagai fakta."""
    p = {"nama_pool": "X / SOL", "alamat_token": SOL_MINT, "likuiditas_usd": 20000.0,
         "fdv_usd": 100000.0, "umur_jam": 2.0, "perubahan_24j_persen": 5.0,
         "harga_usd": 0.001}
    k = tb.kartu(p, _sol(holder_count=None), [], konteks=None, gmgn_data={"holder": 417})
    assert "Pemegang 417" in k and "belum terindeks" not in k


def test_belum_terindeks_hanya_kalau_KEDUA_sumber_kosong(monkeypatch):
    p = {"nama_pool": "X / SOL", "alamat_token": SOL_MINT, "likuiditas_usd": 20000.0,
         "fdv_usd": 100000.0, "umur_jam": 2.0, "perubahan_24j_persen": 5.0, "harga_usd": 0.001}
    k = tb.kartu(p, _sol(holder_count=0), [], konteks=None, gmgn_data={"holder": 0})
    assert "belum terindeks" in k


def test_catatan_honeypot_solana_tidak_diulang_tiap_kartu(monkeypatch):
    """Diulang lima kali dalam satu balasan, catatan yang benar pun jadi derau yang dilewati.
    Cukup sekali di kaki, karena berlaku untuk SELURUH pemindaian Solana."""
    monkeypatch.setattr(tb, "gmgn", _gmgn_palsu())
    monkeypatch.setattr(tb, "try_json", lambda url: (
        {"data": [{"attributes": {"name": f"T{i} / SOL",
                                  "pool_created_at": "2026-09-18T05:00:00Z",
                                  "reserve_in_usd": "50000", "fdv_usd": "100000",
                                  "base_token_price_usd": "0.001"},
                   "relationships": {"base_token": {"data": {"id": f"solana_{SOL_MINT}{i}"}}}}
                  for i in range(3)]}
        if "geckoterminal" in url else {"result": {f"{SOL_MINT}{i}": _sol() for i in range(3)}}))
    monkeypatch.setattr(tb.time, "sleep", lambda *_: None)
    hasil, _ = tb.pindai("solana", 3, 0.0, None)
    gabung = "\n".join(h["kartu"] for h in hasil)
    assert gabung.count("honeypot") <= 1, "catatan yang sama tidak boleh berulang di tiap kartu"
    assert "honeypot" in tb.catatan_chain("solana").lower()
    assert tb.catatan_chain("bsc") is None


@pytest.mark.parametrize("mentah,rapi", [
    ("meteora_virtual_curve", "Meteora Virtual Curve"),
    ("pump", "Pump"),
    ("Pump.fun", "Pump.fun"),
])
def test_nama_launchpad_dirapikan(mentah, rapi):
    assert tb._rapi_launchpad(mentah) == rapi


def test_endpoint_pool_baru_hanya_ditembak_sekali(monkeypatch):
    """Dua panggilan identik beruntun membuat yang kedua kena batas laju GeckoTerminal, dan
    hasilnya jadi "tidak ada pool baru" padahal 20 pool terbaca di panggilan pertama.
    Terlihat 21 Sep saat memverifikasi perbaikan kartu."""
    hit = []

    def palsu(url):
        if "geckoterminal" in url:
            hit.append(url)
            return {"data": [{"attributes": {
                "name": "X / SOL", "pool_created_at": "2026-09-18T05:00:00Z",
                "reserve_in_usd": "50000", "fdv_usd": "100000",
                "base_token_price_usd": "0.001"},
                "relationships": {"base_token": {"data": {"id": f"solana_{SOL_MINT}"}}}}]}
        return {"result": {SOL_MINT: _sol()}}

    monkeypatch.setattr(tb, "gmgn", _gmgn_palsu())
    monkeypatch.setattr(tb, "try_json", palsu)
    monkeypatch.setattr(tb.time, "sleep", lambda *_: None)
    hasil, err = tb.pindai("solana", 1, 0.0, None)
    assert err is None and len(hasil) == 1
    assert len(hit) == 1, f"endpoint pool baru ditembak {len(hit)}x"


def test_token_yang_sama_tidak_dipindai_dua_kali(monkeypatch):
    """Satu token bisa punya BEBERAPA pool baru sekaligus (mis. "McDonald's / SOL" dua kali,
    "Wizard / SOL" tiga kali, 21 Sep). Tanpa penyaringan, slot pemindaian terbuang untuk
    token yang sama dan kuota GMGN ikut dipakai berulang untuk alamat yang identik."""
    dua_pool = {"data": [
        {"attributes": {"name": f"X / SOL (pool {i})",
                        "pool_created_at": "2026-09-18T05:00:00Z",
                        "reserve_in_usd": str(50000 - i), "fdv_usd": "100000",
                        "base_token_price_usd": "0.001"},
         "relationships": {"base_token": {"data": {"id": f"solana_{SOL_MINT}"}}}}
        for i in range(3)]}
    dilihat = []

    def palsu(url):
        if "geckoterminal" in url:
            return dua_pool
        dilihat.append(url)
        return {"result": {SOL_MINT: _sol()}}

    monkeypatch.setattr(tb, "gmgn", _gmgn_palsu())
    monkeypatch.setattr(tb, "try_json", palsu)
    monkeypatch.setattr(tb.time, "sleep", lambda *_: None)
    hasil, _ = tb.pindai("solana", 5, 0.0, None)
    assert len(hasil) == 1, f"token sama dipindai {len(hasil)}x"
    assert len(dilihat) == 1, "pemeriksaan keamanan tidak boleh diulang untuk alamat sama"
    # Yang dipakai pool PERTAMA (paling baru di daftar GeckoTerminal).
    assert hasil[0]["pool"]["likuiditas_usd"] == 50000.0


# ---- Robinhood Chain (22 Sep 2026) --------------------------------------------------------
# Didukung GeckoTerminal ("robinhood") dan GoPlus (chain 4663), TAPI cakupan GoPlus di sana
# sangat tipis: 8 kolom, bukan ~30 seperti BSC. Tidak ada honeypot, pajak, owner, kunci LP,
# maupun daftar pemegang — dan sebagian token tidak dijawab sama sekali. Dipasang tanpa
# catatan, kartunya jadi SUNYI, dan sunyi terbaca sebagai "aman".

def test_registry_robinhood():
    assert tb.CHAIN["robinhood"]["gecko"] == "robinhood"
    assert tb.CHAIN["robinhood"]["goplus"] == 4663
    assert tb.chain_dari("rhc") == "robinhood" and tb.chain_dari("robinhood") == "robinhood"


def test_catatan_robinhood_menyebut_yang_tidak_diperiksa():
    catat = tb.catatan_chain("robinhood")
    assert catat and "honeypot" in catat.lower()
    for kata in ("pajak", "likuiditas", "pemegang"):
        assert kata in catat.lower(), kata
    assert "tidak diperiksa" in catat.lower() or "tidak tersedia" in catat.lower()


def test_robinhood_tetap_memeriksa_yang_memang_ada(monkeypatch):
    """Yang TERSEDIA di sana tetap dipakai: open source, cannot_buy, plus likuiditas/umur."""
    r = {"token_name": "PairPad", "token_symbol": "PAIR", "is_open_source": "0",
         "cannot_buy": "1", "is_in_dex": "0"}
    t = tb.temuan(r, {"likuiditas_usd": 4748.0, "umur_jam": 1.0})
    pesan = " ".join(x["pesan"].lower() for x in t)
    assert "open source" in pesan and "likuiditas cuma" in pesan


def test_tidak_bisa_dibeli_jadi_temuan_berat():
    t = tb.temuan({"cannot_buy": "1"}, {"likuiditas_usd": 50000.0, "umur_jam": 5.0})
    assert any("dibeli" in x["pesan"].lower() and x["berat"] for x in t), [x["pesan"] for x in t]


def test_open_source_hanya_ditandai_kalau_DINYATAKAN():
    """Di chain bercakupan tipis, kolomnya bisa HILANG sama sekali. Ketiadaan data bukan
    temuan — menandainya "tidak open source" adalah tuduhan yang tidak berdasar."""
    ada = tb.temuan({"is_open_source": "0"}, {"likuiditas_usd": 50000.0, "umur_jam": 5.0})
    assert any("open source" in x["pesan"].lower() for x in ada)
    hilang = tb.temuan({"token_symbol": "X"}, {"likuiditas_usd": 50000.0, "umur_jam": 5.0})
    assert not any("open source" in x["pesan"].lower() for x in hilang), [x["pesan"] for x in hilang]
    terbuka = tb.temuan({"is_open_source": "1"}, {"likuiditas_usd": 50000.0, "umur_jam": 5.0})
    assert not any("open source" in x["pesan"].lower() for x in terbuka)

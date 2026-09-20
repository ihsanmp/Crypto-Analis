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


def test_fdv_lebih_kecil_dari_likuiditas_ditandai():
    """Keluaran produksi 20 Sep, token LAST: FDV $9,32 rb dengan likuiditas $16,90 rb.
    Nilai SELURUH token tidak mungkin lebih kecil daripada isi kolamnya sendiri — salah
    satu angka itu salah, dan menampilkannya diam-diam membuatnya tampak sahih."""
    t = tb.temuan(_aman(), {"likuiditas_usd": 16900.0, "fdv_usd": 9320.0, "umur_jam": 5.0})
    assert any("tidak konsisten" in x["pesan"].lower() for x in t), [x["pesan"] for x in t]


def test_fdv_wajar_tidak_ditandai():
    t = tb.temuan(_aman(), {"likuiditas_usd": 20000.0, "fdv_usd": 230000.0, "umur_jam": 5.0})
    assert not any("tidak konsisten" in x["pesan"].lower() for x in t)


def test_likuiditas_tipis_memakai_format_yang_sama(monkeypatch):
    """Produksi sempat menulis "$6,052" (gaya Inggris) di temuan, sementara kepala kartu
    menulis "$6.05 rb" — angka yang sama tampil dua rupa."""
    t = tb.temuan(_aman(), {"likuiditas_usd": 6052.0, "fdv_usd": 50000.0, "umur_jam": 5.0})
    pesan = " ".join(x["pesan"] for x in t)
    assert "$6.05 rb" in pesan and "$6,052" not in pesan


@pytest.mark.parametrize("fdv,likuid,ditandai", [
    (6040.0, 6052.0, False),     # selisih 0,2%: derau pembulatan, bukan kejanggalan
    (9320.0, 16900.0, True),     # FDV cuma 55% likuiditas: salah satu angka keliru
])
def test_ambang_kejanggalan_fdv(fdv, likuid, ditandai):
    t = tb.temuan(_aman(), {"likuiditas_usd": likuid, "fdv_usd": fdv, "umur_jam": 5.0})
    assert any("tidak konsisten" in x["pesan"].lower() for x in t) is ditandai

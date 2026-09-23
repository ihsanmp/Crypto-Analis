"""Tes cariwallet.py — mencari alamat dompet dari potongan huruf/angka.

BATAS YANG MENENTUKAN BENTUK FITUR INI: pencarian sebagian di SELURUH blockchain tidak
mungkin. Ruang alamat Ethereum 2^160, dan tidak ada indeks global yang bisa ditanya
"alamat apa saja yang mengandung abc". Yang bisa dicari hanya alamat yang SUDAH DIKENAL:
29.772 alamat berlabel di repo ini, indeks Blockscout, dan daftar token GMGN.

Karena itu "tidak ketemu" TIDAK BOLEH terbaca sebagai "alamat itu tidak ada" — bedanya
harus dinyatakan, kalau tidak user akan menyimpulkan dompetnya lenyap.
"""

import json
import os
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import cariwallet as cw  # noqa: E402

_LABEL = {
    "0xf977814e90da44bfa03b6295a0616a897441acec": "Binance 8",
    "0xfe5986e06210ac1ecc1adcafc0cc7f8d63b3f977": "Lido: EVM Script Executor",
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance 14",
    "0x742d35cc6634c0532925a3b844bc454e4438f44e": "Bitfinex: Old Wallet",
}


@pytest.fixture(autouse=True)
def _tanpa_jaringan(monkeypatch):
    monkeypatch.setattr(cw, "load_labels", lambda: _LABEL)
    monkeypatch.setattr(cw, "_blockscout", lambda frag, chain: [])
    monkeypatch.setattr(cw, "_gmgn_token", lambda frag: [])


def test_potongan_hex_menemukan_semua_yang_mengandungnya():
    h = cw.cari("f977")
    alamat = [x["alamat"] for x in h]
    assert "0xf977814e90da44bfa03b6295a0616a897441acec" in alamat
    assert "0xfe5986e06210ac1ecc1adcafc0cc7f8d63b3f977" in alamat, "di TENGAH pun harus kena"
    assert len(alamat) == 2


def test_awalan_diutamakan_di_urutan():
    """User yang ingat 4 huruf pertama hampir selalu mencari yang AWALANNYA itu."""
    h = cw.cari("f977")
    assert h[0]["alamat"].startswith("0xf977")
    assert h[0]["kecocokan"] == "awalan" and h[1]["kecocokan"] == "mengandung"


def test_alamat_lengkap_dikenali_dan_dilabeli():
    h = cw.cari("0xF977814E90DA44BFA03B6295A0616A897441ACEC")   # huruf besar
    assert len(h) == 1 and h[0]["kecocokan"] == "persis"
    assert h[0]["label"] == "Binance 8"


def test_cari_lewat_nama_bukan_hanya_hex():
    h = cw.cari("binance")
    assert {x["label"] for x in h} == {"Binance 8", "Binance 14"}


def test_salah_ketik_nama_masih_ketemu():
    """"bitfinex" vs "bitfinx" — menolak karena satu huruf membuat fitur ini rewel."""
    h = cw.cari("bitfinx")
    assert any(x["label"].startswith("Bitfinex") for x in h), h


def test_potongan_terlalu_pendek_ditolak_dengan_alasan():
    h, catatan = cw.cari_dengan_catatan("ab")
    assert h == []
    assert "terlalu pendek" in catatan.lower() and "3" in catatan


def test_tidak_ketemu_bukan_berarti_tidak_ada():
    """Bedanya harus dinyatakan: yang dicari hanya alamat yang sudah dikenal."""
    h, catatan = cw.cari_dengan_catatan("deadbeef99")
    assert h == []
    assert "belum tentu" in catatan.lower() or "bukan berarti" in catatan.lower()
    assert "dikenal" in catatan.lower()


def test_hasil_banyak_dipotong_tapi_jumlahnya_disebut(monkeypatch):
    banyak = {f"0xabc{i:037x}": f"Dompet {i}" for i in range(60)}
    monkeypatch.setattr(cw, "load_labels", lambda: banyak)
    h, catatan = cw.cari_dengan_catatan("abc", batas=10)
    assert len(h) == 10
    assert "60" in catatan, catatan


def test_sumber_tiap_hasil_disebut(monkeypatch):
    monkeypatch.setattr(cw, "_blockscout", lambda frag, chain: [
        {"alamat": "0xf9772d58909ac97d9b430f3c353b3b8a6488fa1e", "label": None,
         "sumber": "Blockscout (ethereum)", "chain": "ethereum", "jenis": "alamat"}])
    h = cw.cari("f977")
    sumber = {x["sumber"] for x in h}
    assert any("label lokal" in s for s in sumber) and any("Blockscout" in s for s in sumber)


def test_duplikat_antar_sumber_digabung(monkeypatch):
    monkeypatch.setattr(cw, "_blockscout", lambda frag, chain: [
        {"alamat": "0xf977814e90da44bfa03b6295a0616a897441acec", "label": None,
         "sumber": "Blockscout (ethereum)", "chain": "ethereum", "jenis": "alamat"}])
    h = cw.cari("f977814e90da44bfa03b6295a0616a897441acec")
    assert len(h) == 1, "alamat sama dari dua sumber jangan tampil dua kali"
    assert h[0]["label"] == "Binance 8", "label lokal tetap dipakai"
    assert "Blockscout" in h[0]["sumber"] and "label lokal" in h[0]["sumber"]


def test_kartu_menyebut_batas_pencarian():
    kartu = cw.kartu("f977", *cw.cari_dengan_catatan("f977"))
    assert "Binance 8" in kartu and "0xf977814e" in kartu.lower()
    assert "dikenal" in kartu.lower(), "batas pencarian harus ikut tertulis"


def test_main_json(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cariwallet.py", "f977", "--json"])
    cw.main()
    d = json.loads(capsys.readouterr().out)
    assert d["fragmen"] == "f977" and len(d["hasil"]) == 2
    assert d["catatan"]


def test_yang_berlabel_didahulukan(monkeypatch):
    """Produksi: tiga alamat tanpa label muncul di atas "Binance 8" hanya karena urutan
    hex-nya lebih kecil. Yang dicari orang hampir selalu yang dikenali."""
    monkeypatch.setattr(cw, "_blockscout", lambda frag, chain: [
        {"alamat": "0xf9771f93b68d1270133f715c2c7d780a8a1ca5a2", "label": None,
         "sumber": "Blockscout (ethereum)", "chain": "ethereum", "jenis": "alamat"}])
    h = cw.cari("f977")
    assert h[0]["label"] == "Binance 8", [x["label"] for x in h]


def test_nama_token_dirapikan(monkeypatch):
    monkeypatch.setattr(cw, "load_labels", lambda: {})
    monkeypatch.setattr(cw, "_gmgn_token", lambda frag: [
        {"alamat": "0x0054d82c8d92391f1c37eda9af5d7033579c85eb",
         "label": "Binance   (token)", "sumber": "GMGN (base)", "chain": "base",
         "jenis": "token"}])
    h = cw.cari("binance")
    assert h[0]["label"] == "Binance (token)"


# ---- bentuk singkat "0xda...099" (produksi 22 Sep, run 35743975623) -----------------------
# User menempel alamat seperti yang DITAMPILKAN explorer dan dompet: awalan, titik-titik,
# akhiran. Dibaca sebagai nama, hasilnya nihil — padahal justru bentuk inilah yang paling
# sering diingat dan disalin orang.

_LABEL_SINGKAT = {
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "Tether: USDT",
    "0xda9d4f9b69ac6c22e444ed9af0cfc043b7a7f099": "Contoh Cocok",
    "0xda1122334455667788990011223344556677f099": "Cocok Juga",
    "0xbb9d4f9b69ac6c22e444ed9af0cfc043b7a7f099": "Akhiran Saja",
    "0xda9d4f9b69ac6c22e444ed9af0cfc043b7a7abcd": "Awalan Saja",
}


@pytest.mark.parametrize("ditulis", ["0xda...099", "0xda…099", "0xda..099", "0xDA...099"])
def test_bentuk_singkat_dicocokkan_awalan_dan_akhiran(monkeypatch, ditulis):
    monkeypatch.setattr(cw, "load_labels", lambda: _LABEL_SINGKAT)
    h = cw.cari(ditulis)
    label = {x["label"] for x in h}
    assert label == {"Contoh Cocok", "Cocok Juga"}, label
    assert all(x["kecocokan"] == "awalan+akhiran" for x in h)


def test_bentuk_singkat_tanpa_0x(monkeypatch):
    monkeypatch.setattr(cw, "load_labels", lambda: _LABEL_SINGKAT)
    assert {x["label"] for x in cw.cari("da...099")} == {"Contoh Cocok", "Cocok Juga"}


def test_bentuk_singkat_diutamakan_di_atas_yang_lain(monkeypatch):
    """Cocok di dua ujung sekaligus jauh lebih menentukan daripada cocok di satu sisi."""
    monkeypatch.setattr(cw, "load_labels", lambda: _LABEL_SINGKAT)
    h = cw.cari("0xda...099")
    assert h[0]["kecocokan"] == "awalan+akhiran"


def test_blockscout_ditanya_dengan_awalannya_saja(monkeypatch):
    """API-nya tidak mengerti "0xda...099" — yang dikirim awalannya, akhirannya disaring
    di sisi kita."""
    ditanya = []

    def palsu(frag, chain):
        ditanya.append(frag)
        return [{"alamat": "0xda9d4f9b69ac6c22e444ed9af0cfc043b7a7f099", "label": None,
                 "sumber": "Blockscout (ethereum)", "chain": "ethereum", "jenis": "alamat"},
                {"alamat": "0xda0000000000000000000000000000000000dead", "label": None,
                 "sumber": "Blockscout (ethereum)", "chain": "ethereum", "jenis": "alamat"}]

    monkeypatch.setattr(cw, "load_labels", lambda: {})
    monkeypatch.setattr(cw, "_blockscout", palsu)
    h = cw.cari("0xda...099")
    assert ditanya == ["0xda"], ditanya
    assert [x["alamat"] for x in h] == ["0xda9d4f9b69ac6c22e444ed9af0cfc043b7a7f099"]


def test_setiap_jenis_kecocokan_punya_label_tampilan():
    """Produksi 22 Sep: menambah jenis "awalan+akhiran" membuat kartu CRASH karena label
    tampilannya belum ada — seluruh balasan hilang, bukan cuma satu baris."""
    for kec in cw._URUTAN:
        assert kec in cw._LABEL_KECOCOKAN, kec


def test_kartu_tidak_pernah_crash_untuk_jenis_tak_dikenal():
    """Jaring pengaman: jenis baru boleh tampil apa adanya, tapi TIDAK BOLEH menjatuhkan
    seluruh jawaban."""
    palsu = [{"alamat": "0x" + "a" * 40, "label": "X", "sumber": "uji",
              "chain": "ethereum", "jenis": "alamat", "kecocokan": "jenis-baru"}]
    teks = cw.kartu("x", palsu, "catatan")
    assert "0x" + "a" * 40 in teks and "jenis-baru" in teks


# ---- cari di dalam KUMPULAN token (22 Sep 2026) -------------------------------------------
# Asalnya perburuan nyata: "0xda...09d9" dari kartu PNL GMGN. Pola sependek itu mengenai
# ~1 dari 65 ribu alamat — tak berguna di seluruh blockchain, tapi di dalam daftar trader
# satu token biasanya tinggal satu. Dompetnya ketemu di Levera Markets (Robinhood Chain)
# dan cocok sampai sen terakhir: profit 354,67 / beli 165,65 / jual 536,48.

def _trader(alamat, profit=354.67, beli=165.65, jual=536.48):
    return {"address": alamat, "realized_profit": profit, "buy_volume_cur": beli,
            "sell_volume_cur": jual, "balance": 0, "tags": ["gmgn"]}


def _gmgn_tiruan(monkeypatch, kandidat, trader):
    class Palsu:
        CHAIN_CARI = ["robinhood", "bsc", "base", "solana"]
        dipanggil = []
        dicari = []

        @staticmethod
        def cari_token(q, chain):
            Palsu.dicari.append((q, chain))
            return kandidat.get(chain, [])

        @staticmethod
        def trader_token(chain, alamat, limit=100):
            Palsu.dipanggil.append((chain, alamat))
            return trader.get(alamat, [])
    monkeypatch.setattr(cw, "gmgn_cari", Palsu.cari_token)
    monkeypatch.setattr(cw, "gmgn_trader", Palsu.trader_token)
    monkeypatch.setattr(cw.time, "sleep", lambda *_: None)
    return Palsu


def test_menemukan_dompet_di_daftar_trader_token(monkeypatch):
    target = "0xdaddc6d4839197e684874b08f6fccc4670b309d9"
    palsu = _gmgn_tiruan(
        monkeypatch,
        {"robinhood": [("0x492f", "Levera Markets"), ("0x1198", "Levera.fun")]},
        {"0x492f": [_trader("0xbeef" + "0" * 35), _trader(target)],
         "0x1198": [_trader("0xcafe" + "0" * 35)]})
    hasil, catatan = cw.cari_di_token("0xda...09d9", "LEVERA", maks_token=5)
    assert [h["alamat"] for h in hasil] == [target]
    h = hasil[0]
    assert h["token"] == "Levera Markets" and h["chain"] == "robinhood"
    assert h["profit_usd"] == 354.67 and h["beli_usd"] == 165.65 and h["jual_usd"] == 536.48
    assert "2 token" in catatan and "LEVERA" in catatan
    assert len(palsu.dipanggil) == 2


def test_berhenti_di_batas_token_dan_menyebutkannya(monkeypatch):
    banyak = [(f"0x{i:04x}", f"Levera {i}") for i in range(40)]
    _gmgn_tiruan(monkeypatch, {"robinhood": banyak}, {})
    hasil, catatan = cw.cari_di_token("0xda...09d9", "LEVERA", maks_token=6)
    assert hasil == []
    assert "6" in catatan and "40" in catatan, catatan


def test_tidak_ketemu_di_token_dijelaskan(monkeypatch):
    _gmgn_tiruan(monkeypatch, {"robinhood": [("0x492f", "Levera Markets")]},
                 {"0x492f": [_trader("0xbeef" + "0" * 35)]})
    hasil, catatan = cw.cari_di_token("0xda...09d9", "LEVERA", maks_token=5)
    assert hasil == []
    assert "belum tentu" in catatan.lower() or "bukan berarti" in catatan.lower()


def test_token_tak_ditemukan_dikatakan_apa_adanya(monkeypatch):
    _gmgn_tiruan(monkeypatch, {}, {})
    hasil, catatan = cw.cari_di_token("0xda...09d9", "TOKENGAIB", maks_token=5)
    assert hasil == [] and "tidak ada token" in catatan.lower()


def test_kartu_konteks_menyebut_angka_pembanding(monkeypatch):
    target = "0xdaddc6d4839197e684874b08f6fccc4670b309d9"
    _gmgn_tiruan(monkeypatch, {"robinhood": [("0x492f", "Levera Markets")]},
                 {"0x492f": [_trader(target)]})
    hasil, catatan = cw.cari_di_token("0xda...09d9", "LEVERA", maks_token=5)
    kartu = cw.kartu_token("0xda...09d9", "LEVERA", hasil, catatan)
    assert target in kartu and "Levera Markets" in kartu and "robinhood" in kartu
    # Angka harus ikut supaya user bisa MEMBANDINGKAN dengan yang ia lihat sendiri.
    for angka in ("354", "165", "536"):
        assert angka in kartu, angka


@pytest.mark.parametrize("nilai,harap", [
    (354.67, "$354,67"),
    (1234.5, "$1.234,50"),
    (1234567.89, "$1.234.567,89"),
])
def test_uang_bergaya_indonesia(nilai, harap):
    """Format lama menghasilkan "$1.234.56" — dua titik, dan desimalnya tak terbaca."""
    assert cw._uang(nilai) == harap


# ---- bug yang ketemu saat pemeriksaan 23 Sep 2026 -----------------------------------------

@pytest.mark.parametrize("ditulis,nama,chain", [
    ("LEVERA robinhood", "LEVERA", "robinhood"),
    ("levera markets bsc", "levera markets", "bsc"),
    ("levera bnb chain", "levera", "bsc"),
    ("levera sol", "levera", "solana"),
    ("levera", "levera", None),
    ("ethereum", "", "ethereum"),
])
def test_kata_chain_dipisahkan_dari_nama_token(ditulis, nama, chain):
    """"di LEVERA robinhood" dulu dikirim UTUH sebagai nama token ke GMGN, jadi kata yang
    dimaksudkan mempersempit justru membuat hasilnya nihil — padahal catatannya sendiri
    menyuruh "sebutkan chain-nya untuk mempersempit"."""
    assert cw.pisah_chain(ditulis) == (nama, chain)


def test_chain_dari_perintah_membatasi_sapuan(monkeypatch):
    palsu = _gmgn_tiruan(monkeypatch, {"robinhood": [("0x492f", "Levera Markets")]},
                         {"0x492f": [_trader("0xdaddc6d4839197e684874b08f6fccc4670b309d9")]})
    hasil, catatan = cw.cari_di_token("0xda...09d9", "LEVERA robinhood")
    assert [h["alamat"] for h in hasil] == ["0xdaddc6d4839197e684874b08f6fccc4670b309d9"]
    # Hanya SATU chain yang disisir, dan nama tokennya tidak lagi memuat kata chain-nya.
    assert palsu.dicari == [("LEVERA", "robinhood")]
    assert "robinhood" in catatan and "LEVERA robinhood" not in catatan


def test_yang_disebut_cuma_nama_chain_dijelaskan(monkeypatch):
    _gmgn_tiruan(monkeypatch, {}, {})
    hasil, catatan = cw.cari_di_token("f977", "ethereum")
    assert hasil == [] and "nama chain" in catatan


@pytest.mark.parametrize("fragmen", ["a", "ab", "0x1"])
def test_fragmen_terlalu_pendek_ditolak_juga_di_jalur_token(monkeypatch, fragmen):
    """Jalur biasa menolak potongan < 3 karakter, jalur token dulu tidak: "a" cocok dengan
    sekitar sepertiga isi daftar trader dan dilaporkan sebagai "hasil pencarian"."""
    banyak = [_trader("0x%040x" % i) for i in range(200)]
    _gmgn_tiruan(monkeypatch, {"robinhood": [("0x492f", "Levera")]}, {"0x492f": banyak})
    hasil, catatan = cw.cari_di_token(fragmen, "LEVERA robinhood")
    assert hasil == [] and "terlalu pendek" in catatan


def test_token_yang_sama_tidak_disisir_dua_kali(monkeypatch):
    palsu = _gmgn_tiruan(
        monkeypatch,
        {"robinhood": [("0x492F", "Levera Markets"), ("0x492f", "Levera Markets")]},
        {"0x492F": [_trader("0xdaddc6d4839197e684874b08f6fccc4670b309d9")]})
    hasil, _ = cw.cari_di_token("0xda...09d9", "LEVERA robinhood")
    assert len(palsu.dipanggil) == 1
    assert len(hasil) == 1


def test_hasil_diurutkan_dari_yang_paling_dekat(monkeypatch):
    """"mengandung" sempat tercetak di atas "awalan" hanya karena tokennya lebih dulu
    disisir — yang dibaca user pertama justru calon yang paling lemah."""
    lemah = "0xfffdad111111111111111111111111111111dead"
    kuat = "0xdad" + "1" * 33 + "dead"
    _gmgn_tiruan(monkeypatch, {"robinhood": [("0x492f", "Levera")]},
                 {"0x492f": [_trader(lemah), _trader(kuat)]})
    hasil, catatan = cw.cari_di_token("dad", "LEVERA robinhood")
    assert [h["alamat"] for h in hasil] == [kuat, lemah]
    # Jenis kecocokannya ikut ditulis, seperti di kartu pencarian biasa.
    kartu = cw.kartu_token("dad", "LEVERA robinhood", hasil, catatan)
    assert "awalannya cocok" in kartu and "mengandung" in kartu


def test_rugi_ditulis_minus_di_depan_dolar():
    """Di daftar trader angka minus itu biasa; "$-354,67" terbaca seperti salah cetak."""
    assert cw._uang(-354.67) == "-$354,67"
    assert cw._uang(-1234.5) == "-$1.234,50"


SOLANA = "Hn7xK9PqR2sTuVwXyZaBcDeFgHjKmNpQrStUvWxYz12"


@pytest.mark.parametrize("fragmen,kelas", [
    ("Hn7x...Yz12", "awalan+akhiran"),
    ("hn7x", "awalan"),
    ("k9pqr2", "mengandung"),
    ("Zz9x...Yz12", None),
])
def test_potongan_alamat_solana_bisa_dicocokkan(fragmen, kelas):
    """Alamat Solana base58, bukan hex. Semua pola dulu hex-saja, jadi fragmen Solana tak
    pernah bisa cocok — dan user tetap dijawab "tidak ada di daftar trader", seolah sudah
    diperiksa."""
    assert cw._kecocokan(cw._bersih(fragmen), SOLANA, None) == kelas


def test_kode_chain_gmgn_bukan_nama_chain_kita(monkeypatch):
    """GMGN memakai "sol", bukan "solana". Yang dikirim mentah TIDAK ditolak — GMGN
    menjawab 200 dengan 0 kandidat (run 35813445159: "sol" 76, "solana" 0), jadi
    sapuan Solana mati tanpa meninggalkan jejak apa pun."""
    dicatat = []

    class GmgnPalsu:
        BASIS = "https://openapi.gmgn.ai/v1"

        @staticmethod
        def _url(jalur, param):
            dicatat.append(param.get("chain"))
            return jalur

        @staticmethod
        def try_json(url):
            return {"data": {"coins": []}}

    monkeypatch.setitem(sys.modules, "gmgn", GmgnPalsu)
    cw.gmgn_cari("levera", "solana")
    cw.gmgn_cari("levera", "ethereum")
    cw.gmgn_trader("solana", "0x1")
    assert dicatat == ["sol", "eth", "sol"]


def test_chain_tanpa_indeks_alamat_dikatakan(monkeypatch):
    """"--chain bsc" dulu diterima diam-diam lalu tidak menyisir apa pun — hasil kosongnya
    terbaca seolah BSC sudah diperiksa."""
    _hasil, catatan = cw.cari_dengan_catatan("f9778", "bsc")
    assert "bsc" in catatan and "tidak punya indeks" in catatan
    assert "tidak punya indeks" not in cw.cari_dengan_catatan("f9778", "ethereum")[1]


def test_di_yang_ternyata_nama_chain_jatuh_ke_pencarian_biasa(monkeypatch, capsys):
    """"cari wallet f977 di ethereum" menyebut CHAIN, bukan token."""
    monkeypatch.setattr(sys, "argv", ["cariwallet.py", "f9778", "--di", "ethereum", "--json"])
    monkeypatch.setattr(cw, "cari_di_token",
                        lambda *a, **k: pytest.fail("tidak boleh dicari sebagai token"))
    cw.main()
    keluar = json.loads(capsys.readouterr().out)
    assert keluar["hasil"] and "token" not in keluar


# ---- liputan pencarian: banyak koin senama, beberapa jaringan (23 Sep 2026) ---------------
# Angka nyata dari run 35813836601: "LEVERA" cocok dengan 309 token di lima chain
# (robinhood 61, bsc 75, base 62, solana 76, ethereum 35), sedangkan jatah penyisiran cuma
# belasan. Jadi yang menentukan berhasil-tidaknya bukan jumlahnya, melainkan URUTAN dan
# PEMBAGIAN jatahnya — dan bagian yang tidak sempat diperiksa harus dikatakan.

def test_jatah_dibagi_merata_antar_chain(monkeypatch):
    """Dulu jatah diambil dari pangkal daftar yang disusun chain demi chain: seluruh jatah
    habis di chain pertama dan empat chain lain tidak pernah disentuh sama sekali."""
    banyak = {c: [(f"0x{c}{i:03x}", f"Levera {i}") for i in range(20)]
              for c in ("robinhood", "bsc", "base", "solana", "ethereum")}
    palsu = _gmgn_tiruan(monkeypatch, banyak, {})
    _hasil, catatan = cw.cari_di_token("0xda...09d9", "LEVERA", maks_token=10)
    chain_disisir = {c for c, _a in palsu.dipanggil}
    assert chain_disisir == set(banyak), chain_disisir
    assert "10 dari 100 token" in catatan, catatan
    for c in banyak:
        assert f"{c} 2/20" in catatan, catatan


def test_daftar_trader_yang_gagal_dibaca_tidak_dihitung_sebagai_tidak_ada(monkeypatch):
    """Run 35813736311: batas laju GMGN membuat SELURUH penyisiran pulang kosong, lalu
    dilaporkan "tidak ada alamat yang cocok" — kalimat yang terbaca seperti jawaban,
    padahal tidak satu pun daftar berhasil dibaca."""
    _gmgn_tiruan(monkeypatch, {"robinhood": [("0x492f", "Levera Markets")]}, {})
    monkeypatch.setattr(cw, "gmgn_trader", lambda *a, **k: None)
    hasil, catatan = cw.cari_di_token("0xda...09d9", "LEVERA robinhood")
    assert hasil == []
    assert "gagal dibaca" in catatan and "belum diperiksa" in catatan
    assert "BERHASIL dibaca" in catatan


def test_chain_yang_tidak_bisa_ditanya_dikatakan(monkeypatch):
    _gmgn_tiruan(monkeypatch, {}, {})
    monkeypatch.setattr(cw, "gmgn_cari", lambda q, c: None)
    hasil, catatan = cw.cari_di_token("0xda...09d9", "LEVERA robinhood")
    assert hasil == []
    assert "BELUM dicari" in catatan and "tidak ketemu" in catatan


def test_kandidat_diurutkan_dari_yang_paling_mungkin(monkeypatch):
    """Likuiditas memisahkan token yang benar dari tiruan senamanya: di run 35813836601
    Levera Markets punya $7.002 sedangkan dua tiruannya $0,00 dan $379."""
    coins = [
        {"address": "0xtiruan", "name": "Levera.fun", "symbol": "LEVERA",
         "liquidity": "0.000000", "holder_count": 1, "mcp": "4349"},
        {"address": "0xasli", "name": "Levera Markets", "symbol": "LEVERA",
         "liquidity": "7002.118997", "holder_count": 40, "mcp": "5157"},
        {"address": "0xtengah", "name": "LEVERAGE", "symbol": "LEVERA",
         "liquidity": "379.737521", "holder_count": 3, "mcp": "4196"},
        {"address": "0xlain", "name": "Bukan Yang Dicari", "symbol": "XYZ",
         "liquidity": "999999", "holder_count": 9},
    ]

    class GmgnPalsu:
        BASIS = "b"
        _url = staticmethod(lambda jalur, param: jalur)
        try_json = staticmethod(lambda url: {"data": {"coins": coins}})

    monkeypatch.setitem(sys.modules, "gmgn", GmgnPalsu)
    assert cw.gmgn_cari("levera", "robinhood") == [
        ("0xasli", "Levera Markets"), ("0xtengah", "LEVERAGE"), ("0xtiruan", "Levera.fun")]


def test_permintaan_gagal_bukan_daftar_kosong(monkeypatch):
    """None berarti GAGAL, [] berarti benar-benar tidak ada. Selama keduanya [], batas laju
    tidak bisa dibedakan dari jawaban."""
    class GmgnPalsu:
        BASIS = "b"
        _url = staticmethod(lambda jalur, param: jalur)
        try_json = staticmethod(lambda url: {"__err": "429 Too Many Requests"})

    monkeypatch.setitem(sys.modules, "gmgn", GmgnPalsu)
    assert cw.gmgn_cari("levera", "robinhood") is None
    assert cw.gmgn_trader("robinhood", "0x1") is None


# ---- explorer sebagai jaring yang lebih lebar (23 Sep 2026) -------------------------------
# Daftar trader GMGN hanya 100 teratas per token. Etherscan V2 memberi SETIAP alamat yang
# pernah menyentuh token itu — jadi dompet kecil pun terjangkau. Gratis untuk Ethereum,
# Robinhood, dan Arbitrum; BSC & Base hanya untuk paket berbayar, dan itu dikatakan.

class _ExplorerPalsu:
    CHAIN = {"ethereum": 1, "robinhood": 4663, "arbitrum": 42161}
    dipakai = []
    punya_kunci = True
    isi = set()

    @staticmethod
    def kunci():
        return "kunci-uji" if _ExplorerPalsu.punya_kunci else ""

    @staticmethod
    def catatan_kunci():
        return "ETHERSCAN_API_KEY belum dipasang, jadi bagian itu belum diperiksa."

    @staticmethod
    def alamat_token(chain, kontrak, halaman=3):
        _ExplorerPalsu.dipakai.append((chain, kontrak))
        return set(_ExplorerPalsu.isi), f"Explorer {chain}: {len(_ExplorerPalsu.isi)} alamat."


@pytest.fixture
def explorer(monkeypatch):
    _ExplorerPalsu.dipakai = []
    _ExplorerPalsu.punya_kunci = True
    _ExplorerPalsu.isi = set()
    monkeypatch.setitem(sys.modules, "etherscan", _ExplorerPalsu)
    return _ExplorerPalsu


def test_explorer_menjangkau_alamat_di_luar_100_trader(monkeypatch, explorer):
    target = "0xdaddc6d4839197e684874b08f6fccc4670b309d9"
    explorer.isi = {target, "0x" + "b" * 40}
    # GMGN tidak memuat dompet ini di 100 teratasnya.
    _gmgn_tiruan(monkeypatch, {"robinhood": [("0x492f", "Levera Markets")]},
                 {"0x492f": [_trader("0xbeef" + "0" * 35)]})
    hasil, catatan = cw.cari_di_token("0xda...09d9", "LEVERA robinhood")
    assert [h["alamat"] for h in hasil] == [target]
    assert hasil[0]["sumber"] == "explorer (robinhood)"
    assert explorer.dipakai == [("robinhood", "0x492f")]
    assert "Explorer robinhood" in catatan


def test_explorer_tidak_dipakai_untuk_chain_yang_tidak_dilayani(monkeypatch, explorer):
    explorer.isi = {"0xdaddc6d4839197e684874b08f6fccc4670b309d9"}
    _gmgn_tiruan(monkeypatch, {"bsc": [("0x1", "Levera")]}, {})
    _hasil, _catatan = cw.cari_di_token("0xda...09d9", "LEVERA bsc")
    assert explorer.dipakai == [], "bsc hanya untuk paket berbayar"


def test_kunci_explorer_hilang_dikatakan_bukan_didiamkan(monkeypatch, explorer):
    explorer.punya_kunci = False
    _gmgn_tiruan(monkeypatch, {"robinhood": [("0x492f", "Levera Markets")]}, {})
    _hasil, catatan = cw.cari_di_token("0xda...09d9", "LEVERA robinhood")
    assert "ETHERSCAN_API_KEY" in catatan and "belum diperiksa" in catatan


def test_hasil_explorer_tanpa_angka_tidak_merusak_kartu(monkeypatch, explorer):
    """Hasil explorer tidak punya profit/beli/jual — kartunya harus tetap utuh."""
    target = "0xdaddc6d4839197e684874b08f6fccc4670b309d9"
    explorer.isi = {target}
    _gmgn_tiruan(monkeypatch, {"robinhood": [("0x492f", "Levera Markets")]}, {})
    hasil, catatan = cw.cari_di_token("0xda...09d9", "LEVERA robinhood")
    kartu = cw.kartu_token("0xda...09d9", "LEVERA robinhood", hasil, catatan)
    assert target in kartu and "explorer (robinhood)" in kartu
    assert "profit" not in kartu

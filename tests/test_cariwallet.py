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

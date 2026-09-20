"""Tes wallet.py — pengganti Moralis (19 Sep 2026).

Akun Moralis habis masa uji coba ("Free Trial Plan usage 0 of 0 CU", Data API terkunci),
jadi seluruh fitur isi dompet mati. Pengganti yang diuji terbuka tanpa key: Blockscout
(ethereum/base/arbitrum/optimism/polygon), Routescan (avalanche), RPC publik Solana (saldo
SOL saja — getTokenAccountsByOwner ditolak). BSC tidak punya sumber gratis.
"""

import json
import os
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import wallet  # noqa: E402

W = "0xF977814e90dA44bFA03b6295A0616a897441aceC"


def _blockscout(url, headers=None, data=None):
    if url.endswith(f"/addresses/{W}"):
        return {"coin_balance": "2000000000000000000", "exchange_rate": "3000"}
    if url.endswith(f"/addresses/{W}/token-balances"):
        return [
            {"value": "5000000", "token": {"symbol": "USDT", "name": "Tether", "decimals": "6",
                                           "exchange_rate": "1.0", "reputation": "ok"}},
            {"value": "10" + "0" * 18, "token": {"symbol": "SCAM", "name": "Claim reward",
                                                 "decimals": "18", "exchange_rate": "99",
                                                 "reputation": "scam"}},
            {"value": "7", "token": {"symbol": "NOPRICE", "name": "x", "decimals": "0",
                                     "exchange_rate": None, "reputation": "ok"}},
        ]
    raise AssertionError(url)


def test_blockscout_wallet_nilai_dan_spam(monkeypatch):
    monkeypatch.setattr(wallet, "try_json", _blockscout)
    p = wallet.blockscout_wallet(W, "base")
    sim = {h["symbol"]: h for h in p["holdings"]}
    assert "SCAM" not in sim                       # reputasi scam dibuang
    assert sim["ETH"]["usd"] == 6000.0 and sim["ETH"]["native"] is True
    assert sim["USDT"]["usd"] == 5.0 and sim["USDT"]["jumlah"] == 5.0
    assert sim["NOPRICE"]["usd"] is None           # tanpa harga: bukan 0 yang menyesatkan
    assert p["nilai_bersih_usd"] == 6005.0
    assert p["holdings"][0]["symbol"] == "ETH"     # terurut nilai
    assert sim["ETH"]["persen_portofolio"] == pytest.approx(99.92, abs=0.01)


def test_routescan_wallet(monkeypatch):
    monkeypatch.setattr(wallet, "try_json", lambda url, headers=None, data=None: {"items": [
        {"tokenSymbol": "USDt", "tokenName": "TetherToken", "tokenDecimals": 6,
         "tokenQuantity": "8867977", "tokenValueInUsd": "8.865"}]})
    p = wallet.routescan_wallet(W)
    assert p["holdings"][0]["usd"] == 8.87 and p["holdings"][0]["jumlah"] == 8.867977


def test_solana_saldo_sol_dari_rpc(monkeypatch):
    monkeypatch.setattr(wallet, "try_json",
                        lambda url, headers=None, data=None: {"result": {"value": 34598135245}})
    p = wallet.solana_wallet("5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1")
    assert p["holdings"][0]["symbol"] == "SOL" and p["holdings"][0]["jumlah"] == 34.598135245
    assert "token SPL" in p["catatan"]


def test_bsc_disebut_tanpa_sumber_gratis(monkeypatch, capsys):
    monkeypatch.setattr(wallet, "MORALIS_KEY", "")
    monkeypatch.setattr(sys, "argv", ["wallet.py", W, "--chain", "bsc"])
    wallet.main()
    h = json.loads(capsys.readouterr().out)
    assert "tidak ada sumber gratis" in h["portofolio"]["error"]


@pytest.mark.parametrize("chain,harap", [
    ("ethereum", "Blockscout"), ("base", "Blockscout"), ("avalanche", "Routescan"),
    ("solana", "RPC publik Solana"),
])
def test_sumber_tercatat_benar(monkeypatch, capsys, chain, harap):
    monkeypatch.setattr(wallet, "try_json", lambda url, headers=None, data=None: {"__err": "x"})
    addr = W if chain != "solana" else "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
    monkeypatch.setattr(sys, "argv", ["wallet.py", addr, "--chain", chain])
    wallet.main()
    assert harap in json.loads(capsys.readouterr().out)["sumber"]


KUNCI_RAHASIA = "eyJhbGciOiJIUzI1NiJ9.eyJyYWhhc2lhIjoieWEifQ.tandatanganRahasia123"


@pytest.mark.parametrize("jawaban,ok", [
    ({"result": []}, True),
    ({"__err": 'HTTP 401 {"message":"Token is invalid format"}'}, False),
])
def test_periksa_kunci_tidak_pernah_mencetak_isinya(monkeypatch, jawaban, ok):
    """Log Actions repo ini publik: laporan pemeriksaan tidak boleh memuat sepotong pun kunci."""
    monkeypatch.setattr(wallet, "try_json", lambda url, headers=None, data=None: jawaban)
    hasil, lap = wallet.periksa_kunci(KUNCI_RAHASIA)
    teks = "\n".join(lap)
    assert hasil is ok
    for potong in KUNCI_RAHASIA.split("."):
        assert potong not in teks
    assert "wajar (JWT)" in teks


@pytest.mark.parametrize("kunci,harap", [
    ("", "TIDAK ADA"),
    ("abc123", "BUKAN JWT"),
    ('"eyJa.eyJb.c"', "tanda kutip"),
])
def test_periksa_kunci_mendiagnosis_bentuk(monkeypatch, kunci, harap):
    monkeypatch.setattr(wallet, "try_json", lambda url, headers=None, data=None: {"__err": "HTTP 401"})
    hasil, lap = wallet.periksa_kunci(kunci) if kunci else wallet.periksa_kunci("  ")
    assert hasil is False and harap in "\n".join(lap)


def test_401_kuota_dihentikan_tidak_disebut_key_salah():
    """Periksa 19 Sep: key sah (JWT), tapi Moralis membalas 401 'Free usage is paused'."""
    pesan = wallet._galat_moralis(
        'HTTP 401 {"message":"Your Moralis Free usage is paused. Upgrade to a paid plan'
        ' to resume usage."}')
    assert "key-nya sah" in pesan and "tidak valid" not in pesan

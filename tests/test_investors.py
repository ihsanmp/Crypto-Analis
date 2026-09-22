"""Tes investors.py — resolusi kontrak & pesan galat.

Run 35289835742 (18 Sep, "skor naratif TAO"): TAO adalah koin natif chain Bittensor, tapi
CoinGecko mencantumkan kontrak TAO versi bridge di Base. investors.py memakainya, menarik
holder token bridge itu lewat Moralis, dan kena HTTP 401. Balasannya lalu menulis "Tim & VC
tidak bisa dinilai — data investor gagal ditarik (Moralis 401)": holder on-chain dibaca
sebagai data VC, padahal sumber ini tidak pernah memuat VC sama sekali.
"""

import json
import os
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import investors  # noqa: E402

TAO_BASE = "0xf3081494b87e8d5fb7960f066e931d1d0e6e3d67"


def _palsu_cg(asset_platform_id, platforms):
    def try_json(url, headers=None):
        if "/search?" in url:
            return {"coins": [{"id": "bittensor", "symbol": "TAO"}]}
        if "/coins/" in url:
            return {"name": "Bittensor", "asset_platform_id": asset_platform_id,
                    "platforms": platforms}
        if "moralis" in url:
            return {"__err": 'HTTP 401 {"message":"Token is invalid format"}'}
        if "blockscout" in url:
            return {"items": []} if url.endswith("/holders") else {"total_supply": "1"}
        raise AssertionError(f"URL tak terduga: {url}")
    return try_json


def _jalankan(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["investors.py"] + argv)
    investors.main()
    return json.loads(capsys.readouterr().out)


def test_koin_natif_tidak_memakai_kontrak_bridge(monkeypatch, capsys):
    # Koin natif: asset_platform_id kosong; platforms hanya berisi versi bridge/wrapped.
    monkeypatch.setattr(investors, "try_json", _palsu_cg(None, {"base": TAO_BASE, "": ""}))
    h = _jalankan(monkeypatch, capsys, ["TAO"])
    assert "kontrak" not in h and "chain" not in h
    assert "natif" in h["error"] and "bridge" in h["error"]
    assert "base" in h["error"]


def test_koin_natif_tetap_bisa_dipaksa(monkeypatch, capsys):
    """User yang SENGAJA meminta chain tertentu tetap dilayani."""
    monkeypatch.setattr(investors, "try_json", _palsu_cg(None, {"base": TAO_BASE}))
    h = _jalankan(monkeypatch, capsys, ["TAO", "--chain", "base"])
    assert h["kontrak"] == TAO_BASE


def test_token_kontrak_tetap_berjalan(monkeypatch, capsys):
    monkeypatch.setattr(investors, "try_json", _palsu_cg("base", {"base": TAO_BASE}))
    h = _jalankan(monkeypatch, capsys, ["XYZ"])
    assert h["kontrak"] == TAO_BASE and h["chain"] == "base"


@pytest.mark.parametrize("platform,platforms", [
    (None, {"base": TAO_BASE}),          # jalur error natif
])
def test_setiap_keluaran_menegaskan_holder_bukan_data_vc(monkeypatch, capsys, platform, platforms):
    monkeypatch.setattr(investors, "try_json", _palsu_cg(platform, platforms))
    h = _jalankan(monkeypatch, capsys, ["XYZ"])
    teks = " ".join(h["peringatan"])
    assert "BUKAN data VC" in teks and "Tim & VC" in teks


# ---- Pengganti Moralis (19 Sep): akun Moralis habis masa uji coba, "0 of 0" CU. ----------
# Hasil probe: Blockscout terbuka tanpa key untuk ethereum/base/arbitrum/optimism/polygon,
# Routescan untuk avalanche. BSC & Solana tidak punya sumber gratis tanpa key (Ankr 403,
# Routescan 400, Etherscan v2 "upgrade", RPC publik Solana 429 untuk metode ini).

AERO = "0x940181a94a35a4569e4529a3cdfb74e38fd98631"


def _blockscout_palsu(url, headers=None):
    if url.endswith(f"/tokens/{AERO}"):
        return {"name": "Aerodrome", "symbol": "AERO", "holders_count": "123",
                "total_supply": "1000", "decimals": "18"}
    if url.endswith(f"/tokens/{AERO}/holders"):
        return {"items": [
            {"address": {"hash": "0xA", "is_contract": True, "name": None,
                         "metadata": {"tags": [{"name": "Aerodrome: Voting Escrow", "tagType": "name"},
                                               {"name": "DeFi", "tagType": "generic"}]}},
             "value": "400"},
            {"address": {"hash": "0xB", "is_contract": False, "name": None, "metadata": None},
             "value": "100"},
        ]}
    raise AssertionError(url)


def test_blockscout_menghitung_persen_dan_label(monkeypatch):
    monkeypatch.setattr(investors, "try_json", _blockscout_palsu)
    daftar, token, err = investors.blockscout_holders(AERO, "base", 10)
    assert err is None and token["symbol"] == "AERO"
    assert daftar[0] == {"alamat": "0xA", "persen_supply": 40.0,
                         "label": "Aerodrome: Voting Escrow", "kategori": "KONTRAK/PROTOKOL"}
    assert daftar[1]["persen_supply"] == 10.0
    assert daftar[1]["kategori"].startswith("TIDAK DIKENALI")


def test_blockscout_timeout_dilaporkan_bukan_crash(monkeypatch):
    monkeypatch.setattr(investors, "try_json", lambda url, headers=None: {"__err": "TimeoutError: x"})
    daftar, token, err = investors.blockscout_holders(AERO, "base", 10)
    assert daftar is None and "Blockscout" in err


def test_routescan_pecahan_jadi_persen(monkeypatch):
    monkeypatch.setattr(investors, "try_json", lambda url, headers=None: {"items": [
        {"address": "0xA", "balance": "5", "percentage": 0.209452}]})
    daftar, _, err = investors.routescan_holders("0x" + "1" * 40, 10)
    assert err is None and daftar[0]["persen_supply"] == 20.95


@pytest.mark.parametrize("chain,harap", [
    ("base", "Blockscout"), ("arbitrum", "Blockscout"), ("optimism", "Blockscout"),
    ("polygon", "Blockscout"), ("avalanche", "Routescan"), ("ethereum", "Ethplorer"),
])
def test_rute_tidak_lagi_lewat_moralis(chain, harap):
    assert harap in investors.SUMBER_CHAIN[chain]


def test_kontrak_bernama_tanpa_kata_kunci_tetap_kontrak():
    assert investors.klasifikasi_alamat(None, "Aave Matic Market AAVE", True) == (
        "Aave Matic Market AAVE", "KONTRAK/PROTOKOL")
    assert investors.klasifikasi_alamat(None, "Binance 8", False)[1] == "BURSA"
    assert investors.klasifikasi_alamat(None, "Wintermute", False)[1] == "TERLABELI"


# ---- GoPlus menutup celah BSC & Solana (20 Sep 2026) --------------------------------------
# Kesimpulan 19 Sep "BSC & Solana tidak punya sumber gratis" TERNYATA SALAH: GoPlus Security
# memberi daftar pemegang untuk keduanya, tanpa key. Dicek dari kartu bot pemindai token:
# angkanya cocok (holder 7.914, pajak 1%), dan GoPlus juga menyebut LP terkunci atau tidak.

CAKE = "0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82"
MATI = "0x000000000000000000000000000000000000dead"


def _goplus_evm(url, headers=None):
    assert "gopluslabs.io/api/v1/token_security/56" in url
    return {"result": {CAKE: {
        "token_name": "PancakeSwap Token", "token_symbol": "Cake",
        "holder_count": "1911826", "total_supply": "5375267287.75",
        "holders": [
            {"address": MATI, "tag": "", "is_contract": 0, "percent": "0.9285", "is_locked": 1},
            {"address": "0xf977814e", "tag": "Binance", "is_contract": 0,
             "percent": "0.0146", "is_locked": 0},
            {"address": "0xabc", "tag": "", "is_contract": 1, "percent": "0.005", "is_locked": 0},
        ]}}}


def _goplus_sol(url, headers=None):
    assert "gopluslabs.io/api/v1/solana/token_security" in url
    return {"result": {"MINT": {
        "metadata": {"name": "Jupiter", "symbol": "JUP"}, "holder_count": 828815,
        "holders": [{"account": "EXJHiMkj", "percent": "0.2478", "tag": "", "is_locked": 0}]}}}


def test_goplus_bsc_persen_label_dan_alamat_burn(monkeypatch):
    monkeypatch.setattr(investors, "try_json", _goplus_evm)
    daftar, token, err = investors.goplus_holders(CAKE, 56, 10)
    assert err is None and token["symbol"] == "Cake" and token["jumlah_holder"] == 1911826
    assert daftar[0]["persen_supply"] == 92.85
    # Token yang DIBAKAR bukan konsentrasi di satu tangan — harus dibedakan, bukan
    # dihitung sebagai whale 92% yang menakutkan.
    assert daftar[0]["kategori"] == "BURN/HANGUS"
    assert daftar[1] == {"alamat": "0xf977814e", "persen_supply": 1.46,
                         "label": "Binance", "kategori": "BURSA"}
    assert daftar[2]["kategori"] == "KONTRAK/PROTOKOL"


def test_konsentrasi_tidak_menghitung_alamat_burn(monkeypatch, capsys):
    monkeypatch.setattr(investors, "try_json", lambda url, headers=None: (
        _palsu_cg("binance-smart-chain", {"binance-smart-chain": CAKE})(url)
        if "coingecko" in url else _goplus_evm(url)))
    h = _jalankan(monkeypatch, capsys, ["CAKE"])
    assert h["konsentrasi"]["top10_non_bursa_kontrak_persen"] == 0.0


def test_goplus_solana(monkeypatch):
    monkeypatch.setattr(investors, "try_json", _goplus_sol)
    daftar, token, err = investors.goplus_solana_holders("MINT", 10)
    assert err is None and token["symbol"] == "JUP"
    assert daftar[0]["alamat"] == "EXJHiMkj" and daftar[0]["persen_supply"] == 24.78


def test_goplus_gagal_dilaporkan(monkeypatch):
    monkeypatch.setattr(investors, "try_json", lambda url, headers=None: {"__err": "HTTP 429"})
    daftar, _, err = investors.goplus_holders(CAKE, 56, 10)
    assert daftar is None and "GoPlus" in err and "429" in err


@pytest.mark.parametrize("chain", ["bsc", "solana"])
def test_bsc_dan_solana_kini_punya_sumber(chain):
    assert "GoPlus" in investors.SUMBER_CHAIN[chain]


def test_moralis_tidak_lagi_dipakai_untuk_holder():
    """Akunnya berbayar dan tidak ada jalur holder yang membutuhkannya lagi — kode mati
    yang pesannya menyuruh user mengurus langganan hanya menyesatkan. Pemeriksa kuncinya
    pindah ke wallet.py, satu-satunya pemakai Moralis yang tersisa (isi dompet BSC)."""
    isi = open(os.path.join(AKAR, "cloud", "investors.py"), encoding="utf-8").read()
    assert "moralis" not in isi.lower(), "sisa jalur Moralis di investors.py"


def test_robinhood_lewat_goplus():
    assert investors.GOPLUS_CHAIN["robinhood"] == 4663
    assert investors.CHAINS["robinhood"]["cg"] == "robinhood"
    assert "GoPlus" in investors.SUMBER_CHAIN["robinhood"]


def test_goplus_tanpa_daftar_pemegang_dilaporkan(monkeypatch):
    """Di Robinhood, GoPlus menjawab tanpa field holders sama sekali. Daftar kosong yang
    dikembalikan diam-diam akan terbaca sebagai "tidak ada yang memegang token ini"."""
    monkeypatch.setattr(investors, "try_json", lambda url, headers=None: {
        "result": {CAKE: {"token_name": "PairPad", "token_symbol": "PAIR"}}})
    daftar, token, err = investors.goplus_holders(CAKE, 4663, 10)
    assert daftar is None and err and "pemegang" in err.lower()

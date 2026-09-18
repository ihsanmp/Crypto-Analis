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
        raise AssertionError(f"URL tak terduga: {url}")
    return try_json


def _jalankan(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["investors.py"] + argv)
    investors.main()
    return json.loads(capsys.readouterr().out)


def test_koin_natif_tidak_memakai_kontrak_bridge(monkeypatch, capsys):
    # Koin natif: asset_platform_id kosong; platforms hanya berisi versi bridge/wrapped.
    monkeypatch.setattr(investors, "try_json", _palsu_cg(None, {"base": TAO_BASE, "": ""}))
    monkeypatch.setattr(investors, "MORALIS_KEY", "kunci")
    h = _jalankan(monkeypatch, capsys, ["TAO"])
    assert "kontrak" not in h and "chain" not in h
    assert "natif" in h["error"] and "bridge" in h["error"]
    assert "base" in h["error"]


def test_koin_natif_tetap_bisa_dipaksa(monkeypatch, capsys):
    """User yang SENGAJA meminta chain tertentu tetap dilayani."""
    monkeypatch.setattr(investors, "try_json", _palsu_cg(None, {"base": TAO_BASE}))
    monkeypatch.setattr(investors, "MORALIS_KEY", "kunci")
    h = _jalankan(monkeypatch, capsys, ["TAO", "--chain", "base"])
    assert h["kontrak"] == TAO_BASE


def test_token_kontrak_tetap_berjalan(monkeypatch, capsys):
    monkeypatch.setattr(investors, "try_json", _palsu_cg("base", {"base": TAO_BASE}))
    monkeypatch.setattr(investors, "MORALIS_KEY", "kunci")
    h = _jalankan(monkeypatch, capsys, ["XYZ"])
    assert h["kontrak"] == TAO_BASE and h["chain"] == "base"


def test_401_moralis_menyebut_secret_yang_harus_diperbarui(monkeypatch, capsys):
    monkeypatch.setattr(investors, "try_json", _palsu_cg("base", {"base": TAO_BASE}))
    monkeypatch.setattr(investors, "MORALIS_KEY", "kunci")
    h = _jalankan(monkeypatch, capsys, ["XYZ"])
    assert "401" in h["error"] and "MORALIS_API_KEY" in h["error"]
    assert "menolak API key" in h["error"]


@pytest.mark.parametrize("platform,platforms", [
    (None, {"base": TAO_BASE}),          # jalur error natif
    ("base", {"base": TAO_BASE}),        # jalur error 401
])
def test_setiap_keluaran_menegaskan_holder_bukan_data_vc(monkeypatch, capsys, platform, platforms):
    monkeypatch.setattr(investors, "try_json", _palsu_cg(platform, platforms))
    monkeypatch.setattr(investors, "MORALIS_KEY", "kunci")
    h = _jalankan(monkeypatch, capsys, ["XYZ"])
    teks = " ".join(h["peringatan"])
    assert "BUKAN data VC" in teks and "Tim & VC" in teks

"""Tes fundamentals.py — resolusi protokol vs CHAIN.

Run 35489055215 ("analisa sui", 20 Sep 2026): DefiLlama punya protokol bernama
"Sui Foundation" berkategori Canonical Bridge dengan symbol SUI, dan itulah yang terambil.
Akibatnya revenue chain Sui dilaporkan $826 rb TTM (fees bridge), padahal chain-nya sendiri
$88 juta setahun — lalu dipakai menghitung P/S 4.082x. Modelnya kebetulan curiga dan
menurunkan bobotnya sendiri; kalau tidak, rasio itu masuk skor sebagai fakta.
"""

import json
import os
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import fundamentals as fd  # noqa: E402

_CHAINS = [{"name": "Sui", "tokenSymbol": "SUI", "tvl": 487405182.0},
           {"name": "Ethereum", "tokenSymbol": "ETH", "tvl": 9e10}]
_PROTOKOL = [{"name": "Sui Foundation", "slug": "sui-foundation", "symbol": "SUI",
              "category": "Canonical Bridge", "tvl": None, "mcap": 3376115115.0},
             {"name": "Aave V3", "slug": "aave-v3", "symbol": "AAVE",
              "category": "Lending", "tvl": 2e10, "mcap": 4e9}]
_CHART = [[1789689600, 100000.0], [1789862400, 124333.34]]


def _palsu(url):
    if url.endswith("/v2/chains"):
        return _CHAINS
    if url.endswith("/protocols"):
        return _PROTOKOL
    if "/overview/fees/sui" in url:
        return {"totalDataChart": _CHART, "total30d": 3339506.71, "total1y": 88292848.35}
    if "/v2/historicalChainTvl/sui" in url:
        return [{"date": 1789689600, "tvl": 480000000}, {"date": 1789862400, "tvl": 487416323}]
    return None


def _jalankan(monkeypatch, capsys, argv):
    monkeypatch.setattr(fd, "try_json", _palsu)
    monkeypatch.setattr(fd, "http_json", _palsu)
    monkeypatch.setattr(sys, "argv", ["fundamentals.py"] + argv)
    fd.main()
    return json.loads(capsys.readouterr().out)


def test_koin_chain_tidak_diambil_dari_protokol_bridge(monkeypatch, capsys):
    h = _jalankan(monkeypatch, capsys, ["SUI"])
    assert h["protokol"]["name"] == "Sui"
    assert "Bridge" not in (h["protokol"]["category"] or "")
    assert h["protokol"]["slug"] == "sui"
    assert h["fees"]["total_1thn_usd"] == 88292848.35
    assert h["tvl"]["sekarang_usd"] == 487416323


def test_chain_ditandai_supaya_tidak_dibaca_sebagai_protokol(monkeypatch, capsys):
    h = _jalankan(monkeypatch, capsys, ["SUI"])
    teks = " ".join(h["catatan"])
    assert "chain" in teks.lower() and "protokol" in teks.lower()


def test_valuasi_chain_memakai_angka_chain(monkeypatch, capsys):
    h = _jalankan(monkeypatch, capsys, ["SUI", "--mcap", "3374000000"])
    # P/F dari fees chain (TTM dari deret), bukan dari fees bridge.
    assert h["valuasi"]["mc_tvl"] == pytest.approx(3374000000 / 487416323, abs=0.01)


def test_token_protokol_tetap_lewat_jalur_lama(monkeypatch, capsys):
    h = _jalankan(monkeypatch, capsys, ["AAVE"])
    assert h["protokol"]["name"] == "Aave V3" and h["protokol"]["category"] == "Lending"


def test_slug_paksa_mengalahkan_deteksi_chain(monkeypatch, capsys):
    h = _jalankan(monkeypatch, capsys, ["SUI", "--slug", "sui-foundation"])
    assert h["protokol"]["slug"] == "sui-foundation"

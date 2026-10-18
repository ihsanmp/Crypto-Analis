"""Cadangan Yahoo (18 Okt 2026): host kedua + coba ulang galat sementara; simbol forex."""
import io
import json
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import market  # noqa: E402
import yahoo  # noqa: E402


class _Balas(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _palsu(urutan, diminta):
    def buka(req, timeout):
        diminta.append(req.full_url)
        hasil = urutan.pop(0)
        if isinstance(hasil, Exception):
            raise hasil
        return _Balas(json.dumps(hasil).encode())
    return buka


def _http(kode):
    return urllib.error.HTTPError("u", kode, "x", {}, None)


def test_host_kedua_dipakai_saat_429(monkeypatch):
    diminta = []
    monkeypatch.setattr(yahoo.urllib.request, "urlopen",
                        _palsu([_http(429), {"chart": {"result": [1]}}], diminta))
    assert yahoo.chart("NVDA", "range=1d&interval=1d") == {"chart": {"result": [1]}}
    assert "query1" in diminta[0] and "query2" in diminta[1]


def test_404_tidak_diulang(monkeypatch):
    diminta = []
    monkeypatch.setattr(yahoo.urllib.request, "urlopen", _palsu([_http(404)], diminta))
    with pytest.raises(urllib.error.HTTPError) as e:
        yahoo.chart("TIDAKADA", "range=1d")
    assert e.value.code == 404 and len(diminta) == 1


def test_semua_host_gagal_melempar_galat_terakhir(monkeypatch):
    diminta = []
    monkeypatch.setattr(yahoo.time, "sleep", lambda s: None)
    monkeypatch.setattr(yahoo.urllib.request, "urlopen",
                        _palsu([_http(503), urllib.error.URLError("x"), _http(429)], diminta))
    with pytest.raises(urllib.error.HTTPError) as e:
        yahoo.chart("NVDA", "range=1d")
    assert e.value.code == 429 and len(diminta) == 3


def test_simbol_forex_dan_logam_dinormalkan_untuk_semua_pemanggil_tarik():
    """Bot merutekan 'analisa eurusd' dengan simbol mentah; backtest/proyeksi/kejutan
    memanggil tarik() langsung -> 404 di lima blok tiap analisa forex."""
    assert market.simbol_yahoo("EURUSD") == "EURUSD=X"
    assert market.simbol_yahoo("usdjpy") == "USDJPY=X"
    assert market.simbol_yahoo("EURUSD=X") == "EURUSD=X"
    assert market.simbol_yahoo("XAUUSD") == "GC=F"
    for tetap in ("NVDA", "GOLD", "CL=F", "BTC-USD", "USDUSD"):
        assert market.simbol_yahoo(tetap) == tetap


def test_tarik_memakai_simbol_yahoo(monkeypatch):
    dipakai = []
    monkeypatch.setattr(yahoo, "chart", lambda s, q, timeout=20: (dipakai.append(s),
                                                                  {"chart": {"result": []}})[1])
    market.tarik("EURUSD", "1y", "1d")
    assert dipakai == ["EURUSD=X"]


def test_simbol_yang_sudah_terencode_tidak_diencode_ulang(monkeypatch):
    diminta = []
    monkeypatch.setattr(yahoo.urllib.request, "urlopen",
                        _palsu([{"ok": 1}, {"ok": 1}], diminta))
    yahoo.chart("%5EVIX3M", "range=1mo")
    yahoo.chart("^VIX", "range=1mo")
    assert "/chart/%5EVIX3M?" in diminta[0] and "/chart/%5EVIX?" in diminta[1]

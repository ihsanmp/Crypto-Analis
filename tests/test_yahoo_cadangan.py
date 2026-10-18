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


def test_mingguan_pakai_sumber_lain_bila_riwayat_harian_pendek(monkeypatch):
    """HYPE di Kraken ~260 hari -> 37 minggu; sumber lain dengan riwayat lebih panjang dipakai."""
    import indicators as ind
    hari = 86400000
    pendek = [[i * hari, 1, 1, 1, 1, 0] for i in range(260)]
    panjang = [[i * hari, 1, 2, 0.5, 1, 0] for i in range(400)]
    monkeypatch.setattr(ind, "_DEAD", set())
    monkeypatch.setattr(ind, "EXCHANGES", [("kraken", lambda t, i: pendek),
                                           ("okx", lambda t, i: panjang)])
    w, src, kual = ind.mingguan_cadangan("HYPE", None, "kraken", 37)
    assert src == "okx" and kual == "native" and len(w) >= ind.MIN_MINGGUAN
    # Tidak ada yang lebih panjang -> None (blok tetap jujur "candle tidak cukup").
    monkeypatch.setattr(ind, "EXCHANGES", [("kraken", lambda t, i: pendek)])
    assert ind.mingguan_cadangan("HYPE", None, "kraken", 37) is None


def test_timeout_tidak_diulang_supaya_waktu_tunggu_tidak_berlipat(monkeypatch):
    jam = iter([0.0, 40.0])          # percobaan pertama makan 40 dtk = timeout
    monkeypatch.setattr(yahoo.time, "time", lambda: next(jam))
    diminta = []
    monkeypatch.setattr(yahoo.urllib.request, "urlopen",
                        _palsu([TimeoutError("lambat"), {"ok": 1}], diminta))
    with pytest.raises(TimeoutError):
        yahoo.chart("BTC-USD", "range=1d", timeout=40)
    assert len(diminta) == 1


def test_galat_jaringan_cepat_dicoba_di_host_lain(monkeypatch):
    jam = iter([0.0, 0.2, 1.0])
    monkeypatch.setattr(yahoo.time, "time", lambda: next(jam))
    diminta = []
    monkeypatch.setattr(yahoo.urllib.request, "urlopen",
                        _palsu([urllib.error.URLError("dns"), {"ok": 1}], diminta))
    assert yahoo.chart("BTC-USD", "range=1d", timeout=40) == {"ok": 1}
    assert "query2" in diminta[1]

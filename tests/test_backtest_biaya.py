import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import backtest  # noqa: E402
import uji_jam_likuiditas as uj  # noqa: E402


def test_biaya_per_kelas_aset():
    assert backtest.biaya_untuk("BTC", False) == 0.30
    assert backtest.biaya_untuk("PEPE", False) == 0.60
    assert backtest.biaya_untuk("NVDA", True) == 0.10
    assert backtest.biaya_untuk("GC=F", True) == 0.05


def _hari(n, mulai=date(2020, 1, 1)):
    return [(mulai + timedelta(days=i)).isoformat() for i in range(n)]


def test_keunggulan_dibanding_rata2_paruh_bukan_tanggal_sinyal():
    """Versi pertama membandingkan return sinyal dengan return di TANGGAL yang sama —
    selalu nol. Pembandingnya harus rata-rata seluruh hari paruh itu."""
    hari = _hari(400)
    acak = {t: 1.0 for t in hari}                       # masuk kapan saja: +1%
    kejadian = [{"tanggal": hari[i], "return_persen": 5.0} for i in range(0, 400, 10)]
    for e in kejadian:
        acak[e["tanggal"]] = 5.0                        # hari sinyal itu sendiri
    r = backtest.nilai_oos(kejadian, acak, "beli", 0.30)
    assert r["keunggulan_vs_acak_persen"] > 3.0
    assert r["vonis"].startswith("BERTAHAN")
    assert r["expectancy_bersih_persen"] == 4.70


def test_hindari_dinilai_terbalik_dan_gagal_paruh_akhir():
    hari = _hari(400)
    acak = {t: 2.0 for t in hari}
    kejadian = ([{"tanggal": hari[i], "return_persen": -3.0} for i in range(0, 200, 10)]
                + [{"tanggal": hari[i], "return_persen": 6.0} for i in range(200, 400, 10)])
    r = backtest.nilai_oos(kejadian, acak, "hindari", 0.30)
    assert r["paruh_awal_akhir"][0] > 0 > r["paruh_awal_akhir"][1]
    assert r["vonis"].startswith("TIDAK BERTAHAN")


def test_sampel_kecil_tidak_diberi_vonis():
    hari = _hari(100)
    r = backtest.nilai_oos([{"tanggal": hari[5], "return_persen": 9.0}],
                           {t: 0.0 for t in hari}, "beli", 0.3)
    assert r["vonis"].startswith("SAMPEL KECIL")


def test_yahoo_ditolak_bila_harga_tidak_cocok(monkeypatch):
    """Ticker Yahoo bisa milik koin LAIN dengan simbol sama."""
    import json
    import urllib.request

    class R:
        def __init__(self, harga):
            self.b = json.dumps({"chart": {"result": [{"timestamp": [1, 2], "indicators": {
                "quote": [{"open": [1, harga], "high": [1, harga], "low": [1, harga],
                           "close": [1, harga], "volume": [0, 0]}]}}]}}).encode()

        def read(self):
            return self.b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: R(0.5))
    assert backtest._yahoo_panjang("ABC", 100.0) is None
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: R(101.0))
    assert len(backtest._yahoo_panjang("ABC", 100.0)) == 2


def test_strategi_jam_membayar_biaya_dan_punya_rincian_tahunan():
    jumat = [date(2015, 1, 2) + timedelta(days=7 * i) for i in range(120)]
    tutup = {date(2015, 1, 2) + timedelta(days=d): 100.0 * (1.001 ** d) for d in range(900)}
    liq = [0.8 if (i // 10) % 2 else -0.8 for i in range(120)]
    tanpa = uj.strategi(jumat, liq, [False] * 120, tutup, biaya=0.0)
    dengan = uj.strategi(jumat, liq, [False] * 120, tutup)
    assert dengan["biaya_total_persen"] > 0
    assert dengan["cagr_strategi"] < tanpa["cagr_strategi"]
    assert set(dengan["per_tahun"]) >= {2015, 2016}

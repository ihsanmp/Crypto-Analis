import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import makro  # noqa: E402
import sebab  # noqa: E402

AKAR = os.path.join(os.path.dirname(__file__), "..")


def test_perubahan_harian_bukan_sebulan(monkeypatch):
    """Yahoo range=1mo tidak mengirim previousClose; dulu chartPreviousClose (sebulan lalu)
    tersaji sebagai perubahan harian — MOVE +34,6% padahal hari itu -0,8%."""
    isi = {"chart": {"result": [{"meta": {"regularMarketPrice": 107.29,
                                          "chartPreviousClose": 79.71},
                                 "indicators": {"quote": [{"close": [74.68, 108.13, 107.29]}]}}]}}

    class _R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(makro.urllib.request, "urlopen",
                        lambda *a, **k: _R(json.dumps(isi).encode()))
    nilai, harian, bulanan, err = makro._yahoo_terakhir("%5EMOVE")
    assert (nilai, harian, bulanan, err) == (107.29, 108.13, 79.71, None)


def test_ringkas_lintas_aset_memuat_korelasi_dan_n():
    h = {"simbol": "BTC", "pembanding_pasar": "sisa pasar",
         "vs_pasar": {"7h": {"koin_persen": 2.72, "pasar_persen": 0.48, "arti": "MENGUNGGULI"}},
         "pembanding": {"QQQ": {"nama": "Nasdaq 100", "perubahan_7h_persen": 0.68,
                                "perubahan_30h_persen": 5.69, "tanggal": "2026-10-02"}},
         "korelasi": {"pembanding": {"Nasdaq 100": {"30h": {"korelasi": 0.6575,
                                                            "hari_sepadan": 22}}}},
         "rezim_makro": {"move": {"terbaru": 107.29, "perubahan_1hari_persen": -0.78,
                                  "perubahan_1bulan_persen": 34.6}}}
    t = sebab.ringkas(h)
    assert "Nasdaq 100 30h +0,66 (n=22)" in t
    assert "MOVE 107,29 (1 hari -0,78%, 1 bulan +34,60%)" in t
    assert "BUKAN sebab" in t and len(t) < 2000


def test_ringkas_menyebut_yang_gagal():
    t = sebab.ringkas({"simbol": "X", "korelasi_tidak_tersedia": "HTTPError"})
    assert "Korelasi tidak tersedia: HTTPError" in t


def test_brief_crypto_memuat_lintas_aset():
    src = open(os.path.join(AKAR, "cloud", "bot_oneshot.py"), encoding="utf-8").read()
    i = src.index("def data_mentah_crypto(")
    assert '["cloud/sebab.py", coin, "--ringkas"]' in src[i:i + 9000]
    md = open(os.path.join(AKAR, "cloud", "prompts", "analisa.md"), encoding="utf-8").read()
    assert "LINTAS ASET (sebab.py)" in md

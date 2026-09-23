"""Tes etherscan.py — Etherscan V2, satu kunci untuk beberapa explorer.

YANG MENENTUKAN BENTUK MODUL INI (diuji langsung 23 Sep 2026, tanpa kunci sama sekali,
karena pesan penolakannya sudah membedakan keduanya):

    chain 1 / 4663 / 42161  -> "Missing/Invalid API Key"                  = gratis
    chain 56 / 8453         -> "Free API access is not supported ..."     = berbayar

Jadi bscscan dan basescan tidak bisa dipakai tanpa langganan. Yang penting bukan
faktanya, melainkan bahwa fakta itu DIKATAKAN: chain berbayar yang dibiarkan diam-diam
akan muncul sebagai "hasil kosong", dan hasil kosong terbaca seperti jawaban.
"""

import json
import os
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import etherscan as es  # noqa: E402


@pytest.fixture(autouse=True)
def _kunci_bersih(monkeypatch):
    monkeypatch.delenv(es.NAMA_ENV, raising=False)


def _transfer(dari, ke):
    return {"from": dari, "to": ke, "hash": "0x0", "value": "1"}


def test_tanpa_kunci_dikatakan_belum_diperiksa():
    alamat, catatan = es.alamat_token("ethereum", "0x1")
    assert alamat == set()
    assert es.NAMA_ENV in catatan and "belum diperiksa" in catatan


@pytest.mark.parametrize("chain", ["bsc", "base"])
def test_chain_berbayar_disebut_sebabnya(chain):
    """Paket gratis menolak chain ini. Kalau tidak dikatakan, penolakannya akan terbaca
    sebagai "tidak ada pemegangnya"."""
    alasan = es.alasan_chain(chain)
    assert "berbayar" in alasan and "GoPlus" in alasan
    assert es.alasan_chain("ethereum") is None
    assert es.alasan_chain("robinhood") is None


def test_chain_berbayar_tidak_ditanyakan_meski_kunci_ada(monkeypatch):
    monkeypatch.setenv(es.NAMA_ENV, "kunci-uji")
    monkeypatch.setattr(es, "try_json",
                        lambda url: pytest.fail("chain berbayar tidak boleh ditanya"))
    alamat, catatan = es.alamat_token("bsc", "0x1")
    assert alamat == set() and "berbayar" in catatan


def test_status_nol_dianggap_galat_meski_http_200(monkeypatch):
    """Etherscan membalas 200 untuk penolakan. Kalau status "0" tidak dibaca sebagai
    galat, penolakan akan masuk sebagai data kosong."""
    monkeypatch.setattr(es.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("tidak dipakai"))
    monkeypatch.setattr(es, "try_json", es.try_json)

    class Balasan:
        def __init__(self, isi):
            self.isi = isi

        def read(self):
            return json.dumps(self.isi).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(es.urllib.request, "urlopen",
                        lambda *a, **k: Balasan({"status": "0", "message": "NOTOK",
                                                 "result": "Missing/Invalid API Key"}))
    d = es.try_json("https://contoh")
    assert d["__err"] == "Missing/Invalid API Key"


def test_alamat_dikumpulkan_dari_pengirim_dan_penerima(monkeypatch):
    monkeypatch.setenv(es.NAMA_ENV, "kunci-uji")
    a1 = "0x" + "a" * 40
    a2 = "0x" + "B" * 40
    monkeypatch.setattr(es, "try_json", lambda url: {
        "status": "1", "result": [_transfer(a1, a2), _transfer(a2, a1)]})
    alamat, catatan = es.alamat_token("robinhood", "0x1", maks_halaman=1)
    # Huruf besar/kecil disamakan, kalau tidak satu dompet terhitung dua.
    assert alamat == {a1, a2.lower()}
    assert "2 alamat" in catatan and "robinhood" in catatan


def test_berhenti_di_halaman_pendek(monkeypatch):
    monkeypatch.setenv(es.NAMA_ENV, "kunci-uji")
    dipanggil = []

    def palsu(url):
        dipanggil.append(url)
        return {"status": "1", "result": [_transfer("0x" + "a" * 40, "0x" + "b" * 40)]}

    monkeypatch.setattr(es, "try_json", palsu)
    es.alamat_token("ethereum", "0x1", maks_halaman=5)
    assert len(dipanggil) == 1, "halaman yang belum penuh berarti sudah habis"


def test_daftar_yang_dipotong_dikatakan_terpotong(monkeypatch):
    """Daftar terpotong dan daftar lengkap tidak boleh terlihat sama — kalau tidak,
    "tidak ketemu" terbaca seperti kesimpulan."""
    monkeypatch.setenv(es.NAMA_ENV, "kunci-uji")
    penuh = [_transfer("0x%040x" % i, "0x%040x" % (i + 1000)) for i in range(es.HALAMAN)]
    monkeypatch.setattr(es, "try_json", lambda url: {"status": "1", "result": penuh})
    _alamat, catatan = es.alamat_token("ethereum", "0x1", maks_halaman=2)
    assert "dipotong di batas" in catatan


def test_penolakan_di_halaman_pertama_bukan_hasil_kosong(monkeypatch):
    monkeypatch.setenv(es.NAMA_ENV, "kunci-uji")
    monkeypatch.setattr(es, "try_json", lambda url: {"__err": "Max rate limit reached"})
    alamat, catatan = es.alamat_token("ethereum", "0x1")
    assert alamat == set() and "menolak" in catatan and "rate limit" in catatan


def test_kunci_tidak_pernah_ikut_tercetak(monkeypatch, capsys):
    """Repo ini publik dan log Actions ikut terbaca publik."""
    monkeypatch.setenv(es.NAMA_ENV, "rahasia-sekali-123")
    monkeypatch.setattr(es, "try_json", lambda url: {"__err": "HTTP 403"})
    _alamat, catatan = es.alamat_token("ethereum", "0x1")
    assert "rahasia" not in catatan
    monkeypatch.setattr(sys, "argv", ["etherscan.py", "--periksa"])
    es.main()
    assert "rahasia" not in capsys.readouterr().out


def test_alamat_tidak_pernah_dicetak_ke_keluaran(monkeypatch, capsys):
    """Keluaran CLI ikut masuk log Actions yang publik, jadi yang boleh keluar hanya
    JUMLAHNYA."""
    monkeypatch.setenv(es.NAMA_ENV, "kunci-uji")
    alamat = "0x" + "d" * 40
    monkeypatch.setattr(es, "try_json",
                        lambda url: {"status": "1", "result": [_transfer(alamat, alamat)]})
    monkeypatch.setattr(sys, "argv", ["etherscan.py", "robinhood", "0x1"])
    es.main()
    keluar = capsys.readouterr().out
    assert alamat not in keluar and '"jumlah_alamat": 1' in keluar


def test_hanya_endpoint_baca():
    """Modul ini tidak boleh punya jalan untuk MENULIS apa pun — bot jalan tanpa
    pengawasan."""
    src = open(os.path.join(AKAR, "cloud", "etherscan.py"), encoding="utf-8").read()
    for terlarang in ("method=\"POST\"", "urlopen(req, data", "data=", "proxy&action=eth_send"):
        assert terlarang not in src, terlarang

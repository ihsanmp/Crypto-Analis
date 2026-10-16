import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import fred  # noqa: E402

RAHASIA = "kunci-rahasia-123"


class _Balasan:
    def __init__(self, isi):
        self.isi = isi

    def read(self):
        return self.isi.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _reset(monkeypatch):
    fred._GRAPH_DIBLOKIR[0] = False
    monkeypatch.delenv("FRED_API_KEY", raising=False)


def test_api_resmi_dipakai_dulu_bila_kunci_ada(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("FRED_API_KEY", RAHASIA)
    url = {}

    def buka(req, timeout):
        url["u"] = req.full_url
        return _Balasan(json.dumps({"observations": [
            {"date": "2026-10-01", "value": "4.8"}, {"date": "2026-10-02", "value": "."}]}))
    monkeypatch.setattr(fred.urllib.request, "urlopen", buka)
    monkeypatch.setattr(fred.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("fredgraph tidak boleh dipanggil bila API berhasil")))
    assert fred.seri("DGS2", "2026-01-01") == ([("2026-10-01", 4.8)], None)
    assert "observation_start=2026-01-01" in url["u"]


def test_fredgraph_diblokir_sekali_lalu_dilewati(monkeypatch):
    """Runner GitHub: fredgraph habis waktu untuk SETIAP seri (run 38828031530). Menunggu
    tujuh kali 45 detik membuang batas 300 detik pengumpul data."""
    _reset(monkeypatch)
    panggil = []

    def curl(*a, **k):
        panggil.append(1)
        return subprocess.CompletedProcess(a, 28, "", "")      # curl: timed out
    monkeypatch.setattr(fred.subprocess, "run", curl)
    _, e1 = fred.seri("WALCL")
    _, e2 = fred.seri("WDTGAL")
    assert len(panggil) == 1
    assert "TimeoutError" in e1 and "dilewati" in e2 and "FRED_API_KEY kosong" in e2


def test_kunci_tidak_pernah_muncul_di_pesan_galat(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("FRED_API_KEY", RAHASIA)

    def gagal(req, timeout):
        raise fred.urllib.error.HTTPError(req.full_url, 400, "Bad " + req.full_url, {}, None)
    monkeypatch.setattr(fred.urllib.request, "urlopen", gagal)
    monkeypatch.setattr(fred.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 28, "", ""))
    data, err = fred.seri("DGS2")
    assert data is None and "API HTTP 400" in err and RAHASIA not in err


def test_makro_ambil_meneruskan_awal_riwayat(monkeypatch):
    import makro
    dapat = {}
    monkeypatch.setattr(fred, "seri", lambda k, m=None: (dapat.update(k=k, m=m), ([], None))[1])
    makro.ambil("WALCL&cosd=2012-01-01")
    assert dapat == {"k": "WALCL", "m": "2012-01-01"}
    makro.ambil("DGS2")
    assert dapat == {"k": "DGS2", "m": None}

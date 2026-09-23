"""Tes solscan.py — Solscan Pro API v2 untuk Solana.

DUA HAL YANG MENENTUKAN BENTUKNYA:

1. Punya kunci belum tentu punya akses. Solscan membagikan kunci begitu akun dibuat, tapi
   kunci itu "tied to your account and current plan", dan tabel paket resminya (23 Sep
   2026) dimulai dari Lite $49/bulan tanpa baris gratis. Modul ini karena itu tidak
   memutuskan siapa yang benar — `--periksa` menembak endpointnya dan mencetak jawabannya.

2. Yang dicocokkan harus `owner`, bukan `address`. Di jawaban Solscan, `address` adalah
   akun token (turunan) sedangkan yang dikenali orang sebagai "dompet saya" adalah
   `owner`. Mencocokkan yang salah berarti mencari di ruang alamat yang tidak pernah
   dilihat siapa pun — dan hasilnya nihil tanpa sebab yang kelihatan.
"""

import json
import os
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import solscan as sc  # noqa: E402

MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
A1 = "J6vHZDKghn3dbTG7pcBLzHMnXFoqUEiHVaFfZxojMjXs"
A2 = "7rhxnLV8C77o6d8oz26AgK8x8m5ePsdeRawjqvojbjnQ"


@pytest.fixture(autouse=True)
def _bersih(monkeypatch):
    monkeypatch.delenv(sc.NAMA_ENV, raising=False)
    monkeypatch.setattr(sc.time, "sleep", lambda d: None)
    monkeypatch.setattr(sc, "_terakhir", [0.0])


def test_tanpa_kunci_dikatakan_belum_diperiksa():
    alamat, catatan = sc.alamat_token(MINT)
    assert alamat == set()
    assert sc.NAMA_ENV in catatan and "belum diperiksa" in catatan
    pemilik, catatan2 = sc.pemegang(MINT)
    assert pemilik == set() and sc.NAMA_ENV in catatan2


def test_alamat_dikumpulkan_dari_kedua_sisi_transfer(monkeypatch):
    monkeypatch.setenv(sc.NAMA_ENV, "kunci-uji")
    monkeypatch.setattr(sc, "try_json", lambda url: {
        "success": True,
        "data": [{"from_address": A1, "to_address": A2, "token_address": MINT}]})
    alamat, catatan = sc.alamat_token(MINT, maks_halaman=1)
    assert alamat == {A1, A2}
    assert "2 alamat" in catatan and "solana" in catatan


def test_pemegang_memakai_owner_bukan_akun_token(monkeypatch):
    """`address` itu akun token, `owner` itu dompetnya. Salah pilih = mencari di ruang
    alamat yang tidak pernah dilihat siapa pun."""
    monkeypatch.setenv(sc.NAMA_ENV, "kunci-uji")
    akun_token = "26ddLrqXDext6caX1gRxARePN4kzajyGiAUz9JmzmTGQ"
    monkeypatch.setattr(sc, "try_json", lambda url: {
        "success": True,
        "data": {"total": 947781,
                 "items": [{"address": akun_token, "amount": 1, "owner": A1}]}})
    pemilik, _catatan = sc.pemegang(MINT, maks_halaman=1)
    assert pemilik == {A1}
    assert akun_token not in pemilik


def test_penolakan_bukan_hasil_kosong(monkeypatch):
    monkeypatch.setenv(sc.NAMA_ENV, "kunci-uji")
    monkeypatch.setattr(sc, "try_json",
                        lambda url: {"__err": "HTTP 401: Token is missing"})
    alamat, catatan = sc.alamat_token(MINT)
    assert alamat == set() and "menolak" in catatan and "401" in catatan


def test_success_false_dibaca_sebagai_galat(monkeypatch):
    """Solscan bisa membalas 200 dengan success:false. Kalau itu tidak dibaca sebagai
    galat, penolakan masuk sebagai data kosong."""
    class Balasan:
        def read(self):
            return json.dumps({"success": False,
                               "errors": {"code": 401, "message": "Token is missing"}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(sc.urllib.request, "urlopen", lambda *a, **k: Balasan())
    assert sc._sekali("https://contoh")["__err"] == "Token is missing"


def test_daftar_terpotong_dikatakan(monkeypatch):
    monkeypatch.setenv(sc.NAMA_ENV, "kunci-uji")
    penuh = [{"from_address": f"A{i}", "to_address": f"B{i}"}
             for i in range(sc.HALAMAN_TRANSFER)]
    monkeypatch.setattr(sc, "try_json", lambda url: {"success": True, "data": penuh})
    _alamat, catatan = sc.alamat_token(MINT, maks_halaman=2)
    assert sc.TANDA_POTONG in catatan


def test_berhenti_di_halaman_pendek(monkeypatch):
    monkeypatch.setenv(sc.NAMA_ENV, "kunci-uji")
    panggil = []
    monkeypatch.setattr(sc, "try_json", lambda url: panggil.append(url) or {
        "success": True, "data": [{"from_address": A1, "to_address": A2}]})
    sc.alamat_token(MINT, maks_halaman=5)
    assert len(panggil) == 1


def test_kunci_dikirim_sebagai_header_token(monkeypatch):
    """Dokumennya tegas: header `token`, bukan query, bukan bearer. Kunci di query string
    juga ikut tercatat di log perantara — itu alasan kedua."""
    monkeypatch.setenv(sc.NAMA_ENV, "kunci-rahasia")
    tercatat = {}

    class Balasan:
        def read(self):
            return b'{"success": true, "data": []}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def palsu(req, timeout=None):
        tercatat["header"] = dict(req.headers)
        tercatat["url"] = req.full_url
        return Balasan()

    monkeypatch.setattr(sc.urllib.request, "urlopen", palsu)
    sc._sekali(sc._url("token/transfer", {"address": MINT}))
    assert tercatat["header"].get("Token") == "kunci-rahasia"
    assert "kunci-rahasia" not in tercatat["url"]


def test_batas_laju_dicoba_ulang_sekali(monkeypatch):
    balasan = [{"__err": "HTTP 429: Too Many Requests"}, {"success": True, "data": []}]
    monkeypatch.setattr(sc, "_sekali", lambda url: balasan.pop(0))
    assert sc.try_json("https://contoh").get("success") is True
    assert not balasan


def test_alamat_tidak_pernah_dicetak_ke_keluaran(monkeypatch, capsys):
    """Keluaran CLI ikut masuk log Actions yang publik."""
    monkeypatch.setenv(sc.NAMA_ENV, "kunci-uji")
    monkeypatch.setattr(sc, "try_json", lambda url: {
        "success": True, "data": [{"from_address": A1, "to_address": A2}]})
    monkeypatch.setattr(sys, "argv", ["solscan.py", MINT])
    sc.main()
    keluar = capsys.readouterr().out
    assert A1 not in keluar and MINT not in keluar and '"jumlah": 2' in keluar


def test_kunci_tidak_pernah_ikut_tercetak(monkeypatch, capsys):
    monkeypatch.setenv(sc.NAMA_ENV, "rahasia-sekali-123")
    monkeypatch.setattr(sc, "try_json", lambda url: {"__err": "HTTP 403"})
    monkeypatch.setattr(sys, "argv", ["solscan.py", "--periksa"])
    sc.main()
    assert "rahasia" not in capsys.readouterr().out


def test_hanya_endpoint_baca():
    src = open(os.path.join(AKAR, "cloud", "solscan.py"), encoding="utf-8").read()
    for terlarang in ('method="POST"', "urlopen(req, data", "private_key", "/trade"):
        assert terlarang not in src, terlarang


def test_endpoint_publik_memakai_host_yang_benar():
    """Host pro menjawab 404 untuk /chaininfo; host publiknya terpisah. Diuji 23 Sep 2026:
    keduanya tetap minta token, jadi tidak ada endpoint Solscan yang benar-benar terbuka
    — tapi setidaknya yang dicetak --periksa harus penolakan yang SEBENARNYA, bukan 404
    karena jalurnya salah."""
    assert sc.PUBLIK == "https://public-api.solscan.io/chaininfo"
    assert not sc.PUBLIK.startswith(sc.BASIS)

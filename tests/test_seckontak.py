"""Tes kontak SEC — alamat email tidak boleh lagi tertulis di kode.

SEC mewajibkan User-Agent berisi identitas + kontak (kebijakan fair access); tanpa itu
permintaan dibalas HTTP 403 yang TIDAK menjelaskan dirinya — mudah terbaca sebagai "emiten
tidak ditemukan". Jadi kontaknya fungsional. Tapi repo ini PUBLIK: alamat yang ditulis di
kode terbuka untuk pemanen alamat, maka nilainya pindah ke secret SEC_CONTACT (20 Sep 2026).
"""

import os
import re
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import seckontak  # noqa: E402

_SKRIP_SEC = ("konteks.py", "sec_tickers.py", "stockfund.py")
_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


@pytest.mark.parametrize("nama", _SKRIP_SEC)
def test_tidak_ada_alamat_email_di_kode(nama):
    isi = open(os.path.join(AKAR, "cloud", nama), encoding="utf-8").read()
    temuan = [e for e in _RE_EMAIL.findall(isi) if not e.endswith(("example.com", "contoh.com"))]
    assert not temuan, f"{nama}: alamat email di repo publik: {temuan}"


@pytest.mark.parametrize("nama", _SKRIP_SEC)
def test_ketiganya_memakai_kontak_yang_sama(nama):
    isi = open(os.path.join(AKAR, "cloud", nama), encoding="utf-8").read()
    assert "seckontak" in isi, f"{nama}: harus memakai modul kontak bersama"


def test_header_memuat_identitas_dan_kontak(monkeypatch):
    monkeypatch.setenv("SEC_CONTACT", "bot@contoh.com")
    ua = seckontak.header()["User-Agent"]
    assert ua.startswith("Crypto-Analis Research bot") and ua.endswith("bot@contoh.com")


def test_spasi_dan_kutip_yang_ikut_tersalin_dibersihkan(monkeypatch):
    monkeypatch.setenv("SEC_CONTACT", '  "bot@contoh.com" ')
    assert seckontak.header()["User-Agent"].endswith("bot@contoh.com")


def test_tanpa_secret_pesannya_menjelaskan_diri(monkeypatch):
    """403 dari SEC terbaca seperti 'emiten tidak ditemukan'. Penyebab sebenarnya harus
    disebut sebelum permintaannya dikirim."""
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    assert seckontak.kontak() == ""
    pesan = seckontak.alasan_kosong()
    assert "SEC_CONTACT" in pesan and "403" in pesan


@pytest.mark.parametrize("nilai", ["bukan-email", "@a.com", "a@b"])
def test_nilai_yang_jelas_bukan_email_ditolak(monkeypatch, nilai):
    """Kontak yang tidak valid = 403 juga, tapi diam-diam. Lebih baik ketahuan di awal."""
    monkeypatch.setenv("SEC_CONTACT", nilai)
    assert seckontak.kontak() == ""


def test_workflow_mengirim_secretnya():
    alur = open(os.path.join(AKAR, ".github", "workflows", "bot.yml"), encoding="utf-8").read()
    assert "SEC_CONTACT: ${{ secrets.SEC_CONTACT }}" in alur


def test_stockfund_berhenti_dengan_alasan_jelas(monkeypatch, capsys):
    import json
    import stockfund
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    monkeypatch.setattr(sys, "argv", ["stockfund.py", "NVDA"])
    monkeypatch.setattr(stockfund, "get", lambda *a, **k: pytest.fail("jangan menembak SEC"))
    stockfund.main()
    h = json.loads(capsys.readouterr().out)
    assert "SEC_CONTACT" in h["error"] and "403" in h["error"]

"""Tes gmgn.py — data GMGN OpenAPI untuk memperkaya pemindai token baru.

KENAPA LEWAT KODE, BUKAN "SKILL": repo GMGNAI/gmgn-skills menyediakan 14 skill untuk agen
AI, dan setengahnya mengeksekusi transaksi on-chain. Yang dipakai di sini HANYA endpoint
baca-saja, dipanggil kode — pola yang sama dengan seluruh proyek ini. Alat yang bergantung
pada model mau memanggilnya sudah terbukti gagal diam-diam (MCP CoinGlass, dicabut 20 Sep).

YANG TIDAK DIPAKAI: /v1/trade/*, swap, order, cooking. Bot ini berjalan tanpa pengawasan;
kemampuan mengirim order tidak boleh ada di dalamnya, gratis sekalipun.
"""

import json
import os
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import gmgn  # noqa: E402

MINT = "3GzrKw5MoivhvBHP2aXNxBwcatpUJx6kfjnGRp6Lpump"


def _info(**ubah):
    d = {"symbol": "STAMPCAT", "name": "Stamp Cat", "holder_count": 3,
         "launchpad_platform": "Pump.fun", "launchpad_progress": 0.0132,
         "locked_ratio": 0, "image_dup_count": 0,
         "dev": {"creator_address": "D4Q2fJ", "creator_token_status": "creator_hold",
                 "twitter_name_change_history": []},
         "wallet_tags_stat": {"smart_wallets": 0, "fresh_wallets": 2, "renowned_wallets": 0,
                              "sniper_wallets": 0, "rat_trader_wallets": 0,
                              "bundler_wallets": 0, "whale_wallets": 0},
         "stat": {"creator_created_count": 0, "creator_hold_rate": "0.0105",
                  "dev_team_hold_rate": "0.0104", "fresh_wallet_rate": "0.0105",
                  "top_10_holder_rate": "0.0105", "top_rat_trader_percentage": "0",
                  "top_bundler_trader_percentage": "0", "bot_degen_rate": "0"}}
    d.update(ubah)
    return d


def _palsu(info=None, err=None):
    def try_json(url, kunci=None):
        assert "/v1/trade/" not in url and "swap" not in url, "endpoint transaksi dilarang"
        if err:
            return {"__err": err}
        return {"code": 0, "data": {"data": info if info is not None else _info()}}
    return try_json


def test_hanya_endpoint_baca_saja():
    """Penjaga: tidak boleh ada jalur eksekusi transaksi di modul ini.

    Diperiksa di KODE, bukan prosa: docstring memang MENYEBUT swap/order untuk menjelaskan
    kenapa keduanya tidak dipakai, dan penjaga yang ikut melarang penjelasan itu justru
    mendorong penghapusan alasannya."""
    import ast
    sumber = open(os.path.join(AKAR, "cloud", "gmgn.py"), encoding="utf-8").read()
    pohon = ast.parse(sumber)
    teks = []
    for n in ast.walk(pohon):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            # docstring modul/fungsi/kelas dilewati; sisanya string yang benar-benar dipakai
            teks.append(n.value)
        elif isinstance(n, ast.Name):
            teks.append(n.id)
        elif isinstance(n, ast.Attribute):
            teks.append(n.attr)
    # clean=False: versi rapinya TIDAK identik dengan konstanta aslinya, jadi docstring
    # tidak akan terkecualikan dan penjaganya salah menuduh.
    doc = {ast.get_docstring(n, clean=False) for n in ast.walk(pohon)
           if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))}
    dipakai = " ".join(t for t in teks if t not in doc).lower()
    for terlarang in ("/v1/trade", "/swap", "private_key", "cooking"):
        assert terlarang not in dipakai, terlarang


def test_info_dinormalkan(monkeypatch):
    monkeypatch.setattr(gmgn, "try_json", _palsu())
    d = gmgn.info("solana", MINT)
    assert d["symbol"] == "STAMPCAT" and d["holder"] == 3
    assert d["launchpad"] == "Pump.fun"
    assert d["dev_token_dibuat"] == 0
    assert d["sniper"] == 0 and d["fresh"] == 2


def test_gagal_tidak_melempar(monkeypatch):
    monkeypatch.setattr(gmgn, "try_json", _palsu(err="HTTP 429"))
    d = gmgn.info("solana", MINT)
    assert d is None or d.get("error"), d


def test_chain_tak_didukung(monkeypatch):
    assert gmgn.info("polygon", "0x1") is None


@pytest.mark.parametrize("ubah,cuplikan,berat", [
    ({"stat": dict(_info()["stat"], creator_created_count=12)}, "12 token", True),
    ({"dev": dict(_info()["dev"], creator_token_status="creator_sell")}, "sudah menjual", True),
    ({"stat": dict(_info()["stat"], creator_hold_rate="0.35")}, "pembuat memegang 35", True),
    ({"stat": dict(_info()["stat"], top_rat_trader_percentage="0.22")}, "rat trader", False),
    ({"stat": dict(_info()["stat"], top_bundler_trader_percentage="0.3")}, "bundler", False),
    ({"wallet_tags_stat": dict(_info()["wallet_tags_stat"], sniper_wallets=14)}, "sniper", False),
    ({"image_dup_count": 3}, "logo", False),
    ({"dev": dict(_info()["dev"], twitter_name_change_history=[{"name": "x"}])}, "ganti nama", False),
])
def test_tiap_sinyal_punya_pesannya_sendiri(monkeypatch, ubah, cuplikan, berat):
    monkeypatch.setattr(gmgn, "try_json", _palsu(_info(**ubah)))
    t = gmgn.temuan(gmgn.info("solana", MINT))
    cocok = [x for x in t if cuplikan.lower() in x["pesan"].lower()]
    assert cocok, [x["pesan"] for x in t]
    assert cocok[0]["berat"] is berat


def test_token_bersih_tidak_menghasilkan_temuan(monkeypatch):
    monkeypatch.setattr(gmgn, "try_json", _palsu())
    assert gmgn.temuan(gmgn.info("solana", MINT)) == []


def test_sinyal_positif_dipisah_dari_temuan(monkeypatch):
    """Smart money masuk BUKAN temuan risiko. Mencampurnya membuat daftar risiko
    kehilangan arti — dan "ada smart money" bukan alasan membeli."""
    monkeypatch.setattr(gmgn, "try_json", _palsu(_info(
        wallet_tags_stat=dict(_info()["wallet_tags_stat"], smart_wallets=4, renowned_wallets=2))))
    d = gmgn.info("solana", MINT)
    assert gmgn.temuan(d) == []
    r = gmgn.ringkas(d)
    assert "smart money 4" in r.lower() and "kol 2" in r.lower()


def test_kunci_demo_ditandai_sebagai_uji_coba(monkeypatch):
    monkeypatch.delenv("GMGN_API_KEY", raising=False)
    assert gmgn.kunci() == gmgn.KUNCI_DEMO
    assert "demo" in gmgn.catatan_kunci().lower() and "uji coba" in gmgn.catatan_kunci().lower()
    monkeypatch.setenv("GMGN_API_KEY", "punyaku")
    assert gmgn.kunci() == "punyaku" and gmgn.catatan_kunci() is None


def test_kunci_tidak_pernah_dicetak(monkeypatch, capsys):
    """Log Actions repo ini publik."""
    monkeypatch.setenv("GMGN_API_KEY", "RAHASIA-123")
    monkeypatch.setattr(gmgn, "try_json", _palsu(err="HTTP 401 RAHASIA-123 ditolak"))
    d = gmgn.info("solana", MINT)
    keluar = capsys.readouterr()
    assert "RAHASIA-123" not in (keluar.out + keluar.err + json.dumps(d or {}))


# ---- diagnosis kunci (21 Sep 2026) --------------------------------------------------------
# Kunci pribadi pertama ditolak 401 dari runner. Penyebab yang mungkin: nilainya salah tempel
# (kunci publik, terpotong, ikut tanda kutip) ATAU endpoint baca menuntut tanda tangan.
# Keduanya harus bisa dibedakan TANPA pernah mencetak kuncinya — log Actions repo ini publik.

@pytest.mark.parametrize("nilai,cuplikan", [
    ("", "TIDAK ADA"),
    ("-----BEGIN PUBLIC KEY-----\nMCow\n-----END PUBLIC KEY-----", "kunci PUBLIK"),
    ('"gmgn_abc"', "tanda kutip"),
    ("gmgn_abc def", "spasi"),
    ("gmgn_abcdefghijklmno", "wajar"),
    ("abcdefghijklmnop", "tidak diawali"),
])
def test_bentuk_kunci_didiagnosis_tanpa_mencetak(monkeypatch, nilai, cuplikan):
    monkeypatch.setenv("GMGN_API_KEY", nilai)
    lap = gmgn.bentuk_kunci()
    assert cuplikan.lower() in lap.lower(), lap
    if nilai.strip():
        assert nilai not in lap, "kunci tidak boleh ikut tercetak"

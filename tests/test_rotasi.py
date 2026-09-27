"""Tes rotasi.py — screening narasi cara mentor #2 (transkrip dikirim user 27 Sep 2026)."""

import os
import sys

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import rotasi as R  # noqa: E402


def _k(simbol, mcap, ubah, vol_rasio=0.05, id_=None):
    return {"id": id_ or simbol.lower(), "simbol": simbol, "mcap": mcap,
            "volume": mcap * vol_rasio, "ubah_7h": ubah, "ubah_30h": None}


def test_ambang_dari_penilaian_mentor():
    """ETH +5% & BNB +4% "biasa aja", XRP +11% "lumayan", SOL +14% "bagus"."""
    assert R.AMBANG_GERAK == 10.0
    for bagus in (11, 14, 19):
        assert bagus >= R.AMBANG_GERAK
    for biasa in (4, 5):
        assert biasa < R.AMBANG_GERAK


def test_yang_sudah_naik_bukan_kandidat_belum_bergerak():
    """Versi pertama: CYBER +16,4% disebut 'belum ikut bergerak' karena pemimpinnya +37%."""
    anggota = [_k("WLD", 9e9, 37.2), _k("OP", 8e9, 16.2), _k("LSK", 7e9, -11.1),
               _k("CYBER", 1e9, 16.4), _k("CELO", 9e8, 3.0)]
    h = R.pemimpin_dan_kandidat(anggota)
    assert h["pemimpin_bergerak"]
    assert [k["simbol"] for k in h["kandidat"]] == ["CELO"]


def test_koin_yang_anjlok_bukan_menunggu_giliran():
    """G -22,3% saat narasinya naik itu MELEMAH, bukan 'belum ikut bergerak'."""
    anggota = [_k("A", 9e9, 20.0), _k("B", 8e9, 5.0), _k("C", 7e9, 1.0),
               _k("G", 1e9, -22.3), _k("D", 9e8, 2.0)]
    h = R.pemimpin_dan_kandidat(anggota)
    assert [k["simbol"] for k in h["kandidat"]] == ["D"]
    assert [k["simbol"] for k in h["melemah"]] == ["G"]


def test_pemimpin_belum_bergerak_tanpa_kandidat():
    anggota = [_k("A", 9e9, 6.0), _k("B", 8e9, 5.0), _k("C", 7e9, 1.0), _k("D", 1e9, 0.5)]
    h = R.pemimpin_dan_kandidat(anggota)
    assert not h["pemimpin_bergerak"] and h["kandidat"] == []


def test_kandidat_tidak_likuid_disaring():
    anggota = [_k("A", 9e9, 20.0), _k("B", 8e9, 5.0), _k("C", 7e9, 1.0),
               _k("SEPI", 1e9, 2.0, vol_rasio=0.001)]
    assert R.pemimpin_dan_kandidat(anggota)["kandidat"] == []


def test_jalur_kategori_hanya_untuk_tema():
    """Ekosistem chain milik jalur B; portofolio VC bukan narasi."""
    for bukan in ("Optimism Superchain Ecosystem", "Camera Capital Portfolio",
                  "Solana Ecosystem", "Coinbase 50 Index"):
        assert R._BUKAN_TEMA.search(bukan), bukan
    for tema in ("Artificial Intelligence (AI)", "Data Availability", "Real World Assets (RWA)"):
        assert not R._BUKAN_TEMA.search(tema), tema


def test_tingkat_narasi():
    assert R.tingkat(26.5e9) == "BESAR"      # AI
    assert R.tingkat(2.9e9) == "SEDANG"
    assert R.tingkat(154e6) == "KECIL"


def test_chain_hanya_koin_asli(monkeypatch):
    """Keputusan mentor, dibuat kode lewat platform UTAMA: RENDER (ethereum), CAKE (bsc),
    STRK (ethereum), USDT dicoret; JUP, RAY, PENGU lolos."""
    big = [{"id": "solana", "symbol": "sol", "market_cap": 9e10, "total_volume": 5e9,
            "price_change_percentage_7d_in_currency": 14.0}]
    eko = [{"id": i, "symbol": s, "market_cap": m, "total_volume": m * 0.05,
            "price_change_percentage_7d_in_currency": 3.0}
           for i, s, m in (("tether", "usdt", 1e11), ("render-token", "render", 3e9),
                           ("pancakeswap-token", "cake", 2e9), ("starknet", "strk", 1e9),
                           ("jupiter-exchange-solana", "jup", 2e9), ("raydium", "ray", 1e9),
                           ("pudgy-penguins", "pengu", 2e9))]
    monkeypatch.setattr(R, "_pasar", lambda p: (eko if p.get("category") else big, None))
    platform = {"tether": "ethereum", "render-token": "ethereum",
                "pancakeswap-token": "binance-smart-chain", "starknet": "ethereum",
                "jupiter-exchange-solana": "solana", "raydium": "solana",
                "pudgy-penguins": "solana"}
    ch = R.narasi_chain(kecuali={"tether"}, platform=platform)
    asli = [k["simbol"] for k in ch["chain"][0]["asli"]]
    assert sorted(asli) == ["JUP", "PENGU", "RAY"]
    assert ch["chain"][0]["dicoret_bukan_asli"] == 4


def test_tanpa_peta_platform_tidak_menebak(monkeypatch):
    big = [{"id": "solana", "symbol": "sol", "market_cap": 9e10, "total_volume": 5e9,
            "price_change_percentage_7d_in_currency": 14.0}]
    monkeypatch.setattr(R, "_pasar", lambda p: (big, None))
    ch = R.narasi_chain(platform=None)
    assert "tidak bisa dipisahkan" in ch["chain"][0]["galat"]


def test_blok_menyebut_hipotesis_dan_charting():
    teks = R.ringkas({"kategori": []}, {"galat": "uji"})
    assert "HIPOTESIS" in teks and "DAFTAR PANTAU" in teks and "charting sendiri" in teks


def test_cache_platform_tidak_di_file_yang_dicommit():
    """Daftar 4,5 MB sempat tertulis ke kategori_cache.json (ikut di-commit)."""
    src = open(os.path.join(AKAR, "cloud", "rotasi.py"), encoding="utf-8").read()
    assert "tempfile.gettempdir()" in src
    assert 'kategori.ambil("/coins/list"' not in src

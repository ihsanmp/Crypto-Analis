"""Tes fundamentals.py — resolusi protokol vs CHAIN.

Run 35489055215 ("analisa sui", 20 Sep 2026): DefiLlama punya protokol bernama
"Sui Foundation" berkategori Canonical Bridge dengan symbol SUI, dan itulah yang terambil.
Akibatnya revenue chain Sui dilaporkan $826 rb TTM (fees bridge), padahal chain-nya sendiri
$88 juta setahun — lalu dipakai menghitung P/S 4.082x. Modelnya kebetulan curiga dan
menurunkan bobotnya sendiri; kalau tidak, rasio itu masuk skor sebagai fakta.
"""

import json
import os
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import fundamentals as fd  # noqa: E402

_CHAINS = [{"name": "Sui", "tokenSymbol": "SUI", "tvl": 487405182.0},
           {"name": "Ethereum", "tokenSymbol": "ETH", "tvl": 9e10}]
_PROTOKOL = [{"name": "Sui Foundation", "slug": "sui-foundation", "symbol": "SUI",
              "category": "Canonical Bridge", "tvl": None, "mcap": 3376115115.0},
             {"name": "Aave V3", "slug": "aave-v3", "symbol": "AAVE",
              "category": "Lending", "tvl": 2e10, "mcap": 4e9}]
_CHART = [[1789689600, 100000.0], [1789862400, 124333.34]]


def _palsu(url):
    if url.endswith("/v2/chains"):
        return _CHAINS
    if url.endswith("/protocols"):
        return _PROTOKOL
    if "/overview/fees/sui" in url:
        return {"totalDataChart": _CHART, "total30d": 3339506.71, "total1y": 88292848.35}
    if "/v2/historicalChainTvl/sui" in url:
        return [{"date": 1789689600, "tvl": 480000000}, {"date": 1789862400, "tvl": 487416323}]
    return None


def _jalankan(monkeypatch, capsys, argv):
    monkeypatch.setattr(fd, "try_json", _palsu)
    monkeypatch.setattr(fd, "http_json", _palsu)
    monkeypatch.setattr(sys, "argv", ["fundamentals.py"] + argv)
    fd.main()
    return json.loads(capsys.readouterr().out)


def test_koin_chain_tidak_diambil_dari_protokol_bridge(monkeypatch, capsys):
    h = _jalankan(monkeypatch, capsys, ["SUI"])
    assert h["protokol"]["name"] == "Sui"
    assert "Bridge" not in (h["protokol"]["category"] or "")
    assert h["protokol"]["slug"] == "sui"
    assert h["fees"]["total_1thn_usd"] == 88292848.35
    assert h["tvl"]["sekarang_usd"] == 487416323


def test_chain_ditandai_supaya_tidak_dibaca_sebagai_protokol(monkeypatch, capsys):
    h = _jalankan(monkeypatch, capsys, ["SUI"])
    teks = " ".join(h["catatan"])
    assert "chain" in teks.lower() and "protokol" in teks.lower()


def test_valuasi_chain_memakai_angka_chain(monkeypatch, capsys):
    h = _jalankan(monkeypatch, capsys, ["SUI", "--mcap", "3374000000"])
    # P/F dari fees chain (TTM dari deret), bukan dari fees bridge.
    assert h["valuasi"]["mc_tvl"] == pytest.approx(3374000000 / 487416323, abs=0.01)


def test_token_protokol_tetap_lewat_jalur_lama(monkeypatch, capsys):
    h = _jalankan(monkeypatch, capsys, ["AAVE"])
    assert h["protokol"]["name"] == "Aave V3" and h["protokol"]["category"] == "Lending"


def test_slug_paksa_mengalahkan_deteksi_chain(monkeypatch, capsys):
    h = _jalankan(monkeypatch, capsys, ["SUI", "--slug", "sui-foundation"])
    assert h["protokol"]["slug"] == "sui-foundation"


# ------------------------------------------------------------- holder revenue
def _bulanan(nilai_per_bulan):
    """Satu titik per bulan (tgl 15) mundur dari bulan lalu; bulan berjalan tidak diisi."""
    from datetime import datetime, timezone
    kini = datetime.now(timezone.utc)
    keluar, th, bl = [], kini.year, kini.month
    for v in reversed(nilai_per_bulan):
        bl -= 1
        if bl == 0:
            th, bl = th - 1, 12
        keluar.append([int(datetime(th, bl, 15, tzinfo=timezone.utc).timestamp()), v])
    return sorted(keluar)


def test_holder_revenue_porsi_dan_yield_berjalan():
    d = {"totalDataChart": _bulanan([1e6] * 12), "total30d": 1e6, "total1y": 12e6}
    h = fd.ringkas_holder(d, "x", {"ttm_usd": 48e6}, mcap=240e6)
    assert h["tersedia"] and h["ttm_usd"] == 12e6
    assert h["porsi_dari_revenue_persen"] == 25.0
    assert h["yield_holder_run_rate_persen"] == 5.0 and h["p_holder_rev_ttm"] == 20.0
    assert "peringatan" not in h


def test_holder_revenue_yang_berhenti_diberi_peringatan():
    """17 Okt 2026: AAVE TTM $20 jt tapi 30 hari terakhir NOL — yield TTM 0,8% menyesatkan."""
    d = {"totalDataChart": _bulanan([2e6] * 9 + [0, 0, 0]), "total30d": 0, "total1y": 18e6}
    h = fd.ringkas_holder(d, "aave", {"ttm_usd": 90e6}, mcap=2.4e9)
    assert h["yield_holder_run_rate_persen"] == 0.0
    assert "berhenti" in h["peringatan"]


def test_holder_revenue_kosong_dibedakan_dari_nol():
    ada_rev = fd.ringkas_holder(None, None, {"ttm_usd": 5e6}, mcap=1e8)
    tanpa = fd.ringkas_holder(None, None, None, mcap=1e8)
    assert ada_rev["tersedia"] is False and "treasury" in ada_rev["catatan"]
    assert "tidak ada dasar" in tanpa["catatan"] and "ttm_usd" not in tanpa


def test_holder_revenue_ikut_di_output_dan_chain_memakai_endpoint_chain(monkeypatch, capsys):
    diminta = []

    def palsu(url):
        diminta.append(url)
        return _palsu(url)
    monkeypatch.setattr(fd, "try_json", palsu)
    monkeypatch.setattr(fd, "http_json", palsu)
    monkeypatch.setattr(sys, "argv", ["fundamentals.py", "SUI"])
    fd.main()
    h = json.loads(capsys.readouterr().out)
    assert h["holder_revenue"]["tersedia"] is True
    assert any("/overview/fees/sui?dataType=dailyHoldersRevenue" in u for u in diminta)
    assert "DIBAKAR" in h["holder_revenue"]["catatan"]


def test_prompt_mewajibkan_holder_revenue():
    teks = open(os.path.join(AKAR, "cloud", "prompts", "analisa.md"), encoding="utf-8").read()
    assert "HOLDER REVENUE — WAJIB" in teks and "• Holder revenue TTM" in teks
    assert "yield_holder_run_rate_persen" in teks and "JANGAN menganggapnya nol" in teks


def test_slug_dipilih_dari_total_terbesar_bukan_yang_pertama_berisi(monkeypatch):
    """PUMP: 'pumpswap' (pertama, holder revenue 0) vs 'pump.fun' ($285 jt buyback)."""
    data = {"pumpswap": {"totalDataChart": _CHART, "total1y": 0},
            "pumpkin-dao": None,
            "pump.fun": {"totalDataChart": _CHART, "total1y": 284606543}}
    monkeypatch.setattr(fd, "try_json",
                        lambda url: data[url.split("/summary/fees/")[1].split("?")[0]])
    d, slug = fd.ambil_fees(["pumpswap", "pumpkin-dao", "pump.fun"], "dailyHoldersRevenue")
    assert slug == "pump.fun" and d["total1y"] == 284606543
    # Seri: urutan kandidat (induk dulu) yang menang.
    data["pump.fun"]["total1y"] = 0
    assert fd.ambil_fees(["pumpswap", "pump.fun"], "x")[1] == "pumpswap"


def test_protokol_induk_jadi_kandidat_pertama_dan_mcap_dari_induk(monkeypatch, capsys):
    """Cek bug 18 Okt 2026: COMP terbaca Compound V2 saja, PUMP pump.fun saja; mcap
    cadangan PUMP diambil dari protokol LAIN bersimbol sama ($37,6 jt vs $2,0 miliar)."""
    protokol = [
        {"name": "PumpSwap", "slug": "pumpswap", "symbol": "PUMP", "tvl": 5e8,
         "parentProtocol": "parent#pump"},
        {"name": "pump.fun", "slug": "pump.fun", "symbol": "PUMP", "tvl": 1e8,
         "parentProtocol": "parent#pump"},
        {"name": "PumpBTC", "slug": "pumpbtc", "symbol": "PUMP", "tvl": 3e7, "mcap": 37.6e6}]
    induk = {"totalDataChart": _CHART, "total1y": 485e6, "total30d": 30e6}
    anak = {"totalDataChart": _CHART, "total1y": 314e6, "total30d": 20e6}

    def palsu(url):
        if url.endswith("/v2/chains"):
            return []
        if url.endswith("/protocols"):
            return protokol
        if "/summary/fees/pump?" in url:
            return induk
        if "/summary/fees/pump.fun?" in url:
            return anak
        if url.endswith("/protocol/pump"):
            return {"tvl": [{"date": 1789689600, "totalLiquidityUSD": 3.4e8}], "mcap": 2.0e9}
        return None
    monkeypatch.setattr(fd, "try_json", palsu)
    monkeypatch.setattr(fd, "http_json", palsu)
    info, kand = fd.resolve_protocol("PUMP")
    assert kand[0] == "pump"
    monkeypatch.setattr(sys, "argv", ["fundamentals.py", "PUMP"])
    fd.main()
    h = json.loads(capsys.readouterr().out)
    assert h["revenue"]["slug"] == "pump" and h["holder_revenue"]["slug"] == "pump"
    assert h["valuasi"]["mcap_usd"] == 2.0e9


def test_porsi_holder_memakai_total_1thn_bila_belum_12_bulan():
    d = {"totalDataChart": _bulanan([1e6] * 5), "total30d": 1e6, "total1y": 5e6}
    h = fd.ringkas_holder(d, "x", {"ttm_usd": None, "total_1thn_usd": 20e6}, mcap=None)
    assert h["porsi_dari_revenue_persen"] == 25.0
    kosong = fd.ringkas_holder(None, None, {"ttm_usd": None, "total_1thn_usd": 20e6}, None)
    assert "treasury" in kosong["catatan"]            # revenue ADA, bukan "tidak tercatat"

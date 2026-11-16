import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import earnings  # noqa: E402
import reaksi_earnings as rk  # noqa: E402


def _palsu(isi):
    def ambil(jalur, params, kunci):
        return {"metric": isi[params["symbol"]]}, False, None
    return ambil


def test_premi_vs_median_peer_dan_multipel_negatif_dibuang(monkeypatch):
    isi = {"NVDA": {"peTTM": 50, "psTTM": 25, "netProfitMarginTTM": 55, "revenueGrowthTTMYoy": 60},
           "AMD": {"peTTM": 100, "psTTM": 8, "netProfitMarginTTM": 10, "revenueGrowthTTMYoy": 20},
           "INTC": {"peTTM": -30, "psTTM": 2, "netProfitMarginTTM": -5, "revenueGrowthTTMYoy": -2},
           "AVGO": {"peBasicExclExtraTTM": 40, "psTTM": 15, "netProfitMarginTTM": 30,
                    "revenueGrowthTTMYoy": 40},
           "QCOM": {"peTTM": 20, "psTTM": 5, "netProfitMarginTTM": 25, "revenueGrowthTTMYoy": 10}}
    monkeypatch.setattr(earnings, "ambil", _palsu(isi))
    h = earnings.perbandingan("NVDA", ["AMD", "INTC", "AVGO", "QCOM"])
    # P/E: INTC negatif dibuang -> median(100, 40, 20) = 40 -> NVDA 50 = premi +25%
    assert h["median_peer"]["pe_ttm"] == 40
    assert h["selisih_vs_median"]["pe_ttm_premi_vs_median_persen"] == 25.0
    # margin median(10, -5, 30, 25) = 17,5 -> selisih +37,5 pp
    assert h["selisih_vs_median"]["margin_bersih_persen_selisih_pp"] == 37.5
    assert "pertumbuhan atau margin" in h["cara_pakai"]


def test_peer_terlalu_sedikit_tidak_dipaksakan(monkeypatch):
    isi = {"X": {"peTTM": 10}, "A": {"peTTM": 12}, "B": {}}
    monkeypatch.setattr(earnings, "ambil", _palsu(isi))
    h = earnings.perbandingan("X", ["A", "B"])
    assert "tidak_tersedia" in h


def test_reaksi_jendela_dua_hari_mencakup_pra_dan_pasca_pasar():
    tutup = {"2026-07-29": 100.0, "2026-07-30": 101.0, "2026-07-31": 110.0, "2026-08-03": 111.0}
    # 8-K tgl 30 Jul (rilis pasca-tutup): close 29 Jul -> close 31 Jul
    assert rk.reaksi(tutup, ["2026-07-30"]) == [("2026-07-30", 10.0)]
    # 8-K di akhir pekan / hari libur: hari bursa terdekat sebelum & sesudah
    assert rk.reaksi(tutup, ["2026-08-01"]) == [("2026-08-01", round((111 / 110 - 1) * 100, 2))]
    r = rk.ringkas([("a", 8.0), ("b", -4.0), ("c", 6.0), ("d", -10.0)], [1.0, 2.0, 3.0])
    assert r["median_gerak_mutlak_persen"] == 7.0 and r["kelipatan_vs_hari_biasa"] == 3.5
    assert r["naik_dari"] == "2 dari 4"


def test_arsip_lama_sec_dibaca_bila_recent_kurang(monkeypatch):
    """JPM: 'recent' SEC hanya ~1 tahun (banyak 8-K/424B) -> 4 rilis saja."""
    def palsu(url):
        if url.endswith("CIK0000019617.json"):
            return {"filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-10-13"],
                                           "items": ["2.02,9.01"]},
                                "files": [{"name": "CIK0000019617-submissions-001.json"}]}}
        return {"form": ["8-K", "424B2", "8-K"], "filingDate": ["2025-10-14", "2025-10-01",
                                                                "2025-07-15"],
                "items": ["2.02", "", "7.01"]}
    monkeypatch.setattr(rk, "_ambil_json", palsu)
    assert rk.tanggal_rilis(19617) == ["2025-10-14", "2026-10-13"]

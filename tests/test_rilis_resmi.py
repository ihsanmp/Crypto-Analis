import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import kejutan as k  # noqa: E402


def test_tanggal_cpi_diganti_tanggal_resmi_bls():
    """Grafik Cleveland Fed mencatat CPI Agustus 2026 rilis 9 Sep; BLS: 11 Sep. Semua
    reaksi harga dulu mengukur hari SEBELUM rilis."""
    data = {"riwayat": [{"bulan_target": "2026-8", "tanggal_rilis": "2026-09-09",
                         "kejutan_pp": 0.037}],
            "belum_rilis": [{"bulan_target": "2026-9", "nowcast_mom_persen": 0.5}]}
    d = k._tanggal_resmi(data, "CPI")
    r = d["riwayat"][0]
    assert r["tanggal_rilis"] == "2026-09-11" and r["tanggal_grafik"] == "2026-09-09"
    assert r["tanggal_sumber"] == "BLS (resmi)"
    assert d["belum_rilis"][0]["jadwal_rilis_bls"].startswith("2026-10-14")


def test_pce_ditandai_perkiraan():
    d = k._tanggal_resmi({"riwayat": [{"bulan_target": "2026-8",
                                       "tanggal_rilis": "2026-09-25"}]}, "PCE")
    assert "perkiraan" in d["riwayat"][0]["tanggal_sumber"]
    assert d["riwayat"][0]["tanggal_rilis"] == "2026-09-25"


def test_tabel_bls_lengkap_dan_konsisten():
    t = k._tabel_bls()
    assert len(t["rilis"]) >= 170
    for bulan, tgl in t["rilis"].items():
        thn, bln = (int(x) for x in bulan.split("-"))
        assert tgl > f"{thn}-{bln:02d}-31" or tgl[:7] > f"{thn}-{bln:02d}", (bulan, tgl)


def test_bulan_dari_teks():
    hari = dt.date(2026, 10, 12)
    assert k.bulan_dari_teks("cpi bulan september 2026", hari) == (2026, 9)
    assert k.bulan_dari_teks("cpi september", hari) == (2026, 9)
    assert k.bulan_dari_teks("cpi november", hari) == (2025, 11)
    assert k.bulan_dari_teks("cpi kemarin", hari) is None


def test_peta_rilis_menjawab_kedua_arti(monkeypatch):
    monkeypatch.setattr(k, "_per_rilis", lambda *a, **kw: (
        [{"ret": {0: 0.5, 1: 0.85, 5: -1.26}}], {"simbol": "BTC", "kualitas": "native"}))
    data = k._tanggal_resmi({"riwayat": [{"bulan_target": "2026-8",
                                          "tanggal_rilis": "2026-09-09",
                                          "aktual_mom_persen": 0.396,
                                          "nowcast_mom_persen": 0.359,
                                          "kejutan_pp": 0.037}],
                             "belum_rilis": [{"bulan_target": "2026-9",
                                              "nowcast_mom_persen": 0.531}]}, "CPI")
    p = k.peta_rilis("CPI", data, (2026, 9), "BTC", hari_ini=dt.date(2026, 10, 12))
    assert p["arti_1_data_untuk_bulan_itu"]["status"] == "BELUM RILIS"
    assert p["arti_1_data_untuk_bulan_itu"]["jadwal_rilis"].startswith("2026-10-14")
    a2 = p["arti_2_rilis_yang_terjadi_di_bulan_itu"]
    assert a2["status"] == "SUDAH RILIS" and a2["tanggal_rilis"] == "2026-09-11"
    assert a2["reaksi_harga"]["sampai_H+1_persen"] == 0.85
    assert "DILARANG menolak" in p["wajib_dibaca"]


def test_candle_hanya_tutup_tidak_jadi_nol_palsu(monkeypatch):
    monkeypatch.setattr(k, "_per_rilis", lambda *a, **kw: (
        [{"ret": {0: 0.0, 1: 0.85}}], {"simbol": "BTC", "kualitas": "approx_close_only"}))
    data = {"riwayat": [{"bulan_target": "2026-8", "tanggal_rilis": "2026-09-11",
                         "kejutan_pp": 0.0}], "belum_rilis": []}
    p = k.peta_rilis("CPI", data, None, "BTC", hari_ini=dt.date(2026, 10, 12))
    assert "tidak tersedia" in p["rilis_terakhir"]["reaksi_harga"]["hari_rilis_buka_ke_tutup_persen"]

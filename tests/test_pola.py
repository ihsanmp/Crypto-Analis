"""Tes pola.py — double bottom/top (bagian "Pattern" outlook gaya Astronacci).

Yang dijaga: (1) definisinya sesuai buku teks dan tidak mengintip masa depan;
(2) hasil ujinya yang MENGUBAH kesimpulan — keunggulan double bottom hanya milik
2012–2018 — tidak hilang dari blok brief.
"""

import os
import sys

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import pola as P  # noqa: E402


def _w():
    """Turun ke lembah 100, naik ke 115 (neckline), turun ke 101, lalu menembus 115."""
    # Tanpa nilai kembar di titik balik: pivot mensyaratkan lembah LEBIH rendah dari
    # tetangganya, jadi dua candle bernilai sama persis bukan lembah.
    harga = ([130 - i for i in range(31)]            # turun ke 100 (indeks 30)
             + [101 + i for i in range(15)]          # naik ke 115 (indeks 45)
             + [114 - i for i in range(14)]          # turun ke 101 (indeks 59)
             + [102 + i for i in range(20)])         # naik menembus neckline
    return [[i, h, h + 0.5, h - 0.5, h, 1.0] for i, h in enumerate(harga)]


def test_double_bottom_terdeteksi_dengan_neckline_dan_target_ukur():
    k = _w()
    n = P.PARAM["harian"]["fraktal"]
    piv = P._pivot_semua(k, n)
    b = [i for i in piv[False] if i <= len(k) - 1 - n][-1]
    h = P._pola_untuk(k, piv, b, "harian", False, len(k) - 1)
    assert h and h["jenis"] == "DOUBLE BOTTOM"
    assert h["neckline"] == 115.5 and h["invalid"] == 99.5
    # Target ukur = neckline + (neckline − lembah terdalam).
    assert h["target_ukur"] == 115.5 + (115.5 - 99.5)
    assert h["status"] == "SUDAH TEMBUS"


def test_belum_tembus_sebelum_close_melewati_neckline():
    k = _w()[:71]                                    # berhenti sebelum menembus
    n = P.PARAM["harian"]["fraktal"]
    piv = P._pivot_semua(k, n)
    b = [i for i in piv[False] if i <= len(k) - 1 - n][-1]
    h = P._pola_untuk(k, piv, b, "harian", False, len(k) - 1)
    assert h and h["status"] == "MENUNGGU TEMBUS"


def test_lembah_yang_terlalu_berbeda_bukan_double_bottom():
    k = _w()
    for c in k[46:60]:                               # lembah kedua jauh lebih dalam
        c[3] -= 20
    n = P.PARAM["harian"]["fraktal"]
    piv = P._pivot_semua(k, n)
    semua = [P._pola_untuk(k, piv, b, "harian", False, len(k) - 1) for b in piv[False]]
    assert not any(h and h["i_2"] >= 45 for h in semua)


def test_mingguan_dari_harian():
    harian = [[(1767225600 + i * 86400) * 1000, 1, 2 + i, 0.5, 1.5, 1] for i in range(14)]
    w = P.mingguan(harian)
    assert len(w) in (2, 3)
    assert all(x[2] >= x[4] >= x[3] for x in w)


def test_hasil_uji_dipotong_per_periode_ikut_di_blok():
    teks = P.HASIL_UJI
    for wajib in ("77,4%", "66,9%", "2012–2018", "67,1% vs 67,0%", "TIDAK menambah informasi"):
        assert wajib in teks, wajib


def test_parameter_a_priori():
    assert P.PARAM["harian"] == {"fraktal": 3, "jeda_min": 10, "jeda_maks": 120,
                                 "tembus_maks": 60}
    assert (P.TOLERANSI, P.KEDALAMAN_MIN) == (0.05, 0.08)



def test_btc_memakai_riwayat_panjang_agar_pola_mingguan_terlihat(monkeypatch):
    """Candle bursa saja terlalu pendek: di run 35994887380 pola mingguan (neckline $82.833)
    hilang dari blok live. Tanpa jaringan pun riwayat repo harus terpakai."""
    import indicators
    monkeypatch.setattr(indicators, "fetch_base", lambda *a, **k: (None, None, None, "uji"))
    k, sumber = P.data_btc()
    assert len(k) > 5000 and "riwayat repo" in sumber
    hidup = P.cari(P.mingguan(k), "mingguan")
    assert any(round(h["neckline"]) == 82833 for h in hidup), hidup


def test_blok_menyebut_rentang_data_dan_koma_desimal():
    k = P._muat_btc()
    teks = P.ringkas("BTC", k, "riwayat repo (Bitstamp)")
    assert "Data harian 2012-01-01 s.d. 2026-09-01" in teks
    assert "7.5%" not in teks and "% dari harga kini" in teks

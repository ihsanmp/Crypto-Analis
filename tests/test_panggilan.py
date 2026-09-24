"""Tes panggilan.py — rekam jejak panggilan eksternal (Astronacci), dinilai oleh data."""

import datetime as dt
import json
import os
import sys

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import panggilan as pg  # noqa: E402


def _c(tgl, o, h, l, c):
    t = dt.datetime.fromisoformat(tgl).replace(tzinfo=dt.timezone.utc)
    return [int(t.timestamp() * 1000), o, h, l, c, 0]


P_LEVEL = {"tanggal": "2026-09-21", "judul": "Daily — target 91.614", "arah": "naik",
           "target": [91614], "invalid": 74835, "invalid_basis": "close"}


def test_target_tersentuh_lebih_dulu():
    k = [_c("2026-09-22", 84000, 86000, 83000, 85000), _c("2026-09-23", 85000, 92000, 84500, 91000)]
    h = pg.nilai_level(P_LEVEL, k)
    assert h["status"] == "SEMUA TARGET KENA" and h["tanggal"] == "2026-09-23"


def test_invalid_berbasis_close_bukan_sentuh():
    """"Selama bertahan di atas 74.835" — sumbu yang sempat di bawahnya belum membatalkan."""
    k = [_c("2026-09-22", 80000, 81000, 74000, 76000)]
    assert pg.nilai_level(P_LEVEL, k)["status"] == "TERBUKA"
    k.append(_c("2026-09-23", 76000, 76500, 73000, 74000))
    assert pg.nilai_level(P_LEVEL, k)["status"] == "INVALID"


def test_hari_yang_menyentuh_keduanya_dihitung_invalid():
    p = dict(P_LEVEL, invalid_basis="sentuh")
    k = [_c("2026-09-22", 84000, 92000, 74000, 80000)]
    assert pg.nilai_level(p, k)["status"] == "INVALID"


def test_pemicu_buy_stop_harus_tersentuh_dulu():
    p = {"tanggal": "2026-09-23", "judul": "Minor Swing", "arah": "naik", "pemicu": 87281,
         "target": [89140], "invalid": 85460, "invalid_basis": "sentuh"}
    k = [_c("2026-09-24", 84000, 85000, 83000, 84100)]
    assert pg.nilai_level(p, k)["status"] == "PEMICU BELUM TERSENTUH"


def test_candle_pada_tanggal_panggilan_tidak_dihitung():
    """Panggilan dibuat di tengah hari itu — candle harinya sudah sebagian terjadi."""
    k = [_c("2026-09-21", 84000, 95000, 83000, 90000)]
    assert pg.nilai_level(P_LEVEL, k)["status"] == "TERBUKA"


def test_klaim_waktu_dicatat_tanpa_vonis():
    p = {"tanggal_klaim": "2026-09-23", "jendela_hari": 2}
    k = [_c("2026-09-23", 0, 0, 0, 100), _c("2026-09-24", 100, 103, 95, 96),
         _c("2026-09-25", 96, 99, 94, 98)]
    h = pg.nilai_waktu(p, k)
    assert h["status"] == "TERCATAT"
    assert h["turun_terdalam_persen"] == -6.0 and h["naik_tertinggi_persen"] == 3.0


def test_periode_belum_jatuh_tempo():
    p = {"jatuh_tempo": "2027-12-31", "mulai": "2026-10-01"}
    assert pg.nilai_periode(p, [], dt.date(2026, 9, 24))["status"] == "BELUM JATUH TEMPO"


def test_format_tidak_merusak_judul():
    hasil = [{"tanggal": "2026-09-21", "judul": "Weekly — neckline 83.000",
              "hasil": {"status": "TERCATAT", "turun_terdalam_persen": -2.5,
                        "naik_tertinggi_persen": 1.2, "hari": 7}}]
    teks = pg.ringkas(hasil)
    assert "83.000" in teks and "-2,5%" in teks and "+1,2%" in teks


def test_berkas_panggilan_memuat_lima_panggilan_astronacci():
    with open(pg.BERKAS, encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 5
    level = {p["id"]: p for p in data if p.get("jenis", "level") == "level"}
    assert level["astronacci-btc-mingguan-20260921"]["target"] == [98000, 127000]
    assert level["astronacci-btc-harian-20260921"]["invalid"] == 74835
    assert level["astronacci-btc-minorswing-20260923"]["pemicu"] == 87281

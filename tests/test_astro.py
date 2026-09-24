"""Tes astro.py — mesin astronomi stdlib (elemen orbit JPL + teori Bulan Meeus).

Mesin ini menjadi dasar SEMUA fitur astro-trading bot. Kalau ia salah, setiap uji dan
setiap "tanggal penting" sesudahnya ikut salah tanpa ada yang tahu. Karena itu yang
diuji adalah peristiwa langit yang tanggalnya sudah PASTI, bukan keluaran yang kebetulan
terlihat masuk akal.
"""

import datetime as dt
import os
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import astro as a  # noqa: E402


def T(s, jam=12):
    return dt.datetime.fromisoformat(s).replace(hour=jam, tzinfo=dt.timezone.utc)


def test_konjungsi_besar_jupiter_saturnus_2020():
    """21 Des 2020: jarak ~0,1°, di 0°29' Aquarius — konjungsi terdekat sejak 1623."""
    p = a.posisi(T("2020-12-21"))
    assert a.selisih(p["Jupiter"][0], p["Saturnus"][0]) < 0.2
    assert 300.0 < p["Jupiter"][0] < 301.0


@pytest.mark.parametrize("nama,mulai,akhir,fakta", [
    ("Merkurius", "2024-03-20", "2025-01-05",
     ["2024-04-01", "2024-04-25", "2024-08-05", "2024-08-28", "2024-11-25", "2024-12-15"]),
    ("Mars", "2022-10-01", "2023-02-01", ["2022-10-30", "2023-01-12"]),
    ("Venus", "2023-07-01", "2023-09-30", ["2023-07-22", "2023-09-03"]),
])
def test_stasiun_retrograde_jatuh_di_tanggal_yang_benar(nama, mulai, akhir, fakta):
    d0, d1 = dt.date.fromisoformat(mulai), dt.date.fromisoformat(akhir)
    st = [e[0] for e in a.peristiwa(d0, (d1 - d0).days)
          if e[1].startswith(nama + " ") and "stasiun" in e[1]]
    assert len(st) == len(fakta), st
    for hasil, benar in zip(st, fakta):
        # Resolusi harian (12:00 UTC): stasiun yang jatuh malam hari tercatat hari
        # sesudahnya. Lebih dari 1 hari berarti elemen orbitnya yang salah.
        assert abs((dt.date.fromisoformat(hasil) - dt.date.fromisoformat(benar)).days) <= 1


def test_merkurius_retrograde_di_tengah_periodenya():
    assert a.mundur("Merkurius", T("2024-04-12"))
    assert not a.mundur("Merkurius", T("2024-05-12"))


def test_gerhana_matahari_8_april_2024_adalah_bulan_baru():
    e = a.fase_bulan(T("2024-04-08", 18))
    assert min(e, 360 - e) < 1.0


def test_purnama_25_januari_2024():
    assert abs(a.fase_bulan(T("2024-01-25", 18)) - 180) < 1.0


def test_ekuinoks_maret_2024():
    """Matahari di 0° Aries pada 20 Mar 2024 03:06 UTC — sekaligus bukti koreksi presesi
    (tanpa presesi, bujurnya meleset ~0,34°)."""
    lon = a.posisi(T("2024-03-20", 3))["Matahari"][0]
    assert min(lon, 360 - lon) < 0.05


def test_bulan_di_luar_batas_deklinasi_normal_tidak_mungkin():
    """Deklinasi Matahari tidak pernah melewati kemiringan ekliptika."""
    for d in ("2024-06-20", "2024-12-21", "2024-03-20"):
        t = T(d)
        lon, lat = a.posisi(t)["Matahari"]
        assert abs(a.deklinasi(lon, lat, t)) <= a.kemiringan(t) + 0.05


def test_aspek_tanpa_bulan_di_fitur_harian():
    """Bulan membentuk ~40 aspek eksak sebulan; memasukkannya ke fitur hanya menambah
    derau dan memperbesar peluang 'menemukan' efek palsu."""
    f = a.fitur_harian(dt.date(2020, 12, 21))
    assert f.get("Jupiter_konjungsi_Saturnus") == 1
    assert not any("Bulan_" in k and ("konjungsi" in k or "square" in k) for k in f)


def test_orb_ditetapkan_sekali():
    assert a.ORB == 6.0 and sorted(a.ASPEK) == [0, 60, 90, 120, 180]


def test_hanya_pustaka_standar():
    """Runner tidak memasang pustaka astronomi, dan pyswisseph berlisensi AGPL."""
    src = open(os.path.join(AKAR, "cloud", "astro.py"), encoding="utf-8").read()
    for terlarang in ("import swisseph", "import ephem", "import skyfield", "import numpy"):
        assert terlarang not in src

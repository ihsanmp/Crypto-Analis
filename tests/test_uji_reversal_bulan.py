import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import uji_reversal_bulan as u  # noqa: E402


def test_tanda_reversal():
    # naik lalu turun di t=2 (n=2): reversal; naik terus: bukan
    rev = u.tanda_reversal([1, 2, 3, 2, 1], 2)
    assert rev == {2: True}
    assert u.tanda_reversal([1, 2, 3, 4, 5], 2) == {2: False}


def test_uji_placebo_berjalan():
    rng = random.Random(0)
    tutup = [100 * (1 + 0.01 * rng.gauss(0, 1)) ** i for i in range(800)]
    event = list(range(10, 790, 30))
    h = u.uji(tutup, event, list(range(800)), 7, 300, random.Random(1))
    assert 0 < h["p"] <= 1 and h["event"] > 20


def test_status_bukti_menyebut_uji_reversal():
    import astro
    assert "REVERSAL" in astro.STATUS_BUKTI and "p=0,33" in astro.STATUS_BUKTI


def test_placebo_bukan_siklus_palsu_berperiode_tetap():
    """Siklus palsu 29,53 hari di data harian hanya ~30 himpunan berbeda dan sempat
    memberi p=0,000 palsu; placebo harus geseran melingkar."""
    src = open(u.__file__, encoding="utf-8").read()
    assert "geser = rng.randint(30, panjang - 30)" in src
    assert "def hari_siklus_palsu" not in src

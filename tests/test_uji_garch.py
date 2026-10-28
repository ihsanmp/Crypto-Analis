import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import uji_garch as ug  # noqa: E402


def test_garch_memulihkan_parameter_simulasi():
    random.seed(1)
    a, p, vL = 0.10, 0.95, 1e-4
    w, v, r = vL * (1 - p), vL, []
    for _ in range(3000):
        x = random.gauss(0, math.sqrt(v))
        r.append(x)
        v = w + a * x * x + (p - a) * v
    a_, p_, _ = ug.garch_fit(r)
    assert abs(a_ - a) <= 0.04 and abs(p_ - p) <= 0.03


def test_ramalan_dan_ukuran():
    assert ug.ramal_garch(2e-4, 0.1, 0.95, 1e-4, 1) == 2e-4
    # h besar -> mendekati h x varians jangka panjang
    assert abs(ug.ramal_garch(2e-4, 0.1, 0.95, 1e-4, 400) / 400 - 1e-4) < 1e-5
    assert ug.qlike(1.0, 1.0) == 0 and ug.qlike(2.0, 1.0) > 0
    _, p = ug.diebold_mariano([1.0, 1.2, 0.9, 1.1] * 50, 3)
    assert p < 0.001

import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import proyeksi  # noqa: E402
import uji_kronos as uk  # noqa: E402


def _harian(n=400, sigma=0.03, benih=3):
    rng = random.Random(benih)
    p, k = 100.0, []
    for i in range(n):
        p *= math.exp(rng.gauss(0, sigma))
        k.append([i * 86400000, p, p, p, p, 1.0, p])
    return k


def test_pembanding_sama_persis_dengan_prediksi_harga_bot():
    """Lawan Kronos harus metode yang DIPAKAI bot, bukan versi tiruan."""
    h = _harian()
    for hari in (1, 7):
        s = uk.sigma_pembanding(h, len(h), hari)
        b = proyeksi.prediksi_harga([c[:6] for c in h], [hari], "BTC")["per_horizon"][0]
        lebar_bot = math.log(b["kisaran_80_persen"][1] / b["kisaran_80_persen"][0])
        assert abs(lebar_bot - 2 * 1.2816 * s) < 1e-6, hari


def test_ukuran_dasar():
    assert uk.pinball(0.0, {0.5: 0.0}) == 0
    assert uk.kuantil_empiris([1, 2, 3, 4, 5], 0.5) == 3
    assert abs(uk.spearman([1, 2, 3], [10, 20, 30]) - 1) < 1e-12
    _, p = uk.diebold_mariano([0.1, 0.12, 0.08, 0.11] * 30, 3)
    assert p < 0.001


def test_gabung_menerapkan_kriteria(tmp_path, monkeypatch):
    rng = random.Random(1)
    for a in uk.ASET:
        for st in uk.SETELAN:
            baris = []
            for k in range(60):
                tgl = f"2025-{9 + k // 30:02d}-{1 + k % 30:02d}"
                nyata = rng.gauss(0, 0.03)
                baris.append({"tgl": tgl, "periode": "utama", "nyata": nyata,
                              "pin_k": 0.010 + rng.random() * 0.001, "pin_b": 0.012,
                              "cak_k": True, "cak_b": True, "median_k": nyata * 0.5})
            (tmp_path / f"hasil_{a}_{st}.json").write_text(
                json.dumps({"aset": a, "setelan": st, "baris": baris}), encoding="utf-8")
    h = uk.gabung(str(tmp_path))
    u = h["setelan"]["H24"]["utama"]
    assert u["menang_kisaran"] == "3/3" and u["lolos_kisaran"] and u["lolos_arah"]

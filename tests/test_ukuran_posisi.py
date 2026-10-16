import json
import math
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import uji_ukuran_posisi as up  # noqa: E402


def _tutup(n, gerak):
    d0, x, keluar = date(2020, 1, 1), 100.0, {}
    for i in range(n):
        x *= math.exp(gerak(i))
        keluar[d0 + timedelta(days=i)] = x
    return keluar


def test_vol_terealisasi_tahunan():
    t = _tutup(40, lambda i: 0.02 if i % 2 else -0.02)
    v = up.vol_terealisasi(t, max(t))
    assert 0.35 < v < 0.40                                  # ~0,02 x akar(365) = 0,38


def test_target_vol_hanya_dari_masa_lalu():
    vol = {date(2020, 1, 1) + timedelta(days=i): (0.5 if i < 400 else 5.0) for i in range(800)}
    f = date(2020, 1, 1) + timedelta(days=500)
    assert up.target_vol(vol, f) == 0.5                     # lonjakan sesudah f tidak bocor
    assert up.target_vol(vol, date(2020, 6, 1)) is None     # riwayat < 365 hari


def test_pengali_dipotong():
    vol = {date(2020, 1, 1) + timedelta(days=i): 0.6 for i in range(400)}
    f = date(2020, 1, 1) + timedelta(days=399)
    vol[f] = 0.1                                            # tenang sekali -> pengali besar
    assert up.pengali(vol, f) == up.PENGALI_MAKS


def test_simulasi_membayar_biaya_saat_eksposur_berubah():
    jumat = [date(2020, 1, 3) + timedelta(days=7 * i) for i in range(80)]
    tutup = {date(2020, 1, 3) + timedelta(days=d): 100.0 * 1.001 ** d for d in range(600)}
    rata = up.simulasi(jumat, [0.5] * 80, tutup, date(2020, 1, 1), date(2022, 1, 1))
    ganti = up.simulasi(jumat, [0.2 if (i // 4) % 2 else 0.8 for i in range(80)], tutup,
                        date(2020, 1, 1), date(2022, 1, 1))
    assert ganti["biaya_persen"] > rata["biaya_persen"] and ganti["ubah"] > 0


def test_vonis_tersimpan_tidak_diadopsi():
    d = json.load(open(up.HASIL_PATH, encoding="utf-8"))
    assert d["diadopsi"] is False
    assert d["varian"]["C_gabungan"]["penuh"]["sharpe"] < d["varian"]["A_likuiditas"]["penuh"]["sharpe"]

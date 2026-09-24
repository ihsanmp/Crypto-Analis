"""Tes swing.py — MINOR SWING STRATEGY (materi Astronacci), dideteksi kode.

Yang paling penting dijaga: TIDAK MENGINTIP MASA DEPAN. Pivot fraktal baru sah setelah
3 candle sesudahnya tertutup; tanpa itu backtest-nya "menang" karena tahu ke mana harga
akan pergi.
"""

import os
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import swing as sw  # noqa: E402


def _c(t, o, h, l, c):
    return [t, o, h, l, c, 1.0]


def _seri(skala=1.0, naik=True):
    """Tren panjang, lalu puncak → pullback → pantulan: satu setup BELI (atau JUAL)."""
    k, p, t, arah = [], 80000.0, 0, 1 if naik else -1
    for _ in range(120):
        k.append(_c(t, p, p + 30, p - 30, p + 20 * arah)); p += 20 * arah; t += 1
    for d in (150, 200, 250, 300):
        d *= skala * arah
        k.append(_c(t, p, max(p, p + d) + 5, min(p, p + d) - 5, p + d - 30 * arah)); p += d - 30 * arah; t += 1
    for d in (-200, -250, -300, -150):
        d *= skala * arah
        k.append(_c(t, p, max(p, p + d) + 5, min(p, p + d) - 5, p + d + 30 * arah)); p += d + 30 * arah; t += 1
    for d in (80, 90, 100, 60, 70):
        d *= arah
        k.append(_c(t, p, max(p, p + d) + 5, min(p, p + d) - 5, p + d - 10 * arah)); p += d - 10 * arah; t += 1
    return k


def _setup(k):
    e, g = sw._indikator(k)
    hasil = [sw.setup_di(k, i, e, g) for i in range(len(k))]
    return [s for s in hasil if s]


def test_satuan_pip_dari_gambar():
    """1.155,61 ditulis "115 pips" di gambarnya → 1 pip = $10, 200 pips = $2.000."""
    assert sw.PIP_BTC == 10 and sw.MAKS_PIPS * sw.PIP_BTC == 2000
    # Kedua contoh di gambar: 1.155,61 → "115 pips", 1.212,66 → "121 pips".
    assert int(1155.61 / sw.PIP_BTC) == 115 and int(1212.66 / sw.PIP_BTC) == 121


def test_contoh_gambar_memenuhi_aturan():
    """Buy stop 87.281, support 85.460 → rentang 182 pips (≤ 200), TP 1:1 = 89.102."""
    rentang = 87281 - 85460
    assert rentang / sw.PIP_BTC <= sw.MAKS_PIPS
    assert 87281 + sw.RR * rentang == 89102


def test_setup_beli_terdeteksi():
    s = _setup(_seri())
    assert len(s) == 1 and s[0]["arah"] == "BELI"
    assert s[0]["tp"] - s[0]["entry"] == pytest.approx(s[0]["entry"] - s[0]["sl"])


def test_setup_jual_cermin():
    s = _setup(_seri(naik=False))
    assert len(s) == 1 and s[0]["arah"] == "JUAL"
    assert s[0]["tp"] < s[0]["entry"] < s[0]["sl"]


def test_tidak_mengintip_masa_depan():
    k = _seri()
    e, g = sw._indikator(k)
    for i in range(len(k)):
        penuh = sw.setup_di(k, i, e, g)
        dipotong = sw.setup_di(k[:i + 1], i)
        assert (penuh is None) == (dipotong is None), i
        if penuh:
            assert penuh["entry"] == dipotong["entry"] and penuh["sl"] == dipotong["sl"]


def test_rentang_lebih_dari_200_pips_ditolak():
    assert _setup(_seri(skala=3.0)) == []


def _lanjut(k, s, gerak):
    t, p = k[-1][0] + 1, k[-1][4]
    for o, h, l, c in gerak(s, p):
        k.append(_c(t, o, h, l, c)); t += 1
    return k


def test_tembus_resisten_lalu_tp_kena():
    k = _seri()
    s = _setup(k)[0]
    k = _lanjut(k, s, lambda s, p: [(p, s["entry"] + 20, p - 5, s["entry"] + 10),
                                     (s["entry"], s["tp"] + 20, s["entry"] - 5, s["tp"])])
    tr = sw.backtest(k, biaya=0.0)
    assert [x["hasil_R"] for x in tr] == [1.0]


def test_tembus_lalu_sl_kena():
    k = _seri()
    s = _setup(k)[0]
    k = _lanjut(k, s, lambda s, p: [(p, s["entry"] + 20, p - 5, s["entry"] + 10),
                                     (s["entry"], s["entry"] + 5, s["sl"] - 20, s["sl"] - 10)])
    assert [x["hasil_R"] for x in sw.backtest(k, biaya=0.0)] == [-1.0]


def test_candle_yang_menyentuh_sl_dan_tp_dihitung_kalah():
    """Dalam satu candle H1 tidak bisa diketahui mana yang tersentuh duluan."""
    k = _seri()
    s = _setup(k)[0]
    k = _lanjut(k, s, lambda s, p: [(p, s["entry"] + 20, p - 5, s["entry"] + 10),
                                     (s["entry"], s["tp"] + 20, s["sl"] - 20, s["entry"])])
    assert [x["hasil_R"] for x in sw.backtest(k, biaya=0.0)] == [-1.0]


def test_biaya_dihitung_dalam_R():
    """Biaya 0,1% pada harga ~$83rb dan rentang ~$840 ≈ 0,1R — cukup untuk membuat win
    rate 50% jadi rugi."""
    k = _seri()
    s = _setup(k)[0]
    k = _lanjut(k, s, lambda s, p: [(p, s["entry"] + 20, p - 5, s["entry"] + 10),
                                     (s["entry"], s["tp"] + 20, s["entry"] - 5, s["tp"])])
    r = sw.backtest(k, biaya=0.001)[0]["hasil_R"]
    assert r == pytest.approx(1 - 0.001 * s["entry"] / s["rentang"])


def test_hasil_uji_yang_dipaku_menyebut_kerugiannya():
    """Versi berbias memberi 60,3% menang. Sesudah bias dibuang: 47,4%, −0,143R. Blok
    brief wajib membawa angka yang benar — bukan yang menyenangkan."""
    st = {"tren": "NAIK", "harga": 84000, "ema50": 83000, "macd": 120, "setup": None}
    teks = sw.ringkas(st)
    for wajib in ("234 transaksi", "47,4%", "−0,143R", "RUGI", "JANGAN"):
        assert wajib in teks, wajib
    assert "60,3" not in teks


def test_setup_jual_ditandai_di_luar_cakupan_spot():
    st = {"tren": "TURUN", "harga": 83470, "ema50": 84635, "macd": -465,
          "setup": {"arah": "JUAL", "entry": 83501, "sl": 84650, "tp": 82352,
                    "rentang": 1149, "terisi": True, "umur_candle": 10}}
    teks = sw.ringkas(st)
    assert "short" in teks and "khusus spot" in teks and "bukan saran" in teks


def test_parameter_a_priori():
    assert (sw.EMA_PERIODE, sw.FRAKTAL, sw.RR, sw.KEDALUWARSA, sw.BIAYA_PP) == \
        (50, 3, 1.0, 48, 0.001)
    assert (sw.MACD_CEPAT, sw.MACD_LAMBAT, sw.MACD_SINYAL) == (12, 26, 9)



# ---- bias optimis yang ketahuan dari status live (run 35993312501) ----------------------

def test_setup_ditolak_kalau_penembusan_sudah_terjadi():
    """Status live menampilkan SELL STOP $83.730 padahal harga sudah $83.504: penembusan
    terjadi selama candle konfirmasi pivot. Backtest versi pertama "mengisinya" di $83.730
    — hadiah ~0,26R per transaksi yang mustahil didapat."""
    k = _seri()
    s = _setup(k)
    assert s, "prasyarat: seri dasar punya setup"
    t = s[0]["t"]
    # Candle konfirmasi terakhir (t) melonjak menembus resisten.
    k2 = [list(x) for x in k]
    k2[t][2] = s[0]["entry"] + 50
    e, g = sw._indikator(k2)
    assert sw.setup_di(k2, t, e, g) is None


def test_isi_lewat_gap_memakai_harga_pembukaan():
    k = _seri()
    s = _setup(k)[0]
    gap = s["entry"] + 100
    # Candle pengisian membuka DI ATAS entry (gap), lalu mencapai TP.
    k = _lanjut(k, s, lambda s, p: [(gap, s["tp"] + 20, gap - 5, s["tp"])])
    r = sw.backtest(k, biaya=0.0)[0]["hasil_R"]
    assert r == pytest.approx((s["tp"] - gap) / s["rentang"])
    assert r < 1.0

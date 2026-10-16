import json
import math
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import model_kuant as mk  # noqa: E402


def test_logistik_memulihkan_parameter():
    rng = random.Random(1)
    xs = [rng.uniform(-1, 1) for _ in range(4000)]
    ys = [1 if rng.random() < mk.sigmoid(0.3 + 2.0 * x) else 0 for x in xs]
    a, b = mk.logistik(xs, ys, l2=0.0)
    assert abs(a - 0.3) < 0.15 and abs(b - 2.0) < 0.3


def test_data_latih_hanya_target_yang_sudah_terwujud():
    """Return 12 minggu yang tumpang tindih dengan titik prediksi TIDAK boleh ikut dilatih."""
    jumat = [date(2020, 1, 3) + timedelta(days=7 * i) for i in range(200)]
    y = [0.1] * 200
    titik = jumat[150]
    idx = mk.indeks_latih(jumat, y, titik, 12)
    assert max(jumat[i] for i in idx) + timedelta(days=7 * 12) < titik


def test_target_dari_penutupan_sabtu():
    harga = {(date(2026, 1, 3) + timedelta(days=d)).isoformat(): 100.0 * (1.01 ** d)
             for d in range(120)}
    y = mk.target([date(2026, 1, 2)], harga, 4)
    assert abs(y[0] - 28 * math.log(1.01)) < 1e-9


def test_gabung_mengabaikan_fitur_kosong_dan_menormalkan_bobot():
    fit = {"a": [1.0], "b": [None], "c": [-1.0]}
    assert mk.gabung(fit, {"a": 0.3, "b": 0.5, "c": 0.2}, 0) == (0.3 - 0.2) / 1.0


def test_peluang_hanya_bila_versi_diadopsi(monkeypatch, tmp_path):
    p = tmp_path / "uji.json"
    monkeypatch.setattr(mk, "STATUS_PATH", str(p))
    jumat = [date(2015, 1, 2) + timedelta(days=7 * i) for i in range(400)]
    rng = random.Random(2)
    liq = [math.sin(i / 9) for i in range(400)]
    harga, x = {}, 100.0
    for d in range(400 * 7 + 120):
        t = date(2015, 1, 2) + timedelta(days=d)
        x *= math.exp(0.004 * liq[min(d // 7, 399)] + rng.gauss(0, 0.02))
        harga[t.isoformat()] = x
    assert mk.peluang_likuiditas(jumat, liq, harga, 399) is None          # belum diuji
    p.write_text(json.dumps({"horizon": {"12": {
        "versi": "likuiditas_saja", "diadopsi": True, "ic_oos": 0.3, "p_placebo": 0.01,
        "brier_skill": 0.1, "tahun_positif": "5/8"}}}), encoding="utf-8")
    hasil = mk.peluang_likuiditas(jumat, liq, harga, 399)
    assert 0 <= hasil["peluang_btc_naik_persen"] <= 100 and "OOS" in hasil["uji_walk_forward"]
    p.write_text(json.dumps({"horizon": {"12": {"versi": None, "diadopsi": False}}}),
                 encoding="utf-8")
    assert mk.peluang_likuiditas(jumat, liq, harga, 399) is None          # gagal uji


def test_vonis_uji_tersimpan_sesuai_pra_registrasi():
    d = json.load(open(mk.STATUS_PATH, encoding="utf-8"))["horizon"]
    assert d["12"]["versi"] == "likuiditas_saja" and d["12"]["ic_oos_gabungan"] < d["12"]["ic_oos"]
    assert d["4"]["diadopsi"] is False
    assert "GAGAL" in mk.WAJIB_DIBACA


def test_arah_model_kuant_ditempel_hanya_btc_horizon_2_sampai_4_bulan():
    import bot_oneshot as bot
    br = '{"peluang_model_kuant":{"horizon_minggu":12,"peluang_btc_naik_persen":38,' \
         '"laju_dasar_naik_persen":58}}'
    assert "38%" in bot.arah_model_kuant(br, "btc 3 bulan ke depan gimana?", "BTC")
    assert bot.arah_model_kuant(br, "prediksi btc weekly", "BTC") == ""
    assert bot.arah_model_kuant(br, "eth 3 bulan ke depan", "ETH") == ""
    assert bot.arah_model_kuant("{}", "btc 3 bulan ke depan", "BTC") == ""


def test_laju_dasar_sampel_pendek_ditandai():
    import proyeksi
    k = [[i * 86400000, 100 + i, 100 + i, 100 + i, 100.0 + (i % 7), 0] for i in range(400)]
    teks = proyeksi.prediksi_harga(k, [90], "BTC")["per_horizon"][0][
        "riwayat_aset_ini_ditutup_lebih_tinggi"]
    assert "SAMPEL PENDEK" in teks and "1.1 tahun" in teks

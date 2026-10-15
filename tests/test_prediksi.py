import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import bot_oneshot as bot  # noqa: E402
import proyeksi  # noqa: E402


def _candles(n=400, sigma=0.02, benih=1):
    rng = random.Random(benih)
    p, k = 100.0, []
    for i in range(n):
        p *= math.exp(rng.gauss(0, sigma))
        k.append([i * 86400000, p, p, p, p, 0])
    return k


def test_horizon_prediksi_membaca_daily_weekly_dan_angka():
    """"prediksi btc daily" dulu dijawab dengan horizon 60 hari."""
    assert bot.horizon_prediksi("prediksi btc daily") == [1]
    assert bot.horizon_prediksi("prediksi eth weekly") == [7]
    assert bot.horizon_prediksi("prediksi btc daily dan weekly") == [1, 7]
    assert bot.horizon_prediksi("prediksi sol 3 hari ke depan") == [3]
    assert bot.horizon_prediksi("ramal btc dua minggu") == [14]
    assert bot.horizon_prediksi("prediksi btc besok") == [1]
    assert bot.horizon_prediksi("prediksi harga btc") == [1, 7, 30]


def test_kisaran_prediksi_tersusun_dan_melebar_dengan_horizon():
    k = _candles()
    h = proyeksi.prediksi_harga(k, [1, 7, 30], "BTC")
    harga = k[-1][4]
    lebar = []
    for b in h["per_horizon"]:
        lo80, hi80 = b["kisaran_80_persen"]
        lo50, hi50 = b["kisaran_50_persen"]
        assert lo80 < lo50 < b["titik_tengah"] < hi50 < hi80
        assert abs(b["titik_tengah"] - harga) < 1e-6        # tanpa arah
        lebar.append(hi80 - lo80)
        assert b["jarak_80_dari_harga"].startswith("-") and " s/d +" in b["jarak_80_dari_harga"]
    assert lebar[0] < lebar[1] < lebar[2]
    assert "JANGAN satu angka" in h["wajib_dibaca"]


def test_kalibrasi_hanya_untuk_horizon_yang_diukur():
    h = proyeksi.prediksi_harga(_candles(), [3, 7], "SOL")
    tiga, tujuh = h["per_horizon"]
    assert "BELUM diukur" in tiga["kalibrasi_terukur"]
    assert tujuh["kalibrasi_terukur"]["kisaran_80_benar"].startswith("79,5%")
    assert "altcoin" in h["wajib_dibaca"]                  # kalibrasi diukur pada BTC


def test_riwayat_pendek_ditolak_bukan_ditebak():
    assert "tidak_tersedia" in proyeksi.prediksi_harga(_candles(n=50), [1], "BTC")


def test_bot_meneruskan_horizon_ke_proyeksi():
    tangkap = []
    asli = bot._jalankan_terukur
    bot._jalankan_terukur = lambda label, args, *a, **k: (tangkap.append(args), ("{}", None))[1]
    try:
        bot.data_proyeksi("prediksi btc daily dan weekly", "crypto", "BTC")
        args = tangkap[0]
        assert args[args.index("--prediksi") + 1] == "1,7"
        tangkap.clear()
        teks = bot.data_proyeksi("prediksi btc 4h", "crypto", "BTC")
        assert "CATATAN HORIZON" in teks
    finally:
        bot._jalankan_terukur = asli


def test_kemana_hanya_proyeksi_bila_ada_aset():
    assert bot._KEMANA_RE.search("btc bulan depan kemana?")
    assert not bot.pesan_pasar("long weekend enaknya kemana")


def test_pertanyaan_prediksi_sampai_ke_prompt_lewat_process():
    import tempfile as _tf
    asli = (bot.JEJAK_PATH, bot.simpan_riwayat, bot.send_message, bot.run_claude,
            bot.data_mentah_crypto, bot.data_proyeksi, bot._muat_riwayat)
    bot.JEJAK_PATH = os.path.join(_tf.mkdtemp(), "d.json")
    bot.simpan_riwayat = lambda *a: None
    bot.send_message = lambda *a: True
    bot._muat_riwayat = lambda: []
    bawaan = []
    bot.data_mentah_crypto = lambda *a, **k: (bawaan.append(k.get("proyeksi", True)),
                                              "### DATA")[1]
    dipanggil, prompt = [], {}
    bot.data_proyeksi = lambda t, j, s: (dipanggil.append((t, s)), "### PREDIKSI KISARAN")[1]
    bot.run_claude = lambda p, *a, **k: (prompt.__setitem__("p", p), ("ok", None))[1]
    try:
        for teks in ("prediksi btc daily", "prediksi harga eth weekly", "btc bulan depan kemana?"):
            dipanggil.clear(); prompt.clear(); bawaan.clear()
            bot.process("tok", "9", teks)
            assert dipanggil and "### PREDIKSI KISARAN" in prompt.get("p", ""), teks
            # Blok proyeksi 60 hari bawaan dilewati: dua blok proyeksi = token dobel dan
            # dua kalibrasi yang sempat tertukar.
            assert bawaan == [False], (teks, bawaan)
        bawaan.clear()
        bot.process("tok", "9", "penyebab btc tiba tiba naik pagi ini")
        assert bawaan == [True], bawaan
    finally:
        (bot.JEJAK_PATH, bot.simpan_riwayat, bot.send_message, bot.run_claude,
         bot.data_mentah_crypto, bot.data_proyeksi, bot._muat_riwayat) = asli


def test_jarak_dari_harga_bukan_lebar_total():
    """Produksi 15 Okt: lebar total 5,08% ditulis model sebagai "±5%" — padahal -2,5/+2,6%."""
    b = proyeksi.prediksi_harga(_candles(sigma=0.02), [1], "BTC")["per_horizon"][0]
    bawah, atas = (float(x.strip(" %").replace("+", "")) for x in b["jarak_80_dari_harga"].split("s/d"))
    assert -4 < bawah < -1 and 1 < atas < 4


def test_kalibrasi_prediksi_tidak_tertukar_dengan_tabel_puncak_dasar():
    """Produksi: "80-84% benar -> lebih sempit dari kenyataan" — arahnya terbalik, dicampur
    dari kalibrasi tabel puncak/dasar 60 hari."""
    b = proyeksi.prediksi_harga(_candles(), [7], "BTC")["per_horizon"][0]
    assert "LEBIH LEBAR" in b["kalibrasi_terukur"]["wajib_dibaca"]
    src = open(proyeksi.__file__, encoding="utf-8").read()
    assert "BUKAN prediksi_harga" in src


def test_audit_outlook_tidak_salah_vonis_jawaban_ngobrol():
    """>= 8 dari 25 run: "Sebaran 60 hari ... tidak dipakai" menempel di jawaban ngobrol."""
    bawaan = "PROYEKSI (proyeksi.py)\n{'peluang_historis': {}}"          # brief koin biasa
    diminta = "### PROYEKSI (proyeksi.py, horizon 7 hari)\n{'peluang_historis': {}}"
    assert bot.audit_outlook(bawaan, "BTC naik karena likuidasi short", "chat") is None
    assert bot.audit_outlook(diminta, "Kisaran 80% besok: $79.005-$83.130", "chat") is None
    assert bot.audit_outlook(diminta, "Target $100 -> $120", "chat") == "HILANG"
    assert bot.audit_outlook(bawaan, "Target $100 -> $120", "analisa") == "HILANG"

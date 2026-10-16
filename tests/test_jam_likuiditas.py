import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import jam_likuiditas as jl  # noqa: E402


def test_skor_hanya_memakai_masa_lalu():
    """Mengubah nilai MASA DEPAN tidak boleh mengubah skor minggu ini."""
    x = [float(i % 7) + i * 0.1 for i in range(120)]
    a = jl.skor(x)
    y = x[:100] + [999.0] * 20
    b = jl.skor(y)
    assert a[:100] == b[:100]
    assert all(v is None or -1 < v < 1 for v in a)
    assert a[jl.MIN_RIWAYAT + jl.K_MINGGU - 1] is None      # riwayat belum cukup


def test_tanda_negatif_membalik_arah():
    x = [float(i % 5) for i in range(100)] + [50.0]
    assert jl.skor(x)[-1] > 0.9 and jl.skor(x, tanda=-1)[-1] < -0.9


def test_ketersediaan_point_in_time():
    jumat = [date(2026, 10, 9)]
    titik = [(date(2026, 10, 8), 1.0), (date(2026, 10, 10), 2.0)]   # tersedia Sabtu
    assert jl.ke_mingguan(titik, jumat) == [1.0]
    assert jl.ke_mingguan([(date(2026, 9, 1), 1.0)], jumat) == [None]   # basi


def test_satuan_likuiditas_bersih_diseragamkan_ke_miliar():
    """WALCL & WDTGAL dalam JUTA, RRPONTSYD dalam MILIAR."""
    jumat = jl.jumat_dari(date(2020, 1, 3), date(2020, 1, 3))
    f = jumat[0] - timedelta(days=1)
    fred = {k: [(f, 1.0)] for k in jl.SERI}
    fred.update(WALCL=[(f, 7_000_000.0)], WDTGAL=[(f, 800_000.0)], RRPONTSYD=[(f, 200.0)])
    L = jl.deret_likuiditas(fred, jumat)
    assert L["likuiditas_bersih_miliar"] == [7000 - 800 - 200]


def test_komponen_hilang_mengosongkan_skor():
    assert jl._rata(0.2, None, 0.1, 0.3) is None


def test_eksposur_dan_filter_resesi():
    assert jl.eksposur(1.0, None, False) == 1.0
    assert jl.eksposur(-1.0, None, False) == 0.0
    assert jl.eksposur(0.8, 0.8, True) == 0.5
    assert jl.eksposur(0.0, -0.4, False) == 0.4


def test_aturan_gelombang_dimatikan_karena_ditolak_data():
    """Rancangan: Gelombang > 0,5 -> potong 25 pp. Uji: minggu-minggu itu justru diikuti
    median +20% dalam 12 minggu. Aturan yang merugikan tidak boleh diam-diam aktif."""
    assert jl.PAKAI_ATURAN_GELOMBANG is False
    assert jl.eksposur(0.2, None, False, gelombang=0.9) == jl.eksposur(0.2, None, False)
    assert "DITOLAK" in jl.STATUS_GELOMBANG


def test_arti_kuadran_dari_uji_bukan_teori():
    j = jl.jarum(-0.3, 0.2, terukur=True)
    assert j["fase"] == "KETAT, MULAI MEMBAIK"
    assert "MENOLAKNYA" in j["riwayat_btc_12mg_kuadran_ini"]
    assert j["riwayat_btc_12mg_tersil_skor"].startswith("RENDAH")
    adopsi = jl.jarum(0.3, 0.2)
    assert adopsi["fase"].startswith("ADOPSI") and "BELUM TERBUKTI" in adopsi["riwayat"]
    assert "TERUJI" in jl.STATUS_BUKTI and "4 minggu TIDAK lolos" in jl.STATUS_BUKTI
    assert "ETH" in jl.STATUS_BUKTI and "SOL" in jl.STATUS_BUKTI


def _arus(n=400, awal=date(2024, 1, 11)):
    return [((awal + timedelta(days=i)).isoformat(), (100.0 if i % 3 else -50.0) * (1 + i % 11))
            for i in range(n)]


def test_adopsi_dari_arus_etf():
    arus = _arus()
    harga = {t: 50_000.0 for t, _ in arus}
    jumat = jl.jumat_dari(date(2024, 1, 12), date(2024, 1, 11) + timedelta(days=400))
    A = jl.deret_adopsi(arus, harga, jumat)
    assert A["A1"][0] is None and A["A1"][-1] is not None
    assert 0 <= A["A2"][-1] <= 1
    i = max(k for k, v in enumerate(A["struktural"]) if v is not None)
    assert A["komponen_terpakai"][i] == ("A1", "A2")      # A3/A4 belum ada -> tidak ikut


def test_a3_dari_13f_memakai_tanggal_tersedia_bukan_akhir_kuartal():
    arus = _arus()
    harga = {t: 50_000.0 for t, _ in arus}
    jumat = jl.jumat_dari(date(2024, 1, 12), date(2025, 2, 1))
    q = [(date(2024, 6, 30) + timedelta(days=45),
          {"akhir_kuartal": "2024-06-30", "pemegang": 1000, "nilai_usd": 5e10}),
         (date(2024, 9, 30) + timedelta(days=45),
          {"akhir_kuartal": "2024-09-30", "pemegang": 1100, "nilai_usd": 6e10})]
    A = jl.deret_adopsi(arus, harga, jumat, q)
    sebelum = [s for f, s in zip(jumat, A["skor_A3"]) if f < date(2024, 11, 14)]
    sesudah = [s for f, s in zip(jumat, A["skor_A3"]) if f >= date(2024, 11, 14)]
    assert all(s is None for s in sebelum) and sesudah[0] > 0
    assert A["info_A3"][-1]["inti_qoq_persen"] == 10.0


def test_validasi_menolak_satuan_dan_menandai_basi():
    hari = date(2026, 10, 15)
    fred = {k: [(hari, sum(jl.RENTANG_WAJAR[k]) / 2)] for k in jl.SERI}
    assert jl.validasi(fred, hari) == ([], [])
    fred["WALCL"] = [(hari, 6_700.0)]                       # miliar, bukan juta
    fred["NFCI"] = [(hari - timedelta(days=30), 0.0)]
    satuan, basi = jl.validasi(fred, hari)
    assert satuan and "WALCL" in satuan[0] and basi and "NFCI" in basi[0]


def test_pesan_telegram_menyebut_kedua_eksposur():
    h = {"sinyal_jumat": "2026-10-09", "skor_likuiditas": -0.43,
         "komponen": {"L1_bunga": -0.3}, "filter_resesi_L5": {"aktif": False},
         "jam_likuiditas": {"fase": "KETAT & MAKIN KETAT",
                            "riwayat_btc_12mg_kuadran_ini": "median -0,2%"},
         "adopsi_struktural": {"tidak_tersedia": "x"}, "gelombang": {},
         "target_eksposur_btc_persen": 43, "eksposur_komponen_teruji_saja_persen": 29}
    t = jl.pesan(h)
    assert "43%" in t and "29%" in t and "bukan sinyal entry" in t


def test_masuk_brief_crypto():
    src = open(os.path.join(os.path.dirname(__file__), "..", "cloud", "bot_oneshot.py"),
               encoding="utf-8").read()
    assert '"cloud/jam_likuiditas.py", "--ringkas"' in src
    seed = open(os.path.join(os.path.dirname(__file__), "..", "cloud", "prompts", "peran",
                             "analis.md"), encoding="utf-8").read()
    assert "JAM LIKUIDITAS" in seed


def test_fred_gagal_memakai_salinan_dan_menyebut_umurnya(tmp_path, monkeypatch):
    import makro
    monkeypatch.setattr(jl, "FRED_PATH", str(tmp_path / "fred.json"))
    ok = {k: [("2026-10-01", 1.0)] for k in jl.SERI}
    monkeypatch.setattr(makro, "ambil", lambda kode: (ok[kode.split("&")[0]], None))
    data, gagal = jl.ambil_fred()
    assert not gagal and "_cadangan" not in data
    monkeypatch.setattr(makro, "ambil", lambda kode: (None, "TimeoutError"))
    data, gagal = jl.ambil_fred()
    assert not gagal and "salinan" in data["_cadangan"] and set(jl.SERI) <= set(data)


def test_ringkas_mengganti_teks_bukti_panjang_tanpa_mengubah_angka():
    h = {"status_bukti": jl.STATUS_BUKTI, "skor_likuiditas": -0.43,
         "gelombang": {"skor": 0.1, "status_bukti": jl.STATUS_GELOMBANG},
         "adopsi_struktural": {"jam_adopsi": {"riwayat": jl.STATUS_ADOPSI}},
         "jejak_basis_trade_cftc": {"short_bersih_leveraged_funds_btc": 1, "arti": "x" * 300}}
    r = jl.ringkas(h)
    assert len(json.dumps(r)) < len(json.dumps(h)) / 2
    assert r["skor_likuiditas"] == -0.43 and r["gelombang"]["skor"] == 0.1
    assert "DITOLAK" in r["gelombang"]["status_bukti"]
    assert h["gelombang"]["status_bukti"] == jl.STATUS_GELOMBANG       # asli tidak diubah


def test_blok_jam_sampai_ke_prompt_lewat_process_sungguhan():
    """Sumber teks saja tidak cukup: label JAM harus benar-benar diminta lewat
    data_mentah_crypto dan keluarannya sampai ke prompt model — di analisa DAN ngobrol."""
    import tempfile
    import bot_oneshot as bot
    import indicators
    import kategori
    asli = (bot.JEJAK_PATH, bot.simpan_riwayat, bot.send_message, bot.belajar_dari,
            bot._jalankan_terukur, bot.run_claude, indicators.resolve_ticker, kategori.data_koin)
    label, prompt = [], []
    bot.JEJAK_PATH = os.path.join(tempfile.mkdtemp(), "j.json")
    bot.simpan_riwayat = lambda *a, **k: None
    bot.send_message = lambda *a, **k: True
    bot.belajar_dari = lambda *a, **k: []
    indicators.resolve_ticker = lambda c: (c.upper(), c.lower(), c)
    kategori.data_koin = lambda x: {"mcap_usd": 1.0}

    def palsu(lb, args, min_kar=0):
        label.append(lb)
        if "cloud/jam_likuiditas.py" in args:
            return '{"skor_likuiditas":-0.43,"target_eksposur_btc_persen":44}', None
        return f"<<{lb}>>", None
    bot._jalankan_terukur = palsu
    bot.run_claude = lambda p, *a, **k: (prompt.append(p), ("ok", None))[1]
    try:
        for teks in ("analisa btc", "btc kenapa turun minggu ini", "eth layak hold 3 bulan?"):
            label.clear()
            prompt.clear()
            bot.process("tok", "9", teks)
            assert "JAM LIKUIDITAS (jam_likuiditas.py)" in label, teks
            assert any('"skor_likuiditas":-0.43' in p for p in prompt), teks
    finally:
        (bot.JEJAK_PATH, bot.simpan_riwayat, bot.send_message, bot.belajar_dari,
         bot._jalankan_terukur, bot.run_claude, indicators.resolve_ticker,
         kategori.data_koin) = asli


def test_pemicu_jam_tanpa_aset_dan_jam_bukan_koin():
    """15 Okt 2026: "jam berapa rilis cpi" & "jam likuiditas minggu ini" terbaca koin JAM,
    dan pertanyaan rezim makro tanpa nama koin tidak mendapat skor sama sekali."""
    import tempfile
    import bot_oneshot as bot
    assert bot.aset_dari_pesan("jam berapa rilis cpi", dalam=True)[1] != "JAM"
    assert bot.aset_dari_pesan("jam likuiditas minggu ini", dalam=True)[1] != "JAM"
    asli = (bot.JEJAK_PATH, bot.simpan_riwayat, bot.send_message, bot.belajar_dari,
            bot._jalankan_terukur, bot.run_claude, bot.data_mentah_crypto)
    label = []
    bot.simpan_riwayat = lambda *a, **k: None
    bot.send_message = lambda *a, **k: True
    bot.belajar_dari = lambda *a, **k: []
    bot._jalankan_terukur = lambda lb, args, min_kar=0: (
        label.append(lb), ('{"skor_likuiditas":-0.4}', None))[1]
    bot.data_mentah_crypto = lambda c, *a, **k: (
        label.append("JAM LIKUIDITAS (jam_likuiditas.py)"),
        '[JAM LIKUIDITAS (jam_likuiditas.py)]\n{"skor_likuiditas":-0.4}')[1]
    bot.run_claude = lambda p, *a, **k: ("ok", None)
    try:
        for teks, harus in (("likuiditas fed lagi gimana?", 1),
                            ("rezim makro sekarang risk on?", 1),
                            ("yield 2 tahun naik, dampaknya?", 1),
                            ("arus etf minggu ini", 1),
                            ("jam berapa rilis cpi", 0),
                            ("apa itu likuiditas", 0),          # konsep: tanpa angka
                            ("btc gimana makro sekarang?", 1),  # sekali, bukan dua kali
                            ("halo", 0)):
            label.clear()
            bot.JEJAK_PATH = os.path.join(tempfile.mkdtemp(), "j.json")
            bot.process("tok", "9", teks)
            n = sum(1 for x in label if "JAM LIKUIDITAS" in x)
            assert n == harus, (teks, label)
    finally:
        (bot.JEJAK_PATH, bot.simpan_riwayat, bot.send_message, bot.belajar_dari,
         bot._jalankan_terukur, bot.run_claude, bot.data_mentah_crypto) = asli


def test_momentum_lemah_tidak_dibaca_sebagai_tren():
    """Produksi 16 Okt 2026: momentum -0,05 (persentil 14) ditulis "mengetat makin dalam",
    padahal skor seminggu itu membaik -0,43 -> -0,29."""
    liq = [0.3 * ((-1) ** (i // 4)) for i in range(60)] + [-0.24, -0.30, -0.467, -0.429, -0.289]
    k = jl.konteks_momentum(liq, len(liq) - 1)
    assert k["momentum_persentil_mutlak"] < jl.PERSENTIL_MOMENTUM_LEMAH
    assert k["perubahan_1mg"] == 0.14
    assert "PERBATASAN" in k["catatan_momentum"] and "membaik +0.14" in k["catatan_momentum"]
    kuat = [0.0] * 60 + [0.0, 0.0, 0.0, 0.0, 0.9]
    assert "catatan_momentum" not in jl.konteks_momentum(kuat, len(kuat) - 1)
    assert all("dari 199 minggu" in t for _, t in jl.TERUKUR_TERSIL_12MG)


def test_matriks_pemicu_jam_tanpa_aset():
    """164 frasa dari matriks pemicu (set tuning + 3 set held-out). Peluang aktif untuk
    frasa yang BELUM pernah dilihat diukur 69% -> 67% -> 88% (jam_likuiditas.md); tes ini
    mengunci agar perluasan pola berikutnya tidak menurunkan yang sudah tertangkap."""
    import bot_oneshot as bot
    sys.path.insert(0, os.path.dirname(__file__))
    from _frasa_jam import NEGATIF, POSITIF

    def aktif(t):
        # Mengikuti urutan routing bot: analisa selalu memuat blok; mode lain (narasi, dst.)
        # tidak; ngobrol memuat lewat aset crypto ATAU pola tanpa aset.
        jenis = bot.classify(t)
        if jenis == "analisa":
            return True
        if jenis != "chat":
            return False
        if bot.aset_dari_pesan(t, dalam=True)[0] == "crypto":
            return True
        return (bool(bot._MINTA_JAM.search(t)) and not bot._KONSEP_RE.search(t)
                and not bot._KONSEP_JAM.search(t))
    lolos = [t for t in POSITIF if not aktif(t)]
    salah = [t for t in NEGATIF if aktif(t)]
    assert not lolos, lolos
    assert not salah, salah


def test_etf_bukan_koin():
    import bot_oneshot as bot
    assert bot.aset_dari_pesan("arus masuk etf ethereum", dalam=True)[1] == "ETH"
    assert bot.aset_dari_pesan("fund manager masih beli etf?", dalam=True)[1] != "ETF"


def test_label_fase_menyatakan_momentum_datar():
    j = jl.tandai_perbatasan({"fase": "KETAT & MAKIN KETAT", "catatan_momentum": "LEMAH"})
    assert j["fase"].startswith("KETAT, MOMENTUM DATAR") and "MAKIN KETAT)" in j["fase"]
    tegas = jl.tandai_perbatasan({"fase": "LONGGAR & MAKIN LONGGAR"})
    assert tegas["fase"] == "LONGGAR & MAKIN LONGGAR"


def test_run_claude_memakai_system_prompt_bot_dan_bisa_dikembalikan(monkeypatch):
    """System prompt bawaan Claude Code (agen pemrograman) ±8,4 rb token per panggilan."""
    import bot_oneshot as bot
    dapat = {}
    monkeypatch.setattr(bot.shutil, "which", lambda n: "/usr/bin/claude")
    monkeypatch.setattr(bot.subprocess, "run", lambda cmd, **k: (
        dapat.__setitem__("cmd", cmd), (_ for _ in ()).throw(bot.subprocess.TimeoutExpired(cmd, 1)))[1])
    monkeypatch.delenv("BOT_SYSTEM_BAWAAN", raising=False)
    bot.run_claude("halo", 5, 1)
    i = dapat["cmd"].index("--system-prompt")
    assert dapat["cmd"][i + 1] == bot.SYSTEM_PROMPT_BOT and "Ringkas" in bot.SYSTEM_PROMPT_BOT
    monkeypatch.setenv("BOT_SYSTEM_BAWAAN", "1")
    bot.run_claude("halo", 5, 1)
    assert "--system-prompt" not in dapat["cmd"]


def test_jam_tidak_dijalankan_dua_kali_saat_blok_koin_gagal():
    """Blok JAM di jalur koin gagal -> brief memuat label tanpa skor. Jalur berdiri sendiri
    tidak boleh menjalankan script yang sama lagi."""
    import tempfile
    import bot_oneshot as bot
    asli = (bot.JEJAK_PATH, bot.simpan_riwayat, bot.send_message, bot.belajar_dari,
            bot._jalankan_terukur, bot.run_claude, bot.data_mentah_crypto)
    label = []
    bot.JEJAK_PATH = os.path.join(tempfile.mkdtemp(), "j.json")
    bot.simpan_riwayat = lambda *a, **k: None
    bot.send_message = lambda *a, **k: True
    bot.belajar_dari = lambda *a, **k: []
    bot._jalankan_terukur = lambda lb, args, min_kar=0: (label.append(lb), ("{}", None))[1]
    bot.data_mentah_crypto = lambda c, *a, **k: (
        "[JAM LIKUIDITAS (jam_likuiditas.py)]\nGAGAL DIAMBIL — TimeoutError")
    bot.run_claude = lambda p, *a, **k: ("ok", None)
    try:
        bot.process("tok", "9", "btc gimana kalau dolar menguat?")
        assert not any("JAM LIKUIDITAS" in x for x in label), label
    finally:
        (bot.JEJAK_PATH, bot.simpan_riwayat, bot.send_message, bot.belajar_dari,
         bot._jalankan_terukur, bot.run_claude, bot.data_mentah_crypto) = asli


def test_ringkas_membuang_teori_rancangan_bila_angka_uji_ada():
    """Produksi 16 Okt: "(defensif)" dikutip dari menurut_rancangan padahal riwayatnya netral."""
    h = {"jam_likuiditas": {"fase": "KETAT, MOMENTUM DATAR", "menurut_rancangan": "defensif",
                            "riwayat_btc_12mg_kuadran_ini": "median -0,2%"},
         "fase_adopsi": {"fase": "EUFORIA TERDUKUNG", "menurut_rancangan": "rawan koreksi",
                         "status_bukti": "BELUM TERBUKTI"}}
    r = jl.ringkas(h)
    assert "menurut_rancangan" not in r["jam_likuiditas"]
    assert "menurut_rancangan" not in r["fase_adopsi"] and r["fase_adopsi"]["status_bukti"]

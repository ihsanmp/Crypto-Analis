"""Tes routing & pengaman mutu bot Crypto-Analis.

KENAPA BERKAS INI ADA: seluruh routing bot ditentukan regex — classify, is_narasi,
topik_ai, jenis_aset, rakit_chat, bobot_chat, aset_dari_pesan. Sampai sebelum ini tidak ada
satu pun tes, dan pola kegagalannya konsisten: bug DITEMUKAN DI TELEGRAM, bukan oleh CI.
Contoh yang tercatat di komentar kode sendiri — run 30918498339 & 30918500749 sama-sama
membalas pesan yang sama; "analisis sektor ai" dijawab dengan daftar koin AI; ejaan
"analisis" tidak dikenali padahal "analisa" dikenali.

Semua tes berbentuk TABEL supaya menambah kasus baru cukup satu baris.

Menjalankan:  pytest tests/ -v
"""

import os
import re
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import bot_oneshot as bot          # noqa: E402
import memori                      # noqa: E402


# ---------------------------------------------------------------- classify

@pytest.mark.parametrize("pesan,harap", [
    # bantuan
    ("/help", "help"), ("start", "help"), ("bantuan", "help"),
    # analisa satu aset
    ("analisa sol", "analisa"), ("analisa gold", "analisa"),
    ("analisa eurusd", "analisa"), ("analisa koin pump", "analisa"),
    ("analisa the", "analisa"),                 # THE = Thena, bukan kata sandang
    # kedua ejaan HARUS sama — dulu hanya "analisa" yang dikenali
    ("analisa btc", "analisa"), ("analisis btc", "analisa"),
    # screening narasi
    ("carikan koin narasi privacy yang menarik", "narasi"),
    ("carikan koin narasi yang menarik", "narasi"),
    ("koin ai apa yang menarik", "narasi"),
    ("analisa sektor rwa", "narasi"),           # bukan koin bernama "SEKTOR"
    # JEBAKAN: AI sebagai INDUSTRI, bukan narasi koin
    ("analisis sektor ai", "chat"),
    ("analisa sektor ai", "chat"),
    ("perkembangan ai terbaru", "chat"),
    ("apa yang baru di sektor ai sekarang", "chat"),
    ("ada yang baru di ai?", "chat"),
    # pertanyaan FAKTA, bukan permintaan screening
    ("koin apa saja yang di hold blackrock", "chat"),
    ("bagaimana pendapatmu tentang bitcoin", "chat"),
    # ngobrol biasa
    ("halo", "chat"), ("apa itu RAG?", "chat"), ("rsi eth di daily berapa?", "chat"),
])
def test_classify(pesan, harap):
    assert bot.classify(pesan) == harap


def test_ejaan_analisa_dan_analisis_setara():
    """Perintah yang sama tidak boleh berperilaku beda karena ejaan."""
    for aset in ("sol", "btc", "gold", "eurusd"):
        assert bot.classify(f"analisa {aset}") == bot.classify(f"analisis {aset}")


# --------------------------------------------------------------- jenis_aset

@pytest.mark.parametrize("sisa,jenis,simbol", [
    # JEBAKAN: ticker "GOLD" di NYSE adalah Barrick Gold (tambang), bukan logamnya
    ("gold", "forex", "GC=F"), ("emas", "forex", "GC=F"), ("xauusd", "forex", "GC=F"),
    ("xau", "forex", "GC=F"),
    ("silver", "forex", "SI=F"), ("perak", "forex", "SI=F"), ("xagusd", "forex", "SI=F"),
    # pasangan mata uang
    ("eurusd", "forex", "EURUSD"), ("gbpusd", "forex", "GBPUSD"),
    ("usdjpy", "forex", "USDJPY"),
    # saham disebut eksplisit
    ("saham nvda", "saham", "NVDA"), ("saham aapl", "saham", "AAPL"),
    ("stock msft", "saham", "MSFT"),
    # crypto (bawaan)
    ("sol", "crypto", "SOL"), ("btc", "crypto", "BTC"), ("ondo", "crypto", "ONDO"),
    # kata pengantar dibuang — "analisa koin pump" adalah koin PUMP, bukan koin "KOIN"
    ("koin pump", "crypto", "PUMP"), ("token ondo", "crypto", "ONDO"),
    ("sektor ai", "crypto", "AI"),
    # kata generik yang berdiri sendiri = permintaan scan, bukan nama koin
    ("koin", "crypto", None), ("crypto", "crypto", None),
])
def test_jenis_aset(sisa, jenis, simbol):
    assert bot.jenis_aset(sisa) == (jenis, simbol)


# ---------------------------------------------- is_narasi & topik_ai (positif + negatif)

@pytest.mark.parametrize("pesan,harap", [
    ("carikan koin narasi privacy", True),
    ("koin privacy apa yang menarik", True),
    ("analisa sektor rwa", True),
    ("tema depin lagi jalan ga", True),
    # istilah AMBIGU: butuh konteks koin, kalau tidak itu topik lain
    ("analisis sektor ai", False),
    ("sektor gaming gimana", False),
    ("koin gaming apa yang bagus", True),
    ("cerita soal privacy di internet", False),
    # "ai" di dalam kata lain TIDAK boleh memicu
    ("pakai cara apa", False), ("saya pakai wallet ini", False),
    ("halo", False), ("analisa sol", False),
])
def test_is_narasi(pesan, harap):
    assert bot.is_narasi(pesan.lower()) is harap


@pytest.mark.parametrize("pesan,harap", [
    ("analisis sektor ai", True), ("perkembangan ai terbaru", True),
    ("kabar industri ai", True), ("ada yang baru di ai?", True),
    ("regulasi ai di eropa", True),
    # yang JELAS soal koin tidak boleh dianggap topik industri
    ("koin ai apa yang bagus", False), ("token ai murah", False),
    # tanpa penanda topik / tanpa kata "ai" sama sekali
    ("halo", False), ("analisa sol", False), ("pakai yang mana", False),
])
def test_topik_ai(pesan, harap):
    assert bot.topik_ai(pesan.lower()) is harap


# ---------------------------------------------------------------- rakit_chat

def _muat_chat_md():
    with open(os.path.join(AKAR, "cloud", "prompts", "chat.md"), encoding="utf-8") as f:
        return f.read()


def _blok_aktif(hasil, semua_blok, teks_asli):
    """Blok mana yang isinya benar-benar ikut ke prompt."""
    aktif = set()
    for nama, _, isi in bot._BLOK_RE.findall(teks_asli):
        penanda = isi.strip().split("\n")[0][:60]
        if penanda and penanda in hasil:
            aktif.add(nama)
    return aktif


@pytest.mark.parametrize("pesan,harus_ada,harus_tidak_ada", [
    # Pertanyaan gold TIDAK boleh menyeret aturan 13F & riset X — inilah yang dijaga
    # setelah gagal-aman diubah dari biner jadi berkelompok.
    ("apa dampaknya ke harga gold?", {"gold", "makro"}, {"institusi", "x-twitter"}),
    ("prospek saham nvda gimana", {"saham-forex"}, {"institusi", "x-twitter", "gold"}),
    # Sapaan & konseptual: tidak perlu aturan domain sama sekali
    ("halo", set(), {"gold", "makro", "institusi", "x-twitter", "saham-forex"}),
    ("apa itu RAG?", set(), {"gold", "institusi", "x-twitter"}),
])
def test_rakit_chat_blok(pesan, harus_ada, harus_tidak_ada):
    teks = _muat_chat_md()
    semua = [n for n, _, _ in bot._BLOK_RE.findall(teks)]
    hasil = bot.rakit_chat(teks, pesan)
    aktif = _blok_aktif(hasil, semua, teks)
    assert harus_ada <= aktif, f"blok hilang: {harus_ada - aktif}"
    bocor = harus_tidak_ada & aktif
    assert not bocor, f"blok tidak relevan ikut termuat: {bocor}"


def test_rakit_chat_gagal_aman_masih_ada():
    """Kalau menyentuh kosakata pasar tapi tak ada rumpun yang cocok, SEMUA blok dimuat.

    Ini jaring pengaman terakhir; kehilangan aturan lebih merugikan daripada boros token.
    """
    teks = _muat_chat_md()
    hasil = bot.rakit_chat(teks, "menurutmu pasar gimana")
    semua = [n for n, _, _ in bot._BLOK_RE.findall(teks)]
    assert len(_blok_aktif(hasil, semua, teks)) == len(semua)


# ------------------------------------------------------- _digit & _cocok_angka

@pytest.mark.parametrize("a,b", [
    ("1.864,32", "1864.32194"),      # pemisah ribuan/desimal berbeda, digit sama
    ("$4.399", "4399"),
    ("35,9", "359"),
])
def test_digit_menyamakan_format(a, b):
    assert bot._digit(a) == bot._digit(b)[:len(bot._digit(a))]


@pytest.mark.parametrize("ditulis,mentah,cocok", [
    ("358", "35853160", True),        # dipotong
    ("359", "35853160", True),        # DIBULATKAN ke atas — ini yang dulu tertandai palsu
    ("4399", "43997", True),
    ("999", "35853160", False),       # benar-benar beda
    ("12345", "999", False),
])
def test_cocok_angka(ditulis, mentah, cocok):
    assert bot._cocok_angka(ditulis, mentah) is cocok


# ---------------------------------------------------------------- audit_angka

BRIEF_CONTOH = """[TEKNIKAL]
close: 4399.7
ema21: 4281.5
rsi14: 58.3
[MAKRO]
fed funds: 3.63
"""


def test_audit_angka_baik_kalau_dari_brief():
    balasan = ("Harga $4.399,7 di atas EMA21 $4.281,5. RSI 58,3 netral. "
               "Fed funds 3,63%.")
    hasil = bot.audit_angka(BRIEF_CONTOH, balasan)
    assert "BAIK" in hasil, hasil


def test_audit_angka_mencurigakan_kalau_dikarang():
    balasan = ("Harga $7.123 dengan EMA21 $6.888. RSI 91,4. Volume $55.321 juta. "
               "Market cap $88.777. Funding 12,5%. Holder 66.543. TVL $99.111.")
    hasil = bot.audit_angka(BRIEF_CONTOH, balasan)
    assert "MENCURIGAKAN" in hasil, hasil


def test_audit_angka_tanpa_brief_tidak_error():
    assert bot.audit_angka(None, "apa pun") is None


# ------------------------------------------------------ memori.masalah_privasi

@pytest.mark.parametrize("teks", [
    "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",          # alamat EVM
    "dompet saya 0xAbC1234567890123456789012345678901234567",
    "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",        # kemungkinan Solana
    "saldo saya 12,5 ETH",
])
def test_privasi_menolak(teks):
    assert memori.masalah_privasi(teks), f"seharusnya ditolak: {teks}"


@pytest.mark.parametrize("teks", [
    "BTC ditutup di $64.978 pada 8 Agustus 2026",
    "BlackRock memegang sekitar 750.000 BTC lewat IBIT",
    "EMA21 harian SOL ada di $148,2",
    "Fed funds rate 3,63% per 5 Agustus 2026",
    "sektor AI sedang ramai karena rilis model baru",
])
def test_privasi_tidak_terlalu_galak(teks):
    """Penyaring yang kelewat galak diam-diam membuang fakta yang sah."""
    assert not memori.masalah_privasi(teks), f"seharusnya LOLOS: {teks}"


# ------------------------------------------- fungsi baru: bobot, rumpun, deteksi aset

@pytest.mark.parametrize("pesan,ada_konteks,tingkat", [
    ("halo", False, "RINGAN"),
    ("terima kasih", False, "RINGAN"),
    ("apa itu RAG?", False, "RINGAN"),
    # butuh menjalankan indicators.py — kalau kebagian 8 putaran, balasannya bisa
    # terpotong DIAM-DIAM tanpa error
    ("rsi eth di daily berapa?", False, "SEDANG"),
    ("gold di atas ema21?", False, "SEDANG"),
    ("apa dampaknya ke harga gold?", False, "SEDANG"),
    # konteks MENURUNKAN bobot, bukan menaikkan
    ("jadi gambaranmu bagaimana?", True, "RINGAN"),
    ("bandingkan prospek sol dan sui", False, "BERAT"),
    ("jelaskan lebih detail", False, "BERAT"),
])
def test_bobot_chat(pesan, ada_konteks, tingkat):
    _, _, _, label = bot.bobot_chat(pesan, ada_konteks)
    assert label.startswith(tingkat), label


@pytest.mark.parametrize("pesan,jenis,simbol", [
    ("rsi eth di daily berapa?", "crypto", "ETH"),
    ("apa dampaknya ke harga gold?", "forex", "GC=F"),
    ("emas lagi naik ya", "forex", "GC=F"),
    ("gimana eurusd sekarang", "forex", "EURUSD"),
    ("prospek saham nvda gimana", "saham", "NVDA"),
    ("$ADA gimana", "crypto", "ADA"),
    # kata Indonesia yang kebetulan sama dengan ticker TIDAK boleh tertangkap
    ("koin ada gimana", None, None),
    ("halo", None, None),
    ("apa itu RAG?", None, None),
    ("analisis sektor ai", None, None),
])
def test_aset_dari_pesan(pesan, jenis, simbol):
    assert bot.aset_dari_pesan(pesan) == (jenis, simbol)


# ------------------------------------------------------------ peringatan audit

@pytest.mark.parametrize("jejak,asal,segar,penggal", [
    # hanya SATU yang muncul, yang paling parah
    ("MENCURIGAKAN", "⚠️ ADA DATA CLOSE-ONLY · DATA BASI (>48 jam)", "BURUK", "penutupan"),
    ("MENCURIGAKAN", "DATA BASI (>48 jam)", "OK", "kulacak"),
    ("BAIK", "DATA BASI (>48 jam)", "OK", "48 jam"),
    ("BAIK", "sumber=kraken", "kesegaran: BURUK — 12 angka", "tanpa satu pun tanggal"),
    # PERIKSA sengaja TIDAK memicu peringatan ke user
    ("PERIKSA — 20% tidak terlacak", "sumber=kraken", "OK", None),
    ("BAIK", "sumber=kraken", "OK", None),
])
def test_peringatan_audit(jejak, asal, segar, penggal):
    hasil = bot.peringatan_audit(jejak, asal, segar)
    if penggal is None:
        assert hasil is None, hasil
    else:
        assert hasil and penggal in hasil, hasil


def test_peringatan_disisipkan_sebelum_disclaimer():
    body = "SKOR 58/100\n\n⚠️ Riset pasar berbasis data, bukan saran keuangan. DYOR."
    hasil = bot.sisipkan_peringatan(body, "⚠️ PERINGATAN UJI")
    baris = [b for b in hasil.split("\n") if b.strip()]
    assert baris.index("⚠️ PERINGATAN UJI") < baris.index(
        "⚠️ Riset pasar berbasis data, bukan saran keuangan. DYOR.")


# ------------------------------------------------------------------ angka_kunci

def test_angka_kunci_menangkap_yang_penting():
    teks = ("Gold $4.365 saat ini, di atas EMA21 $4.281 di daily. RSI 58,3 netral. "
            "Skor 62/100. Naik 2,4% pekan ini.")
    hasil = bot.angka_kunci(teks)
    gabung = " ".join(hasil)
    assert "4.365" in gabung and "58,3" in gabung and "2,4%" in gabung
    assert len(hasil) <= bot._ANGKA_MAKS


def test_angka_kunci_kosong_aman():
    assert bot.angka_kunci("") == []
    assert bot.angka_kunci(None) == []


# ---------------------------------------------- perbandingan MULTI-ASET (bug nyata)

@pytest.mark.parametrize("pesan", [
    "bandingkan prospek sol dan sui",
    "sol vs eth bagusan mana",
    "btc dan gold gimana",
    "mending eurusd atau gbpusd",
])
def test_multi_aset_tidak_dikumpulkan(pesan):
    """Pertanyaan PERBANDINGAN tidak boleh menghasilkan brief satu-aset.

    Bug yang ditemukan tes ini: brief hanya berisi aset PERTAMA, lalu angka aset kedua
    otomatis tertandai "tidak terlacak" oleh audit_angka dan memicu peringatan PALSU ke
    user. Peringatan yang salah menyala membuat orang berhenti membaca peringatan.
    """
    assert bot.aset_dari_pesan(pesan) == (None, None)


def test_satu_aset_tetap_dikumpulkan():
    """Penjaga multi-aset tidak boleh ikut mematikan kasus satu aset."""
    assert bot.aset_dari_pesan("rsi eth di daily berapa?") == ("crypto", "ETH")
    assert bot.aset_dari_pesan("apa dampaknya ke harga gold?") == ("forex", "GC=F")


# --------------------------------------------------------------- rapor (T7)

import rapor  # noqa: E402

_BALASAN_LENGKAP = """🧮 SKOR 62/100  (Fund 58 - Tek 65)

🎯 BIAS SPOT: TAHAN

Harga $4.399,7 - EMA21 harian $4.281,5 - RSI harian 58

Invalid $4.230  (tesis gugur bila close di bawah ini)
Target  $4.520 - $4.680 - $4.850
"""


def test_rapor_urai_panggilan_lengkap():
    p = rapor.urai_panggilan(_BALASAN_LENGKAP)
    assert p["bias"] == "TAHAN"
    assert p["skor"] == 62
    assert p["harga_saat_panggilan"] == 4399.7
    assert p["level_invalid"] == 4230.0
    assert p["level_target"] == [4520.0, 4680.0, 4850.0]


@pytest.mark.parametrize("rusak", [
    _BALASAN_LENGKAP.replace("Harga $4.399,7", "Harga"),              # tanpa harga
    _BALASAN_LENGKAP.replace("Invalid $4.230", "Invalid")
                    .replace("Target  $4.520 - $4.680 - $4.850", "Target"),  # tanpa level
    "obrolan biasa tanpa bias apa pun",
])
def test_rapor_menolak_panggilan_tak_terukur(rusak):
    """Panggilan tanpa harga ATAU tanpa level TIDAK BISA dinilai — jangan dipaksakan masuk."""
    assert rapor.urai_panggilan(rusak) is None


@pytest.mark.parametrize("teks,nilai", [
    ("4.399,7", 4399.7), ("4399.70", 4399.7), ("$1.234", 1234.0),
    ("64.978", 64978.0), ("0,32", 0.32),
])
def test_rapor_angka_dua_format(teks, nilai):
    assert rapor._angka(teks) == nilai


@pytest.mark.parametrize("bias,status,ret,harap", [
    ("AKUMULASI", "TARGET_KENA", 10.0, True),
    ("AKUMULASI", "INVALID_KENA", -20.0, False),
    ("TAHAN", "MASIH_TERBUKA", 3.0, None),
    # SADAR ARAH: menghindar terbukti benar kalau harganya memang turun.
    # Tanpa ini, panggilan HINDARI yang tepat justru terhitung KALAH.
    ("HINDARI", "INVALID_KENA", -60.0, True),
    ("HINDARI", "TARGET_KENA", 15.0, False),
    ("KURANGI", "MASIH_TERBUKA", -8.0, True),
])
def test_rapor_penilaian_sadar_arah(bias, status, ret, harap):
    e = {"bias": bias, "status": status, "return_30h_persen": ret}
    assert rapor._benar(e) is harap


@pytest.mark.parametrize("skor,kelompok", [
    (10, "0-40"), (40, "0-40"), (41, "41-60"), (60, "41-60"),
    (61, "61-80"), (80, "61-80"), (81, "81-100"), (100, "81-100"), (None, "tanpa skor"),
])
def test_rapor_kelompok_skor(skor, kelompok):
    assert rapor._kelompok_skor(skor) == kelompok


def test_rapor_sampel_kecil_ditandai():
    kecil = [{"bias": "AKUMULASI", "status": "TARGET_KENA", "return_30h_persen": 5.0}]
    assert "peringatan" in rapor._hitung(kecil)


# ------------------------------- audit tidak boleh menyala palsu (bug nyata)

_BRIEF_KECIL = "[TEKNIKAL]\nclose: 148.20\nema21: 145.00\nrsi14: 58"
_STEMPEL = "🕒 Data per 9 Agustus 2026, 12:54 WIB\n\n🧮 SKOR 62/100\n"
_DISCLAIMER = "\n⚠️ Riset pasar berbasis data, bukan saran keuangan."


def test_audit_tidak_menyala_untuk_balasan_jujur():
    """Stempel waktu, penyebut skor, dan disclaimer bukan angka pasar.

    Bug nyata: ketiganya dulu terhitung "tidak terlacak". Pada analisa panjang derau itu
    terencerkan, tapi di mode NGOBROL briefnya kecil sehingga tiga angka ini saja mendorong
    vonis ke MENCURIGAKAN dan memunculkan PERINGATAN PALSU ke user.
    """
    jujur = (_STEMPEL + "Harga $148,20 · EMA21 harian $145,00 · RSI harian 58"
             + _DISCLAIMER)
    vonis = bot.audit_angka(_BRIEF_KECIL, jujur)
    assert "BAIK" in vonis, vonis
    assert bot.peringatan_audit(vonis, None, "OK") is None


def test_audit_tetap_menangkap_karangan():
    """Presisi yang dinaikkan tidak boleh mematikan deteksi yang sebenarnya."""
    karang = (_STEMPEL + "Harga $7.123 · EMA21 $6.888 · RSI 91,4 · Volume $55.321 juta "
              "· Mcap $88.777" + _DISCLAIMER)
    vonis = bot.audit_angka(_BRIEF_KECIL, karang)
    assert "MENCURIGAKAN" in vonis, vonis
    assert bot.peringatan_audit(vonis, None, "OK") is not None


# ---------------------------------------- rapor: horizon & tolok ukur (bug nyata)

def _entri(umur_hari, bias="AKUMULASI"):
    from datetime import datetime, timedelta, timezone
    t = datetime.now(timezone.utc) - timedelta(days=umur_hari)
    return {"aset": "BTC", "jenis": "crypto", "bias": bias,
            "tanggal_utc": t.strftime("%Y-%m-%d %H:%M"),
            "harga_saat_panggilan": 100.0, "level_invalid": 1.0,
            "level_target": [9999999.0]}


def _candle_naik(hari, awal=100.0, per_hari=0.5):
    """Candle harian sintetis yang naik tetap — supaya tesnya tidak menyentuh jaringan."""
    from datetime import datetime, timedelta, timezone
    mulai = datetime.now(timezone.utc) - timedelta(days=hari)
    keluar = []
    for i in range(hari + 1):
        h = awal * (1 + per_hari / 100) ** i
        ts = int((mulai + timedelta(days=i)).timestamp() * 1000)
        keluar.append([ts, h, h, h, h, 0])
    return keluar


def test_rapor_horizon_belum_penuh_tidak_dilaporkan(monkeypatch):
    """Panggilan berumur 20 hari TIDAK boleh melaporkan return 30 & 90 hari.

    Bug nyata: dulu return 20 hari diberi label return_30h dan return_90h, lalu masuk ke
    kalibrasi ambang skor sebagai data sah.
    """
    monkeypatch.setattr(rapor, "_riwayat_harga", lambda a, j: (_candle_naik(20), None))
    h = rapor.nilai_satu(_entri(20))
    assert h.get("return_7h_persen") is not None
    assert h.get("return_30h_persen") is None
    assert h.get("return_90h_persen") is None


def test_rapor_tolok_ukur_mengukur_sesuatu(monkeypatch):
    """Tolok ukur harus MEMBANDINGKAN, bukan menyalin return panggilan itu sendiri.

    Bug nyata: versi lama menyalin return-nya sendiri sebagai "tolok ukur", sehingga
    selisihnya selalu nol dan tidak mengukur apa pun.
    """
    monkeypatch.setattr(rapor, "_riwayat_harga", lambda a, j: (_candle_naik(100), None))
    ikut = rapor.nilai_satu(_entri(100, "AKUMULASI"))
    hindar = rapor.nilai_satu(_entri(100, "HINDARI"))
    # Pasar naik: memegang = ikut arus (selisih 0), menghindar = tertinggal (selisih negatif)
    assert ikut["selisih_vs_beli_tahan"] == 0.0
    assert hindar["selisih_vs_beli_tahan"] < 0
    assert hindar["beli_dan_tahan_persen"] > 0
    assert hindar["hasil_ikut_saran_persen"] == 0.0


# --------------------------------- makro: jendela persentil sesuai frekuensi seri

def test_makro_jendela_persentil_dari_tanggal():
    """NFCI itu MINGGUAN. Jendela berbasis jumlah titik membuatnya 14,5 tahun, bukan 3.

    Diuji tanpa jaringan: data sintetis mingguan selama 10 tahun, jendela harus
    memuat kira-kira 3 tahun saja.
    """
    import makro
    from datetime import datetime, timedelta
    mulai = datetime(2016, 1, 1)
    data = [((mulai + timedelta(weeks=i)).strftime("%Y-%m-%d"), float(i))
            for i in range(520)]                      # 10 tahun mingguan
    item = makro.olah("NFCI", "uji", "indeks", "harian", data)
    j = item.get("jendela_persentil") or ""
    assert j, item
    awal, akhir = j.split(" (")[0].split(" s/d ")
    rentang = (datetime.strptime(akhir, "%Y-%m-%d")
               - datetime.strptime(awal, "%Y-%m-%d")).days / 365.25
    assert 2.5 <= rentang <= 3.5, f"jendela {rentang:.1f} tahun, seharusnya ~3"



# ============================================================================
# KELAS BUG: angka SALAH berlabel BENAR
#
# Tes di atas sebagian besar menguji BENTUK keluaran. Tiga bug berturut-turut lolos
# darinya karena yang salah adalah NILAI-nya terhadap waktu & frekuensi data — bukan
# strukturnya. Blok ini menguji kebenaran nilainya, dengan data sintetis yang lubangnya
# dibuat sengaja, sehingga tidak menyentuh jaringan.
# ============================================================================

def test_makro_yoy_menolak_periode_yang_hilang():
    """Deret resmi pun berlubang: CPI Oktober 2025 tidak ada di FRED (rilis tertunda).

    Bug nyata: data[-13] lalu mendarat 13 bulan lalu dan tetap dilaporkan sebagai
    yoy_persen. Inflasi tahunan adalah angka utama untuk analisa emas.
    """
    import makro
    data = []
    for tahun, bulan in [(2025, m) for m in range(1, 13)] + [(2026, m) for m in range(1, 7)]:
        if (tahun, bulan) == (2025, 10):
            continue                                   # LUBANG yang disengaja
        data.append((f"{tahun}-{bulan:02d}-01", 100.0 + len(data)))
    item = makro.olah("CPIAUCSL", "uji", "indeks", "bulanan", data)
    # Juni 2026 vs Juni 2025 ADA keduanya -> YoY harus terhitung dan TIDAK meleset
    assert item["yoy_persen"] is not None
    juni25 = dict((t[:7], v) for t, v in data)["2025-06"]
    juni26 = dict((t[:7], v) for t, v in data)["2026-06"]
    assert item["yoy_persen"] == round((juni26 - juni25) / juni25 * 100, 2)


def test_makro_yoy_kosong_kalau_pembanding_tidak_ada():
    """Kalau periode pembandingnya memang hilang, jangan dihitung dari yang terdekat."""
    import makro
    data = [("2026-05-01", 100.0), ("2026-06-01", 101.0)]     # tidak ada 2025-06
    item = makro.olah("CPIAUCSL", "uji", "indeks", "bulanan", data)
    assert item["yoy_persen"] is None
    assert "catatan_yoy_persen" in item


def test_makro_perubahan_30h_benar_untuk_seri_mingguan():
    """Mundur 22 TITIK hanya benar untuk seri harian.

    Bug nyata: pada seri MINGGUAN (klaim pengangguran, NFCI) itu berarti 147 hari, tapi
    tetap dilaporkan sebagai perubahan_30h_persen.
    """
    import makro
    from datetime import datetime, timedelta
    mulai = datetime(2026, 1, 1)
    data = [((mulai + timedelta(weeks=i)).strftime("%Y-%m-%d"), 100.0 + i) for i in range(60)]
    item = makro.olah("ICSA", "uji", "orang", "harian", data)
    jarak = (datetime.strptime(item["tanggal_data"], "%Y-%m-%d")
             - datetime.strptime(item["tanggal_pembanding"], "%Y-%m-%d")).days
    assert 28 <= jarak <= 37, f"pembanding {jarak} hari, seharusnya sekitar 30"


def test_onchain_tren_menyebut_rentang_sebenarnya():
    """Label periode harus mengikuti jendela yang benar-benar dipakai."""
    import onchain
    t = onchain.tren([100.0 + i for i in range(35)], 35)
    assert t["rentang_hari"] == 35
    assert t["titik_dipakai"] == 35


def test_onchain_tren_menolak_pembagi_nol():
    """Nilai awal 0 tidak bisa dijadikan dasar persentase — kembalikan None, jangan 0."""
    import onchain
    assert onchain.tren([0.0] + [float(i) for i in range(1, 35)], 35) is None



# ------------------------------------------------------- T6: konteks & earnings

def test_konteks_pemetaan_sic_tidak_menebak():
    """Kode SIC di luar peta harus DILAPORKAN, bukan dicocokkan ke sektor terdekat.

    Pembanding sektor yang salah lebih menyesatkan daripada mengaku tidak tahu.
    """
    import konteks
    ketemu = [etf for (a, b), etf, _ in konteks.SIC_KE_SEKTOR if a <= 3674 <= b]
    assert ketemu == ["XLK"], ketemu            # semikonduktor -> teknologi
    assert not [etf for (a, b), etf, _ in konteks.SIC_KE_SEKTOR if a <= 9999 <= b]


def test_konteks_semua_etf_dikenali():
    """Tiap ETF di peta SIC harus punya nama sektor — kalau tidak, keluarannya bolong."""
    import konteks
    for _, etf, _ in konteks.SIC_KE_SEKTOR:
        assert etf in konteks.SEKTOR, etf


def test_konteks_tutup_pada_berbasis_tanggal():
    """Mundur sekian CANDLE tidak setara antar simbol karena libur bursa berbeda."""
    import konteks
    hari = 86400
    akhir = 1_700_000_000
    # candle harian dengan satu lubang panjang (libur) di tengah
    candles = [[(akhir - n * hari) * 1000, 0, 0, 0, 100.0 + n, 0]
               for n in range(120, -1, -1) if not (40 < n < 60)]
    harga, tgl = konteks._tutup_pada(candles, 30)
    assert harga is not None and tgl
    from datetime import datetime, timezone
    jarak = (akhir - datetime.strptime(tgl, "%Y-%m-%d")
             .replace(tzinfo=timezone.utc).timestamp()) / 86400
    assert 29 <= jarak <= 36, f"{jarak} hari, seharusnya sekitar 30"


def test_earnings_tanpa_kunci_tidak_mati(monkeypatch):
    """Pola kunci opsional: laporkan tidak tersedia, JANGAN mematikan analisa."""
    import earnings
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    data, cache, err = earnings.ambil("/stock/peers", {"symbol": "NVDA"}, "uji")
    assert data is None and err and "kosong" in err


def test_stockfund_turunan_menuntut_periode_sama():
    """Arus kas bebas menuntut arus kas operasi DAN capex dari periode yang SAMA.

    Memasangkan komponen dari periode berbeda menghasilkan angka yang terlihat wajar
    tapi salah — kelas kesalahan yang tidak pernah ketahuan dari log.
    """
    import stockfund
    assert "capex" in stockfund.METRIK
    assert "laba_kotor" in stockfund.METRIK
    assert "beban_bunga" in stockfund.METRIK



# ------------------------------------------------------------ T8: kebersihan

def test_chat_id_tidak_disimpan_polos(monkeypatch):
    """Repo ini PUBLIK. Chat ID adalah identifier akun Telegram.

    memori.py sudah menolak alamat dompet & saldo di level kode, tapi chat ID sempat lolos.
    """
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-uji")
    h = bot._id_chat("7525096497")
    assert h != "7525096497"
    assert not h.isdigit()
    assert len(h) == 16
    assert bot._id_chat("7525096497") == h          # deterministik dalam satu garam


def test_chat_id_bergaram(monkeypatch):
    """Tanpa garam, sha256 dari ~10 digit praktis sama dengan menyimpannya polos."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-A")
    a = bot._id_chat("7525096497")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-B")
    assert bot._id_chat("7525096497") != a


def test_label_eth_terbaca_dari_gz():
    """Berkas label 1,94 MB adalah yang TERBESAR di repo dan ikut ditarik tiap checkout."""
    import investors
    import wallet
    a, b = investors.load_labels(), wallet.load_labels()
    assert len(a) > 20000, len(a)
    assert len(a) == len(b)


def test_berkas_besar_tidak_masuk_repo():
    """Penjaga agar berkas mentah 2 MB tidak diam-diam kembali."""
    import os
    assert not os.path.exists(os.path.join(AKAR, "cloud", "data", "eth_labels.json"))
    assert os.path.exists(os.path.join(AKAR, "cloud", "data", "eth_labels.json.gz"))



def test_berkas_riwayat_tidak_memuat_id_polos():
    """Penjaga CI: chat ID polos tidak boleh diam-diam kembali ke repo publik.

    Menguji BERKAS-nya, bukan fungsinya — satu run yang berjalan dengan kode lama sudah
    cukup untuk menaruh identifier akun ke dalam repo, dan itu tidak akan terlihat dari
    tes yang hanya memanggil _id_chat().
    """
    import json
    import os
    p = os.path.join(AKAR, "cloud", "data", "percakapan.json")
    if not os.path.exists(p):
        return
    with open(p, encoding="utf-8") as f:
        riwayat = json.load(f)
    polos = [str(r.get("chat")) for r in riwayat if str(r.get("chat", "")).isdigit()]
    assert not polos, f"chat ID polos di repo publik: {polos}"


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


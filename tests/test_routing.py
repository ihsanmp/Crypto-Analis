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

import json
import os
import re
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import bot_oneshot as bot          # noqa: E402
import memori                      # noqa: E402

N = chr(10)      # newline, dipakai membangun contoh balasan multi-baris


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
    """Persentase SENGAJA tidak lagi diambil — tanpa subjeknya, "2,4%" tidak bermakna
    saat dibaca ulang di giliran berikutnya, dan slot 8 lebih berguna untuk harga & level."""
    teks = ("Gold $4.365 saat ini, di atas EMA21 $4.281 di daily. RSI 58,3 netral. "
            "Skor 62/100. Naik 2,4% pekan ini.")
    hasil = bot.angka_kunci(teks)
    gabung = " ".join(hasil)
    assert "harga=4.365" in gabung
    assert "ema21=4.281" in gabung
    assert "rsi=58,3" in gabung
    assert "skor=62" in gabung
    assert len(hasil) <= bot._ANGKA_MAKS


def test_angka_kunci_tidak_memungut_mcap_volume_atau_btc():
    """Bug NYATA dari riwayat produksi: angka kunci PUMP berisi harga=37,6 & harga=14,72

    (itu MCAP dan VOLUME), plus harga BTC dari baris pasar — sementara harga koin yang
    dianalisa tenggelam. MODE PENDAPAT bersandar pada angka ini untuk menjawab pertanyaan
    lanjutan, jadi angka yang salah di sini menjadi jawaban yang salah di sana.
    """
    teks = ("📊 PASAR" + N + "BTC $64.978 · Dominasi 59,0%" + N + N +
            "Mcap $37,6 juta · Volume 24j $14,72 juta" + N +
            "Harga $0,002683 · EMA21 harian $0,002084 · RSI harian 66")
    hasil = bot.angka_kunci(teks)
    gabung = " ".join(hasil)
    assert "harga=0,002683" in gabung, hasil
    for salah in ("64.978", "37,6", "14,72"):
        assert salah not in gabung, f"{salah} seharusnya tidak ikut: {hasil}"


def test_angka_kunci_rsi_bukan_timeframe():
    """Bug NYATA: "RSI 4H 75,8" menghasilkan rsi=4 — angka timeframe, bukan nilainya."""
    hasil = bot.angka_kunci("EMA21 4H $0,002404 · RSI 4H 75,8")
    assert "rsi=75,8" in hasil, hasil
    assert "rsi=4" not in hasil, hasil
    assert "ema21=0,002404" in hasil, hasil


def test_angka_kunci_harga_inline_mode_ngobrol():
    """Mode ngobrol menulis harga di tengah kalimat, bukan di awal baris."""
    hasil = bot.angka_kunci(
        "Entry $0,002551 kamu profit tipis — harga 4H terakhir $0,002683, sekitar +5%.")
    assert "harga=0,002683" in hasil, hasil


@pytest.mark.parametrize("pesan,tingkat", [
    ("kalo buy pump di 0.002551 bagaimana menurutmu?", "SEDANG"),
    ("worth nggak masuk eth di 2400?", "SEDANG"),
    ("bagusnya beli sol di 140 apa tunggu?", "SEDANG"),
    ("kalo cut loss di 0.0021 gimana?", "SEDANG"),
    ("jadi gambaranmu bagaimana?", "RINGAN"),
    ("menurutmu gimana?", "RINGAN"),
])
def test_keputusan_transaksi_butuh_data_segar(pesan, tingkat):
    """Bug NYATA: "kalo buy pump di 0.002551 bagaimana menurutmu?" jatuh ke tingkat RINGAN

    — 8 putaran, tanpa shell, tanpa brief — karena kata "menurutmu" dianggap penafsiran
    lanjutan. Jawabannya lalu bersandar pada angka giliran SEBELUMNYA untuk sebuah
    keputusan beli. Niat transaksi + harga konkret selalu butuh data segar.
    """
    assert bot.bobot_chat(pesan, True)[3].startswith(tingkat)


def test_aset_terdeteksi_dari_niat_transaksi():
    """Ticker di luar daftar terbatas tidak pernah mendapat brief. Pola "buy <TOKEN>"

    menyebut asetnya secara eksplisit, jadi cukup aman diambil.
    """
    assert bot.aset_dari_pesan("kalo buy pump di 0.002551 gimana?") == ("crypto", "PUMP")
    assert bot.aset_dari_pesan("halo apa kabar") == (None, None)


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


# ------------------------------------------- sapuan ke-4: konkurensi & cache

def test_rapor_id_unik_dalam_detik_yang_sama(tmp_path, monkeypatch):
    """Id harus unik.

    Dengan detik saja, dua panggilan untuk aset yang sama dalam detik yang sama
    menghasilkan id IDENTIK — membuat pembaruan status di nilai() ambigu, dan janji
    "koreksi lewat entri baru yang merujuk id lama" mustahil dipenuhi.
    """
    monkeypatch.setattr(rapor, "RAPOR_PATH", str(tmp_path / "r.jsonl"))
    balasan = ("🎯 BIAS SPOT: TAHAN\nHarga $100\nInvalid $90\nTarget $120")
    ids = [rapor.catat(balasan, "BTC", "crypto") for _ in range(30)]
    assert len(set(ids)) == 30, f"hanya {len(set(ids))} id unik dari 30"


def test_sec_tickers_menyimpan_nama_bukan_hanya_cik():
    """Cache yang hanya menyimpan CIK membuat nama emiten HILANG diam-diam.

    Regresi nyata saat cache diperkenalkan: pemanggil lama mengambil nama dari respons
    yang sama, jadi setelah dialihkan ke cache kolom namanya kosong tanpa error apa pun.
    """
    import sec_tickers
    peta, _, _err = sec_tickers.peta_ticker()
    if not peta:
        return                       # jaringan tidak tersedia: lewati
    rekam = peta.get("NVDA")
    assert rekam and rekam.get("cik") and rekam.get("nama"), rekam


# ------------------------------- sapuan ke-5: data produksi & format saham

def test_rapor_tidak_menyusut_dari_commit_sebelumnya():
    """Penjaga: catatan panggilan TIDAK BOLEH berkurang.

    Sudah terjadi DUA KALI dalam sesi ini bahwa skrip uji ad-hoc menghapus berkas data
    lalu terbawa `git add -A`: berkas cache Windows ikut ter-commit, dan rapor.jsonl
    terpangkas dari 3 entri jadi 0 sehingga tiga panggilan produksi hilang permanen.
    Rapor bersifat append-only; menyusut berarti ada yang terhapus tanpa sengaja.
    """
    import subprocess
    p = os.path.join(AKAR, "cloud", "data", "rapor.jsonl")
    if not os.path.exists(p):
        return
    with open(p, encoding="utf-8") as f:
        sekarang = sum(1 for baris in f if baris.strip().startswith("{"))
    try:
        lama = subprocess.run(["git", "show", "HEAD:cloud/data/rapor.jsonl"],
                              cwd=AKAR, capture_output=True, text=True, timeout=30)
    except Exception:
        return                                   # git tidak tersedia: lewati
    if lama.returncode != 0:
        return                                   # belum pernah di-commit
    sebelum = sum(1 for baris in lama.stdout.split(chr(10))
                  if baris.strip().startswith("{"))
    assert sekarang >= sebelum, (
        f"rapor menyusut {sebelum} -> {sekarang} entri — ada panggilan yang terhapus")


def test_audit_mengecualikan_rencana_kedua_format():
    """Judul bagian rencana BERBEDA antar prompt: analisa.md menulis "RENCANA SPOT",

    analisa_pasar.md hanya "RENCANA". Pola lama hanya mengenali yang pertama, sehingga pada
    analisa SAHAM & FOREX seluruh level turunan (entry, invalidasi, target) ikut dinilai dan
    balasan yang jujur divonis MENCURIGAKAN 83% — lalu memicu peringatan palsu ke user.
    """
    brief = "[TEKNIKAL]" + N + "close: 313.33" + N + "rsi14: 52"
    inti = ("🧮 SKOR 54/100" + N + "🎯 BIAS: TAHAN" + N +
            "Harga $313,33 · RSI harian 52" + N + N)
    rencana = ("Entry   bertahap di $300–305" + N + "Invalid $291,00" + N +
               "Target  $340,00 → $365,00" + N)
    for judul in ("🧭 RENCANA" + N, "🧭 RENCANA SPOT" + N):
        vonis = bot.audit_angka(brief, inti + judul + rencana)
        assert "BAIK" in vonis, f"{judul.strip()}: {vonis}"
        assert bot.peringatan_audit(vonis, None, "OK") is None


@pytest.mark.parametrize("baris,harap", [
    ("Target  $165,00 → $180,00 → $195,00", [165.0, 180.0, 195.0]),
    ("Target  $340,00 → $365,00", [340.0, 365.0]),
    ("Target $120", [120.0]),
    ("Target  $120 -> $140", [120.0, 140.0]),
])
def test_rapor_target_semua_format_resmi(baris, harap):
    """Target harus terbaca dari format analisa.md MAUPUN analisa_pasar.md."""
    teks = "🎯 BIAS SPOT: TAHAN" + N + "Harga $100" + N + "Invalid $90" + N + baris
    assert rapor.urai_panggilan(teks)["level_target"] == harap



def test_audit_kesegaran_tidak_ditutupi_stempel_sendiri():
    """pastikan_bertanggal() menyisipkan tanggal buatan kita SENDIRI.

    Kalau audit kesegaran berjalan sesudah itu, ia selalu melihat tanggal dan memvonis OK —
    sehingga vonis BURUK ("angka tanpa satu pun tanggal") mustahil menyala, padahal justru
    itu yang menandai jawaban dari ingatan. Bug nyata: tingkat peringatan keempat praktis
    kode mati sampai urutannya diperbaiki.
    """
    tanpa = "Harga $64.978 dengan RSI 58 dan volume 12.345 juta."
    assert "BURUK" in bot.audit_kesegaran(tanpa)
    assert "BURUK" not in bot.audit_kesegaran(bot.pastikan_bertanggal(tanpa))


def test_urutan_audit_sebelum_stempel_di_kode():
    """Penjaga urutan: audit_kesegaran harus dipanggil SEBELUM pastikan_bertanggal."""
    with open(os.path.join(AKAR, "cloud", "bot_oneshot.py"), encoding="utf-8") as f:
        kode = f.read()
    for potong in ("kesegaran = audit_kesegaran(body)",
                   "kesegaran_foto = audit_kesegaran(body)"):
        i = kode.index(potong)
        j = kode.index("pastikan_bertanggal(body)", max(0, i - 900))
        assert i < j, f"{potong}: stempel dipasang sebelum audit"



# ------------------------------- sapuan ke-6: observabilitas & penilaian saham

def test_rapor_menjelaskan_kalau_belum_bisa_dinilai(monkeypatch):
    """Panggilan yang belum punya candle baru harus MENJELASKAN DIRI, bukan diam.

    Bug nyata: panggilan saham dibuat saat bursa tutup tidak punya candle sesudahnya, dan
    nilai_satu mengembalikan None — entrinya tetap TERBUKA dengan seluruh field kosong dan
    tanpa catatan apa pun, tidak bisa dibedakan dari kegagalan penilaian sesungguhnya.
    """
    from datetime import datetime, timedelta, timezone
    lampau = datetime.now(timezone.utc) - timedelta(days=3)
    candle = [[int(lampau.timestamp() * 1000), 100.0, 100.0, 100.0, 100.0, 0]]
    monkeypatch.setattr(rapor, "_riwayat_harga", lambda a, j: (candle, None))
    entri = {"aset": "NVDA", "jenis": "saham", "bias": "AKUMULASI",
             "tanggal_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
             "harga_saat_panggilan": 100.0, "level_invalid": 90.0, "level_target": [120.0]}
    hasil = rapor.nilai_satu(entri)
    assert hasil is not None
    assert "belum ada candle" in hasil.get("catatan_penilaian", "")


def test_timing_per_script_tetap_dicatat():
    """Penjaga observabilitas: durasi tiap script harus dicetak.

    Timing per-script sempat HILANG saat pengumpulan data diparalelkan — padahal itulah
    yang dulu membongkar makro.py 65 detik dan stockfund.py 58 detik di runner.
    """
    with open(os.path.join(AKAR, "cloud", "bot_oneshot.py"), encoding="utf-8") as f:
        kode = f.read()
    assert "_jalankan_terukur" in kode
    assert kode.count("pool.submit(_jalankan_terukur") >= 2, (
        "kedua pengumpul (crypto & pasar) harus memakai pembungkus terukur")



# ------------------------------------- sapuan ke-7: Worker & berkas yang di-commit

def _worker():
    with open(os.path.join(AKAR, "deploy", "cloudflare-worker.js"), encoding="utf-8") as f:
        return f.read()


def test_worker_tidak_membocorkan_chat_id():
    """Endpoint GET Worker TERBUKA tanpa autentikasi.

    Bug nyata: ia mencetak nilai ALLOWED_CHAT_IDS apa adanya — identifier akun Telegram
    yang justru repot-repot di-hash keluar dari repo publik di T8. Komentar di kodenya
    sendiri sudah menyatakan "tidak pernah nilainya", tapi barisnya melanggar itu.
    """
    js = _worker()
    assert "ALLOWED_CHAT_IDS: env.ALLOWED_CHAT_IDS ||" not in js, (
        "nilai ALLOWED_CHAT_IDS dicetak apa adanya di endpoint publik")
    assert "terisi (" in js, "seharusnya hanya melaporkan jumlahnya"


def test_worker_gagal_tertutup():
    """Daftar chat KOSONG harus menolak semua, bukan melayani semua.

    Versi lama: `if (allowed.length && ...)` — satu salah konfigurasi diam-diam membuka
    bot ke siapa pun yang menemukan webhook-nya.
    """
    js = _worker()
    assert "if (!allowed.length || !allowed.includes(chatId))" in js
    assert "if (allowed.length && !allowed.includes(chatId))" not in js


def test_berkas_besar_disimpan_terkompresi():
    """Berkas yang di-commit ikut ditarik SETIAP checkout, termasuk run yang tidak

    membutuhkannya. Peta ticker SEC ~669 KB mentah; versi .gz 180 KB.
    """
    data = os.path.join(AKAR, "cloud", "data")
    for mentah in ("eth_labels.json", "sec_tickers_cache.json"):
        assert not os.path.exists(os.path.join(data, mentah)), (
            f"{mentah} mentah tidak boleh ikut ter-commit")
        assert os.path.exists(os.path.join(data, mentah + ".gz")), (
            f"{mentah}.gz tidak ditemukan")



# ----------------------------- dilaporkan user: tanggal singkat & rencana vs posisi

@pytest.mark.parametrize("teks", [
    "9 Agustus 2026", "9 Agu 2026", "9 Ags 2026", "1 Sept 2026",
    "3 Des 2026", "17 Jul 2026", "2026-08-09", "Agustus 2026",
])
def test_tanggal_singkatan_bulan_dikenali(teks):
    """Model kerap menulis "9 Agu 2026" alih-alih nama bulan lengkap.

    Bug yang DILAPORKAN USER: tanpa singkatan di daftar bulan, tanggalnya tidak dikenali
    sehingga audit memvonis "angka TANPA satu pun tanggal" dan memunculkan peringatan
    palsu — terlihat langsung di layar user pada balasan yang jelas bertanggal.
    """
    assert bot._TGL_RE.search(teks), teks


def test_kesegaran_tidak_menyala_untuk_tanggal_singkat():
    balasan = ("🕒 Data per 9 Agu 2026, candle 4H tutup 19:00 WIB" + N + N +
               "EMA21 Daily $0,002084. RSI 4H 75,8.")
    assert "BURUK" not in bot.audit_kesegaran(balasan)
    assert bot.peringatan_audit(None, None, bot.audit_kesegaran(balasan)) is None


def test_kesegaran_tetap_menyala_kalau_benar_benar_tanpa_tanggal():
    """Menerima singkatan tidak boleh melumpuhkan deteksinya."""
    assert "BURUK" in bot.audit_kesegaran("EMA21 $0,002084. RSI 75,8. Harga $0,002683.")


@pytest.mark.parametrize("berkas", [
    "chat.md", "analisa.md", "analisa_pasar.md",
])
def test_aturan_rencana_vs_posisi_ada_di_prompt(berkas):
    """Bug yang DILAPORKAN USER: "kalo buy di $X bagaimana menurutmu?" dijawab seolah

    posisinya sudah ada ("entry kamu sekarang profit tipis", "Sudah pegang: TAHAN"),
    padahal user baru HENDAK membeli. Kata pengandaian berarti RENCANA, bukan kepemilikan.
    """
    with open(os.path.join(AKAR, "cloud", "prompts", berkas), encoding="utf-8") as f:
        isi = f.read()
    assert "RENCANA vs POSISI" in isi
    assert "Belum punya" in isi



# --------------------------- sapuan ke-9: regresi pada yang baru saja diubah

@pytest.mark.parametrize("pesan,harap", [
    # yang SAH harus tetap terdeteksi
    ("kalo buy pump di 0.0026 gimana?", ("crypto", "PUMP")),
    ("beli sol sekarang?", ("crypto", "SOL")),
    ("masuk ondo di 0.85?", ("crypto", "ONDO")),
    ("jual saham nvda sekarang?", ("saham", "NVDA")),
    ("beli emas di 4300 gimana?", ("forex", "GC=F")),
    # kata biasa setelah kata kerja transaksi BUKAN nama aset
    ("beli banyak nggak ya", (None, None)),
    ("entry lagi di harga berapa?", (None, None)),
    ("buy the dip gimana?", (None, None)),
    ("jual sebagian dulu", (None, None)),
    ("beli lagi besok aja", (None, None)),
    ("masuk sekarang atau tunggu?", (None, None)),
])
def test_aset_transaksi_tidak_salah_tangkap(pesan, harap):
    """Regresi yang KUPERKENALKAN SENDIRI di sapuan ke-8.

    Pola "buy <TOKEN>" membuat "beli banyak" terbaca sebagai koin BANYAK, "entry lagi"
    jadi koin LAGI, dan "buy the dip" jadi koin THE — bot lalu mengumpulkan data untuk
    aset yang tidak ada. Kelas kesalahan yang persis sama dengan "analisa koin pump"
    yang dulu sudah diperbaiki, muncul kembali di tempat baru.
    """
    assert bot.aset_dari_pesan(pesan) == harap


def test_tidak_mengulang_kalau_semua_sumber_gagal():
    """Keluaran tipis karena ASET TIDAK ADA tidak akan membaik dengan diulang.

    Satu salah ketik ticker sempat memakan 40,3 detik dari jatah 300 detik, hanya untuk
    mengulang sesuatu yang pasti gagal lagi. Rate limit biasanya menyisakan sebagian
    sumber; seluruh sumber gagal sekaligus adalah ciri aset yang memang tidak ada.
    """
    gagal = ('{"timeframes": {"1d": {"error": "gagal ambil candle harian: '
             'binance: URLError; kraken: URLError; coinbase: URLError; okx: RuntimeError"}}}')
    assert bot._SEMUA_SUMBER_GAGAL.search(gagal)
    # keluaran normal TIDAK boleh ikut tertandai
    assert not bot._SEMUA_SUMBER_GAGAL.search('{"close": 148.2, "rsi14": 58}')



# ------------------------- sapuan ke-10: struktur blok & pertumbuhan prompt

def test_semua_blok_chat_terbentuk_utuh():
    """Penjaga STRUKTUR: tiap pembuka BLOK harus punya penutupnya sendiri.

    Bug nyata: satu penutup salah tempat membuat blok rencana-posisi MENELAN blok
    berikutnya, sehingga peta-korelasi tidak pernah terbentuk dan isinya ikut dimuat
    untuk SETIAP pesan — termasuk sapaan. Kegagalannya sunyi: promptnya tetap sah,
    hanya jadi jauh lebih boros tanpa ada yang error.
    """
    with open(os.path.join(AKAR, "cloud", "prompts", "chat.md"), encoding="utf-8") as f:
        teks = f.read()
    pembuka = teks.count("<!-- BLOK:")
    penutup = teks.count("<!-- /BLOK -->")
    terbentuk = len(bot._BLOK_RE.findall(teks))
    assert pembuka == penutup, f"{pembuka} pembuka vs {penutup} penutup"
    assert terbentuk == pembuka, f"hanya {terbentuk} dari {pembuka} blok terbentuk"


def test_sapaan_tidak_memuat_aturan_pasar():
    """Sapaan tidak butuh peta tool, mode pendapat, maupun aturan transaksi.

    Penghematan T3/T4 sempat tergerus tanpa disadari: "halo" naik dari 15.229 menjadi
    20.221 karakter karena bagian yang ditambahkan belakangan semuanya masuk INTI.
    """
    p = bot.build_chat_prompt("halo")
    for bagian in ("PETA KORELASI", "MODE PENDAPAT", "RENCANA vs POSISI"):
        assert bagian not in p, f"{bagian} tidak seharusnya dimuat untuk sapaan"
    assert len(p) < 18000, f"prompt sapaan {len(p)} kar — terlalu boros"


@pytest.mark.parametrize("pesan,bagian", [
    ("kalo buy pump di 0.0026 gimana?", "RENCANA vs POSISI"),
    ("worth nggak hold sol sekarang?", "RENCANA vs POSISI"),
    ("apa dampaknya ke harga gold?", "PETA KORELASI"),
    ("jadi gambaranmu bagaimana?", "MODE PENDAPAT"),
])
def test_bagian_dimuat_saat_relevan(pesan, bagian):
    """Menghemat tidak boleh berarti kehilangan aturan saat benar-benar dibutuhkan."""
    assert bagian in bot.build_chat_prompt(pesan)


@pytest.mark.parametrize("pesan", ["kalo buy pump di 0.0026", "mau sell sekarang",
                                   "worth hold nggak"])
def test_kosakata_transaksi_inggris_dikenali(pesan):
    """buy/sell/hold sempat tidak ada di kosakata pasar, padahal lazim dipakai."""
    assert bot._PASAR_UMUM.search(pesan.lower()), pesan



def test_petunjuk_jenis_aset_mencegah_muat_semua():
    """Kalimat transaksi sering tidak memakai satu pun kosakata rumpun.

    "kalo buy pump di 0.0026" menyentuh kosakata pasar lewat kata "buy", tapi tidak
    menyebut koin/token/saham/forex — sehingga gagal-aman memuat SEMUA blok (42 rb
    karakter) padahal jenis asetnya jelas crypto dan sudah dikenali dari pesannya.
    """
    # Dibandingkan pada tingkat rakit_chat, bukan build_chat_prompt: yang diukur adalah
    # pemilihan BLOK. build_chat_prompt ikut menempelkan berkas peran, jadi panjangnya
    # bergerak setiap aturan kalibrasi berubah dan perbandingannya jadi tidak setara.
    pesan = "kalo buy pump di 0.0026 gimana?"
    teks = _muat_chat_md()
    dengan = bot.rakit_chat(teks, pesan, bot.aset_dari_pesan(pesan)[0])
    semua = len(bot.rakit_chat(teks, "menurutmu pasar gimana"))
    assert len(dengan) < semua, "petunjuk jenis aset tidak dipakai"
    assert "RENCANA vs POSISI" in dengan, "aturan transaksi tetap harus ikut"


def test_gagal_aman_masih_utuh_tanpa_petunjuk():
    """Tanpa aset yang dikenali DAN tanpa rumpun yang cocok, semua blok tetap dimuat.

    Itu jaring pengaman terakhir: kehilangan aturan lebih merugikan daripada boros.
    """
    teks = _muat_chat_md()
    hasil = bot.rakit_chat(teks, "menurutmu pasar gimana", None)
    semua = [n for n, _, _ in bot._BLOK_RE.findall(teks)]
    aktif = _blok_aktif(hasil, semua, teks)
    assert len(aktif) == len(semua), f"hanya {len(aktif)} dari {len(semua)} blok"



# --------------------- sapuan ke-11: riwayat, foto, dan boilerplate di ekor

def test_peringatan_audit_tidak_mendorong_kesimpulan_keluar_riwayat():
    """Disclaimer & peringatan audit memakan jatah EKOR potongan riwayat.

    Regresi nyata: sejak peringatan audit ditambahkan (T1a), blok KESIMPULAN terdorong
    keluar dari potongan yang disimpan — padahal mempertahankan kesimpulan itulah alasan
    potongan dua-ujung ini dibuat. Keduanya identik di setiap balasan, jadi tidak menambah
    konteks apa pun saat dibaca ulang.
    """
    inti = ("🧮 SKOR 58/100" + N + "🎯 BIAS SPOT: TAHAN" + N + ("x" * 700) + N +
            "✅ KESIMPULAN SPOT" + N + "Belum punya : TUNGGU DULU" + N +
            "Sudah pegang: TAHAN — selama close di atas EMA21 $148,20" + N)
    disc = "⚠️ Riset pasar berbasis data, bukan saran keuangan."
    dengan = bot.sisipkan_peringatan(
        inti + disc, "⚠️ Sebagian angka di atas tidak bisa kulacak ke data mentah.")
    p = bot._potong_balasan(dengan)
    assert "KESIMPULAN" in p, p[-200:]
    assert "148,20" in p
    assert "SKOR 58" in p              # ujung awal juga tetap ada


def test_buang_ekor_hanya_di_ujung():
    """Bagian RISIKO di TENGAH balasan memakai ⚠️ juga — jangan ikut terbuang."""
    teks = ("Isi analisa" + N + "⚠️ RISIKO" + N + "• unlock besar pekan depan" + N +
            "✅ KESIMPULAN" + N + "TUNGGU DULU" + N + "⚠️ Bukan saran keuangan.")
    hasil = bot._buang_ekor_boilerplate(teks)
    assert "⚠️ RISIKO" in hasil
    assert "unlock besar" in hasil
    assert "Bukan saran keuangan" not in hasil


def test_foto_punya_aturan_rencana_vs_posisi():
    """Mengirim chart lalu bertanya "kalau saya masuk di sini?" adalah hal paling wajar

    di mode foto — tapi aturannya sempat hanya ada di chat.md dan kedua prompt analisa.
    """
    with open(os.path.join(AKAR, "cloud", "prompts", "foto.md"), encoding="utf-8") as f:
        isi = f.read()
    assert "RENCANA vs POSISI" in isi
    assert "Belum punya" in isi


@pytest.mark.parametrize("berkas", [
    "chat.md", "analisa.md", "analisa_pasar.md", "foto.md", "narasi.md",
    "analisa_sumber.md",
])
def test_pagar_kode_prompt_seimbang(berkas):
    """Pagar ``` yang tidak tertutup membuat SELURUH teks sesudahnya terbaca sebagai

    contoh kode, bukan aturan — kegagalan sunyi yang tidak memunculkan error apa pun.
    """
    with open(os.path.join(AKAR, "cloud", "prompts", berkas), encoding="utf-8") as f:
        isi = f.read()
    assert isi.count("```") % 2 == 0, f"{berkas}: pagar kode ganjil"



# ------------------------ sapuan ke-12: pesan gagal & kebocoran ke Telegram

@pytest.mark.parametrize("teks", [
    "gagal auth: bot7525096497:AAF9xKqLmN3pQrS7tUvWxYz012345678ab",
    "fatal: ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456",
    "OPENAI_API_KEY=sk-proj-AbCdEfGhIjKlMnOpQrStUvWx",
])
def test_rahasia_tidak_ikut_terkirim(teks):
    """Pesan gagal kadang membawa potongan konfigurasi.

    Repo ini publik dan chat ID pun sengaja di-hash, jadi membocorkan token lewat pesan
    error ke Telegram akan membatalkan kehati-hatian itu.
    """
    assert "[dirahasiakan]" in bot.tanpa_rahasia(teks)


@pytest.mark.parametrize("teks", [
    "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json",
    "alamat kontrak 0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
    "Harga BTC $64.978 dengan RSI 58 pada 10 Agustus 2026",
    "EMA13/EMA21/EMA33/EMA50/EMA100/EMA200 semuanya searah naik",
])
def test_penyaring_rahasia_tidak_salah_sasar(teks):
    """Penyaring yang kelewat galak akan merusak isi analisa yang sah."""
    assert bot.tanpa_rahasia(teks) == teks


def test_pesan_gagal_tidak_memuat_stderr_mentah():
    """Dulu sampai 1.500 karakter stderr dikirim apa adanya ke Telegram — tidak terbaca

    oleh user, dan berpotensi membawa token, path, atau isi konfigurasi. Detail lengkap
    tetap masuk log Actions, yang memang tempatnya.
    """
    with open(os.path.join(AKAR, "cloud", "bot_oneshot.py"), encoding="utf-8") as f:
        kode = f.read()
    assert "result.stderr or result.stdout or '')[-1500:]}\"" not in kode
    assert "Detailnya ada di log Actions" in kode



# ---------------------- sapuan ke-13: pengiriman pesan (pecah, saring, kosong)

def test_rahasia_terbelah_batas_potongan_tetap_tersaring(monkeypatch):
    """Regresi yang KUPERKENALKAN SENDIRI di sapuan ke-12.

    Penyaring dipasang per-potongan, sehingga token yang kebetulan terbelah di batas
    3.900 karakter lolos: kedua belahannya tampak seperti teks biasa dan tidak cocok pola
    apa pun, padahal begitu digabung kembali di layar user token itu utuh.
    """
    token = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456"
    isi = "x" * (3900 - len(token) // 2) + token + "y" * 100
    terkirim = []
    monkeypatch.setattr(bot, "tg_api",
                        lambda tok, m, p: (terkirim.append(p["text"]), {"ok": True})[1])
    bot.send_message("T", "1", isi)
    gabung = "".join(terkirim)
    assert token not in gabung, "token utuh setelah potongan disatukan kembali"
    assert "[dirahasiakan]" in gabung


def test_teks_panjang_biasa_tidak_rusak_saat_dipecah(monkeypatch):
    """Menyaring sebelum memecah tidak boleh mengubah isi yang sah."""
    normal = "Harga BTC $64.978. " * 400
    terkirim = []
    monkeypatch.setattr(bot, "tg_api",
                        lambda tok, m, p: (terkirim.append(p["text"]), {"ok": True})[1])
    assert bot.send_message("T", "1", normal) is True
    assert "".join(terkirim) == normal


@pytest.mark.parametrize("teks", ["", None, "   ", N + N])
def test_teks_kosong_tidak_mengaku_berhasil(teks, monkeypatch):
    """Perulangan pemecah tidak berjalan untuk teks kosong, sehingga fungsi ini dulu

    mengembalikan True padahal tak satu pun pesan dikirim — kebalikan dari janji
    docstring-nya, dan pemanggil lalu mencatat "TERKIRIM" ke log.
    """
    terkirim = []
    monkeypatch.setattr(bot, "tg_api",
                        lambda tok, m, p: (terkirim.append(p["text"]), {"ok": True})[1])
    assert bot.send_message("T", "1", teks) is False
    assert not terkirim



def test_daemon_bongkar_sesuai_arity_actionable_messages():
    """bot_daemon.py harus membongkar sebanyak nilai yang dikembalikan.

    Regresi nyata: actionable_messages berubah dari 3 jadi 4 nilai saat dukungan foto
    ditambahkan, tapi bot_daemon.py tetap membongkar 3 -> ValueError pada SETIAP pesan.
    Tidak pernah ketahuan karena produksi memakai webhook, bukan daemon.
    """
    upd = [{"update_id": 1, "message": {"chat": {"id": "9"}, "text": "halo"}}]
    arity = len(bot.actionable_messages(upd, {"9"})[0])

    sumber = open(os.path.join(AKAR, "cloud", "bot_daemon.py"), encoding="utf-8").read()
    m = re.search(r"for\s+(.+?)\s+in\s+actionable_messages\(", sumber)
    assert m, "pola pembongkaran actionable_messages tidak ditemukan di bot_daemon.py"
    assert len(m.group(1).split(",")) == arity, (
        f"bot_daemon.py membongkar {len(m.group(1).split(','))} nilai, "
        f"actionable_messages mengembalikan {arity}")


def test_daemon_meneruskan_foto_ke_process():
    """Foto tidak boleh hilang diam-diam di jalur daemon."""
    sumber = open(os.path.join(AKAR, "cloud", "bot_daemon.py"), encoding="utf-8").read()
    m = re.search(r"process\(token,\s*chat_id,\s*text([^)]*)\)", sumber)
    assert m, "panggilan process() tidak ditemukan di bot_daemon.py"
    assert m.group(1).strip(), "bot_daemon.py memanggil process() tanpa meneruskan foto"


_PESAN_PASAR_TANPA_KOSAKATA_UMUM = [
    "apabila dilihat di timeframe weekly, masih possible turun sampai range 55k-58k",
    "btc masih bisa turun ke 55k?",
    "di timeframe weekly gimana",
    "ema21 nya udah ketembus belum",
]


@pytest.mark.parametrize("pesan", _PESAN_PASAR_TANPA_KOSAKATA_UMUM)
def test_aturan_kalibrasi_ikut_pada_pertanyaan_pasar(pesan):
    """Pertanyaan pasar WAJIB membawa inti.md, walau tak menyentuh kosakata _PASAR_UMUM.

    Regresi nyata: gerbang peran memakai _PASAR_UMUM sedangkan bobot_chat memakai
    _PASAR_UMUM ATAU _TEKNIKAL_RE. Pesan "di timeframe weekly masih possible turun
    sampai 55k-58k" dinilai "pertanyaan pasar spesifik" oleh bobot_chat, tapi dijawab
    TANPA aturan konfluensi palsu, base rate, skenario, maupun daftar bias.
    """
    p = bot.build_chat_prompt(pesan, "", None)
    assert "kategori independen" in p, f"aturan konfluensi hilang: {pesan}"
    assert "HIPOTESIS DARI USER" in p, f"aturan uji-hipotesis hilang: {pesan}"


@pytest.mark.parametrize("pesan", ["halo", "apa itu RAG?", "apa itu RSI?", "makasih ya"])
def test_sapaan_dan_konseptual_tetap_ramping(pesan):
    """Penyempitan gerbang tidak boleh menyeret berkas peran ke sapaan / tanya konsep."""
    assert not bot.pesan_pasar(pesan)
    assert "kategori independen" not in bot.build_chat_prompt(pesan, "", None)


def test_gerbang_peran_sejalan_dengan_bobot_chat():
    """Dua ambang untuk satu keputusan adalah sumber bug ini — jangan melenceng lagi.

    Apa pun yang dinilai SEDANG/BERAT oleh bobot_chat harus membawa aturan kalibrasi.
    """
    contoh = _PESAN_PASAR_TANPA_KOSAKATA_UMUM + [
        "kalo buy di 0.002551 bagaimana menurutmu?",
        "prospek sol gimana",
        "bandingkan btc dan eth secara detail",
    ]
    for pesan in contoh:
        tingkat = bot.bobot_chat(pesan, False)[3]
        if tingkat.startswith(("SEDANG", "BERAT")):
            assert bot.pesan_pasar(pesan), (
                f"bobot_chat bilang {tingkat} tapi pesan_pasar() menolak: {pesan}")


def test_aturan_uji_hipotesis_ada_di_inti():
    """Menjawab 'ya' lalu mengumpulkan level di sekitar angka user adalah pembenaran,
    bukan analisa. Aturannya harus tetap ada beserta ketiga kewajibannya."""
    teks = open(os.path.join(AKAR, "cloud", "prompts", "peran", "inti.md"),
                encoding="utf-8").read()
    assert "HIPOTESIS DARI USER" in teks
    for wajib in ("Alternatif yang setara", "Syarat pembatal", "KATEGORI yang mendukung"):
        assert wajib in teks, f"bagian '{wajib}' hilang dari aturan uji-hipotesis"


@pytest.mark.parametrize("pesan,harap", [
    ("solana berpotensi naik sampai $200?", 200.0),
    ("btc bisa ke 55k dalam sebulan?", 55000.0),
    ("emas target 4.000 tahun ini", 4000.0),
    ("sol naik ke 0,002551 gimana", 0.002551),
    ("prospek eth minggu ini", None),
    ("prediksi cpi nanti bullish for gold?", None),
])
def test_target_dari_pesan(pesan, harap):
    """Target user harus terbaca UTUH supaya bisa diuji proyeksi.py --target.

    '4.000' adalah empat ribu, bukan empat koma nol; '55k' lima puluh lima ribu; dan
    '0,002551' desimal. Salah membaca berarti menguji angka yang berbeda dari yang ditanya.
    """
    assert bot.target_dari_pesan(pesan) == harap


@pytest.mark.parametrize("pesan,hari", [
    ("emas target 4.000 tahun ini", 250),
    ("btc bisa ke 55k dalam sebulan?", 30),
    ("prospek eth minggu ini", 10),
    ("sol gimana hari ini", 5),
    ("solana berpotensi naik sampai $200?", 60),
])
def test_horizon_dari_pesan(pesan, hari):
    """Target tanpa horizon tidak bisa salah — horizon wajib ikut kata waktunya."""
    assert bot.horizon_dari_pesan(pesan) == hari


@pytest.mark.parametrize("pesan,simbol", [
    ("solana berpotensi naik sampai $200?", "SOL"),
    ("analisa solana", "SOL"),
    ("bitcoin gimana", "BTC"),
    ("ethereum prospeknya", "ETH"),
])
def test_nama_koin_panjang_dikenali(pesan, simbol):
    """Nama panjang sempat tak dikenali sama sekali walau tickernya ada di daftar.

    Akibatnya berantai: aset None -> bukan pertanyaan pasar -> tanpa aturan kalibrasi
    DAN tanpa brief. Orang justru menulis nama panjang saat tidak memakai perintah.
    """
    assert bot.aset_dari_pesan(pesan) == ("crypto", simbol)


def test_nama_koin_tidak_salah_tangkap():
    """Batas kata harus dijaga: 'solanaverse' bukan Solana."""
    assert bot.aset_dari_pesan("solanaverse gimana") == (None, None)


@pytest.mark.parametrize("pesan,ada", [
    ("solana berpotensi naik sampai $200?", True),
    ("prediksi cpi nanti bullish for gold?", True),
    ("target eth di mana", True),
    ("harga btc berapa sekarang", False),
    ("halo", False),
])
def test_seed_forecaster_dimuat_saat_diminta_proyeksi(pesan, ada):
    """Seed FORECASTER berat; ikut hanya kalau memang diminta proyeksi."""
    p = bot.build_chat_prompt(pesan, "", None)
    assert ("FORECASTER — proyeksi" in p) is ada


def test_analisa_selalu_membawa_forecaster():
    """Analisa penuh berujung pada target & skenario, jadi seed-nya selalu ikut."""
    for sektor in ("crypto", "forex", "saham"):
        teks = bot.rakit_peran(sektor)
        assert "FORECASTER — proyeksi" in teks, sektor
        assert "## Proyeksi" in teks, f"blok sektor {sektor} tidak terpasang"


def test_larangan_prediksi_lama_sudah_dicabut():
    """Kontradiksi prompt menghasilkan perilaku tidak konsisten.

    inti.md dulu melarang memprediksi harga secara total, sementara seed FORECASTER
    memerintahkan sebaliknya. Yang berlaku sekarang: angka BOLEH, asal tidak telanjang.
    """
    teks = open(os.path.join(AKAR, "cloud", "prompts", "peran", "inti.md"),
                encoding="utf-8").read()
    assert "Tugasmu BUKAN memprediksi harga" not in teks
    assert "memPROYEKSIkannya secara terukur" in teks


def test_syarat_proyeksi_lengkap_di_seed():
    """Lima syarat itulah yang memisahkan proyeksi dari ramalan — jangan sampai terkikis."""
    teks = open(os.path.join(AKAR, "cloud", "prompts", "peran", "prediktor.md"),
                encoding="utf-8").read()
    for wajib in ("Metode", "Horizon", "Rentang, bukan titik", "Pembatal", "Basis kejadian"):
        assert wajib in teks, f"syarat '{wajib}' hilang"
    for sektor in ("prediktor-crypto", "prediktor-forex", "prediktor-saham"):
        assert sektor in teks, f"blok {sektor} hilang"
    # Batas yang paling mudah dilupakan saat prompt dirapikan.
    assert "TIDAK ADA EDGE ARAH" in teks
    assert "bukan konsensus ekonom Wall Street" in teks


def test_batas_nfp_fomc_dinyatakan_di_seed():
    """NFP/PPI/FOMC TIDAK punya konsensus historis di sumber gratis mana pun.

    Tanpa aturan eksplisit, model akan memperlakukan "perubahan terhadap bulan lalu"
    sebagai kejutan terhadap ekspektasi — padahal NFP -23 ribu bisa disambut naik kalau
    konsensus memperkirakan lebih buruk. Batas ini harus tetap tertulis.
    """
    # Spasi dinormalkan: prompt dibungkus pada 96 kolom, jadi kalimatnya sering terpotong
    # baris. Tes yang peka pembungkusan akan gagal setiap kali paragrafnya dirapikan.
    teks = " ".join(open(os.path.join(AKAR, "cloud", "prompts", "peran", "prediktor.md"),
                         encoding="utf-8").read().split())
    # Golongan "tanpa ukuran kejutan" kini KOSONG: FOMC dapat seri Bauer-Swanson, NFP dan
    # PPI dapat konsensus SoSoValue sejak 2010. Yang tersisa dari batas lama hanya jebakan
    # membaca perubahan bulanan sebagai kejutan.
    assert "BUKAN kejutan terhadap ekspektasi" in teks
    assert "PPI: tidak ada temuan" in teks, "hasil nol PPI harus tercatat"
    assert "TIDAK punya jejak vintage" in teks, "batas konsensus SoSoValue hilang"


def test_cache_baru_ikut_disimpan_workflow():
    """Runner ephemeral: cache yang tidak di-commit balik berarti ditarik ulang tiap run.

    Untuk jadwal.py itu bukan sekadar boros — BLS tanpa kunci dibatasi 25 permintaan
    per hari, jadi cache yang tidak bertahan bisa menghabiskan kuotanya.
    """
    alur = open(os.path.join(AKAR, ".github", "workflows", "bot.yml"),
                encoding="utf-8").read()
    for berkas in ("cloud/data/kejutan_cache.json", "cloud/data/jadwal_cache.json"):
        assert alur.count(berkas) == 2, f"{berkas} harus ada di pemeriksaan DAN git add"


# ------------------------------------------------- arsip konsensus Forex Factory
import arsip  # noqa: E402


def _arsip_sementara(tmp_path, monkeypatch):
    monkeypatch.setattr(arsip, "ARSIP_PATH", str(tmp_path / "a.jsonl"))


def _acara(aktual, nama="Non-Farm Employment Change"):
    return [{"nama": nama, "mata_uang": "USD", "waktu": "2026-09-04T08:30:00-04:00",
             "dampak": "tinggi", "konsensus": "75K", "sebelumnya": "-23K", "aktual": aktual}]


def test_arsip_tidak_menghapus_aktual_dengan_cache_lama(tmp_path, monkeypatch):
    """Kegagalan paling merusak di arsip ini: aktual tertimpa kosong.

    Feed dibaca dari cache 6 jam, jadi satu acara bisa dibaca ulang dalam keadaan
    'belum rilis' SETELAH aktualnya sempat terekam. Arsip ini tidak punya cadangan di
    mana pun — Forex Factory membuang pekan yang sudah lewat — jadi menimpanya dengan
    kosong berarti angka itu hilang selamanya.
    """
    _arsip_sementara(tmp_path, monkeypatch)
    assert arsip.catat(_acara(None))[0] == 1
    assert arsip.catat(_acara("120K"))[1] == 1
    arsip.catat(_acara(None))
    tersimpan = list(arsip.muat().values())[0]
    assert tersimpan["aktual"] == "120K"


def test_arsip_tidak_menggandakan_acara_yang_sama(tmp_path, monkeypatch):
    """Upsert, bukan append: satu acara dibaca berkali-kali sepanjang pekan."""
    _arsip_sementara(tmp_path, monkeypatch)
    for _ in range(4):
        arsip.catat(_acara("120K"))
    assert len(arsip.muat()) == 1


def test_arsip_hanya_dampak_tinggi(tmp_path, monkeypatch):
    """Dampak rendah lima kali lebih banyak dan tak pernah dipakai untuk studi kejutan."""
    _arsip_sementara(tmp_path, monkeypatch)
    rendah = _acara("120K")
    rendah[0]["dampak"] = "rendah"
    assert arsip.catat(rendah) == (0, 0, 0)


@pytest.mark.parametrize("aktual,konsensus,harap", [
    ("0.4%", "0.2%", 0.2),
    ("-23K", "75K", -98.0),
    ("2.50T", "3.06T", -0.56),
    ("0.2%", "150K", None),      # satuan beda -> tidak berarti
    (None, "75K", None),
    ("120K", None, None),
])
def test_arsip_kejutan_hanya_bila_satuan_sama(aktual, konsensus, harap):
    """aktual - konsensus hanya sah kalau satuannya sama; '0.2%' - '150K' itu omong kosong."""
    hasil = arsip.kejutan({"aktual": aktual, "konsensus": konsensus})
    if harap is None:
        assert hasil is None
    else:
        assert hasil == pytest.approx(harap)


def test_arsip_status_menandai_sampel_kecil(tmp_path, monkeypatch):
    """Arsip tumbuh dari nol — selama tipis, ia harus MENOLAK dianggap bukti."""
    _arsip_sementara(tmp_path, monkeypatch)
    arsip.catat(_acara("120K"))
    st = arsip.status()
    assert st["siap_dipakai"] == "BELUM ADA"
    assert "tidak" in st["aturan_pakai"].lower()


def test_arsip_dilindungi_workflow():
    """Hanya-tambah: ikut di-commit balik, dan dijaga agar tidak menyusut."""
    bot_yml = open(os.path.join(AKAR, ".github", "workflows", "bot.yml"),
                   encoding="utf-8").read()
    assert bot_yml.count("cloud/data/arsip_konsensus.jsonl") == 2
    tes_yml = open(os.path.join(AKAR, ".github", "workflows", "tes.yml"),
                   encoding="utf-8").read()
    assert "arsip_konsensus.jsonl" in tes_yml and "menyusut" in tes_yml


import kejutan as _kejutan  # noqa: E402


def _catatan(tanggal, kejutan_pp, ret_h1, aktual=0.2):
    return {"tanggal": tanggal, "kejutan_pp": kejutan_pp, "aktual": aktual,
            "ret": {0: 0.0, 1: ret_h1, 5: ret_h1}}


def test_vonis_rezim_menandai_tanda_yang_berbalik(monkeypatch):
    """Temuan yang tandanya berbalik antar potongan TIDAK boleh dipakai meramal.

    Ini yang terjadi pada emas: selisih H+5 gabungan -0,30% ternyata artefak periode
    2022-2026 (+0,25 / +0,19 / -2,06 saat dipotong kronologis).
    """
    # Paruh awal: panas lebih BAIK. Paruh akhir: panas lebih BURUK. Tanda pasti berbalik.
    catatan = []
    for i in range(30):
        catatan.append(_catatan(f"2014-{i % 12 + 1:02d}-10", 0.1, 1.0))
        catatan.append(_catatan(f"2015-{i % 12 + 1:02d}-10", -0.1, 0.0))
    for i in range(30):
        catatan.append(_catatan(f"2024-{i % 12 + 1:02d}-10", 0.1, -1.0))
        catatan.append(_catatan(f"2025-{i % 12 + 1:02d}-10", -0.1, 0.0))
    hasil = _kejutan.reaksi_per_rezim("X", [], False, catatan=catatan,
                                      meta={"simbol": "X", "jendela_harga": "-"})
    assert hasil["vonis_H+1"]["tanda_bertahan"] is False
    assert "artefak" in hasil["vonis_H+1"]["tindakan"]


def test_vonis_rezim_mengakui_tanda_yang_bertahan():
    """Kalau tandanya sama di semua potongan, vonisnya harus mengakui — bukan menolak buta."""
    catatan = []
    for tahun in (2014, 2018, 2024):
        for i in range(20):
            catatan.append(_catatan(f"{tahun}-{i % 12 + 1:02d}-10", 0.1, -0.5))
            catatan.append(_catatan(f"{tahun}-{i % 12 + 1:02d}-11", -0.1, 0.0))
    hasil = _kejutan.reaksi_per_rezim("X", [], False, catatan=catatan,
                                      meta={"simbol": "X", "jendela_harga": "-"})
    assert hasil["vonis_H+1"]["tanda_bertahan"] is True


def test_uji_rezim_menolak_sampel_terlalu_tipis():
    """Memotong 20 rilis jadi tujuh bagian menghasilkan angka yang terlihat sah tapi kosong."""
    catatan = [_catatan(f"2024-{i % 12 + 1:02d}-10", 0.1, 0.5) for i in range(20)]
    hasil = _kejutan.reaksi_per_rezim("X", [], False, catatan=catatan,
                                      meta={"simbol": "X", "jendela_harga": "-"})
    assert "tidak_tersedia" in hasil


def test_seed_menegakkan_hasil_uji_rezim():
    """Temuan H+5 yang gugur harus tertulis, bukan hanya diketahui saat pengujian."""
    teks = " ".join(open(os.path.join(AKAR, "cloud", "prompts", "peran", "prediktor.md"),
                         encoding="utf-8").read().split())
    assert "uji_ketahanan_per_rezim` LEBIH DULU" in teks
    assert "tanda_bertahan: false" in teks
    assert "TIDAK ADA EDGE ARAH" in teks


def test_brief_forex_membawa_uji_rezim():
    """Produksi harus melihat uji ketahanannya, bukan cuma angka gabungan."""
    sumber = open(os.path.join(AKAR, "cloud", "bot_oneshot.py"), encoding="utf-8").read()
    assert "--rezim" in sumber, "flag --rezim tidak dipakai di pengumpulan data"
    assert sumber.count("--rezim") >= 2, "jalur analisa DAN jalur proyeksi harus memakainya"


def test_fomc_tidak_lagi_digolongkan_tanpa_ukuran_kejutan():
    """Seed sempat menyatakan dua hal berlawanan tentang FOMC sekaligus.

    Bagian NFP/PPI dulu menulis 'tidak ada konsensus historis untuk ketiga acara ini',
    sementara bagian berikutnya menjelaskan seri kejutan FOMC dari SF Fed. Prompt yang
    berkontradiksi menghasilkan perilaku acak.
    """
    teks = " ".join(open(os.path.join(AKAR, "cloud", "prompts", "peran", "prediktor.md"),
                         encoding="utf-8").read().split())
    assert "historis untuk ketiga acara ini" not in teks
    assert "konsensus historis untuk NFP dan PPI" not in teks, (
        "klaim itu sudah tidak benar — riwayat SoSoValue memuat konsensus sejak 2010")
    assert "Bauer-Swanson" in teks


def test_seed_fomc_menolak_dipakai_sebagai_ramalan():
    """Kejutan FOMC diukur SETELAH pengumuman — memakainya untuk meramal itu salah kaprah."""
    teks = " ".join(open(os.path.join(AKAR, "cloud", "prompts", "peran", "prediktor.md"),
                         encoding="utf-8").read().split())
    assert "BUKAN ramalan" in teks
    assert "berakhir 13 Desember 2023" in teks
    assert "H+5 TIDAK bertahan" in teks


def test_kejutan_fomc_memakai_label_sisi_yang_benar():
    """Pada FOMC, positif berarti HAWKISH — bukan 'inflasi lebih panas'."""
    assert _kejutan.LABEL_SISI["fomc"] == ("kejutan_hawkish", "kejutan_dovish")
    catatan = [{"tanggal": f"202{i//9}-0{i%9+1}-10", "kejutan_pp": 1.0 if i % 2 else -1.0,
                "aktual": None, "ret": {0: 0.0, 1: -0.5 if i % 2 else 0.5, 5: 0.0}}
               for i in range(20)]
    hasil = _kejutan.reaksi_harga("X", [], False, catatan=catatan,
                                  meta={"simbol": "X", "jendela_harga": "-"}, sisi="fomc")
    assert "kejutan_hawkish" in hasil and "kejutan_lebih_panas" not in hasil


def test_potongan_tipis_ditandai():
    """Vonis yang bersandar pada sisi 8 kejadian harus terlihat tipisnya."""
    catatan = [{"tanggal": f"2020-{i % 12 + 1:02d}-10",
                "kejutan_pp": 1.0 if i < 40 else -1.0, "aktual": None,
                "ret": {0: 0.0, 1: -0.5 if i < 40 else 0.5, 5: 0.0}} for i in range(48)]
    hasil = _kejutan.reaksi_per_rezim("X", [], False, catatan=catatan,
                                      meta={"simbol": "X", "jendela_harga": "-"})
    assert hasil.get("potongan_bersampel_tipis"), "potongan bersampel tipis tidak ditandai"


def test_peringatan_cakupan_saat_irisan_pendek():
    """Riwayat harga pendek menghasilkan angka yang tetap terlihat rapi — itu bahayanya."""
    kecil = [{"tanggal": f"2026-{i + 1:02d}-10", "kejutan_pp": 0.1 if i % 2 else -0.1,
              "aktual": 0.2, "ret": {0: 0.0, 1: 0.3, 5: 0.5}} for i in range(10)]
    h = _kejutan.reaksi_harga("BTC", [], False, catatan=kecil,
                              meta={"simbol": "BTC", "jendela_harga": "-"})
    assert "peringatan_cakupan" in h

    besar = [{"tanggal": f"202{i // 12}-{i % 12 + 1:02d}-10",
              "kejutan_pp": 0.1 if i % 2 else -0.1, "aktual": 0.2,
              "ret": {0: 0.0, 1: 0.3, 5: 0.5}} for i in range(40)]
    h2 = _kejutan.reaksi_harga("SPX", [], False, catatan=besar,
                               meta={"simbol": "SPX", "jendela_harga": "-"})
    assert "peringatan_cakupan" not in h2


def test_fomc_tidak_dipasang_ke_jalur_crypto():
    """Seri FOMC berakhir 2023-12; candle crypto gratis mulai jauh sesudahnya.

    Irisannya bukan sedikit melainkan praktis nol, jadi memasangnya di jalur crypto hanya
    menghasilkan bagian kosong yang memakan token — dan lebih buruk, mengundang model
    meminjam angka dari emas.
    """
    sumber = open(os.path.join(AKAR, "cloud", "bot_oneshot.py"), encoding="utf-8").read()
    awal = sumber.index("def data_mentah_crypto")
    blok = sumber[awal:sumber.index("def data_mentah_pasar")]
    assert '"--indikator", "CPI"' in blok, "studi CPI harus ada di jalur crypto"
    assert '"FOMC"' not in blok, "FOMC tidak boleh dipasang di jalur crypto"


def test_saham_membawa_kedua_studi():
    """Riwayat Yahoo 15 tahun — sampelnya penuh, jadi keduanya layak dipasang."""
    sumber = open(os.path.join(AKAR, "cloud", "bot_oneshot.py"), encoding="utf-8").read()
    blok = sumber[sumber.index("def data_mentah_pasar"):]
    blok = blok[:blok.index("ThreadPoolExecutor")]
    assert blok.count("kejutan.py") >= 3, "CPI+FOMC untuk saham dan forex harus terpasang"


def test_seed_menolak_meminjam_angka_fomc_untuk_crypto():
    teks = " ".join(open(os.path.join(AKAR, "cloud", "prompts", "peran", "prediktor.md"),
                         encoding="utf-8").read().split())
    assert "jangan meminjam angka dari emas atau saham" in teks
    assert "peringatan_cakupan` lebih dulu" in teks


# ------------------------------------------------------------ adapter SoSoValue
import sosovalue  # noqa: E402


def test_sosovalue_tanpa_kunci_tidak_mati(capsys, monkeypatch):
    """Pola yang sama dengan Finnhub: melaporkan tidak tersedia, bukan menggagalkan analisa."""
    monkeypatch.delenv("SOSOVALUE_API_KEY", raising=False)
    data, dari_cache, err = sosovalue.panggil("/openapi/v1/apa/pun")
    assert data is None and err and "SOSOVALUE_API_KEY" in err


def test_sosovalue_kunci_tidak_pernah_masuk_keluaran():
    """Repo ini PUBLIK dan log Actions ikut terbaca publik.

    Kunci hanya boleh muncul sebagai header permintaan. Satu f-string ceroboh yang
    memasukkannya ke pesan galat akan menerbitkannya selamanya.
    """
    sumber = open(os.path.join(AKAR, "cloud", "sosovalue.py"), encoding="utf-8").read()
    # Nilai kunci hanya boleh dipakai di satu tempat: header x-soso-api-key.
    assert sumber.count('h["x-soso-api-key"] = key') == 1
    for baris in sumber.splitlines():
        telanjang = baris.strip()
        if telanjang.startswith("#") or '"""' in telanjang:
            continue
        if ("print(" in telanjang or "pesan +=" in telanjang or "return None, False" in telanjang):
            assert "key" not in telanjang.replace("SOSOVALUE_API_KEY", ""), telanjang


def test_workflow_periksa_tidak_menggemakan_kunci():
    alur = open(os.path.join(AKAR, ".github", "workflows", "periksa-sosovalue.yml"),
                encoding="utf-8").read()
    assert "workflow_dispatch" in alur, "harus manual, bukan terjadwal"
    assert "echo $SOSOVALUE_API_KEY" not in alur
    assert 'echo "$SOSOVALUE_API_KEY"' not in alur


def test_sosovalue_semua_akses_lewat_satu_pintu():
    """Tier gratisnya berstatus Demo dan bisa jadi berbayar. Kalau aksesnya tersebar,
    mencabutnya berarti membongkar pipeline."""
    sumber = open(os.path.join(AKAR, "cloud", "sosovalue.py"), encoding="utf-8").read()
    assert sumber.count("urlopen") == 1, "hanya boleh ada satu tempat memanggil jaringan"
    for lain in ("bot_oneshot.py", "kejutan.py", "jadwal.py", "arsip.py"):
        teks = open(os.path.join(AKAR, "cloud", lain), encoding="utf-8").read()
        assert "openapi.sosovalue.com" not in teks, f"{lain} memanggil SoSoValue langsung"


def test_temuan_nfp_tercatat_dengan_horizonnya():
    """Efek NFP nyata TAPI hanya pada hari rilis — dua-duanya harus tertulis.

    Kalau cuma 'ada efek' yang dicatat, model akan memakainya untuk target beberapa hari;
    kalau cuma 'tidak bertahan', temuannya hilang sama sekali.
    """
    teks = " ".join(open(os.path.join(AKAR, "cloud", "prompts", "peran", "prediktor.md"),
                         encoding="utf-8").read().split())
    assert "hanya pada HARI RILIS" in teks
    assert "H+1 dan H+5: gugur" in teks
    assert "tidak bertahan sampai besok" in teks


def test_vonis_menyertakan_hari_rilis():
    """Mengecualikan H dari vonis sempat menyembunyikan satu-satunya sinyal NFP."""
    catatan = []
    for tahun in (2014, 2018, 2024):
        for i in range(20):
            # Kejutan positif -> turun PADA HARI ITU, lalu acak sesudahnya.
            catatan.append({"tanggal": f"{tahun}-{i % 12 + 1:02d}-10", "kejutan_pp": 1.0,
                            "aktual": None, "ret": {0: -0.8, 1: 0.2 if i % 2 else -0.2, 5: 0.0}})
            catatan.append({"tanggal": f"{tahun}-{i % 12 + 1:02d}-11", "kejutan_pp": -1.0,
                            "aktual": None, "ret": {0: 0.1, 1: -0.2 if i % 2 else 0.2, 5: 0.0}})
    hasil = _kejutan.reaksi_per_rezim("X", [], False, catatan=catatan,
                                      meta={"simbol": "X", "jendela_harga": "-"})
    assert "vonis_H" in hasil, "hari rilis harus ikut divonis"
    assert hasil["vonis_H"]["tanda_bertahan"] is True


# ------------------------------------------------------------------ arus ETF spot
import etf as _etf  # noqa: E402


def _muat_etf_tersimpan(jenis):
    """Data ETF asli yang ditarik CI — dipakai supaya tes menguji angka nyata, bukan karangan."""
    berkas = os.path.join(AKAR, "cloud", "data", "sosovalue_etf.json")
    with open(berkas, encoding="utf-8") as f:
        simpan = json.load(f)
    isi = simpan["data"].get(f"{jenis}/historis")
    baris = isi.get("data") if isinstance(isi, dict) else isi
    baris = [b for b in baris if isinstance(b, dict) and b.get("date")]
    baris.sort(key=lambda b: b["date"])
    return baris, None


def test_etf_hanya_btc_dan_eth():
    """Koin lain TIDAK punya ETF spot AS. Meminjam angka BTC untuk SOL itu karangan."""
    h = _etf.analisa("SOL")
    assert "tidak_tersedia" in h
    assert "JANGAN" in h["tidak_tersedia"]


def test_etf_menghitung_dari_data_nyata(monkeypatch):
    """Diuji terhadap balasan API yang sebenarnya, bukan data buatan."""
    import sosovalue
    monkeypatch.setattr(sosovalue, "historis_etf", _muat_etf_tersimpan)
    h = _etf.analisa("BTC")
    assert h["hari_terekam"] == 300
    assert h["arus_5_hari"]["persentil"] is not None
    assert 0 <= h["arus_5_hari"]["persentil"] <= 100
    # Umur data ETF selalu beberapa hari; peringatannya harus menyala.
    # Peringatan kesegaran hanya menyala di atas 3 hari, jadi tes TIDAK boleh menuntutnya
    # selalu ada — data yang baru disegarkan justru membuatnya diam. Yang diuji: ambangnya.
    assert h["umur_data_hari"] >= 0
    assert ("peringatan_kesegaran" in h) == (h["umur_data_hari"] >= 3)


def test_etf_menandai_divergensi_harga_vs_arus(monkeypatch):
    """Bagian paling bernilai: harga dan arus berpisah.

    Ini yang tidak terlihat dari chart maupun on-chain, dan justru sinyal yang dicari
    kerangka kesehatan pasar.
    """
    import sosovalue
    baris = [{"date": f"2026-0{i // 28 + 1}-{i % 28 + 1:02d}",
              "totalNetInflow": -50_000_000.0, "totalNetAssets": 1e10,
              "cumNetInflow": 1e9} for i in range(60)]
    monkeypatch.setattr(sosovalue, "historis_etf", lambda j="us-btc-spot": (baris, None))
    monkeypatch.setattr(_etf, "_gerak_harga", lambda s, n: 8.0)   # harga NAIK
    h = _etf.analisa("BTC")
    assert "distribusi" in h["divergensi_20_hari"]["pola"].lower()

    monkeypatch.setattr(_etf, "_gerak_harga", lambda s, n: -8.0)  # harga TURUN
    for b in baris:
        b["totalNetInflow"] = 50_000_000.0
    h2 = _etf.analisa("BTC")
    assert "akumulasi" in h2["divergensi_20_hari"]["pola"].lower()


def test_etf_tanpa_kunci_tidak_mati(monkeypatch):
    """Pola yang sama dengan Finnhub: lapor tidak tersedia, analisa crypto tetap jalan."""
    monkeypatch.delenv("SOSOVALUE_API_KEY", raising=False)
    import sosovalue
    monkeypatch.setattr(sosovalue, "_muat_cache", dict)
    h = _etf.analisa("BTC")
    assert "tidak_tersedia" in h


def test_etf_hanya_dijalankan_untuk_btc_eth():
    """Koin lain akan menolak dengan pesan yang sama tiap kali — jangan buang waktu."""
    sumber = open(os.path.join(AKAR, "cloud", "bot_oneshot.py"), encoding="utf-8").read()
    blok = sumber[sumber.index("def data_mentah_crypto"):sumber.index("def data_mentah_pasar")]
    assert 'if t in ("BTC", "ETH"):' in blok
    assert "cloud/etf.py" in blok


def test_kunci_sosovalue_dioper_ke_runner():
    """Arus ETF berubah tiap hari, jadi harus ditarik saat analisa — bukan berkas tersimpan."""
    alur = open(os.path.join(AKAR, ".github", "workflows", "bot.yml"), encoding="utf-8").read()
    assert "SOSOVALUE_API_KEY: ${{ secrets.SOSOVALUE_API_KEY }}" in alur


def test_satu_sumber_kejutan_per_acara():
    """Menjalankan dua sumber untuk acara yang sama itu membayar dua kali.

    CPI kini memakai konsensus pasar SoSoValue di ketiga jalur; nowcast Cleveland Fed
    tetap ada sebagai cadangan lewat --sumber nowcast, tapi tidak ikut di brief.
    """
    sumber = open(os.path.join(AKAR, "cloud", "bot_oneshot.py"), encoding="utf-8").read()
    assert sumber.count('"--indikator", "CPI"') == 3, "CPI dipanggil di crypto, forex, saham"
    # Setiap pemanggilan CPI harus menyertakan sumber sosovalue.
    for potong in sumber.split('"--indikator", "CPI"')[1:]:
        assert '"sosovalue"' in potong[:120], "ada jalur CPI yang belum pakai konsensus pasar"


def test_kalender_tidak_lagi_di_brief_tapi_tetap_dijadwalkan():
    """Konsensusnya sudah dari SoSoValue, tapi arsip independen harus tetap tumbuh."""
    sumber = open(os.path.join(AKAR, "cloud", "bot_oneshot.py"), encoding="utf-8").read()
    assert '"cloud/kalender.py", "--ringkas"' not in sumber, "kalender.py masih di brief"
    rapor = open(os.path.join(AKAR, ".github", "workflows", "rapor.yml"),
                 encoding="utf-8").read()
    assert "cloud/kalender.py" in rapor, "arsip konsensus tidak akan tumbuh lagi"
    assert "cloud/data/arsip_konsensus.jsonl" in rapor


def test_perbedaan_antar_sumber_cpi_tercatat():
    """Dua definisi kejutan memberi tanda BERLAWANAN — itu temuan, bukan detail teknis."""
    teks = " ".join(open(os.path.join(AKAR, "cloud", "prompts", "peran", "prediktor.md"),
                         encoding="utf-8").read().split())
    assert "BERBALIK tergantung ekspektasi siapa" in teks
    assert "TIDAK punya edge arah untuk emas" in teks


def test_penyegaran_sosovalue_terjadwal_mingguan():
    """Riwayat konsensus disimpan sebagai berkas, jadi ia HANYA segar kalau ditarik ulang.

    Tanpa jadwal, rilis NFP/CPI/PPI baru tidak akan pernah masuk dan studi kejutan
    diam-diam memakai data yang makin tua tanpa tanda apa pun.
    """
    alur = open(os.path.join(AKAR, ".github", "workflows", "periksa-sosovalue.yml"),
                encoding="utf-8").read()
    assert 'cron: "0 5 * * 0"' in alur, "Minggu 05:00 UTC = 12:00 WIB"
    assert "workflow_dispatch" in alur, "harus tetap bisa dijalankan manual"
    assert "--tarik-riwayat" in alur and "--tarik-etf" in alur
    # Penemuan endpoint sudah selesai; menjalankannya mingguan membuang kuota.
    assert "--periksa --tarik" not in alur


def test_penyegaran_menyimpan_kedua_berkas():
    """Menarik tanpa menyimpan berarti runner ephemeral membuangnya begitu selesai."""
    alur = open(os.path.join(AKAR, ".github", "workflows", "periksa-sosovalue.yml"),
                encoding="utf-8").read()
    for berkas in ("cloud/data/sosovalue_riwayat.json", "cloud/data/sosovalue_etf.json"):
        assert alur.count(berkas) == 2, f"{berkas} harus ada di pemeriksaan DAN git add"


# Field yang dibuang --ringkas TAPI memuat kalimat imperatif. Boleh ada HANYA kalau aturannya
# sudah ditulis di seed, sehingga model tetap menerimanya. Daftar ini adalah ratchet: setiap
# tambahan baru menggagalkan tes sampai diputuskan secara sadar.
_IMPERATIF_DIIZINKAN = {
    ("proyeksi.py", "cara_pakai"),    # urutan level -> sudah ada di "Batas yang WAJIB disebut"
    ("sosovalue.py", "cara_pakai"),   # batas vintage -> sudah ada di blok forex
}


def test_aturan_keras_tidak_hilang_saat_ringkas():
    """--ringkas dipakai PRODUKSI, jadi apa pun yang dibuangnya tidak pernah sampai ke model.

    Bug nyata: aturan "angka gabungan TIDAK BOLEH dikutip sendirian" ditaruh di field
    bernama `cara_baca`, dan kalimat yang memberitahu model harus berbuat apa saat vonis
    gugur ditaruh di `arti`. Keduanya ada di _PANDUAN_STATIS, jadi produksi hanya menerima
    angka dan boolean telanjang.
    """
    from backtest import _PANDUAN_STATIS
    imperatif = ("TIDAK BOLEH", "WAJIB", "JANGAN", "Jangan", "jangan", "harus")
    temuan = []
    for berkas in ("kejutan.py", "proyeksi.py", "jadwal.py", "etf.py", "arsip.py",
                   "sosovalue.py", "indicators.py", "backtest.py", "makro.py", "kalender.py"):
        teks = open(os.path.join(AKAR, "cloud", berkas), encoding="utf-8").read()
        for nama in _PANDUAN_STATIS:
            for m in re.finditer('"' + nama + r'":\s*\(?((?:\s*"[^"]*")+)', teks):
                if any(k in m.group(1) for k in imperatif):
                    if (berkas, nama) not in _IMPERATIF_DIIZINKAN:
                        temuan.append(f"{berkas}:{nama}")
    assert not temuan, ("aturan keras berada di field yang dibuang --ringkas: "
                        + ", ".join(sorted(set(temuan))))


def test_field_mutu_bukan_nama_yang_dibuang():
    """Nama-nama ini sengaja dipilih supaya lolos dari _PANDUAN_STATIS."""
    from backtest import _PANDUAN_STATIS
    for nama in ("wajib_dibaca", "tindakan", "satuan", "peringatan_cakupan",
                 "peringatan_kesegaran", "peringatan_metode", "batas_wajib_disebut"):
        assert nama not in _PANDUAN_STATIS, nama
    for berkas, harus in (("kejutan.py", ("wajib_dibaca", "tindakan")),
                          ("proyeksi.py", ("wajib_dibaca", "peringatan_metode")),
                          ("jadwal.py", ("satuan",)),
                          ("etf.py", ("peringatan_kesegaran",))):
        teks = open(os.path.join(AKAR, "cloud", berkas), encoding="utf-8").read()
        for h in harus:
            assert f'"{h}"' in teks, f"{berkas} tidak memakai {h}"


def test_aturan_urutan_level_ada_di_seed():
    """Dipindah ke seed karena field aslinya memang dibuang --ringkas."""
    teks = " ".join(open(os.path.join(AKAR, "cloud", "prompts", "peran", "prediktor.md"),
                         encoding="utf-8").read().split())
    assert "HARUS melewatinya dulu" in teks

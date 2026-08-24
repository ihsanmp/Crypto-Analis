"""Statistik jejak rekam panggilan — seberapa MENGUNTUNGKAN, bukan seberapa sering benar.

Diambil dari crates/analysis milik nautilus_trader (nautechsystems), yang memisahkan
tingkat menang dari ekspektansi. Pemisahan itu penting karena keduanya bisa berlawanan:
panggilan yang benar 90% kali dengan imbalan +2% dan salah 10% kali dengan rugi -30%
adalah panggilan yang RUGI, dan rapor yang hanya melaporkan "menang 90%" akan
menyebutnya keahlian.

Yang TIDAK diambil dari nautilus: mesin eksekusi, order management, message bus, adapter
bursa, backtest engine. Bot ini tidak mengirim order — semua itu tidak punya padanan di
sini dan menyalinnya hanya menambah kode yang tak pernah dijalankan.

Konvensi angka mengikuti nautilus: nol adalah IMPAS, bukan menang dan bukan kalah, jadi
tidak ikut dihitung dalam tingkat menang. Kalau tidak ada sampel, hasilnya None (bukan 0)
supaya "belum ada data" tidak pernah terbaca sebagai "hasilnya nol".
"""

# Ambang yang di bawahnya sebuah panggilan tidak layak diambil: imbalan lebih kecil
# daripada risikonya. Dengan R:R 0,5 kamu harus benar 2 dari 3 kali hanya untuk impas.
RASIO_MINIMUM = 1.0

# Bias yang sarannya MENGURANGI paparan. Target di atas harga pada bias ini adalah
# kontradiksi, bukan imbalan.
_BIAS_TURUN = ("KURANGI", "HINDARI")


def _rata(xs):
    return sum(xs) / len(xs) if xs else None


def pisah(hasil):
    """Pisah daftar hasil (persen) jadi menang / kalah. Nol dianggap impas."""
    menang = [x for x in hasil if x is not None and x > 0]
    kalah = [x for x in hasil if x is not None and x < 0]
    return menang, kalah


def ekspektansi(hasil):
    """Rata-rata hasil per panggilan, ditimbang peluang menang dan kalah.

    Inilah angka yang menentukan: positif berarti mengulang pola ini menambah nilai,
    negatif berarti mengulangnya menghabiskannya — berapa pun tingkat menangnya.
    """
    menang, kalah = pisah(hasil)
    n = len(menang) + len(kalah)
    if n == 0:
        return None
    p_menang = len(menang) / n
    p_kalah = len(kalah) / n
    return (_rata(menang) or 0.0) * p_menang + (_rata(kalah) or 0.0) * p_kalah


def faktor_untung(hasil):
    """Total keuntungan dibagi total kerugian. Di bawah 1 berarti merugi.

    None kalau belum ada satu pun kerugian — bukan tak terhingga. Rangkaian menang
    tanpa satu kekalahan belum membuktikan apa pun tentang besar kerugiannya nanti.
    """
    menang, kalah = pisah(hasil)
    total_kalah = abs(sum(kalah))
    if total_kalah == 0:
        return None
    return sum(menang) / total_kalah


def rasio_imbalan(hasil):
    """Rata-rata menang dibagi rata-rata kalah. Seberapa besar menangnya dibanding rugi."""
    menang, kalah = pisah(hasil)
    if not menang or not kalah:
        return None
    r = _rata(kalah)
    return _rata(menang) / abs(r) if r else None


def penurunan_maksimum(hasil):
    """Penurunan terdalam dari puncak, kalau panggilan dijalankan berurutan.

    Bukan sekadar kekalahan terbesar: tiga kekalahan berturut-turut yang masing-masing
    kecil bisa lebih menyakitkan — dan lebih menentukan apakah pemakainya bertahan —
    daripada satu kekalahan besar yang langsung pulih.
    """
    if not hasil:
        return None
    nilai = 1.0
    puncak = 1.0
    terdalam = 0.0
    for h in hasil:
        if h is None:
            continue
        nilai *= (1.0 + h / 100.0)
        puncak = max(puncak, nilai)
        turun = (puncak - nilai) / puncak
        terdalam = max(terdalam, turun)
    return -round(terdalam * 100, 2)


def ringkas(hasil):
    """Satu set statistik dari daftar hasil persen. Semua bisa None kalau sampelnya kosong."""
    bersih = [h for h in hasil if h is not None]
    menang, kalah = pisah(bersih)
    n = len(menang) + len(kalah)

    def bulat(x, d=2):
        return round(x, d) if x is not None else None

    return {
        "dinilai": len(bersih),
        "menang": len(menang),
        "kalah": len(kalah),
        "impas": len(bersih) - n,
        "menang_persen": bulat(len(menang) / n * 100, 1) if n else None,
        "menang_rata2_persen": bulat(_rata(menang)),
        "kalah_rata2_persen": bulat(_rata(kalah)),
        "kalah_terburuk_persen": bulat(min(kalah)) if kalah else None,
        "ekspektansi_persen": bulat(ekspektansi(bersih)),
        "faktor_untung": bulat(faktor_untung(bersih)),
        "rasio_imbalan": bulat(rasio_imbalan(bersih)),
        "penurunan_maksimum_persen": penurunan_maksimum(bersih),
    }


# ------------------------------------------------- pemeriksaan sebelum panggilan

def imbalan_risiko(harga, target, invalid, bias=None):
    """Jarak ke target dibanding jarak ke level invalid, dalam persen.

    MEMAKAI RATA-RATA SELURUH TARGET, bukan target pertama. Versi pertama fungsi ini
    memakai `target[0]` saja, dan itu keliru: rencananya bertahap — sebagian posisi keluar
    di tiap target — sehingga membandingkan target PERTAMA dengan stop PENUH adalah apel
    lawan jeruk. Kekeliruan itu membuat panggilan HYPE terbaca 0,33 padahal di target
    terakhir 2,15, dan seluruh rekam jejak terlihat jauh lebih buruk daripada sebenarnya.

    Rata-rata sederhana dipilih karena balasannya TIDAK menyebut porsi keluar di tiap
    target. Menebak bobot 40/35/25 akan terlihat lebih presisi tanpa dasar; rata-rata rata
    adalah asumsi paling sedikit mengarang, dan asumsinya disebut di keluarannya.

    Padanan pemeriksaan pra-order di RiskEngine nautilus: di sana order yang melanggar
    batas DITOLAK sebelum dikirim, dengan alasannya disebut. Di sini panggilan tidak
    ditolak — user bertanya dan berhak dijawab — tetapi rasionya dicatat supaya kelemahan
    yang sama tidak lolos tanpa terlihat.

    Return None kalau levelnya tidak lengkap; itu keadaan yang sah dan bukan kegagalan.
    """
    if not harga or not invalid or not target:
        return None
    tg = [t for t in (target if isinstance(target, (list, tuple)) else [target]) if t]
    if not tg:
        return None
    risiko = abs(harga - invalid) / harga * 100
    if risiko == 0:
        return None

    jarak = [abs(t - harga) / harga * 100 for t in tg]
    imbalan = sum(jarak) / len(jarak)
    hasil = {
        "imbalan_persen": round(imbalan, 2),
        "risiko_persen": round(risiko, 2),
        "rasio_imbalan_risiko": round(imbalan / risiko, 2),
        "jumlah_target": len(tg),
        "dasar": "rata-rata seluruh target (porsi keluar per target tidak disebutkan)",
    }
    if len(tg) > 1:
        hasil["rasio_target_pertama"] = round(jarak[0] / risiko, 2)
        hasil["rasio_target_terakhir"] = round(jarak[-1] / risiko, 2)

    # Target yang arahnya melawan bias bukan imbalan, itu kontradiksi. Menghitungnya
    # sebagai "imbalan" membuat panggilan KURANGI terlihat punya potensi untung dari
    # harga NAIK — persis kebalikan dari sarannya sendiri.
    if bias in _BIAS_TURUN and tg[0] > harga:
        hasil["arah_bertentangan"] = (
            f"bias {bias} tapi target pertama (${tg[0]:g}) DI ATAS harga (${harga:g}). "
            "Levelnya ditulis dalam kerangka beli walau sarannya kurangi — rasio di sini "
            "tidak bisa dibaca sebagai imbalan.")
    return hasil


def perlu_benar_persen(rasio):
    """Berapa persen panggilan harus benar hanya untuk IMPAS pada rasio ini.

    Menerjemahkan rasio jadi kalimat yang bisa diuji: dengan R:R 0,07, kamu harus benar
    93% kali hanya untuk tidak rugi — dan tidak ada analis yang seakurat itu.
    """
    if rasio is None or rasio <= 0:
        return None
    return round(1 / (1 + rasio) * 100, 1)

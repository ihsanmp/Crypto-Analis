"""Tes logregresi.py — chart regresi log BTC 2014 yang ditanam ke agent.

DUA LAPIS PEMBUKTIAN:

1. BACAAN CHART-NYA. Rumus y = 2,9065·ln(x) − 19,493 harus menghasilkan ulang SEMUA angka
   di gambar yang dikirim user (24 Sep 2026): enam tonggak harga, deretan nilai akhir
   tahun, dan jeda antar-10x. Kalau satu saja meleset jauh, bacaan kita yang salah —
   dan semua kesimpulan sesudahnya ikut salah.

2. UJIAN LUAR-SAMPELNYA. Chart dibuat 14 Okt 2014; 12 tahun sesudahnya tidak pernah ia
   lihat. Angka ujian itu dipaku di sini (data repo s.d. 1 Sep 2026), karena merekalah
   yang ditanam ke agent — bukan garisnya.
"""

import datetime as dt
import math
import os
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import logregresi as lr  # noqa: E402

T = dt.date.fromisoformat


@pytest.fixture(scope="module")
def data_repo():
    """Riwayat di repo apa adanya — s.d. 1 Sep 2026, tanpa jaringan."""
    return lr.muat()


@pytest.fixture(scope="module")
def hasil_repo(data_repo):
    return lr.analisa(data_repo)


# ---- 1. bacaan chart ----------------------------------------------------------------------

@pytest.mark.parametrize("harga,tercetak", sorted(lr.TONGGAK_CHART.items()))
def test_rumus_menghasilkan_ulang_tonggak_di_chart(harga, tercetak):
    selisih = abs((lr.tanggal_untuk(harga) - T(tercetak)).days)
    assert selisih <= 3, f"${harga}: rumus meleset {selisih} hari dari chart"


@pytest.mark.parametrize("tahun,tercetak", [
    (2009, 0.004), (2010, 0.44), (2011, 6.77), (2012, 46.96), (2013, 209.5),
    (2014, 710.6), (2015, 1994), (2016, 4885), (2017, 10741), (2018, 21729),
    (2019, 41097), (2020, 74689), (2021, 127623), (2022, 209599), (2023, 332632)])
def test_deretan_atas_chart_adalah_nilai_akhir_tahun(tahun, tercetak):
    """Labelnya diletakkan di AWAL tahun, tapi nilainya milik AKHIR tahun. Dibaca sebagai
    nilai awal tahun, semuanya meleset 36-99% — dan kita akan menyimpulkan chart-nya
    salah, padahal bacaan kitalah yang salah."""
    nilai = lr.garis(dt.date(tahun + 1, 1, 1))
    assert abs(nilai / tercetak - 1) < 0.03, (tahun, nilai, tercetak)


def test_jeda_antar_10x_sama_dengan_chart():
    tercetak = [336, 474, 669, 943, 1332]
    hitung = [(lr.tanggal_untuk(p * 10) - lr.tanggal_untuk(p)).days
              for p in (1, 10, 100, 1000, 10000)]
    for h, c in zip(hitung, tercetak):
        assert abs(h - c) <= 3, (hitung, tercetak)


@pytest.mark.parametrize("dari,ke,tercetak", [
    (2021, 2022, 164), (2022, 2023, 159), (2017, 2018, 202), (2014, 2015, 281)])
def test_persen_di_chart_adalah_kelipatan_bukan_kenaikan(dari, ke, tercetak):
    """"159%" berarti garisnya 1,59× setahun (naik 59%), BUKAN naik 159%. Kalau dibaca
    sebagai kenaikan, setiap angka meleset tepat 100 poin — itu yang membedakan kedua
    bacaan, dan hanya satu yang cocok."""
    kelipatan = lr.garis(dt.date(ke + 1, 1, 1)) / lr.garis(dt.date(dari + 1, 1, 1))
    assert abs(100 * kelipatan - tercetak) <= 3
    assert abs(100 * (kelipatan - 1) - tercetak) > 90


def test_baris_hijau_juga_kelipatan():
    """Harga aktual akhir tahun 2010-2013 di baris hijau: 5,10 -> 13,34 ditulis "262%",
    padahal kenaikannya 162%."""
    for a, b, tercetak in ((0.30, 5.10, 1700), (5.10, 13.34, 262), (13.34, 745.45, 5588)):
        assert round(100 * b / a) == tercetak


def test_rasio_10x_adalah_bawaan_rumus_bukan_temuan():
    """"Tiap 10x makin lama 1,41×" = e^(1/a). Mengutipnya sebagai bukti tambahan berarti
    menghitung satu asumsi dua kali."""
    assert round(lr.rasio_10x(lr.A_2014), 2) == 1.41
    jeda = [(lr.tanggal_untuk(p * 10) - lr.tanggal_untuk(p)).days for p in (10, 100, 1000)]
    assert all(abs(b / a - lr.rasio_10x(lr.A_2014)) < 0.01 for a, b in zip(jeda, jeda[1:]))


def test_hari_nol_9_januari_bukan_genesis():
    """Dengan blok genesis (3 Jan 2009) semua tonggak bergeser 6-9 hari — bukti bahwa
    hari nol chart ini adalah rilis Bitcoin v0.1."""
    asli = lr.NOL
    try:
        lr.NOL = dt.date(2009, 1, 3)
        meleset = [abs((lr.tanggal_untuk(p) - T(t)).days) for p, t in lr.TONGGAK_CHART.items()]
    finally:
        lr.NOL = asli
    assert min(meleset) >= 6


# ---- 2. matematika fit --------------------------------------------------------------------

def test_fit_memulihkan_parameter_yang_diketahui():
    a0, b0 = 2.5, -17.0
    data = {lr.NOL + dt.timedelta(days=d): 10 ** (a0 * math.log(d) + b0)
            for d in range(1000, 6000, 7)}
    a, b, r2, _res, _ac = lr.fit(data)
    assert abs(a - a0) < 1e-9 and abs(b - b0) < 1e-9 and r2 > 0.999999


# ---- 3. ujian luar-sampel (dipaku; data repo s.d. 1 Sep 2026) -----------------------------

def test_garis_2014_hampir_tak_pernah_tersentuh_sesudah_dibuat(hasil_repo):
    c = hasil_repo["chart_2014"]
    assert (c["hari_di_atas_garis"], c["hari_sesudah_chart"]) == (53, 4340)
    # Ke-53 hari itu semuanya di puncak gelembung 2017: di luar sampelnya, garis ini
    # bekerja sebagai garis PUNCAK, bukan garis tengah.
    assert c["pertama_di_atas"] == "2017-12-01" and c["terakhir_di_atas"] == "2018-01-28"


def test_satu_ramalan_jitu_satu_meleset_bertahun_tahun(hasil_repo):
    r = {x["harga"]: x for x in hasil_repo["chart_2014"]["ramalan"]}
    assert r[10000]["selisih_hari"] == 10
    assert r[100000]["selisih_hari"] == 1244
    assert r[1000000]["nyata_close_pertama"] is None


def test_garis_wajar_goyah_terhadap_batas_data(hasil_repo):
    """Garis untuk HARI YANG SAMA berbeda puluhan persen tergantung di mana datanya
    dipotong — terlalu goyah untuk jadi jangkar harga."""
    assert hasil_repo["kepekaan_selisih_persen"] >= 40
    assert len(hasil_repo["kepekaan"]) == 3


def test_r2_tinggi_menutupi_residu_yang_nyaris_random_walk(hasil_repo):
    f = hasil_repo["fit_ulang"]
    assert f["r2"] > 0.9 and f["autokorelasi_residu_lag1"] > 0.99


def test_parameter_a_priori_tidak_diubah_diam_diam():
    """Mengubah titik potong sesudah melihat hasilnya adalah cara termudah membuat
    angka apa pun terlihat dramatis."""
    assert lr.POTONG_KEPEKAAN == (dt.date(2017, 12, 31), dt.date(2021, 12, 31))
    assert lr.TONGGAK_UJI == (10000, 100000, 1000000)


# ---- 4. blok brief ------------------------------------------------------------------------

def test_blok_menyebut_batasnya_sendiri(hasil_repo):
    teks = lr.ringkas(hasil_repo)
    for wajib in ("BUKAN ramalan", "SUDAH GAGAL", "IN-SAMPLE", "bawaan rumus",
                  "autokorelasi residu", "garis PUNCAK", "mulai 2012"):
        assert wajib in teks, wajib


def test_ramalan_yang_belum_lewat_tidak_dinilai(data_repo):
    """Sebelum 1 Sep 2026, ramalan $1 juta belum jatuh tempo — "belum pernah sampai"
    untuk ramalan yang tanggalnya belum tiba adalah penilaian yang tidak adil."""
    lama = {t: c for t, c in data_repo.items() if t <= dt.date(2025, 6, 30)}
    teks = lr.ringkas(lr.analisa(lama))
    assert "belum lewat, belum bisa dinilai" in teks
    assert "BELUM PERNAH" not in teks


def test_harga_acuan_dari_brief_yang_dipakai(data_repo):
    """Angka di blok ini harus sama dengan harga di sisa brief, bukan harga dari tarikan
    kedua yang bisa berbeda beberapa menit."""
    h = lr.analisa(data_repo, 84141.0, dt.date(2026, 9, 24))
    assert h["harga"] == 84141.0 and h["tanggal"] == "2026-09-24"
    assert "$84.141" in lr.ringkas(h)


def test_gagal_menyambung_data_dikatakan(hasil_repo):
    teks = lr.ringkas(hasil_repo, galat_baru="URLError")
    assert "GAGAL" in teks and "URLError" in teks


def test_angka_bergaya_indonesia_tanpa_merusak_kalimat(hasil_repo):
    """`.replace(",", ".")` pada kalimat utuh sempat mengubah koma kalimat jadi titik:
    "nyata 8 Des 2024. terlambat"."""
    teks = lr.ringkas(hasil_repo)
    assert "8 Des 2024, terlambat 1.244 hari" in teks
    assert lr._d(0.0816, 3) == "0,082" and lr._d(1244) == "1.244"
    assert lr._usd(1023270) == "$1.023.270"

def test_celah_data_disebut_bukan_disembunyikan(data_repo):
    """Run lokal 24 Sep 2026: penyambung data gagal, harga dari brief ditempel, dan
    laporannya berbunyi "data s.d. 24 Sep ... berhenti di tanggal itu" — padahal
    riwayatnya berhenti 1 Sep. Celah 22 hari itu harus disebut."""
    h = lr.analisa(data_repo, 84136.0, dt.date(2026, 9, 24))
    assert h["data"]["akhir_riwayat"] == "2026-09-01" and h["data"]["celah_hari"] == 22
    teks = lr.ringkas(h, galat_baru="binance: URLError; kraken: URLError; coinbase: "
                                    "URLError; okx: URLError; coingecko: HTTPError")
    assert "s.d. 1 Sep 2026" in teks
    assert "22 hari di antaranya TIDAK ADA" in teks
    assert "s.d. 24 Sep" not in teks


def test_tanpa_celah_tidak_ada_peringatan_celah(data_repo):
    h = lr.analisa(data_repo, 78294.16, dt.date(2026, 9, 1))
    assert h["data"]["celah_hari"] == 0
    assert "TIDAK ADA di data" not in lr.ringkas(h)


def test_galat_panjang_dipendekkan():
    panjang = "; ".join(f"sumber{i}: URLError" for i in range(12))
    h = lr.analisa(lr.muat())
    baris_data = lr.ringkas(h, galat_baru=panjang).split("\n")[1]
    assert len(baris_data) < 220 and "…" in baris_data

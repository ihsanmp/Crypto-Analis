"""Tes alat gratis yang baru disambung: musim.py, devkode.py, dan listing tier-1.

KENAPA BERKAS INI ADA. Ketiganya dibangun 16 Sep 2026 dan ketiganya SEMPAT MENGELUARKAN
ANGKA YANG SALAH TAPI MASUK AKAL — jenis kesalahan yang tidak pernah membuat apa pun merah:

  1. musim.py mencoret SOLANA dari daftar altcoin, karena "Wrapped SOL" juga bersimbol `sol`
     dan pengecualiannya dicocokkan lewat simbol. Indeksnya tetap keluar, cuma salah.
  2. devkode.py melaporkan NOL commit untuk Bittensor, karena repo dipilih per organisasi dan
     organisasi lamanya memang sudah sepi — padahal kerjanya pindah ke organisasi lain.
  3. cache taksonomi dipotong 200 repo, lalu jumlah itu dilaporkan sebagai jumlah repo
     ekosistemnya. Batas cache menyamar jadi fakta.

Tes di bawah mengunci ketiganya. Semuanya tanpa jaringan: bagian yang menghitung sudah
dipisah dari bagian yang mengambil, justru supaya bisa diuji seperti ini.

Menjalankan:  pytest tests/test_alat_gratis.py -v
"""

import os
import sys

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AKAR, "cloud"))

import devkode                     # noqa: E402
import musim                       # noqa: E402
import naratif                     # noqa: E402


# ---------------------------------------------------------------- musim.py

def _koin(id_, sym, ubah):
    return {"id": id_, "symbol": sym, "price_change_percentage_30d_in_currency": ubah}


def _pasar_palsu(n_unggul, kecuali=()):
    """50 koin layak + BTC. `n_unggul` di antaranya mengungguli BTC (+10%)."""
    pasar = [_koin("bitcoin", "btc", 10.0)]
    pasar += list(kecuali)
    for i in range(50):
        pasar.append(_koin(f"koin-{i}", f"k{i}", 20.0 if i < n_unggul else 5.0))
    return pasar


@pytest.mark.parametrize("n_unggul,harap", [(0, 0), (15, 30), (38, 76), (49, 98)])
def test_indeks_musim_sesuai_definisi(n_unggul, harap):
    """Indeks = jumlah yang mengungguli BTC dibagi 50, bukan dibagi jumlah yang terbaca."""
    h = musim.hitung_30h(set(), pasar=_pasar_palsu(n_unggul))
    assert h["indeks"] == harap


def test_vonis_musim():
    assert musim.vonis(76) == "ALTCOIN SEASON"
    assert musim.vonis(25) == "BITCOIN SEASON"
    assert musim.vonis(50) == "tidak keduanya"
    assert musim.vonis(None) is None


def test_pengecualian_lewat_id_bukan_simbol():
    """REGRESI: "Wrapped SOL" bersimbol `sol`. Kalau pengecualian dicocokkan lewat simbol,
    SOLANA ikut tercoret dan indeksnya salah tanpa ada yang terlihat rusak."""
    wsol = _koin("wrapped-solana", "sol", 99.0)
    sol = _koin("solana", "sol", 40.0)
    pasar = [_koin("bitcoin", "btc", 10.0), wsol, sol]
    pasar += [_koin(f"koin-{i}", f"k{i}", 1.0) for i in range(49)]
    h = musim.hitung_30h({"wrapped-solana"}, pasar=pasar)
    assert "SOL" in h["unggul_teratas"]              # SOLANA tetap ikut dan terhitung unggul
    assert h["n_unggul"] == 1                        # wrapped-nya TIDAK dihitung dua kali
    # Penyebutnya tetap 50 (definisi indeksnya), sementara yang dibandingkan 49 koin non-BTC.
    assert h["n_altcoin"] == 49
    assert h["indeks"] == 2


def test_kurang_dari_50_koin_menolak_menghitung():
    """Indeks dari 30 koin bukan indeks yang sama. Lebih baik kosong daripada mirip."""
    pasar = [_koin("bitcoin", "btc", 10.0)] + [_koin(f"k{i}", f"k{i}", 20.0) for i in range(30)]
    assert musim.hitung_30h(set(), pasar=pasar) is None


HALAMAN_ASLI = ('<button class="btn btn-primary" type="button">Altcoin Season '
                '(<!-- -->27<!-- -->)</button><button class="btn btn-secondary" '
                'type="button">Month (<!-- -->33<!-- -->)</button><button>Year '
                '(<!-- -->33<!-- -->)</button>')


def test_urai_situs_halaman_asli():
    """Potongan halaman blockchaincenter 16 Sep 2026, apa adanya."""
    assert musim.urai_situs(HALAMAN_ASLI) == {"musim_90h": 27, "bulan_30h": 33,
                                              "tahun_365h": 33}


@pytest.mark.parametrize("html", [
    "",
    "<p>Altcoin Season Index</p>",                                  # judul saja, tanpa angka
    "<button>Saison des altcoins (<!-- -->27<!-- -->)</button>",    # label berganti
])
def test_urai_situs_gagal_dengan_jujur(html):
    """Halaman yang berubah bentuk harus menghasilkan None, BUKAN angka lain yang kebetulan
    ada di halaman. Scraper yang menebak lebih buruk daripada scraper yang gagal."""
    assert musim.urai_situs(html) is None


def test_urai_situs_menolak_nilai_di_luar_0_100():
    assert musim.urai_situs("<button>Altcoin Season (<!-- -->427<!-- -->)</button>") is None


# ---------------------------------------------------------------- devkode.py

MIGRASI = [
    "ecoadd Bittensor",
    "ecoadd Solana",
    'ecoadd "Subnet Satu"',
    'ecocon Bittensor "Subnet Satu"',   # nama >1 kata memang berkutip di data aslinya
    "repadd Bittensor https://github.com/opentensor/bittensor",
    "repadd Bittensor https://github.com/opentensor/lama",
    "reprem Bittensor https://github.com/opentensor/lama",
    'repadd "Subnet Satu" https://github.com/macrocosm-os/data-universe',
    "repadd Solana https://github.com/solana-labs/solana",
    "repmov https://github.com/opentensor/bittensor https://github.com/RaoFoundation/bittensor",
]


def test_subpohon_ikut_anak_ekosistem():
    sub, semua = devkode._subpohon(MIGRASI, "bittensor")     # huruf kecil pun harus cocok
    assert sub == {"Bittensor", "Subnet Satu"}
    assert "Solana" in semua


def test_subpohon_nama_asing_mengembalikan_none():
    sub, _ = devkode._subpohon(MIGRASI, "Ekosistem Yang Tidak Ada")
    assert sub is None


def test_repo_subpohon_menghormati_urutan_perintah():
    """reprem membuang, repmov memindahkan, dan repo ekosistem lain tidak ikut."""
    repos = devkode._repo_subpohon(MIGRASI, {"Bittensor", "Subnet Satu"})
    assert repos == ["https://github.com/RaoFoundation/bittensor",
                     "https://github.com/macrocosm-os/data-universe"]
    assert "https://github.com/opentensor/lama" not in repos
    assert "https://github.com/solana-labs/solana" not in repos


def test_pilih_repo_lintas_organisasi():
    """REGRESI: repo paling baru di-push harus menang walaupun organisasinya kecil.

    Versi pertama memilih beberapa repo teratas PER organisasi, jadi lima repo mati milik
    organisasi terbesar mengisi seluruh jatah dan repo yang sebenarnya dikerjakan tidak
    pernah ditanyakan — hasilnya "nol commit" untuk ekosistem yang justru sedang ramai.
    """
    kolam = [{"penuh": f"besar/mati-{i}", "push": "2026-04-0%d" % (i + 1)} for i in range(5)]
    kolam.append({"penuh": "kecil/hidup", "push": "2026-09-16"})
    assert devkode.pilih_repo(kolam, n=3)[0]["penuh"] == "kecil/hidup"


def test_pilih_repo_tanpa_tanggal_tidak_meledak():
    kolam = [{"penuh": "a/b"}, {"penuh": "c/d", "push": "2026-01-01"}]
    assert devkode.pilih_repo(kolam, n=2)[0]["penuh"] == "c/d"


def test_hitung_org_hanya_github():
    hitung = devkode._hitung_org(["https://github.com/a/x", "https://github.com/a/y",
                                  "https://gitlab.com/b/z"])
    assert dict(hitung) == {"a": 2}


def test_batas_github_menghentikan_permintaan(monkeypatch):
    """Sekali kena batas, permintaan berikutnya TIDAK ditembakkan lagi — diukur, versi
    pertama menghabiskan 2 menit 35 detik hanya untuk mengumpulkan penolakan."""
    panggil = []

    def palsu(url, timeout=40, kepala=None):
        panggil.append(url)
        return '{"message": "API rate limit exceeded for 1.2.3.4"}'

    monkeypatch.setattr(devkode, "_curl", palsu)
    monkeypatch.setattr(devkode, "_STATUS", {"batas_kena": False})
    assert devkode._gh("/orgs/a/repos") is None
    assert devkode._gh("/orgs/b/repos") is None
    assert len(panggil) == 1


# ---------------------------------------------------------------- listing tier-1

def _tiket(ident, vol, **lain):
    d = {"market": {"identifier": ident}, "converted_volume": {"usd": vol}}
    d.update(lain)
    return d


def test_porsi_volume_tier1():
    tik = [_tiket("binance", 60), _tiket("gdax", 20), _tiket("bursa-antah-berantah", 20)]
    h = naratif.ringkas_tickers(tik)
    assert h["porsi_volume_tier1_persen"] == 80.0
    assert h["n_bursa_tier1"] == 2
    assert h["bursa_tier1"][0] == "Binance"          # urut volume, terbesar dulu


def test_tiket_anomali_dibuang():
    """Volume anomali tidak boleh ikut, di pembilang maupun di penyebut.

    Angkanya sengaja TIDAK simetris. Versi pertama tes ini memakai volume yang sama besar di
    kedua sisi, jadi membuang penyaringnya tidak mengubah persentasenya sama sekali: tesnya
    tetap hijau padahal yang diuji sudah tidak bekerja.
    """
    tik = [_tiket("binance", 50), _tiket("bursa-lain", 50),
           _tiket("bursa-lain", 900, is_anomaly=True)]
    assert naratif.ringkas_tickers(tik)["porsi_volume_tier1_persen"] == 50.0


def test_tiket_basi_dibuang():
    tik = [_tiket("binance", 50), _tiket("bursa-lain", 50),
           _tiket("binance", 900, is_stale=True)]
    assert naratif.ringkas_tickers(tik)["porsi_volume_tier1_persen"] == 50.0


def test_tanpa_tiket_mengembalikan_none():
    assert naratif.ringkas_tickers([]) is None
    assert naratif.ringkas_tickers(None) is None

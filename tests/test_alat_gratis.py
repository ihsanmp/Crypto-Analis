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


def test_push_terbaru_dari_repo_terbaru(monkeypatch):
    """REGRESI: "push terbaru di ekosistem" harus tanggal repo TERBARU, bukan repo pertama
    yang kebetulan dikembalikan organisasi pertama.

    Ketahuan saat uji live: dilaporkan 2026-05-07 padahal repo teratasnya di-push
    2026-09-16. Penyebabnya pilih_repo mengembalikan SALINAN terurut, sedangkan kolam
    aslinya tidak pernah ikut terurut — tanggal yang dilaporkan jadi acak, dan tetap masuk
    akal dibaca, jadi tidak ada yang curiga. Diuji lewat aktivitas(), bukan lewat
    pilih_repo: yang salah dulu pemanggilnya, bukan pengurutannya.
    """
    isi = {"besar": [{"penuh": "besar/lama", "push": "2026-05-07T10:00:00Z"}],
           "kecil": [{"penuh": "kecil/baru", "push": "2026-09-16T02:58:20Z"}]}
    monkeypatch.setattr(devkode, "_repo_org", lambda org: isi.get(org, []))
    monkeypatch.setattr(devkode, "_mingguan", lambda penuh, ulang=1: [1] * 52)
    h = devkode.aktivitas(["besar", "kecil"])
    assert h["push_terbaru_di_ekosistem"] == "2026-09-16"
    assert h["repo_dipantau"][0]["repo"] in ("besar/lama", "kecil/baru")
    assert h["n_repo_dilihat"] == 2


# ---------------------------------------------------------------- naratif.py di bawah 429
#
# Run produksi 35177796577 (17 Sep 2026): "NARATIF TAO (naratif.py): 3.7 detik — GAGAL",
# padahal di laptop jalan normal. Di GitHub Actions belasan skrip lain sudah menembak
# CoinGecko duluan, jadi naratif.py kena batas permintaan — lalu membuang SELURUH blok,
# keluar dengan kode 1, dan bot membuang keluarannya tanpa mencatat alasannya.

GALAT_429 = '{"status": {"error_code": 429, "error_message": "You\'ve exceeded the Rate Limit"}}'


def test_json_coingecko_diulang_saat_429(monkeypatch):
    balasan = [GALAT_429, '{"ok": 1}']
    jeda = []
    monkeypatch.setattr(naratif, "_curl", lambda url, timeout=35: balasan.pop(0))
    monkeypatch.setattr(naratif.time, "sleep", jeda.append)
    assert naratif._json("https://api.coingecko.com/api/v3/coins/bittensor") == {"ok": 1}
    assert jeda == [naratif.JEDA_ULANG_429[0]]


def test_json_menyerah_setelah_jatah_ulang_habis(monkeypatch):
    panggil = []
    monkeypatch.setattr(naratif, "_curl", lambda url, timeout=35: panggil.append(url) or GALAT_429)
    monkeypatch.setattr(naratif.time, "sleep", lambda s: None)
    # Balasan 429 TIDAK boleh diteruskan sebagai data — pemanggil akan membacanya sebagai
    # koin tanpa market_data dan menyimpulkan hal yang salah.
    assert naratif._json("https://api.coingecko.com/api/v3/search?query=TAO") == {}
    assert len(panggil) == len(naratif.JEDA_ULANG_429) + 1


def test_json_sumber_lain_tidak_diulang(monkeypatch):
    """Kegagalan Wikipedia atau Santiment bukan soal kuota CoinGecko; mengulangnya hanya
    membuang puluhan detik dari jatah 300 detik bot."""
    panggil, jeda = [], []
    monkeypatch.setattr(naratif, "_curl", lambda url, timeout=35: panggil.append(url) or "")
    monkeypatch.setattr(naratif.time, "sleep", jeda.append)
    assert naratif._json("https://wikimedia.org/api/rest_v1/x") == {}
    assert len(panggil) == 1 and jeda == []


def test_trending_gagal_bukan_berarti_tidak_trending(monkeypatch):
    monkeypatch.setattr(naratif, "_json", lambda url: {})
    assert naratif.trending_ids() is None


@pytest.mark.parametrize("id_ketemu", [False, True])
def test_coingecko_gagal_tetap_kirim_yang_tidak_butuh_coingecko(monkeypatch, id_ketemu):
    """REGRESI: dulu CoinGecko gagal = blok kosong. Revenue DefiLlama dan musim altcoin
    tidak butuh CoinGecko sama sekali, jadi keduanya harus tetap sampai ke model."""
    monkeypatch.setattr(naratif, "cari_cg_id", lambda s: "bittensor" if id_ketemu else None)
    monkeypatch.setattr(naratif, "coingecko", lambda cg_id: None)
    monkeypatch.setattr(naratif, "trending_ids", lambda: None)
    monkeypatch.setattr(naratif, "dev_activity", lambda slug: None)
    monkeypatch.setattr(naratif, "revenue_1thn", lambda s: 700e6)
    monkeypatch.setattr(naratif, "data_musim", lambda: {"vonis_90h": "tidak keduanya"})
    h = naratif.analisa("tao")
    assert h["koin"] == "TAO"
    assert "batas permintaan" in h["tidak_tersedia"]      # alasan yang jujur, bukan "tidak dikenali" saja
    assert h["kriteria"]["revenue"]["skor"] == 5
    assert h["sinyal_distribusi"]["musim_altcoin"] == {"vonis_90h": "tidak keduanya"}
    assert "TIDAK terukur" in h["catatan"]


def test_naratif_selalu_keluar_nol(monkeypatch, capsys):
    """Bot membuang keluaran skrip yang keluar bukan 0 — termasuk alasan kegagalan dan data
    yang tetap berhasil diambil. Kelengkapan tetap tercatat lewat kunci tidak_tersedia."""
    monkeypatch.setattr(naratif, "analisa", lambda s: {"koin": s, "tidak_tersedia": "x"})
    monkeypatch.setattr(sys, "argv", ["naratif.py", "TAO", "--json"])
    assert naratif.main() == 0
    assert '"tidak_tersedia"' in capsys.readouterr().out


def test_log_bot_mencatat_alasan_gagal(monkeypatch, capsys):
    import bot_oneshot as bot
    monkeypatch.setattr(bot, "jalankan_script", lambda a, b=300, c=0: (None, "data CoinGecko\ngagal"))
    bot._jalankan_terukur("NARATIF TAO (naratif.py)", ["cloud/naratif.py", "TAO"])
    log = capsys.readouterr().err
    assert "GAGAL: data CoinGecko gagal" in log

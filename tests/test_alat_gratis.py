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
    monkeypatch.setattr(naratif, "analisa", lambda s, cg_id=None: {"koin": s, "tidak_tersedia": "x"})
    monkeypatch.setattr(sys, "argv", ["naratif.py", "TAO", "--json"])
    assert naratif.main() == 0
    assert '"tidak_tersedia"' in capsys.readouterr().out


def test_log_bot_mencatat_alasan_gagal(monkeypatch, capsys):
    import bot_oneshot as bot
    monkeypatch.setattr(bot, "jalankan_script", lambda a, b=300, c=0: (None, "data CoinGecko\ngagal"))
    bot._jalankan_terukur("NARATIF TAO (naratif.py)", ["cloud/naratif.py", "TAO"])
    log = capsys.readouterr().err
    assert "GAGAL: data CoinGecko gagal" in log


# ---------------------------------------------------------------- kunci Demo CoinGecko
#
# Run 35178956460: naratif.py ditolak 429 tiga kali walau sudah menunggu, setelah musim.py
# di run yang sama mendapat data. API publik dibatasi per IP, dan IP runner dipakai bersama.
# Kunci Demo memberi kuota sendiri — dan karena repo ini PUBLIK, kuncinya WAJIB lewat header.

import glob     # noqa: E402

import cgkunci  # noqa: E402

KUNCI_PALSU = "CG-kunci-uji-rahasia"


def test_header_hanya_untuk_coingecko_dan_hanya_kalau_ada_kunci(monkeypatch):
    monkeypatch.delenv(cgkunci.NAMA_ENV, raising=False)
    assert cgkunci.header_untuk("https://api.coingecko.com/api/v3/ping") == {}
    monkeypatch.setenv(cgkunci.NAMA_ENV, KUNCI_PALSU)
    assert cgkunci.header_untuk("https://api.coingecko.com/api/v3/ping") == \
        {"x-cg-demo-api-key": KUNCI_PALSU}
    # Kunci CoinGecko tidak boleh ikut terkirim ke sumber lain.
    assert cgkunci.header_untuk("https://api.github.com/repos/a/b") == {}
    assert cgkunci.argumen_curl("https://wikimedia.org/x") == []


def test_kunci_tidak_pernah_lewat_url():
    """Repo publik: URL tercetak di galat, dan kategori.py memakai URL sebagai kunci cache
    yang ikut ter-commit. Parameter URL untuk kunci CoinGecko dilarang di seluruh kode."""
    pelanggar = [p for p in glob.glob(os.path.join(AKAR, "cloud", "*.py"))
                 if "x_cg_demo_api_key" in open(p, encoding="utf-8").read()]
    assert not pelanggar, pelanggar


def test_setiap_modul_coingecko_memakai_cgkunci():
    """Modul baru yang memanggil CoinGecko tanpa cgkunci akan diam-diam kembali memakai API
    publik — dan kembali kena 429 di runner, tanpa ada yang tahu kenapa."""
    lupa = []
    for p in glob.glob(os.path.join(AKAR, "cloud", "*.py")):
        if os.path.basename(p) == "cgkunci.py":
            continue
        isi = open(p, encoding="utf-8").read()
        if "api.coingecko.com" in isi and "cgkunci." not in isi:
            lupa.append(os.path.basename(p))
    assert not lupa, f"memanggil CoinGecko tanpa cgkunci: {lupa}"


def test_curl_mengirim_header_kunci(monkeypatch):
    dipanggil = []

    class Hasil:
        returncode, stdout = 0, "{}"

    monkeypatch.setenv(cgkunci.NAMA_ENV, KUNCI_PALSU)
    monkeypatch.setattr(naratif.subprocess, "run", lambda a, **k: dipanggil.append(a) or Hasil())
    naratif._curl("https://api.coingecko.com/api/v3/coins/bittensor")
    perintah = dipanggil[0]
    assert f"x-cg-demo-api-key: {KUNCI_PALSU}" in perintah
    assert not any(KUNCI_PALSU in x for x in perintah if x.startswith("http"))


def test_urllib_mengirim_header_kunci(monkeypatch):
    import io as _io
    import indicators
    diminta = []

    class Balasan(_io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setenv(cgkunci.NAMA_ENV, KUNCI_PALSU)
    monkeypatch.setattr(indicators.urllib.request, "urlopen",
                        lambda req, timeout=None: diminta.append(req) or Balasan(b"{}"))
    indicators.http_json("https://api.coingecko.com/api/v3/search?query=TAO")
    assert diminta[0].get_header("X-cg-demo-api-key") == KUNCI_PALSU
    assert KUNCI_PALSU not in diminta[0].full_url


def test_jeda_ulang_melewati_satu_jendela_kuota():
    """REGRESI: jeda (8, 20) = 28 detik belum melewati jendela per menit — run 35178956460
    ditolak di ketiga percobaannya."""
    assert sum(naratif.JEDA_ULANG_429) >= 60


def test_naratif_memakai_cg_id_dari_pemanggil(monkeypatch):
    """id yang sudah ditemukan bot tidak dicari ulang: satu permintaan CoinGecko lebih
    sedikit, tepat saat kuota paling tipis."""
    def jangan_dipanggil(simbol):
        raise AssertionError("cari_cg_id tidak boleh dipanggil kalau cg_id sudah diberikan")

    diminta = []
    monkeypatch.setattr(naratif, "cari_cg_id", jangan_dipanggil)
    monkeypatch.setattr(naratif, "coingecko", lambda cg_id: diminta.append(cg_id) or None)
    monkeypatch.setattr(naratif, "trending_ids", lambda: None)
    monkeypatch.setattr(naratif, "dev_activity", lambda slug: None)
    monkeypatch.setattr(naratif, "revenue_1thn", lambda s: None)
    monkeypatch.setattr(naratif, "data_musim", lambda: None)
    naratif.analisa("TAO", cg_id="bittensor")
    assert diminta == ["bittensor"]


def test_bot_meneruskan_cg_id_ke_naratif(monkeypatch):
    import bot_oneshot as bot
    dijalankan = []
    monkeypatch.setitem(bot._CG_ID_KOIN, "TAO", "bittensor")
    monkeypatch.setattr(bot, "_jalankan_terukur",
                        lambda label, args, min_kar=0: dijalankan.append(args) or ("{}", None))
    bot.data_naratif("TAO")
    assert dijalankan[0][-2:] == ["--cg-id", "bittensor"]


# ---------------------------------------------------------------- tim & VC vs developer
#
# Run 35185856360 (17 Sep 2026): model menilai "Tim & VC: 2 — aktivitas dev MELEMAH", padahal
# pertanyaan kriteria itu di slide adalah "didukung fund tier-1 yang kredibel?". Dan ia
# mengutip "skor dev Santiment turun 32 -> 0" sebagai penguat, padahal sehari sebelumnya
# terbukti Santiment melacak repo yang sudah ditinggalkan. Keduanya bersumber dari alat ini
# sendiri: data developer ditaruh DI DALAM tim_vc, dan prompt menyebutnya alasan menurunkan skor.

import re       # noqa: E402

GH_TAO = {"commit_per_minggu_4_minggu": 79.0, "commit_per_minggu_12_minggu_sebelumnya": 151.0,
          "tren": "melemah"}


def test_santiment_nol_padahal_github_aktif_ditandai_bertentangan():
    """Angka nyata run 35185856360: Santiment 32 -> 0, GitHub 79 commit/minggu."""
    s = naratif.bandingkan_santiment(
        {"rata_4_minggu": 0.0, "rata_12_minggu_sebelumnya": 32.0, "tren": "melemah"}, GH_TAO)
    assert s["bertentangan_dengan_github"] is True
    assert "JANGAN" in s["catatan"] and "79" in s["catatan"]


def test_santiment_sejalan_tetap_sekunder_tanpa_tanda_konflik():
    s = naratif.bandingkan_santiment(
        {"rata_4_minggu": 40.0, "rata_12_minggu_sebelumnya": 80.0, "tren": "melemah"}, GH_TAO)
    assert "bertentangan_dengan_github" not in s
    assert s["peran"].startswith("sekunder")


def test_santiment_tren_berbeda_diberi_catatan():
    s = naratif.bandingkan_santiment(
        {"rata_4_minggu": 60.0, "rata_12_minggu_sebelumnya": 20.0, "tren": "menguat"}, GH_TAO)
    assert "bertentangan_dengan_github" not in s
    assert "Pakai GitHub" in s["catatan"]


def test_santiment_tanpa_github_tidak_diturunkan():
    """Tanpa GitHub, Santiment satu-satunya sumber — jangan diberi label sekunder palsu."""
    asli = {"rata_4_minggu": 5.0, "rata_12_minggu_sebelumnya": 5.0, "tren": "stabil"}
    assert naratif.bandingkan_santiment(asli, None) == asli


def _cg_palsu():
    return {"nama": "Bittensor", "peringkat": 40, "beredar": 11.34e6, "maks": 21e6,
            "total": 21e6, "mcap": 2.55e9, "fdv": 4.7e9, "volume": 1.87e8, "harga": 263.0,
            "ath": 767.0, "ubah_30h": 17.0, "ubah_1thn": -40.0, "kategori": ["AI"],
            "repo": [], "tickers": []}


def test_tim_vc_tidak_berisi_data_developer(monkeypatch):
    monkeypatch.setattr(naratif, "coingecko", lambda cg_id: _cg_palsu())
    monkeypatch.setattr(naratif, "trending_ids", lambda: set())
    monkeypatch.setattr(naratif, "dev_activity",
                        lambda slug: {"rata_4_minggu": 0.0, "rata_12_minggu_sebelumnya": 32.0,
                                      "tren": "melemah"})
    monkeypatch.setattr(naratif, "revenue_1thn", lambda s: None)
    monkeypatch.setattr(naratif, "data_musim", lambda: None)
    monkeypatch.setattr(naratif, "pageviews", lambda j: None)
    monkeypatch.setattr(naratif, "berita_7_hari", lambda n: 37)
    monkeypatch.setattr(naratif, "data_devkode", lambda s, n, r: {"github": GH_TAO})
    h = naratif.analisa("TAO", cg_id="bittensor")
    tim_vc = h["kriteria"]["tim_vc"]
    teks = str(tim_vc)
    assert "commit" not in teks and "aktivitas_developer" not in teks
    assert "PENDUKUNG" in tim_vc["catatan"]
    # Data developer tetap ada — di tempatnya sendiri.
    assert h["developer_github"] == {"github": GH_TAO}
    assert h["developer_santiment"]["bertentangan_dengan_github"] is True


_MENGAITKAN_DEV_KE_TIM = re.compile(r"(menurunkan|mengurangi) skor tim", re.I)


def test_wajib_dibaca_tidak_mengaitkan_developer_ke_skor_tim():
    assert not _MENGAITKAN_DEV_KE_TIM.search(naratif.WAJIB_DIBACA)
    assert "BUKAN untuk skor tim & VC" in naratif.WAJIB_DIBACA
    assert "invalidasi" in naratif.WAJIB_DIBACA.lower()


def test_prompt_chat_tidak_mengaitkan_developer_ke_skor_tim():
    teks = open(os.path.join(AKAR, "cloud", "prompts", "chat.md"), encoding="utf-8").read()
    i = teks.index("BLOK: naratif-mentor")
    blok = teks[i:teks.find("<!-- BLOK:", i + 10) if "<!-- BLOK:" in teks[i + 10:] else None]
    assert not _MENGAITKAN_DEV_KE_TIM.search(blok)
    assert "BUKAN dasar skor tim & VC" in blok
    assert "bertentangan_dengan_github" in blok

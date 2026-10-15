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


def test_arti_kuadran_dari_uji_bukan_teori():
    j = jl.jarum(-0.3, 0.2, terukur=True)
    assert j["fase"] == "KETAT, MULAI MEMBAIK"
    assert "MENOLAKNYA" in j["riwayat_btc_12mg_kuadran_ini"]
    assert j["riwayat_btc_12mg_tersil_skor"].startswith("RENDAH")
    assert "BELUM DIUJI" in jl.jarum(0.3, 0.2)["riwayat"]          # jam adopsi
    assert "TERUJI" in jl.STATUS_BUKTI and "4 minggu TIDAK lolos" in jl.STATUS_BUKTI


def test_adopsi_dari_arus_etf():
    awal = date(2024, 1, 11)
    baris = [{"date": (awal + timedelta(days=i)).isoformat(),
              "totalNetInflow": (100.0 if i % 3 else -50.0) * (1 + i % 11),
              "totalNetAssets": 1e5} for i in range(400)]
    jumat = jl.jumat_dari(awal, awal + timedelta(days=400))
    A = jl.deret_adopsi(baris, jumat)
    assert A["A1"][0] is None and A["A1"][-1] is not None
    assert 0 <= A["A2"][-1] <= 1
    assert any(v is not None for v in A["struktural"])


def test_masuk_brief_crypto():
    src = open(os.path.join(os.path.dirname(__file__), "..", "cloud", "bot_oneshot.py"),
               encoding="utf-8").read()
    assert '"cloud/jam_likuiditas.py", "--ringkas"' in src
    seed = open(os.path.join(os.path.dirname(__file__), "..", "cloud", "prompts", "peran",
                             "analis.md"), encoding="utf-8").read()
    assert "JAM LIKUIDITAS" in seed

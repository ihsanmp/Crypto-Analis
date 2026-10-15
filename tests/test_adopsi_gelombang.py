import io
import os
import sys
import zipfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import adopsi  # noqa: E402
import etf_13f  # noqa: E402
import gelombang  # noqa: E402

_BARIS = ("<tr><td>{}</td><td>1.0</td><td>(2.5)</td><td>-</td><td>{}</td></tr>")


def _html(n=120):
    b = [_BARIS.format(f"{(i % 28) + 1} Feb 2024", "(95.1)" if i % 2 else "1,203.0")
         for i in range(n)]
    b.append("<tr><td>15 Oct 2026</td><td>-</td><td>-</td><td>-</td><td>0.0</td></tr>")
    b.append("<tr><td>Total</td><td>1</td><td>2</td><td>3</td><td>57,027</td></tr>")
    return "<table><tr><th>Date</th><th>IBIT</th></tr>" + "".join(b) + "</table>"


def test_urai_farside_angka_kurung_negatif_dan_hari_kosong_dibuang():
    baris = adopsi.urai_farside(_html())
    assert len(baris) == 120
    assert baris[0] == ("2024-02-01", 1203.0) and baris[1][1] == -95.1
    assert all(t != "2026-10-15" for t, _ in baris)


def test_tantangan_cloudflare_tidak_dianggap_data():
    try:
        adopsi.urai_farside("<title>Just a moment...</title>")
    except ValueError as e:
        assert "Cloudflare" in str(e)
    else:
        raise AssertionError("tantangan Cloudflare lolos sebagai data")


def test_cek_silang_farside_vs_sosovalue():
    far = [("2026-10-01", 100.0), ("2026-10-02", -20.0)]
    soso = [{"date": "2026-10-01", "totalNetInflow": 100e6},
            {"date": "2026-10-02", "totalNetInflow": -90e6}]
    c = adopsi.cek_silang(far, soso)
    assert c["hari_dibandingkan"] == 2 and c["hari_selisih_lebih_50_juta"] == 1


def test_kepemilikan_mulai_dari_gbtc():
    k = adopsi.kepemilikan_btc([("2024-01-11", 50.0)], {"2024-01-11": 50_000.0})
    assert k["2024-01-11"] == adopsi.GBTC_AWAL_BTC + 1000


def test_funding_binance_dinormalkan_ke_8_jam_dan_persen():
    teks = ("calc_time,funding_interval_hours,last_funding_rate\n"
            "1788220800005,8,0.0001\n1788249600000,4,0.0001\n")
    per = gelombang._urai_csv_binance(teks)
    nilai = sorted(v for xs in per.values() for v in xs)
    assert nilai == [0.01, 0.02]


def test_gelombang_mingguan_hanya_hari_sebelum_jumat():
    harian = {f"2026-10-{d:02d}": 1.0 for d in range(2, 9)}
    harian["2026-10-09"] = 999.0                          # hari sinyal itu sendiri
    assert gelombang.ke_mingguan(harian, [date(2026, 10, 9)]) == [1.0]


def test_13f_hanya_etf_spot():
    assert etf_13f.cocok("ISHARES BITCOIN TR")
    assert etf_13f.cocok("ARK 21SHARES BITCOIN ETF")
    assert etf_13f.cocok("FIDELITY WISE ORIGIN BITCOIN")
    assert not etf_13f.cocok("PROSHARES TR BITCOIN STRATEGY")
    assert not etf_13f.cocok("VALKYRIE BITCOIN MINERS ETF")
    assert not etf_13f.cocok("MICROSTRATEGY INC")
    assert not etf_13f.cocok("APPLE INC")


def test_13f_proses_zip_hanya_13f_hr_asli_dan_tanpa_opsi(tmp_path):
    sub = ("ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT\n"
           "A1\t14-MAY-2024\t13F-HR\t1\t31-MAR-2024\n"
           "A2\t15-MAY-2024\t13F-HR\t2\t31-MAR-2024\n"
           "A3\t20-JUN-2024\t13F-HR/A\t1\t31-MAR-2024\n")
    info = ("ACCESSION_NUMBER\tNAMEOFISSUER\tVALUE\tPUTCALL\n"
            "A1\tISHARES BITCOIN TR\t1000\t\n"
            "A1\tFIDELITY WISE ORIGIN BITCOIN\t500\t\n"
            "A1\tISHARES BITCOIN TR\t9999\tPut\n"
            "A2\tGRAYSCALE BITCOIN TR\t300\t\n"
            "A2\tAPPLE INC\t7777\t\n"
            "A3\tISHARES BITCOIN TR\t5555\t\n")
    p = tmp_path / "x_form13f.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("SUBMISSION.tsv", sub)
        z.writestr("INFOTABLE.tsv", info)
    hasil, penerbit = etf_13f.proses_zip(str(p))
    assert hasil == {"2024-03-31": {"filer": 2, "nilai_usd": 1800.0}}
    assert "APPLE INC" not in penerbit

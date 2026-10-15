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
    # Kebocoran nyata dari run 38746731651 (versi pencocokan pertama):
    for nama in ("AMERICAN BITCOIN CORP.", "BTC DEV CORP", "BITCOIN INFRASTRUCTURE ACQUI",
                 "PROSHARES BITCOIN ETF", "GRAYSCALE BITCOIN CASH TRUST BCH",
                 "GRAYSCALE BTC COV CALL ETF", "ROUNDHILL BITCOIN CC STR ETF",
                 "CALAMOS BITCOIN STRUCTURED ALT PROTECTION ETF - JANUARY",
                 "BLACKROCK INSTITUTIONAL TRUST COMPANY N.A. - BTC ISHARES S&P 100 ETF",
                 "PUT ISHR BITCOIN TR ETF $35 EXP 01/15/27"):
        assert not etf_13f.cocok(nama), nama
    for nama in ("GRAYSCALE    BITCOIN     MINI   TR    ET", "RAYSCALE BITCOIN TRUST ETF",
                 "ISHS BITCOIN TRUST", "COINSHARES VALKYRIE BITCOIN FUND",
                 "MORGAN STANLEY BITCOIN TRUST ETP"):
        assert etf_13f.cocok(nama), nama


def _zip_13f(p):
    sub = ("ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT\n"
           "A1\t14-MAY-2024\t13F-HR\t1\t31-MAR-2024\n"
           "A2\t15-MAY-2024\t13F-HR\t2\t31-MAR-2024\n"
           "A3\t20-JUN-2024\t13F-HR/A\t1\t31-MAR-2024\n"
           "A4\t15-MAY-2024\t13F-HR\t4\t31-MAR-2024\n")
    sampul = ("ACCESSION_NUMBER\tFILINGMANAGER_NAME\tCRDNUMBER\tSECFILENUMBER\n"
              "A1\tWEALTH PARTNERS LLC\t000123456\t801-00777\n"
              "A2\tPINE CAPITAL LP\t\t801-99\n"
              "A4\tFIRST NATIONAL BANK\t\t\n")
    info = ("ACCESSION_NUMBER\tNAMEOFISSUER\tVALUE\tPUTCALL\n"
            "A1\tISHARES BITCOIN TR\t1000\t\n"
            "A1\tFIDELITY WISE ORIGIN BITCOIN\t500\t\n"
            "A1\tISHARES BITCOIN TR\t9999\tPut\n"
            "A2\tGRAYSCALE BITCOIN TR\t300\t\n"
            "A2\tAPPLE INC\t7777\t\n"
            "A3\tISHARES BITCOIN TR\t5555\t\n"
            "A4\tISHARES BITCOIN TR\t50\t\n")
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("SUBMISSION.tsv", sub)
        z.writestr("COVERPAGE.tsv", sampul)
        z.writestr("INFOTABLE.tsv", info)


class _KlasPalsu:
    def peta_untuk(self, periode):
        return {("crd", "123456"): "PENASIHAT_KEKAYAAN",
                ("sec", "801-99"): "HEDGE_FUND_DANA_PRIVAT"}, "ia040124.zip"


def test_13f_proses_zip_hanya_13f_hr_asli_dan_tanpa_opsi(tmp_path):
    p = tmp_path / "x_form13f.zip"
    _zip_13f(p)
    hasil, penerbit, _ = etf_13f.proses_zip(str(p))
    h = hasil["2024-03-31"]
    assert (h["filer"], h["nilai_usd"]) == (3, 1850.0)
    assert "APPLE INC" not in penerbit


def test_13f_jenis_pemegang_dari_crd_sec_lalu_nama(tmp_path):
    p = tmp_path / "x_form13f.zip"
    _zip_13f(p)
    hasil, _, ia = etf_13f.proses_zip(str(p), _KlasPalsu())
    pj = hasil["2024-03-31"]["per_jenis"]
    assert pj["PENASIHAT_KEKAYAAN"] == {"filer": 1, "nilai_usd": 1500.0}     # lewat CRD
    assert pj["HEDGE_FUND_DANA_PRIVAT"] == {"filer": 1, "nilai_usd": 300.0}  # lewat 801-
    assert pj["BANK"] == {"filer": 1, "nilai_usd": 50.0}                     # lewat nama
    assert ia == {"2024-03-31": "ia040124.zip"}


def test_jenis_dari_form_adv_5d(tmp_path):
    kepala = ["Organization CRD#", "SEC#"] + [f"5D({h})(3)" for h in "abcdefghijklmn"]
    baris = [["123456", "801-777"] + ["900", "100"] + ["0"] * 12,
             ["999", "801-99"] + ["0"] * 5 + ["5,000,000"] + ["10"] * 8]
    teks = ",".join(kepala) + "\n" + "\n".join(
        ",".join(f'"{x}"' for x in b) for b in baris) + "\n"
    p = tmp_path / "ia090126.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ia09012026.csv", teks)
    peta = etf_13f.baca_ia(str(p))
    assert peta[("crd", "123456")] == "PENASIHAT_KEKAYAAN"
    assert peta[("sec", "801-99")] == "HEDGE_FUND_DANA_PRIVAT"
    assert etf_13f.jenis_dari_nama("PINE CAPITAL LP") == "TIDAK_TERKLASIFIKASI"
    assert etf_13f._tanggal_ia("/x/ia100226.zip").isoformat() == "2026-10-02"


def test_jam_cme_mengikuti_musim_panas_chicago():
    assert gelombang.jam_utc_cme(date(2026, 7, 1), 15) == 20      # CDT
    assert gelombang.jam_utc_cme(date(2026, 12, 1), 15) == 21     # CST
    assert gelombang.jam_utc_cme(date(2026, 3, 8), 15) == 20      # Minggu ke-2 Maret
    assert gelombang.jam_utc_cme(date(2026, 11, 1), 15) == 21     # Minggu ke-1 Nov


def test_kline_mikrodetik_dan_jam_yang_tepat():
    # candle 19:00-20:00 UTC 1 Jul 2026 = tutup 15:00 Chicago (CDT); waktu dalam mikrodetik
    t = 1782932400 * 10**6
    baris = f"{t},1,1,1,100.5,0\n{t + 3600 * 10**6},1,1,1,999,0\n"
    assert gelombang._urai_kline(baris, 15) == {"2026-07-01": 100.5}


def test_basis_tahunan_dan_sisa_hari_minimal():
    assert gelombang.sisa_hari_kontrak(date(2026, 10, 1)) == 29     # Jumat terakhir 30 Okt
    assert gelombang.sisa_hari_kontrak(date(2026, 10, 28)) == 7     # dekat roll: minimal 7
    assert gelombang.sisa_hari_kontrak(date(2026, 10, 31)) == 27    # lewat -> 27 Nov
    b = gelombang.basis_cme({"2026-10-01": 100.0}, {"2026-10-01": 101.0})
    assert abs(b["2026-10-01"] - 1 * 365 / 29) < 1e-9


def test_cftc_short_bersih_dalam_btc(monkeypatch):
    import json
    data = [{"report_date_as_yyyy_mm_dd": "2026-10-06T00:00:00.000",
             "cftc_contract_market_code": "133741",
             "lev_money_positions_long": "100", "lev_money_positions_short": "300"},
            {"report_date_as_yyyy_mm_dd": "2026-10-06T00:00:00.000",
             "cftc_contract_market_code": "133742",
             "lev_money_positions_long": "0", "lev_money_positions_short": "1000"}]
    monkeypatch.setattr(adopsi, "_get", lambda url: json.dumps(data))
    (tgl, x), = adopsi.cftc_leveraged()
    assert tgl == date(2026, 10, 9)                      # Selasa + 3 = terbit Jumat
    assert x["short_bersih_btc"] == 200 * 5 + 1000 * 0.1


def test_berkas_ia_xlsx_juga_terbaca(tmp_path):
    """Run 38750933265: berkas IA lama berisi XLSX, bukan CSV — pembaca jatuh."""
    kepala = ["Organization CRD#", "SEC#", "5D(a)(3)", "5D(f)(3)"]
    nilai = ["123", "801-5", "10", "900"]
    teks = kepala + nilai
    ss = "".join(f"<si><t>{t}</t></si>" for t in teks)
    def baris(r, i0):
        return f'<row r="{r}">' + "".join(
            f'<c r="{chr(65 + k)}{r}" t="s"><v>{i0 + k}</v></c>' for k in range(4)) + "</row>"
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    lembar = f"<worksheet {ns}><sheetData>{baris(1, 0)}{baris(2, 4)}</sheetData></worksheet>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as x:
        x.writestr("xl/sharedStrings.xml", f"<sst {ns}>{ss}</sst>")
        x.writestr("xl/worksheets/sheet1.xml", lembar)
    p = tmp_path / "ia040124.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("IA_FOIA_April_2024.xlsx", buf.getvalue())
    assert etf_13f.baca_ia(str(p))[("crd", "123")] == "HEDGE_FUND_DANA_PRIVAT"

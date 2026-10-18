import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import kalibrasi_skor as ks  # noqa: E402
import model_kuant as mk  # noqa: E402


def _e(aset, tgl, skor, status, bias="TAHAN"):
    return {"aset": aset, "jenis": "crypto", "tanggal_utc": tgl, "skor": skor,
            "status": status, "bias": bias}


def test_episode_menggabungkan_analisa_ulang_dalam_72_jam():
    """9 Agu 2026: NVDA dianalisa tiga kali di harga sama — satu episode, bukan tiga."""
    entri = [_e("NVDA", "2026-08-09 10:46", 72, "MASIH_TERBUKA"),
             _e("NVDA", "2026-08-09 16:08", 66, "TARGET_KENA"),
             _e("NVDA", "2026-08-15 09:00", 60, "TARGET_KENA"),
             _e("SOL", "2026-08-09 11:00", 50, "INVALID_KENA")]
    eps = ks.episode(entri)
    assert sorted(len(e) for e in eps) == [1, 1, 2]
    nvda = [e for e in eps if e[0]["aset"] == "NVDA" and len(e) == 2][0]
    assert nvda[0]["skor"] == 72                       # wakil = panggilan PERTAMA


def test_wilson_lebar_pada_sampel_kecil():
    lo, hi = ks.wilson(6, 8)
    assert lo < 50 < hi
    assert ks.wilson(0, 0) is None


def test_belum_terkalibrasi_di_bawah_ambang_episode():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    entri = [_e(f"K{i}", (t0 + timedelta(days=i)).strftime("%Y-%m-%d %H:%M"),
                40 + i, "TARGET_KENA" if i % 3 else "INVALID_KENA") for i in range(20)]
    k = ks.kalibrasi(entri, sekarang=t0 + timedelta(days=60))
    assert k["status"] == "BELUM TERKALIBRASI" and k["episode_dinilai"] == 20
    assert k["perkiraan_bulan_lagi"] > 0
    assert "BELUM TERKALIBRASI" in ks.catatan_brief(entri)


def test_terkalibrasi_bila_skor_memang_memisahkan_hasil():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    entri = [_e(f"K{i}", (t0 + timedelta(days=i)).strftime("%Y-%m-%d %H:%M"),
                30 + i % 60, "TARGET_KENA" if (30 + i % 60) > 60 else "INVALID_KENA")
             for i in range(80)]
    k = ks.kalibrasi(entri)
    assert k["status"] == "TERKALIBRASI"
    assert k["peta_peluang_benar"]["90"] > k["peta_peluang_benar"]["30"]


def test_uji_maju_dicatat_sekali_lalu_dinilai_sesudah_jatuh_tempo(tmp_path, monkeypatch):
    monkeypatch.setattr(mk, "MAJU_PATH", str(tmp_path / "maju.jsonl"))
    assert mk.catat_maju("2026-01-02", 38, 58) is True
    assert mk.catat_maju("2026-01-02", 40, 58) is False          # tidak menimpa
    harga = {(date(2026, 1, 3) + timedelta(days=d)).isoformat(): 100.0 + d for d in range(120)}
    assert mk.nilai_maju(harga, hari_ini=date(2026, 3, 1)) == 0  # belum jatuh tempo
    assert mk.nilai_maju(harga, hari_ini=date(2026, 4, 30)) == 1
    r = mk.ringkas_maju()
    assert r["dinilai"] == 1 and r["brier"] == round((0.38 - 1) ** 2, 4)
    baris = [json.loads(x) for x in open(mk.MAJU_PATH, encoding="utf-8")]
    assert baris[0]["naik"] is True and baris[0]["peluang_naik_persen"] == 38


def _buku(tmp_path, monkeypatch, n, peluang, naik, aset="BTC", tulis_aset=True):
    """n prediksi maju yang sudah dinilai: semua ramalan `peluang`%, laju dasar 50%."""
    os.makedirs(tmp_path, exist_ok=True)
    monkeypatch.setattr(mk, "MAJU_PATH", str(tmp_path / "maju.jsonl"))
    with open(mk.MAJU_PATH, "a", encoding="utf-8") as f:
        for k in range(n):
            b = {"jumat": (date(2027, 1, 1) + timedelta(days=7 * k)).isoformat(),
                 "horizon_minggu": 12, "peluang_naik_persen": peluang,
                 "laju_dasar_persen": 50, "naik": naik}
            if tulis_aset:
                b["aset"] = aset
            f.write(json.dumps(b) + "\n")


def test_vonis_uji_maju_mengikuti_aturan_yang_didaftarkan(tmp_path, monkeypatch):
    """Ambang 26 / 52 / -0,05 dikunci 17 Okt 2026 sebelum ada prediksi jatuh tempo."""
    _buku(tmp_path / "a", monkeypatch, 25, 90, False)   # sangat buruk, tapi < 26
    assert mk.ringkas_maju()["vonis"] == "BELUM"
    _buku(tmp_path / "b", monkeypatch, 26, 90, False)   # stop dini
    assert mk.ringkas_maju()["vonis"] == "GAGAL"
    _buku(tmp_path / "c", monkeypatch, 51, 60, True)    # bagus, tapi < 52
    assert mk.ringkas_maju()["vonis"] == "BELUM"
    _buku(tmp_path / "d", monkeypatch, 52, 60, True)
    assert mk.ringkas_maju()["vonis"] == "BERTAHAN"
    _buku(tmp_path / "e", monkeypatch, 26, 52, False)   # sedikit buruk: tunggu sampai 52
    _buku(tmp_path / "e", monkeypatch, 26, 52, True)
    r = mk.ringkas_maju()
    assert r["dinilai"] == 52 and -0.05 < r["brier_skill"] <= 0 and r["vonis"] == "GAGAL"


def test_buku_maju_dipisah_per_aset_dan_baris_lama_dianggap_btc(tmp_path, monkeypatch):
    _buku(tmp_path, monkeypatch, 3, 60, True, tulis_aset=False)    # format sebelum ETH
    assert mk.catat_maju("2026-10-16", 37, 52, aset="ETH") is True
    assert mk.catat_maju("2026-10-16", 38, 58) is True              # BTC Jumat sama: boleh
    assert mk.catat_maju("2026-10-16", 40, 52, aset="ETH") is False
    assert mk.ringkas_maju("BTC")["dicatat"] == 4 and mk.ringkas_maju("BTC")["dinilai"] == 3
    assert mk.ringkas_maju("ETH") == {"dicatat": 1, "dinilai": 0, "vonis": "BELUM",
                                      "catatan": mk.ringkas_maju("ETH")["catatan"]}


def test_nilai_maju_memakai_harga_aset_masing2(tmp_path, monkeypatch):
    monkeypatch.setattr(mk, "MAJU_PATH", str(tmp_path / "maju.jsonl"))
    mk.catat_maju("2026-01-02", 60, 50)
    mk.catat_maju("2026-01-02", 60, 50, aset="ETH")
    hari = [(date(2026, 1, 3) + timedelta(days=d)).isoformat() for d in range(120)]
    naik = {t: 100.0 + d for d, t in enumerate(hari)}
    turun = {t: 100.0 - d / 2 for d, t in enumerate(hari)}
    assert mk.nilai_maju({"BTC": naik, "ETH": turun}, hari_ini=date(2026, 4, 30)) == 2
    baris = {b["aset"]: b["naik"] for b in map(json.loads, open(mk.MAJU_PATH, encoding="utf-8"))}
    assert baris == {"BTC": True, "ETH": False}


def test_model_yang_gagal_uji_maju_tidak_menampilkan_angka(tmp_path, monkeypatch):
    import jam_likuiditas as jl
    _buku(tmp_path, monkeypatch, 26, 90, False)
    monkeypatch.setattr(mk, "status_aset", lambda aset, h=12: {"versi": "likuiditas_saja"})
    jumat = [date(2015, 1, 2) + timedelta(days=7 * k) for k in range(300)]
    r = mk.peluang_aset(jumat, [0.1] * 300, {}, 299, "BTC")
    assert "peluang_btc_naik_persen" not in r and "GAGAL" in r["gagal_uji_maju"]
    teks = jl.pesan.__code__.co_consts                    # baris Telegram ada di pesan()
    assert any("GAGAL uji maju" in str(c) for c in teks)


def test_maju_menilai_semua_aset_di_buku(tmp_path, monkeypatch):
    """ETH yang kelak tak diadopsi tetap harus dinilai — harga diambil untuk tiap aset di buku."""
    import jam_likuiditas as jl
    monkeypatch.setattr(mk, "MAJU_PATH", str(tmp_path / "maju.jsonl"))
    mk.catat_maju("2026-01-02", 60, 50, aset="ETH")
    monkeypatch.setattr(mk, "analisa", lambda: {"sinyal_jumat": "2026-01-02", "per_horizon": []})
    monkeypatch.setattr(mk, "status_aset", lambda aset, h=12: {})
    diminta = []
    monkeypatch.setattr(jl, "harga_yahoo", lambda s: (diminta.append(s), {})[1])
    monkeypatch.setattr(sys, "argv", ["model_kuant.py", "--maju"])
    mk.main()
    assert "ETH-USD" in diminta

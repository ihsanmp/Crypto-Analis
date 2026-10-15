"""A3 Adoption Clock — pemegang 13F ETF spot BTC AS per kuartal, dari Form 13F Data Sets SEC.

SEC menerbitkan seluruh isi 13F sebagai berkas zip per rentang TANGGAL FILING (tabel
SUBMISSION, COVERPAGE, INFOTABLE). Skrip ini memindai INFOTABLE untuk baris ETF spot BTC,
lalu menjumlah per PERIODOFREPORT: jumlah filer dan nilai (USD — sejak 2023 kolom VALUE
dalam dolar, bukan ribuan). Hanya 13F-HR asli; amandemen (13F-HR/A) diabaikan supaya satu
filer tidak terhitung dua kali.

Tiap filer menyerahkan satu 13F-HR per kuartal, jadi hasil per data set bisa DIJUMLAH lintas
data set tanpa menyimpan daftar filer — itu yang membuat pembaruan inkremental murah.

BATAS JUJUR: jenis pemegang (penasihat vs hedge fund basis-trade) TIDAK dipisah. 13F tidak
punya kolom jenis, dan menebak dari nama filer tidak bisa diaudit. Sebagian kepemilikan hedge
fund adalah long ETF + short futures (netral arah) — sebut itu saat mengutip.

Butuh secret SEC_CONTACT (lihat seckontak.py); dari jaringan pengembang SEC membalas 403,
jadi dijalankan di workflow jam-mingguan.

    python cloud/etf_13f.py            # proses data set yang belum diproses
    python cloud/etf_13f.py --semua    # ulang dari nol
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seckontak  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HALAMAN = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
SEC = "https://www.sec.gov"
F13_PATH = os.path.join(BASE_DIR, "data", "etf_13f.json")
MULAI = "2024"          # ETF spot BTC mulai diperdagangkan 11 Jan 2024

# Nama penerbit di 13F diketik bebas oleh tiap filer ("ISHARES BITCOIN TR", "ISHS BITCOIN
# TRUST", "RAYSCALE BITCOIN MINI TR ET"). Versi pertama mencocokkan SEMUA yang memuat
# "BITCOIN" lalu membuang pengecualian — run 38746731651 membuktikan itu bocor: saham
# penambang (American Bitcoin Corp), SPAC (BTC Dev Corp, Bitcoin Infrastructure Acqui),
# ETF futures (ProShares), covered call / protection / floor, Grayscale Bitcoin CASH, dan
# "BlackRock Institutional Trust ... BTC iShares MSCI". Sekarang DAFTAR PUTIH: keluarga
# penerbit ETF spot + kata Bitcoin, lalu pengecualian produk turunannya.
VERSI_COCOK = 5          # 3: jenis (Form ADV 5.D); 4: ERA, nama; 5: berkas IA benar
_FAMILI = re.compile(r"I ?SHARES?|ISHS|ISHA|IBIT|FIDELITY|WISE ORIGIN|G?R[AE]YSCALE|\bARK\b|"
                     r"21 ?SHARES|BITWISE|ITWISE|INVESCO|GALAXY|VAN ?ECK|ANECK|FRANKLIN|"
                     r"VALKYRIE|COINSHARES|COINSHRS|WISDOMTREE|ISDOMTREE|HASHDEX|"
                     r"MORGAN STANLEY|BITCOIN INVESTMENT TR")
_BITCOIN = re.compile(r"BITC(?:OI|IO|O)N")
_BUKAN = re.compile(r"CASH|BCH|\bCOV|CALL|\bCC\b|PREM|FLOOR|STRUCT|PROTECT|STANDARD|CORP|"
                    r"EX-BTC|ACTIVE|FUT|MINER|MINING|\bAND\b|\bPUT\b|PROSHARES|STRAT|"
                    r"INCOME|\bINC\b|INSTITUTIONAL TRUST COMPANY|LEVERAG|2X|SHORT|INVERSE")


def cocok(nama):
    nama = re.sub(r"\s+", " ", (nama or "").upper())
    return bool(_FAMILI.search(nama) and _BITCOIN.search(nama)) and not _BUKAN.search(nama)


def _get(url, biner=False):
    if seckontak.alasan_kosong():
        raise RuntimeError(seckontak.alasan_kosong())
    req = urllib.request.Request(url, headers=seckontak.header())
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read() if biner else r.read().decode("utf-8", errors="replace")


def daftar_data_set():
    html = _get(HALAMAN)
    tautan = sorted(set(re.findall(r'href="([^"]*form13f[^"]*\.zip)"', html, re.I)))
    # Nama berkas memuat tahun filing, mis. 01dec2023-29feb2024_form13f.zip
    return [t for t in tautan if any(str(y) in t for y in range(int(MULAI), 2100))]


def _baca(z, nama):
    cari = [n for n in z.namelist() if n.upper().endswith(nama)]
    if not cari:
        raise ValueError(f"{nama} tidak ada di zip")
    return csv.DictReader(io.TextIOWrapper(z.open(cari[0]), encoding="utf-8",
                                           errors="replace"), delimiter="\t")


# ------------------------------------------------------------------ jenis pemegang
# 13F tidak punya kolom jenis, tapi COVERPAGE memuat CRD / nomor berkas SEC filer, dan
# berkas bulanan "Information about Registered Investment Advisers" (Form ADV Part 1A)
# memuat Item 5.D: aset kelolaan (RAUM) per JENIS KLIEN. Jenis pemegang ditentukan dari
# jenis klien yang memegang porsi RAUM terbesar — data resmi, bisa diaudit, bukan tebakan
# dari nama. Filer tanpa CRD (bank, asuransi, penasihat terdaftar di negara bagian, filer
# asing) dipetakan dari nama hanya untuk pola yang tak ambigu; sisanya TIDAK TERKLASIFIKASI.
IA_HALAMAN = ("https://www.sec.gov/data-research/sec-markets-data/"
              "information-about-registered-investment-advisers-exempt-reporting-advisers")
# Item 5.D Form ADV: (a) individu, (b) individu kaya, (c) bank, (d) investment company,
# (e) BDC, (f) pooled investment vehicle (hedge fund/dana privat), (g) dana pensiun,
# (h) yayasan, (i) pemerintah negara bagian/kota, (j) penasihat lain, (k) asuransi,
# (l) dana kekayaan negara, (m) korporasi, (n) lainnya. Kolom (x)(3) = RAUM.
JENIS_5D = {
    "PENASIHAT_KEKAYAAN": ("a", "b"),
    "HEDGE_FUND_DANA_PRIVAT": ("f",),
    "INSTITUSI": ("c", "g", "h", "i", "k", "l"),
    "MANAJER_REKSA_DANA": ("d", "e"),
    "LAINNYA": ("j", "m", "n"),
}
_NAMA_BANK = re.compile(r"\bBANK\b|BANCORP|\bN\.?A\.?$|TRUST CO(MPANY)?\b|SAVINGS")
_NAMA_INSTITUSI = re.compile(r"RETIREMENT|PENSION|TEACHERS|EMPLOYEES|\bSTATE OF\b|"
                             r"INSURANCE|ASSURANCE|\bLIFE\b|UNIVERSITY|ENDOWMENT|"
                             r"FOUNDATION|SOVEREIGN|INVESTMENT AUTHORITY|MONETARY")


def _angka(x):
    try:
        return float(str(x).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def jenis_dari_5d(baris):
    """Jenis klien dengan RAUM terbesar dari satu baris berkas IA. None kalau kosong."""
    raum = {j: sum(_angka(baris.get(f"5D({h})(3)")) for h in hs) for j, hs in JENIS_5D.items()}
    if not any(raum.values()):
        return None
    return max(raum, key=raum.get)


def jenis_dari_nama(nama):
    nama = re.sub(r"\s+", " ", (nama or "").upper().strip())
    if _NAMA_BANK.search(nama):
        return "BANK"
    if _NAMA_INSTITUSI.search(nama):
        return "INSTITUSI"
    return "TIDAK_TERKLASIFIKASI"


def _norm_crd(x):
    x = re.sub(r"\D", "", x or "")
    return x.lstrip("0") or None


def _norm_sec(x):
    m = re.search(r"(\d{3})-0*(\d+)", x or "")
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _baris_xlsx(f):
    """Baris dict dari sheet pertama berkas .xlsx — stdlib saja (zip + XML)."""
    import xml.etree.ElementTree as ET
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(f) as x:
        teks = []
        if "xl/sharedStrings.xml" in x.namelist():
            for _, el in ET.iterparse(x.open("xl/sharedStrings.xml")):
                if el.tag == ns + "si":
                    teks.append("".join(t.text or "" for t in el.iter(ns + "t")))
                    el.clear()
        lembar = sorted(n for n in x.namelist() if n.startswith("xl/worksheets/sheet"))[0]
        kepala = None
        for _, el in ET.iterparse(x.open(lembar)):
            if el.tag != ns + "row":
                continue
            sel = {}
            for c in el.iter(ns + "c"):
                kol = re.match(r"[A-Z]+", c.get("r", "")).group(0)
                v = c.find(ns + "v")
                if v is None:
                    isi = "".join(t.text or "" for t in c.iter(ns + "t"))
                else:
                    isi = teks[int(v.text)] if c.get("t") == "s" else (v.text or "")
                sel[kol] = isi
            el.clear()
            if kepala is None:
                kepala = sel
                continue
            yield {kepala[k]: sel.get(k, "") for k in kepala}


def _baris_ia(z):
    """Berkas IA SEC: CSV untuk bulan-bulan terbaru, XLSX untuk sebagian bulan lama
    (run 38750933265 jatuh karena hanya CSV yang dicari)."""
    nama = z.namelist()
    csvs = [n for n in nama if n.lower().endswith(".csv")]
    if csvs:
        return csv.DictReader(io.TextIOWrapper(z.open(csvs[0]), encoding="latin-1",
                                               newline=""))
    xlsx = [n for n in nama if n.lower().endswith(".xlsx")]
    if xlsx:
        return _baris_xlsx(io.BytesIO(z.read(xlsx[0])))
    raise ValueError(f"berkas IA tanpa CSV/XLSX: {nama}")


_SUFIKS = re.compile(r"\b(LLC|L L C|LP|L P|LLP|INC|INCORPORATED|CORP|CORPORATION|CO|"
                     r"COMPANY|LTD|LIMITED|THE|PLC|NA|N A|SA|AG|GMBH)\b")


def norm_nama(nama):
    """Nama resmi yang dinormalkan untuk mencocokkan sampul 13F dengan Form ADV."""
    n = re.sub(r"&", " AND ", (nama or "").upper())
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    n = _SUFIKS.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip() or None


def baca_ia(path, era=False):
    """{("crd", n) | ("sec", "801-n") | ("nama", norm): jenis} dari satu zip berkas IA.

    era=True: berkas EXEMPT REPORTING ADVISER. Menurut definisinya ERA hanya menasihati
    dana privat (atau modal ventura) — tidak mengisi Item 5.D, jadi jenisnya langsung
    HEDGE_FUND_DANA_PRIVAT. Nama yang dipetakan ke dua jenis berbeda dibuang (ambigu)."""
    peta, nama_ke = {}, {}
    with zipfile.ZipFile(path) as z:
        for b in _baris_ia(z):
            j = "HEDGE_FUND_DANA_PRIVAT" if era else jenis_dari_5d(b)
            if not j:
                continue
            crd = _norm_crd(b.get("Organization CRD#"))
            sec = _norm_sec(b.get("SEC#"))
            if crd:
                peta[("crd", crd)] = j
            if sec:
                peta[("sec", sec)] = j
            for k in ("Legal Name", "Primary Business Name"):
                n = norm_nama(b.get(k))
                if n:
                    nama_ke.setdefault(n, set()).add(j)
    for n, js in nama_ke.items():
        if len(js) == 1:
            peta[("nama", n)] = next(iter(js))
    return peta


def _tanggal_ia(url):
    """Nama berkas IA SEC tidak seragam: ia040423.zip (MMDDYY), ia07012026.zip
    (MMDDYYYY), ia060126_0.zip, ia020226-exemptzip.zip, ia09012026-registered.zip."""
    m = re.search(r"/ia(\d{6,8})[^/]*\.zip$", url, re.I)
    if not m:
        return None
    d = m.group(1)
    try:
        if len(d) == 8:
            return datetime(int(d[4:]), int(d[:2]), int(d[2:4])).date()
        if len(d) == 6:
            return datetime(2000 + int(d[4:]), int(d[:2]), int(d[2:4])).date()
    except ValueError:
        return None
    return None


class Klasifikasi:
    """Memilih berkas IA terdekat SEBELUM batas filing tiap kuartal, memuatnya sekali."""

    def __init__(self, unduh=None):
        self._unduh = unduh
        self._berkas = None
        self._muat = {}

    def _daftar(self):
        """{tanggal: {"terdaftar": url, "era": url}}."""
        if self._berkas is None:
            html = _get(IA_HALAMAN)
            self._berkas = {}
            for t in set(re.findall(r'href="([^"]+/ia\d{6,8}[^"/]*\.zip)"', html, re.I)):
                d = _tanggal_ia(t)
                if d:
                    # Cek NAMA BERKAS saja: folder SEC sejak 2023 bernama "...-exempt-
                    # reporting-advisers/", sehingga memeriksa seluruh URL membuat setiap
                    # berkas terdaftar dianggap ERA (run 38753072380: semua kuartal jatuh
                    # ke berkas Mei 2020).
                    jenis = "era" if "exempt" in t.rsplit("/", 1)[-1].lower() else "terdaftar"
                    self._berkas.setdefault(d, {})[jenis] = t
        return self._berkas

    def _baca(self, url, era):
        if url not in self._muat:
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "ia.zip")
                with open(path, "wb") as f:
                    f.write((self._unduh or _get)(url if url.startswith("http") else SEC + url,
                                                  biner=True))
                try:
                    self._muat[url] = baca_ia(path, era)
                except Exception as e:
                    # Lebih baik kuartal ini TIDAK TERKLASIFIKASI (terlihat) daripada
                    # seluruh pembaruan 13F jatuh.
                    print(f"berkas IA {url.rsplit('/', 1)[-1]} gagal dibaca: {e}", flush=True)
                    self._muat[url] = {}
            time.sleep(1)
        return self._muat[url]

    def peta_untuk(self, periode):
        """Berkas terakhir SEBELUM batas filing kalau ada dalam 120 hari; kalau tidak
        (halaman SEC tidak memuat berkas Jun 2023 - Nov 2025), berkas TERDEKAT — jenis klien
        sebuah penasihat jarang berubah, dan nama berkasnya dicatat per kuartal."""
        from datetime import date as _d, timedelta as _td
        batas = _d.fromisoformat(periode) + _td(days=45)
        daftar = {d: v for d, v in self._daftar().items() if "terdaftar" in v}
        if not daftar:
            return {}, None
        sebelum = [d for d in daftar if batas - _td(days=120) <= d <= batas]
        pilih = max(sebelum) if sebelum else min(daftar, key=lambda d: abs((d - batas).days))
        v = self._daftar()[pilih]
        peta = dict(self._baca(v["era"], True)) if "era" in v else {}
        peta.update(self._baca(v["terdaftar"], False))      # terdaftar menang atas ERA
        label = v["terdaftar"].rsplit("/", 1)[-1] + (
            "" if sebelum else " (terdekat; tidak ada berkas <= 120 hari sebelum batas filing)")
        return peta, label


def proses_zip(path, klasifikasi=None):
    """{periode: {"filer","nilai_usd","per_jenis":{jenis:{"filer","nilai_usd"}}}},
    {penerbit: jumlah baris}, {periode: berkas IA yang dipakai}."""
    with zipfile.ZipFile(path) as z:
        asli = {}
        for b in _baca(z, "SUBMISSION.TSV"):
            if (b.get("SUBMISSIONTYPE") or "").strip() == "13F-HR":
                try:
                    asli[b["ACCESSION_NUMBER"]] = datetime.strptime(
                        b["PERIODOFREPORT"].strip(), "%d-%b-%Y").date().isoformat()
                except (KeyError, ValueError):
                    continue
        sampul = {}
        try:
            for b in _baca(z, "COVERPAGE.TSV"):
                if b.get("ACCESSION_NUMBER") in asli:
                    sampul[b["ACCESSION_NUMBER"]] = (_norm_crd(b.get("CRDNUMBER")),
                                                     _norm_sec(b.get("SECFILENUMBER")),
                                                     b.get("FILINGMANAGER_NAME"))
        except ValueError:
            pass
        nilai, penerbit = {}, {}
        for b in _baca(z, "INFOTABLE.TSV"):
            acc = b.get("ACCESSION_NUMBER")
            if acc not in asli or (b.get("PUTCALL") or "").strip():
                continue
            if not cocok(b.get("NAMEOFISSUER")):
                continue
            nilai[acc] = nilai.get(acc, 0.0) + _angka(b.get("VALUE"))
            n = (b.get("NAMEOFISSUER") or "").strip().upper()
            penerbit[n] = penerbit.get(n, 0) + 1
    hasil, ia_dipakai = {}, {}
    for acc, v in nilai.items():
        p = asli[acc]
        crd, sec, nama = sampul.get(acc, (None, None, None))
        jenis = "TIDAK_TERKLASIFIKASI"
        if klasifikasi is not None:
            peta, berkas = klasifikasi.peta_untuk(p)
            ia_dipakai[p] = berkas
            nn = norm_nama(nama)
            jenis = (peta.get(("crd", crd)) if crd else None) or \
                    (peta.get(("sec", sec)) if sec else None) or \
                    (peta.get(("nama", nn)) if nn else None) or jenis_dari_nama(nama)
        h = hasil.setdefault(p, {"filer": 0, "nilai_usd": 0.0, "per_jenis": {}})
        h["filer"] += 1
        h["nilai_usd"] += v
        pj = h["per_jenis"].setdefault(jenis, {"filer": 0, "nilai_usd": 0.0})
        pj["filer"] += 1
        pj["nilai_usd"] += v
        if jenis == "TIDAK_TERKLASIFIKASI" and nama:
            # Nama filer 13F = data publik institusi. Disimpan supaya pemegang besar yang
            # tak terpetakan bisa diaudit, bukan disembunyikan di satu angka porsi.
            tk = h.setdefault("tak_terklasifikasi", {})
            tk[nama.strip()] = tk.get(nama.strip(), 0.0) + v
    return hasil, penerbit, ia_dipakai


def perbarui(semua=False):
    try:
        with open(F13_PATH, encoding="utf-8") as f:
            simpan = json.load(f)
    except (OSError, ValueError):
        simpan = {}
    if semua or simpan.get("versi_cocok") != VERSI_COCOK:
        simpan = {"versi_cocok": VERSI_COCOK}
    simpan.setdefault("per_data_set", {})
    simpan.setdefault("penerbit_cocok", {})
    simpan.setdefault("berkas_ia", {})
    kl = Klasifikasi()
    baru = [t for t in daftar_data_set() if t.rsplit("/", 1)[-1] not in simpan["per_data_set"]]
    for t in baru:
        nama = t.rsplit("/", 1)[-1]
        url = t if t.startswith("http") else SEC + t
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, nama)
            with open(path, "wb") as f:
                f.write(_get(url, biner=True))
            hasil, penerbit, ia = proses_zip(path, kl)
        simpan["per_data_set"][nama] = hasil
        simpan["berkas_ia"].update(ia)
        for k, v in penerbit.items():
            simpan["penerbit_cocok"][k] = simpan["penerbit_cocok"].get(k, 0) + v
        print(f"{nama}: {sum(h['filer'] for h in hasil.values())} filing ETF BTC", flush=True)
        time.sleep(1)          # fair access SEC: jauh di bawah 10 permintaan/detik
    total = {}
    for hasil in simpan["per_data_set"].values():
        for p, h in hasil.items():
            t = total.setdefault(p, {"filer": 0, "nilai_usd": 0.0, "per_jenis": {}})
            t["filer"] += h["filer"]
            t["nilai_usd"] += h["nilai_usd"]
            for j, x in (h.get("per_jenis") or {}).items():
                tj = t["per_jenis"].setdefault(j, {"filer": 0, "nilai_usd": 0.0})
                tj["filer"] += x["filer"]
                tj["nilai_usd"] += x["nilai_usd"]
            for n, x in (h.get("tak_terklasifikasi") or {}).items():
                tt = t.setdefault("tak", {})
                tt[n] = tt.get(n, 0.0) + x
    simpan["kuartal"] = [
        {"akhir_kuartal": p, "pemegang": t["filer"], "nilai_usd": round(t["nilai_usd"]),
         "per_jenis": {j: {"pemegang": x["filer"], "nilai_usd": round(x["nilai_usd"])}
                       for j, x in sorted(t["per_jenis"].items())},
         "berkas_ia": simpan["berkas_ia"].get(p),
         "tak_terklasifikasi_terbesar": [
             [n, round(x)] for n, x in sorted((t.get("tak") or {}).items(),
                                              key=lambda kv: -kv[1])[:15]]}
        for p, t in sorted(total.items()) if p >= MULAI]
    simpan["diperbarui_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    simpan["catatan"] = (
        "13F-HR asli saja. Jenis pemegang dari Form ADV Item 5.D (jenis klien dengan RAUM "
        "terbesar), lewat CRD/nomor berkas SEC di sampul 13F; berkas IA yang dipakai = yang "
        "terakhir terbit sebelum batas filing kuartal itu. Filer tanpa CRD dipetakan dari nama "
        "hanya untuk bank/institusi yang jelas. HEDGE_FUND_DANA_PRIVAT memuat pelaku basis "
        "trade (long ETF + short futures, netral arah) — bandingkan dengan short leveraged "
        "funds CFTC.")
    os.makedirs(os.path.dirname(F13_PATH), exist_ok=True)
    with open(F13_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(simpan, f, ensure_ascii=False, indent=1, sort_keys=True)
    return simpan


ADV_HALAMAN = (
    "https://www.sec.gov/data-research/sec-markets-data/"
    "information-about-registered-investment-advisers-exempt-reporting-advisers",
    "https://www.sec.gov/foia-services/frequently-requested-documents/form-adv-data",
)


def periksa():
    """Bentuk data untuk memisahkan JENIS pemegang: kolom COVERPAGE 13F (adakah CRD /
    nomor berkas 801- penasihat?) dan berkas data Form ADV. Hanya nama kolom & hitungan
    yang dicetak — tidak ada nama atau alamat filer."""
    t = daftar_data_set()[-1]
    url = t if t.startswith("http") else SEC + t
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "x.zip")
        with open(path, "wb") as f:
            f.write(_get(url, biner=True))
        with zipfile.ZipFile(path) as z:
            print("isi zip:", z.namelist())
            baris = list(_baca(z, "COVERPAGE.TSV"))
    print("COVERPAGE kolom:", list(baris[0].keys()))
    for k in baris[0]:
        isi = [b[k] for b in baris if (b.get(k) or "").strip()]
        print(f"  {k}: terisi {len(isi)}/{len(baris)}"
              + (f" contoh awalan {sorted({x[:4] for x in isi})[:8]}"
                 if k.upper() in ("CRDNUMBER", "SECFILENUMBER", "FORM13FFILENUMBER") else ""))
    for h in ADV_HALAMAN:
        try:
            html = _get(h)
        except Exception as e:
            print(h, "gagal", type(e).__name__)
            continue
        z = sorted(set(re.findall(r'href="([^"]+\.zip)"', html, re.I)))
        print(h, "->", len(z), "zip;", z[:6], "...", z[-6:])
        ia = [x for x in z if re.search(r"/ia\d{6}\.zip$", x)]
        if ia:
            terbaru = max(ia, key=lambda x: (x[-6:-4], x[-10:-8], x[-8:-6]))
            print("berkas IA terbaru:", terbaru)
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "ia.zip")
                with open(path, "wb") as f:
                    f.write(_get(terbaru if terbaru.startswith("http") else SEC + terbaru,
                                 biner=True))
                with zipfile.ZipFile(path) as zz:
                    print("isi:", zz.namelist())
                    nama = zz.namelist()[0]
                    with zz.open(nama) as f:
                        kepala = f.readline().decode("latin-1").rstrip()
                        n = sum(1 for _ in f)
            kol = re.split(r"[,|	]", kepala)
            print(f"{len(kol)} kolom, {n} baris")
            for k in kol:
                if re.search(r"5D|5F|7B|Pool|Hedge|CRD|Organization CRD|SEC#|Legal Name|Primary",
                             k, re.I):
                    print("  kolom:", k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semua", action="store_true")
    ap.add_argument("--periksa", action="store_true")
    ap.add_argument("--daftar-ia", dest="daftar_ia", action="store_true")
    a = ap.parse_args()
    if a.periksa:
        periksa()
        return
    if a.daftar_ia:
        html = _get(IA_HALAMAN)
        for t in sorted(set(re.findall(r'href="([^"]+\.zip)"', html, re.I))):
            if "26" in t.rsplit("/", 1)[-1] or "25" in t.rsplit("/", 1)[-1]:
                print(repr(t))
        d = Klasifikasi()._daftar()
        print("terurai:", len(d), [(k.isoformat(), v) for k, v in sorted(d.items())[-4:]])
        return
    s = perbarui(a.semua)
    for q in s["kuartal"]:
        print(f"{q['akhir_kuartal']}  pemegang {q['pemegang']:>5}  "
              f"nilai ${q['nilai_usd'] / 1e9:,.1f} miliar  ({q.get('berkas_ia')})")
        for j, x in (q.get("per_jenis") or {}).items():
            print(f"    {j:<24} {x['pemegang']:>5}  ${x['nilai_usd'] / 1e9:,.1f} miliar")


if __name__ == "__main__":
    main()

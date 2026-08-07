"""Fundamental SAHAM dari SEC EDGAR (XBRL) — RESMI, gratis, tanpa API key.

Metrik crypto tidak berlaku untuk saham: tidak ada TVL, holder, atau whale. Yang menentukan
mahal-murahnya saham adalah laporan keuangan yang WAJIB dilaporkan ke SEC. Sumber ini
otoritatif — langsung dari filing perusahaan, bukan agregator pihak ketiga.

Menghasilkan (kuartalan & tahunan, lengkap dengan pertumbuhannya):
  revenue, laba bersih, EPS diluted, margin bersih, aset, liabilitas, ekuitas,
  arus kas operasi — plus P/E dan P/S bila harga diberikan lewat --price.

BATASAN YANG HARUS DISAMPAIKAN APA ADANYA:
  - HANYA emiten yang terdaftar di bursa AS. Saham Eropa/Asia/Indonesia TIDAK tercakup.
  - Nama tag XBRL BERBEDA antar perusahaan (mis. NVDA memakai "Revenues", emiten lain
    "RevenueFromContractWithCustomerExcludingAssessedTax"). Script mencoba beberapa
    kandidat; yang tidak ketemu dilaporkan kosong, TIDAK dikarang.
  - Laporan keuangan TERTINGGAL dari harga: kuartal terakhir bisa berumur 1-3 bulan.
    Umur data dihitung dan ditampilkan — perlakukan sebagai fundamental, bukan sinyal harga.
  - Angka bisa DIREVISI (restatement). Dipakai filing yang paling akhir diajukan.

Pemakaian:
    python cloud/stockfund.py NVDA
    python cloud/stockfund.py AAPL --price 232.5      # supaya P/E & P/S ikut dihitung
"""

import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

# SEC mewajibkan User-Agent berisi identitas + kontak (kebijakan fair access).
# JANGAN menambahkan Accept-Encoding: urllib tidak membuka gzip secara otomatis, sehingga
# responsnya terbaca sebagai byte terkompresi dan gagal di-decode.
UA = {"User-Agent": "Crypto-Analis Research bot ihsanmaulanand@gmail.com"}
SEC = "https://data.sec.gov/api/xbrl/companyconcept"
TICKERS = "https://www.sec.gov/files/company_tickers.json"
TIMEOUT = 25

# Tiap metrik punya beberapa kemungkinan nama tag — dicoba berurutan sampai ada yang ada.
METRIK = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "laba_bersih": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
    "aset": ["Assets"],
    "liabilitas": ["Liabilities"],
    "ekuitas": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "arus_kas_operasi": ["NetCashProvidedByUsedInOperatingActivities",
                         "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
}


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"__err": f"HTTP {e.code}"}
    except Exception as e:
        return {"__err": type(e).__name__}


def cari_cik(ticker):
    d = get(TICKERS)
    if "__err" in d:
        return None, None, f"Gagal mengambil daftar emiten SEC ({d['__err']})."
    for v in d.values():
        if str(v.get("ticker", "")).upper() == ticker:
            return str(v["cik_str"]).zfill(10), v.get("title"), None
    return None, None, (f"'{ticker}' tidak ada di daftar emiten SEC. Sumber ini HANYA "
                        "mencakup perusahaan yang terdaftar di bursa AS.")


def hari(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def ambil_metrik(cik, tags):
    """Coba SEMUA kandidat tag, pakai yang datanya PALING BARU.

    Dulu dipakai tag pertama yang ada isinya. Itu keliru saat emiten berganti tag: AAPL
    masih punya "Revenues" warisan yang berhenti di 2018, sementara revenue sebenarnya
    dilaporkan di "RevenueFromContractWithCustomerExcludingAssessedTax" sampai sekarang.
    Akibatnya revenue AAPL macet di 2018 dan setiap rasio yang memakainya salah, tanpa
    peringatan apa pun. Sekarang semua kandidat dicoba dan yang terbaru yang menang.
    """
    kandidat = []
    for tag in tags:
        d = get(f"{SEC}/CIK{cik}/us-gaap/{tag}.json")
        if "__err" in d:
            continue
        entri = []
        for unit, baris in (d.get("units") or {}).items():
            for b in baris:
                akhir, mulai = hari(b.get("end", "")), hari(b.get("start", ""))
                if not akhir:
                    continue
                durasi = (akhir - mulai).days if mulai else 0
                entri.append({"akhir": akhir, "durasi": durasi, "nilai": b.get("val"),
                              "form": b.get("form"), "diajukan": b.get("filed"), "unit": unit})
        if entri:
            kandidat.append((max(e["akhir"] for e in entri), entri, tag))
    if not kandidat:
        return [], None
    kandidat.sort(key=lambda x: x[0])
    _, entri, tag = kandidat[-1]
    return entri, tag


def pilih(entri, kuartalan):
    """Ambil satu nilai per periode. Duplikat (restatement) diselesaikan dengan memakai
    filing yang PALING AKHIR diajukan — bukan yang pertama ditemukan."""
    if kuartalan:
        cocok = [e for e in entri if 80 <= e["durasi"] <= 100]
    else:
        cocok = [e for e in entri if 330 <= e["durasi"] <= 400]
    if not cocok:                       # neraca (aset/ekuitas) bersifat titik waktu
        cocok = [e for e in entri if e["durasi"] <= 1]
    per_periode = {}
    for e in cocok:
        k = e["akhir"]
        if k not in per_periode or (e["diajukan"] or "") > (per_periode[k]["diajukan"] or ""):
            per_periode[k] = e
    return [per_periode[k] for k in sorted(per_periode)]


def tumbuh(baru, lama):
    if baru is None or lama in (None, 0):
        return None
    try:
        return round((baru - lama) / abs(lama) * 100, 1)
    except Exception:
        return None


def deret(entri, n, kuartalan):
    """Deret periode + pertumbuhan. Pertumbuhan HANYA dihitung bila periodenya benar-benar
    berurutan.

    Kenapa penting: kuartal keempat sering TIDAK muncul sebagai 10-Q tersendiri (angkanya
    masuk 10-K tahunan), sehingga deretnya berlubang. Kalau lubang itu diabaikan, selisih
    dua periode yang terpaut 6 bulan akan tertulis sebagai "QoQ" — pernah membuat NVDA
    terbaca +43,2% QoQ padahal itu lompatan Okt -> Apr.
    """
    d = pilih(entri, kuartalan)[-(n + 1):]
    jarak_wajar = (70, 110) if kuartalan else (300, 430)
    keluar = []
    for i, e in enumerate(d):
        ubah, catatan = None, None
        if i > 0:
            selisih = (e["akhir"] - d[i - 1]["akhir"]).days
            if jarak_wajar[0] <= selisih <= jarak_wajar[1]:
                ubah = tumbuh(e["nilai"], d[i - 1]["nilai"])
            else:
                catatan = (f"periode sebelumnya terpaut {selisih} hari — tidak berurutan, "
                           "pertumbuhan tidak dihitung (kemungkinan kuartal itu hanya ada "
                           "di 10-K tahunan)")
        baris = {"periode": str(e["akhir"]), "nilai": e["nilai"],
                 "perubahan_persen": ubah, "form": e["form"]}
        if catatan:
            baris["catatan"] = catatan
        keluar.append(baris)
    return keluar[-n:]


def cari_setahun_lalu(deret_kuartal, periode_akhir):
    """Cari kuartal yang berakhir ~1 tahun sebelum periode ini — bukan sekadar 4 baris ke
    belakang, karena deretnya bisa berlubang."""
    target = hari(periode_akhir)
    if not target:
        return None
    terbaik, jarak_terbaik = None, None
    for q in deret_kuartal:
        t = hari(q["periode"])
        if not t:
            continue
        selisih = abs((target - t).days - 365)
        if selisih <= 45 and (jarak_terbaik is None or selisih < jarak_terbaik):
            terbaik, jarak_terbaik = q, selisih
    return terbaik


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--price", type=float, default=None, help="harga saham untuk hitung P/E & P/S")
    ap.add_argument("--ringkas", action="store_true",
                    help="hanya 6 kuartal & 3 tahun terakhir per metrik — hemat token")
    args = ap.parse_args()
    ticker = args.ticker.upper().replace("$", "")

    hasil = {
        "ticker": ticker,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sumber": "SEC EDGAR XBRL (resmi, gratis, tanpa API key)",
        "peringatan": [
            "HANYA emiten bursa AS. Saham Eropa/Asia/Indonesia tidak tercakup.",
            "Laporan keuangan TERTINGGAL dari harga (kuartal terakhir bisa berumur 1-3 bulan). "
            "Ini fundamental, bukan sinyal harga.",
            "Angka bisa direvisi; dipakai filing yang paling akhir diajukan.",
        ],
    }

    cik, nama, err = cari_cik(ticker)
    if err:
        hasil["error"] = err
        print(json.dumps(hasil, indent=2, ensure_ascii=False))
        return
    hasil["nama"] = nama
    hasil["cik"] = cik

    data, tag_terpakai, kosong = {}, {}, []
    for nama_m, tags in METRIK.items():
        entri, tag = ambil_metrik(cik, tags)
        if not entri:
            kosong.append(nama_m)
            continue
        tag_terpakai[nama_m] = tag
        data[nama_m] = {
            "kuartalan": deret(entri, 8, True),
            "tahunan": deret(entri, 4, False),
            "satuan": entri[0]["unit"],
        }

    hasil["metrik"] = data
    hasil["tag_xbrl_terpakai"] = tag_terpakai
    if kosong:
        hasil["tidak_tersedia"] = kosong
        hasil["kenapa_kosong"] = ("Perusahaan ini tidak melaporkan tag XBRL yang dicari. "
                                  "Perlakukan sebagai TIDAK ADA — jangan dikarang.")

    # Ringkasan siap pakai + umur data, supaya keterlambatan laporan terlihat.
    rev_q = (data.get("revenue") or {}).get("kuartalan") or []
    ni_q = (data.get("laba_bersih") or {}).get("kuartalan") or []
    if rev_q:
        akhir = hari(rev_q[-1]["periode"])
        umur = (datetime.now(timezone.utc).date() - akhir).days if akhir else None
        ring = {"kuartal_terakhir": rev_q[-1]["periode"],
                "umur_hari": umur,
                "revenue": rev_q[-1]["nilai"],
                "revenue_qoq_persen": rev_q[-1]["perubahan_persen"]}
        if rev_q[-1].get("catatan"):
            ring["catatan_qoq"] = rev_q[-1]["catatan"]
        setahun = cari_setahun_lalu(rev_q[:-1], rev_q[-1]["periode"])
        if setahun:
            ring["revenue_yoy_persen"] = tumbuh(rev_q[-1]["nilai"], setahun["nilai"])
            ring["yoy_dibanding"] = setahun["periode"]
        else:
            ring["revenue_yoy_persen"] = None
            ring["catatan_yoy"] = "tidak ada kuartal pembanding ~1 tahun lalu di data"
        if ni_q and rev_q[-1]["nilai"]:
            try:
                ring["margin_bersih_persen"] = round(ni_q[-1]["nilai"] / rev_q[-1]["nilai"] * 100, 1)
            except Exception:
                pass
        if umur is not None and umur > 120:
            ring["catatan"] = ("Laporan terakhir sudah lebih dari 4 bulan — kemungkinan besar "
                               "kuartal terbaru belum diajukan. Sebutkan keterlambatan ini.")
        hasil["ringkasan"] = ring

    # Rasio valuasi hanya dihitung kalau harga diberikan — tanpa harga, JANGAN menebak.
    if args.price:
        eps_q = (data.get("eps_diluted") or {}).get("kuartalan") or []
        eps_ttm = sum(e["nilai"] for e in eps_q[-4:] if e["nilai"] is not None) if len(eps_q) >= 4 else None
        rasio = {"harga_dipakai": args.price}
        if eps_ttm:
            rasio["eps_ttm"] = round(eps_ttm, 2)
            rasio["pe_ttm"] = round(args.price / eps_ttm, 2) if eps_ttm > 0 else "negatif (rugi)"
        rev_ttm = sum(e["nilai"] for e in rev_q[-4:] if e["nilai"] is not None) if len(rev_q) >= 4 else None
        if rev_ttm:
            rasio["revenue_ttm"] = rev_ttm
        rasio["acuan"] = ("P/E TTM: <15 murah relatif · 15-25 wajar · 25-40 mahal · >40 sangat "
                          "mahal (harus dibayar pertumbuhan tinggi). Bandingkan dengan sesama "
                          "emiten di sektor yang sama, bukan lintas sektor.")
        hasil["rasio"] = rasio
    else:
        hasil["catatan_rasio"] = ("P/E & P/S tidak dihitung karena harga tidak diberikan. "
                                  "Jalankan ulang dengan --price <harga> (ambil dari market.py).")

    # Kartu rasio: yang BISA dihitung jujur dari tag XBRL yang ada. Yang tidak bisa
    # (current/quick ratio butuh aset & liabilitas LANCAR terpisah; interest coverage butuh
    # beban bunga & EBIT) dilaporkan tidak tersedia — bukan ditebak.
    def akhir(nama):
        d = (data.get(nama) or {}).get("kuartalan") or []
        return d[-1]["nilai"] if d and d[-1].get("nilai") is not None else None

    def ttm(nama):
        """Jumlah 4 kuartal terakhir. None kalau deretnya BERLUBANG — menjumlahkan kuartal
        yang tidak berurutan menghasilkan TTM palsu (kuartal Q4 sering hanya ada di 10-K)."""
        d = [x for x in ((data.get(nama) or {}).get("kuartalan") or [])
             if x.get("nilai") is not None]
        if len(d) < 4:
            return None
        empat = d[-4:]
        try:
            tgl = [datetime.strptime(x["periode"], "%Y-%m-%d") for x in empat]
        except Exception:
            return None
        for a, b in zip(tgl, tgl[1:]):
            if not (70 <= (b - a).days <= 110):   # jarak kuartal yang wajar
                return None
        return sum(x["nilai"] for x in empat)

    # Arus (laba, revenue, arus kas) dipakai TTM; neraca (aset/liabilitas/ekuitas) dipakai
    # nilai terakhir. Membandingkan laba SATU KUARTAL dengan ekuitas menghasilkan ROE
    # kuartalan yang mudah disalahbaca sebagai tahunan.
    def peta_tahunan(nama):
        return {x["periode"]: x["nilai"]
                for x in ((data.get(nama) or {}).get("tahunan") or [])
                if x.get("nilai") is not None}

    def tahunan_sepadan():
        """Ambil revenue & laba dari PERIODE YANG SAMA.

        Mengambil elemen terakhir tiap metrik secara terpisah bisa memasangkan revenue
        tahun X dengan laba tahun Y — AAPL sempat menghasilkan margin 42% (aslinya ~22%)
        karena keduanya dari tahun berbeda. Periode wajib sama.
        """
        pr, pn = peta_tahunan("revenue"), peta_tahunan("laba_bersih")
        sama = sorted(set(pr) & set(pn))
        if not sama:
            return None, None, None, None
        t = sama[-1]
        return pr[t], pn[t], peta_tahunan("arus_kas_operasi").get(t), t

    # TTM lebih segar, tapi deret kuartalan sering berlubang (kuartal yang hanya ada di
    # 10-K). Kalau begitu, pakai TAHUNAN — itu data sah, cuma lebih lama. Yang dipakai
    # selalu disebutkan supaya tidak disalahbaca sebagai angka terbaru.
    rev, ni, ocf = ttm("revenue"), ttm("laba_bersih"), ttm("arus_kas_operasi")
    dasar = "TTM (4 kuartal terakhir berurutan)"
    if rev is None or ni is None:
        rev_t, ni_t, ocf_t, per_t = tahunan_sepadan()
        if rev_t and ni_t:
            rev, ni, ocf = rev_t, ni_t, ocf_t
            dasar = (f"TAHUNAN {per_t} (deret kuartalan berlubang sehingga TTM tidak bisa "
                     f"dihitung — angka ini lebih lama, WAJIB sebutkan periodenya)")
            try:
                umur_th = (datetime.now(timezone.utc).date()
                           - datetime.strptime(per_t, "%Y-%m-%d").date()).days
                if umur_th > 500:
                    dasar += (f" — PERINGATAN: laporan tahunan ini sudah {umur_th} hari "
                              f"({umur_th // 365} tahun); rasio ini kemungkinan besar TIDAK "
                              f"lagi menggambarkan kondisi sekarang, jangan dipakai menilai "
                              f"valuasi saat ini")
            except Exception:
                pass
    aset, liab, eq = akhir("aset"), akhir("liabilitas"), akhir("ekuitas")
    kartu, kosong = {}, []
    kartu["dasar_perhitungan"] = f"arus = {dasar}; neraca = kuartal terakhir"
    def taruh(k, pembilang, penyebut, kali=1, satuan="x"):
        if pembilang is not None and penyebut:
            kartu[k] = round(pembilang / penyebut * kali, 2)
        else:
            kosong.append(k)
    taruh("roe_ttm_persen", ni, eq, 100)
    taruh("roa_ttm_persen", ni, aset, 100)
    taruh("margin_bersih_ttm_persen", ni, rev, 100)
    taruh("utang_terhadap_ekuitas", liab, eq)
    taruh("perputaran_aset_ttm", rev, aset)
    # Kualitas laba: arus kas operasi dibagi laba bersih. Di bawah 1 berarti laba tidak
    # sepenuhnya menjadi kas — persis tanda tanya yang disebut metodologi saham.
    taruh("kualitas_laba_ocf_per_laba_ttm", ocf, ni)
    if kartu:
        if kosong:
            kartu["tidak_bisa_dihitung"] = kosong
        kartu["tidak_tersedia"] = [
            "current ratio & quick ratio (butuh aset/liabilitas LANCAR terpisah)",
            "interest coverage (butuh beban bunga & EBIT)",
            "ROIC & WACC (butuh modal terinvestasi & biaya modal)",
        ]
        hasil["kartu_rasio"] = kartu

    if args.ringkas:
        for nama, isi in (hasil.get("metrik") or {}).items():
            if isinstance(isi, dict):
                for periode, batas in (("kuartalan", 6), ("tahunan", 3)):
                    if isinstance(isi.get(periode), list):
                        isi[periode] = isi[periode][-batas:]
        for k in ("tag_xbrl_terpakai",):
            hasil.pop(k, None)

    print(json.dumps(hasil, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

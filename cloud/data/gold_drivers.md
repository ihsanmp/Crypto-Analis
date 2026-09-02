# Acuan Analisa GOLD (XAUUSD) — Data Ekonomi Penggerak

Materi acuan milik user, disusun 18 Juli 2026. Dipakai bot saat menganalisa gold/XAUUSD.

**Cara membaca kolom dampak:** arah yang tertulis berlaku bila **actual LEBIH TINGGI dari
forecast**. Kalau actual lebih rendah, arah dampaknya **kebalikannya**.

**Jam rilis (WIB):** mayoritas data 19.30–21.00 (08.30–10.00 pagi waktu AS).
Keputusan FOMC pukul 01.00 dini hari.

---

## Mekanisme utama — satu pintu yang sama

Hampir semua data bekerja lewat satu pertanyaan:

> **Apakah ini membuat The Fed lebih HAWKISH (galak) atau DOVISH (lunak)?**

Data ekonomi KUAT → Fed hawkish → yield & dolar naik → **gold turun**
Data ekonomi LEMAH → Fed dovish → yield & dolar turun → **gold naik**

**Yang menggerakkan pasar adalah SELISIHNYA** — bukan angka absolutnya, melainkan
selisih *actual vs forecast* di kalender ekonomi.

---

## RANTAI SEBABNYA — kenapa data ekonomi sampai ke harga emas

Emas **tidak membayar bunga**. Itu satu kalimat yang menjelaskan hampir seluruh tabel di
bawah:

```
Kebijakan Fed (suku bunga)  →  US Bond Yield  →  DXY (nilai USD)  →  Gold (XAUUSD)
```

| Saat suku bunga NAIK | Saat suku bunga TURUN |
|---|---|
| Yield naik → biaya pinjam mahal | Yield turun → biaya pinjam murah |
| USD menguat → dolar lebih diminati | USD melemah → dolar kurang diminati |
| **Gold turun** → investor pilih aset berbunga | **Gold naik** → investor cari aset lindung nilai |

**Yield riil 10 tahun adalah jalur paling langsung.** Yield naik = biaya peluang memegang
emas (yang tidak memberi bunga) jadi lebih besar → emas ditinggalkan. Itu sebabnya
`makro.py` memantau DGS10 dan **DFII10** (yield riil), bukan hanya suku bunga Fed.

Dua jalur ini kadang berlawanan, dan saat itu terjadi yang menang biasanya yield riil:
DXY bisa menguat karena pelarian risiko (yang justru menopang emas), sementara yield riil
naik hampir selalu menekan emas.

---

## Peringkat kekuatan dampak

```
Federal Funds Rate  >  NFP = CPI = Core PCE  >  sisanya
```

⚠️ **Peringkat ini menyamakan NFP dan CPI, dan pengukuran di repo ini membantahnya.**
Lihat bagian berikutnya sebelum memakai peringkat ini.

---

## SUDAH DIUKUR — mana yang bertahan, mana yang tidak

Tabel-tabel di dokumen ini adalah **materi belajar**, bukan hasil pengukuran. Sebagiannya
sudah diuji terhadap data sungguhan lewat `cloud/kejutan.py` (studi peristiwa, reaksi
dipisah menurut arah kejutan, lalu tandanya diuji apakah bertahan saat data dipotong per
rezim dan di paruh yang belum pernah dilihat). Hasilnya **tidak seragam**:

| Klaim di dokumen ini | Vonis pengukuran |
|---|---|
| NFP di atas forecast → **gold turun (kuat)** | ✅ **BERTAHAN**, tapi MENYUSUT |
| CPI di atas forecast → **gold turun (kuat)** | ❌ **TIDAK ADA EDGE ARAH** |

**NFP → emas** (179 rilis, 2011-09 s/d 2026-09, konsensus SoSoValue). Selisih median hari
rilis panas−dingin **−0,57%**, dan tandanya negatif di **kelima** potongan rezim (−1,30 ·
−0,51 · −0,24 · −0,79 · −0,44). Uji luar sampel: paruh awal −0,80%, paruh akhir −0,31% —
tanda bertahan tapi besarannya menyusut lebih dari separuh. **Kutip −0,31%, bukan −0,57%**;
angka gabungan terlalu optimistis.

**CPI → emas** (178 rilis, jendela sama). Selisih median hari rilis **+0,16%** — bukan cuma
kecil, tapi **berlawanan tanda** dengan yang ditulis di dokumen ini. Dan angka itu tidak
bisa dipakai ke arah mana pun: tandanya berbalik antar potongan (periode +0,02 · +0,39 ·
−0,07; inflasi tinggi +0,35 vs inflasi rendah −0,37), dan di uji luar sampel paruh awal
−0,02% menjadi paruh akhir +0,27% — **tanda tidak bertahan**. Selisih di bawah ~0,3% pada
emas juga tidak bisa dibedakan dari derau harian.

Vonisnya: **CPI tidak punya edge arah untuk emas.** Bukan "lemah", bukan "terbalik" —
tidak ada. Reaksi menit-menit pertama boleh saja terjadi; yang tidak ada adalah arah yang
bisa diandalkan sampai penutupan hari.

**ATURAN SAAT BENTROK: hasil ukur mengalahkan tabel.** Kalau brief memuat keluaran
`kejutan.py`, pakai vonisnya dan sebutkan bahwa angkanya dari pengukuran. Tabel di bawah
tetap berguna untuk **jadwal, mekanisme, dan arah yang masuk akal secara ekonomi** — tapi
jangan menyebut sebuah arah "kuat" hanya karena tertulis kuat di sini.

---

## INFLASI

| Data | Apa yang diukur | Jadwal rutin | Jika actual > forecast |
|---|---|---|---|
| **CPI m/m** | Perubahan harga konsumen vs bulan lalu; inflasi paling ditunggu pasar | Tgl 10–15 tiap bulan (data bulan sebelumnya) | **Gold turun (kuat)** |
| CPI y/y | Inflasi setahun terakhir; untuk konteks tren | Bersamaan CPI m/m | Gold turun |
| **Core CPI m/m** | CPI tanpa makanan & energi; inflasi "murni" yang diperhatikan Fed | Bersamaan CPI m/m | **Gold turun (kuat)** |
| PPI m/m | Inflasi tingkat produsen; sering jadi "bocoran" arah CPI berikutnya | 1–3 hari setelah CPI (tgl 11–17) | Gold turun |
| Core PPI m/m | PPI tanpa makanan & energi | Bersamaan PPI m/m | Gold turun |
| **Core PCE Price Index m/m** | Ukuran inflasi RESMI yang dipakai Fed untuk target 2% | Akhir bulan, tgl 26–31 | **Gold turun (kuat)** |

---

## TENAGA KERJA

| Data | Apa yang diukur | Jadwal rutin | Jika actual > forecast |
|---|---|---|---|
| **Non-Farm Payroll (NFP)** | Pekerjaan baru di luar pertanian; data terbesar awal bulan | Jumat pertama tiap bulan | **Gold turun (kuat)** |
| **Unemployment Rate** | Persentase pengangguran | Bersamaan NFP | ⚠️ **Gold NAIK (arah terbalik)** |
| Average Hourly Earnings m/m | Pertumbuhan upah; upah naik = tekanan inflasi tambahan | Bersamaan NFP | Gold turun |
| ADP Non-Farm Employment | Versi swasta NFP; dipakai pasar "menebak" NFP | Rabu sebelum NFP | Gold turun |
| **Unemployment Claims** (mingguan) | Klaim tunjangan pengangguran baru | Setiap Kamis | ⚠️ **Gold NAIK (arah terbalik)** |
| JOLTS Job Openings | Lowongan kerja terbuka; pelengkap gambaran tenaga kerja | Awal bulan tgl 1–5 (data 2 bulan lalu) | Gold turun |

⚠️ **DUA PENGECUALIAN ARAH:** Unemployment Rate dan Unemployment Claims — angkanya NAIK
berarti ekonomi MELEMAH, sehingga efeknya terbalik (naik = dovish = **gold naik**).

---

## THE FED

| Data | Apa yang diukur | Jadwal rutin | Jika actual > forecast |
|---|---|---|---|
| **Federal Funds Rate (FOMC)** | Keputusan suku bunga; event TERBESAR | 8x setahun (~tiap 6 pekan) | **Gold turun (sangat kuat)** |
| FOMC Meeting Minutes | Notulen rapat | 3 pekan setelah tiap rapat | Hawkish → gold turun |
| Pidato Ketua/Pejabat Fed | "Fed Chair Speaks" dsb; satu kalimat bisa setara dampak CPI | Sporadis, hampir tiap pekan | Hawkish → gold turun |

**Jadwal FOMC 2026:** 27–28 Jan · 17–18 Mar · 28–29 Apr · 16–17 Jun · 28–29 Jul ·
15–16 Sep · 27–28 Okt · 8–9 Des

---

## AKTIVITAS EKONOMI & KONSUMEN

| Data | Apa yang diukur | Jadwal rutin | Jika actual > forecast |
|---|---|---|---|
| ISM Manufacturing PMI | Survei manajer pembelian pabrik; >50 ekspansi, <50 kontraksi | Hari kerja pertama (tgl 1–3) | Gold turun |
| ISM Services PMI | Survei sektor jasa, porsi terbesar ekonomi AS | Hari kerja ke-3 (tgl 3–5) | Gold turun |
| Retail Sales m/m | Belanja konsumen (~70% ekonomi AS); ada versi Core tanpa mobil | Pertengahan bulan (tgl 14–17) | Gold turun |
| Advance GDP q/q | Pertumbuhan ekonomi kuartalan; versi "Advance" paling berdampak | Akhir Jan/Apr/Jul/Okt | Gold turun |
| Flash Manufacturing & Services PMI | Versi awal PMI dari S&P Global, sinyal lebih dini dari ISM | Tgl 21–24 tiap bulan | Gold turun |
| Prelim UoM Consumer Sentiment | Keyakinan konsumen University of Michigan | Jumat tgl 10–15 (final akhir bulan) | Gold turun |
| **UoM Inflation Expectations** | Ekspektasi inflasi masyarakat; sangat dipantau Fed di era inflasi energi 2026 | Bersamaan UoM Sentiment | **Gold turun (kuat)** |
| CB Consumer Confidence | Keyakinan konsumen versi Conference Board | Selasa terakhir (tgl 25–30) | Gold turun |

---

## KONTEKS KHUSUS 2026

| Data | Keterangan | Jadwal | Dampak |
|---|---|---|---|
| EIA Crude Oil Inventories | Stok minyak mentah AS; relevan karena inflasi saat ini didorong energi/Hormuz | Setiap Rabu malam WIB | Stok turun → gold ikut bergerak via jalur inflasi |
| Headline Iran / geopolitik | Bukan data terjadwal; negosiasi atau eskalasi Selat Hormuz menggerakkan minyak lalu gold | Kapan saja | De-eskalasi → dukungan gold via Fed melunak |

---

## Karakter hari dalam sepekan (kecenderungan, BUKAN aturan)

Pengamatan umum trader XAUUSD:

| Hari | Kecenderungan | Sebab yang masuk akal |
|---|---|---|
| **Senin** | Volatilitas rendah | Pasar mencerna akhir pekan; jarang ada rilis data AS |
| **Selasa** | Breakout | Rilis data mulai masuk; posisi pekan baru terbentuk |
| **Rabu** | Kelanjutan tren | Arah pekan biasanya sudah terbaca; sering ada FOMC/minutes |
| **Kamis** | Pembalikan | **Unemployment Claims rilis SETIAP Kamis** — pemicu terjadwal |
| **Jumat** | Fake-out | **NFP di Jumat pertama**; sisanya penutupan posisi jelang akhir pekan |

**CARA MEMAKAINYA — penting:**
- Ini **kecenderungan statistik longgar**, bukan hukum. Jangan dijadikan alasan utama
  masuk atau keluar posisi. Banyak pekan tidak mengikuti pola ini sama sekali.
- **Yang sebenarnya menggerakkan adalah JADWAL RILIS, bukan nama harinya.** Kamis terasa
  sering berbalik karena Unemployment Claims memang rilis tiap Kamis; Jumat terasa banyak
  fake-out karena NFP dan penutupan posisi. Jadi periksa kalender dulu — kalau pekan itu
  Kamisnya tidak ada rilis penting, jangan mengharapkan pembalikan.
- Pakai sebagai **kewaspadaan**, bukan sinyal: mis. "hari ini Jumat NFP, rawan fake-out —
  tunggu konfirmasi close candle sebelum menyimpulkan arah".
- Kalau pola hari **bertentangan** dengan teknikal dan makro, yang menang teknikal + makro.

## Catatan penting cara membaca

- **Arti "Core"** — versi tanpa harga makanan & energi. Di era inflasi energi 2026,
  **selisih headline vs core adalah cerita utamanya** — baca keduanya saat rilis CPI.
- **m/m vs y/y** — m/m (vs bulan lalu) lebih sensitif dan lebih menggerakkan pasar;
  y/y untuk konteks tren.
- **Timing eksekusi** — untuk event berdampak kuat: hindari membuka posisi baru
  **30 menit sebelum rilis**; masuk setelah arah jelas (konfirmasi close candle).
- **Validasi silang** — setelah rilis besar, cek **CME FedWatch** (probabilitas suku bunga)
  dan **US02Y** (yield 2 tahun). Kalau keduanya bergerak searah dugaan, reaksi gold
  biasanya bertahan.

⚠️ Materi belajar, bukan nasihat keuangan. Keputusan trading dan risikonya milik pembaca.

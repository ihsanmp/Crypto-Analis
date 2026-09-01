# BRIEFING: Pengaruh Fase Bulan (Moon Phase) terhadap Pergerakan Harga Bitcoin

**Status dokumen:** referensi faktual untuk agent analis
**Disusun:** 2 September 2026
**Cakupan:** BTC/USD saja (bukan altcoin, bukan ekuitas kecuali sebagai latar literatur)
**Sifat:** dokumen ini berisi hasil pengujian empiris independen + tinjauan literatur. Angka-angka di
Bagian 4 dihasilkan dari data mentah, bukan dikutip dari pihak ketiga, dan dapat direproduksi
dengan skrip yang disertakan.

---

## 0. BOTTOM LINE (baca ini dulu)

**Tidak ditemukan bukti bahwa fase bulan punya efek terukur pada return atau volatilitas BTC.**

- Uji event-window ±3 hari dan ±7 hari: p = 0,66 sampai 0,99 di semua sampel.
- Uji harmonik (sudut fase kontinu): F = 0,29, p = 0,883.
- Uji placebo: siklus bulan asli berkinerja **lebih buruk daripada median siklus palsu** yang
  offset fasenya diacak (p empiris = 0,908).
- Satu-satunya pola yang lolos uji naif (volatilitas) terbukti berasal dari ~4 episode ekor gemuk
  di 2013 dan 2020, dan mati begitu di-winsorize.
- Backtest naif kalah dari buy-and-hold bahkan setelah penyesuaian risiko.

**Instruksi operasional:** perlakukan fase bulan sebagai **fitur null**. Jangan gunakan sebagai
sinyal entry, exit, sizing, maupun filter regime. Lihat Bagian 7 untuk aturan pemakaian rinci.

**Tingkat keyakinan:** tinggi untuk return harian (sampel besar, banyak spesifikasi, semua null,
konsisten dengan literatur akademik terbaru). Sedang untuk klaim yang belum diuji di sini
(intraday, perigee/apogee, gerhana) — lihat Bagian 8.

---

## 1. Apa klaimnya

Hipotesis populer "moon phase trading" punya dua varian yang saling bertentangan:

| Varian | Klaim | Asal |
|---|---|---|
| A (dari literatur saham) | Return lebih **tinggi** di sekitar new moon, lebih **rendah** di sekitar full moon | Dichev & Janes (2003); Yuan, Zheng & Zhu (2006) |
| B (dari backtest kripto ritel) | Beli saat full moon, jual saat new moon | Blog/backtest kripto, arah kebalikan varian A |

Mekanisme yang diusulkan bersifat perilaku: siklus bulan memengaruhi mood/suasana hati investor,
mood memengaruhi selera risiko, selera risiko memengaruhi harga. Tidak ada mekanisme fisik
(gaya pasang surut pada manusia besarnya dapat diabaikan).

**Catatan penting:** varian A dan B punya arah berlawanan. Setiap kali dua kubu mengklaim efek
yang berlawanan tanda dari data yang sama, itu indikasi kuat bahwa yang diamati adalah noise.

---

## 2. Literatur pasar saham (latar belakang, bukan bukti untuk BTC)

**Dichev & Janes (2003), *Journal of Private Equity*.** Data AS. Rata-rata return 15 hari di sekitar
new moon kira-kira dua kali lipat return 15 hari di sekitar full moon. Selisih tahunan 5–10%.

**Yuan, Zheng & Zhu (2006), *Journal of Empirical Finance* 13(1):1–23.** 48 negara. Return saham
lebih rendah di hari-hari sekitar full moon dibanding sekitar new moon; selisih 3–5% per tahun pada
portofolio global equal-weighted maupun value-weighted. Penulis menyatakan efek tidak dijelaskan
oleh volatilitas, volume perdagangan, atau anomali kalender lain.
URL: https://escholarship.org/content/qt70z5b0ng/qt70z5b0ng.pdf

**Konteks kritis yang sering dihilangkan saat dikutip:**
- Yuan et al. sendiri secara eksplisit mengakui kemungkinan hubungan tersebut spurious.
- Efek fase bulan kemudian dipakai sebagai **contoh pengajaran data snooping** — justru karena
  variabelnya non-finansial dan absurd, ia berguna untuk mendemonstrasikan bagaimana pola bisa
  muncul dari pencarian berulang. Referensi: lunar.behaviouralfinance.net
- Studi lanjutan saling bertentangan: Brahmana et al. (2014) menemukan full moon berpengaruh
  negatif tapi new moon tidak; Borowski (2015, Polandia) menemukan kebalikannya — new moon
  berpengaruh positif tapi full moon tidak.

**Kovacs (2025), SSRN 5867668 — replikasi terbaru dan paling ketat.** Menguji ulang hipotesis
"Moonstruck Investors" pada indeks ekuitas global dengan data harian sampai 2025, window ±3 hari,
inferensi HAC (Newey–West). Temuan: **tidak ada anomali lunar global yang robust.** Pada indeks
maju utama (S&P 500, DAX, FTSE 100, TSX, CAC 40, Hang Seng, dll.), return 7-hari sedikit lebih
tinggi di sekitar new moon, tapi selisihnya kecil dan tidak signifikan. Beberapa pasar menunjukkan
premi new moon yang signifikan (Nikkei 225 ~+0,33 pp per window, p≈0,01; ^SNX dan TASI ~0,5–0,6 pp;
JCI Jakarta kuat di dekade 2000-an ~0,9 pp, p≈0,03), tapi dekomposisi per dekade menunjukkan efek
ini **tidak time-invariant** — mereka mengelompok di pasar dan periode tertentu, sementara pasar
dan dekade lain menunjukkan pola lemah atau justru terbalik.
URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5867668

---

## 3. Literatur khusus kripto/BTC

**Kovacs (2025), bagian kripto.** 10 koin besar (BTC, ETH, XRP, BNB, SOL, TRX, DOGE, ADA, LINK,
XLM), window ±7 dan ±3 hari non-overlapping, dibandingkan dengan benchmark rolling-window tanpa
syarat. Temuan:
- Window ±7 hari: baik new moon maupun full moon menunjukkan return positif besar, konsisten dengan
  drift naik kripto secara umum; selisih antar fase kecil dan tidak signifikan.
- Window ±3 hari: window new moon *underperform* window 6-hari tanpa syarat sekitar 1,1 poin persen
  (p≈0,02); window full moon mengungguli window new moon sekitar 1,7 poin (p≈0,07).
  **Arah ini berlawanan dengan hipotesis dari literatur saham.**
- Volatilitas harian realized di window ±3 hari sekitar 4,6–4,7% per hari dan **praktis identik**
  di semua fase bulan maupun dibanding minggu tanpa syarat.
- Kesimpulan penulis: di kripto, efek lunar pada return kecil relatif terhadap drift dan volatilitas
  latar, dan tidak ada pola volatilitas yang menyertainya.

**"Astrofinance and Behavioral Drivers of Cryptocurrency Returns" (2025), JAFAS 11(3).** BTC dan ETH,
event study + regresi + XGBoost, dengan variabel sentimen (Google Trends, Fear & Greed Index, skor
NLP) dan indikator teknikal (RSI, MACD, EMA). Temuan: **tidak ada korelasi langsung yang signifikan
secara statistik antara fase bulan dan return harian.** Uji t terhadap average abnormal return: tidak
satu pun event window untuk BTC atau ETH menunjukkan deviasi signifikan dari nol. Dummy full moon
tidak berpengaruh signifikan pada BTC maupun ETH. Penulis mencatat fase bulan berasosiasi dengan
perubahan sentimen investor dan volume perdagangan, tapi efek harga bersifat transien.
URL: https://www.acadlore.com/article/JAFAS/2025_11_3/jafas110304

**"Do Lunar Cycles Affect Bitcoin Prices?"** Membandingkan harga open/close di awal dan akhir siklus
lunar menggunakan uji McNemar. Kesimpulan: siklus bulan tidak berdampak signifikan secara statistik
terhadap perubahan harga Bitcoin.

**Patil (2025), IJSET 13(3) — sumber angka "30%+" yang beredar.** Melaporkan strategi full moon pada
BTC 2014–2025 menghasilkan return tahunan 32,2%, risk-adjusted return 65,6%, max drawdown 81%.
Dengan filter musiman, return naik ke 43,3%.
**PERINGATAN — baca angka pembandingnya:** dalam paper yang sama, buy-and-hold BTC menghasilkan
risk-adjusted return 68%. Jadi strategi lunar tersebut **kalah dari beli-dan-tahan** di periode yang
kebetulan merupakan bull market terpanjang BTC. Penulisnya sendiri menyimpulkan robustness
statistiknya diperdebatkan, tidak ada mekanisme kausal yang mapan, dan strategi ini paling banter
alat pelengkap, bukan sistem berdiri sendiri.
URL: https://www.ijset.in/wp-content/uploads/IJSET_V13_issue3_421..pdf

**Sintesis literatur:** dari empat studi kripto di atas, tiga menemukan null dan satu melaporkan
hasil positif yang ternyata kalah dari benchmark-nya sendiri. Tidak ada satu pun yang menetapkan
mekanisme kausal.

---

## 4. Pengujian empiris independen (dilakukan untuk dokumen ini)

### 4.1 Data

| Item | Nilai |
|---|---|
| Sumber | Bitstamp BTC/USD, OHLC 1 menit, repo publik `ff137/bitstamp-btcusd-minute-data` |
| Agregasi | Harian, batas hari UTC |
| Periode | 2 Jan 2012 – 31 Agu 2026 |
| Jumlah observasi | 5.356 hari |
| Hari hilang | 0 |
| Jumlah siklus sinodis tercakup | ~181 |
| Variabel target | log return harian dari close ke close |
| Perhitungan fase | ephemeris `ephem` (bukan aproksimasi 29,5 hari); fase dievaluasi di tengah hari bar |
| Definisi fase | p ∈ [0,1); p=0,0 = new moon, p=0,5 = full moon |

Catatan: satu sumber exchange dipakai konsisten sepanjang periode untuk menghindari artefak
penyambungan data antar-bursa.

### 4.2 Spesifikasi uji

1. **Event-window test.** OLS: `r_t = a + b1·NEW_t + b2·FULL_t + kontrol + e_t`, di mana NEW=1 jika
   jarak ke new moon ≤ halfwin, FULL=1 jika jarak ke full moon ≤ halfwin. Kontrol: dummy
   day-of-week, dummy turn-of-month (3 hari pertama + 2 hari terakhir bulan kalender).
   Standard error HAC (Newey–West) dengan maxlags = panjang window, karena window saling tumpang
   tindih dan OLS biasa akan melebih-lebihkan signifikansi. Hipotesis diuji lewat kontras b1 − b2.
2. **Harmonic test.** `r_t = a + Σ_k [c_k·cos(2πkp_t) + s_k·sin(2πkp_t)] + kontrol + e_t`, K=2.
   Uji F gabungan pada semua suku harmonik. Ini lebih ketat daripada dummy biner: kalau efeknya
   nyata, ia harus mulus di seluruh siklus, bukan hanya di dua titik yang dipilih peneliti.
3. **Placebo test.** Prosedur (1) diulang dengan 2.000–3.000 siklus **palsu** berperiode tepat
   29,53 hari tapi offset fase acak. Ini adalah kontrol terpenting: siklus palsu mempertahankan
   karakter "bulanan", sehingga menyerap seluruh musiman bulanan nyata (turn-of-month, expiry opsi
   CME, siklus funding rate, rebalancing). Kalau efek asli tidak berada di ekor distribusi placebo,
   tidak ada informasi lunar di sana.
4. **Uji volatilitas.** Rasio dispersi window ekstrem (new ATAU full ±3d) vs sisanya, dengan empat
   ukuran: sd mentah, MAD, mean|r|, dan sd setelah winsorize 1/99%; plus uji ulang setelah membuang
   20 hari dengan |r| terbesar.
5. **Split dev/hold-out.** Dev 2012–2021 (3.652 hari), hold-out 2022–2026 (1.704 hari).
6. **Backtest naif** dengan biaya 0,1% per switch.

### 4.3 Hasil — event-window test

| Sampel | Window | new (%/hari) | full (%/hari) | selisih new−full | t | p |
|---|---|---|---|---|---|---|
| Full 2012–2026 | ±3d | −0,0678 | −0,0816 | **+0,0138** | +0,08 | 0,937 |
| Full 2012–2026 | ±7d | −0,1393 | −0,1208 | **−0,0185** | −0,17 | 0,869 |
| Dev 2012–2021 | ±3d | +0,0197 | −0,0412 | **+0,0609** | +0,26 | 0,794 |
| Dev 2012–2021 | ±7d | −0,1446 | −0,1459 | **+0,0013** | +0,01 | 0,993 |
| Hold-out 2022–2026 | ±3d | −0,2278 | −0,1568 | **−0,0710** | −0,33 | 0,742 |
| Hold-out 2022–2026 | ±7d | −0,1246 | −0,0690 | **−0,0555** | −0,44 | 0,659 |

Koefisien NEW/FULL bertanda negatif karena diukur relatif terhadap konstanta yang menyerap drift;
yang relevan adalah kolom selisih. Tidak ada yang mendekati signifikan. **Tanda selisih berbalik
antara dev dan hold-out** — ciri khas noise, bukan sinyal.

### 4.4 Hasil — harmonic test

| Sampel | F | p | Amplitudo harmonik-1 |
|---|---|---|---|
| Full 2012–2026 | 0,29 | 0,883 | 0,040 %/hari |
| Dev 2012–2021 | 0,09 | 0,985 | 0,050 %/hari |
| Hold-out 2022–2026 | 0,81 | 0,521 | 0,030 %/hari |

Amplitudo maksimum 0,05%/hari berada **di bawah biaya transaksi** bahkan seandainya nyata.

### 4.5 Hasil — placebo test (uji paling menentukan)

| Window | \|t\| asli | Median \|t\| placebo | p95 placebo | p empiris |
|---|---|---|---|---|
| ±3d | 0,08 | 0,50 | 1,03 | **0,908** |
| ±7d | 0,17 | 0,39 | 0,82 | **0,819** |

**Interpretasi:** siklus bulan asli menjelaskan return BTC lebih buruk daripada siklus 29,53 hari
dengan offset acak. Kalau ada musiman bulanan nyata di BTC, placebo akan ikut menangkapnya — dan
ternyata bulan asli bahkan tidak mengalahkan median placebo.

### 4.6 Hasil — return rata-rata per oktan fase

| Oktan | Rata-rata (%/hari) | SE | n |
|---|---|---|---|
| New | +0,027 | 0,192 | 669 |
| Sabit naik | +0,190 | 0,143 | 669 |
| Kuartal I | +0,233 | 0,140 | 669 |
| Cembung naik | +0,294 | 0,148 | 675 |
| Full | −0,006 | 0,172 | 667 |
| Cembung turun | +0,219 | 0,144 | 674 |
| Kuartal III | +0,253 | 0,154 | 669 |
| Sabit turun | +0,231 | 0,163 | 664 |

Sekilas terlihat menarik: oktan New dan Full sama-sama mendekati nol, sementara enam oktan lain
+0,19% sampai +0,29%. **Tapi standard error-nya 0,14–0,19%** — seluruh selisih berada di dalam
noise, dan interval ±2SE setiap oktan memuat rata-rata keseluruhan (+0,18%/hari). Uji formal atas
kontras ini (ekstrem vs sisanya) memberi t = −0,73, p empiris terhadap placebo = 0,374.

### 4.7 Hasil — volatilitas (satu-satunya yang sempat menjanjikan)

Rasio dispersi window ekstrem (new ATAU full ±3d) dibanding sisanya:

| Ukuran | Rasio | p empiris vs placebo |
|---|---|---|
| sd mentah | **1,166** | **0,0000** |
| MAD (robust) | 1,052 | 0,043 |
| mean \|r\| | 1,046 | 0,039 |
| sd, winsorize 1/99% | 1,013 | 0,318 |
| sd, buang 20 hari \|r\| terbesar | **0,969** | 0,732 |

sd mentah mengalahkan **seluruh 3.000 placebo** (maksimum placebo 1,159). Kalau berhenti di baris
pertama, ini akan dilaporkan sebagai temuan besar. Ia tidak bertahan:

**Stabilitas per subperiode:**

| Periode | sd ekstrem | sd lainnya | rasio |
|---|---|---|---|
| 2012–2015 | 6,04% | 4,69% | 1,287 |
| 2016–2019 | 3,95% | 4,01% | 0,986 |
| 2020–2022 | 4,52% | 3,56% | 1,268 |
| 2023–2026 | 2,34% | 2,49% | 0,938 |

Dua subperiode naik, dua turun. Tidak stabil.

**Penyebabnya.** Dari 20 hari dengan |r| terbesar sepanjang 2012–2026, **tujuh berasal dari hanya dua
episode**: April 2013 dan Desember 2013. Contoh: 2013-04-11 (−66,4%, 1,1 hari dari new moon),
2013-04-10 (−34,6%, 0,1 hari dari new moon), 2013-04-12 (+27,6%), 2013-11-18 (+33,8%, 0,2 hari dari
full moon), 2013-11-19 (−22,2%), 2013-12-18 (−25,9%), 2013-12-19 (+27,6%), 2020-03-12 (−49,4%).

Hari-hari berurutan dalam satu krisis otomatis jatuh di window bulan yang sama. Mereka **bukan
observasi independen**. Ukuran sampel efektif untuk uji volatilitas bukan 5.356 hari, melainkan
beberapa puluh episode — dan pada n sebesar itu, rasio 1,17 sepenuhnya wajar secara kebetulan.

**Ini adalah pelajaran metodologis utama dari seluruh latihan ini:** pada aset berekor sangat gemuk
seperti BTC, statistik berbasis sd dapat didominasi oleh segelintir hari. Selalu ulangi dengan
ukuran robust dan setelah membuang outlier sebelum melaporkan apa pun.

### 4.8 Hasil — backtest naif

| Strategi | CAGR | Vol | Sharpe | max DD |
|---|---|---|---|---|
| Buy & hold | 93,2% | 78,0% | 0,84 | −84,9% |
| Long waxing (new→full), fee 0,1% | 37,1% | 55,1% | 0,57 | −80,4% |
| Long waning (full→new), fee 0,1% | 34,1% | 55,3% | 0,53 | −82,6% |

363 switch dalam 14,7 tahun. Kedua arah kalah dari buy-and-hold setelah penyesuaian risiko, dengan
drawdown tetap ~80%. Keduanya menghasilkan angka yang mirip — persis yang diharapkan jika timing
tidak membawa informasi dan strategi hanya mengambil separuh eksposur pasar secara sewenang-wenang.

### 4.9 Reproduksi independen di repo ini (2 Sep 2026)

Seluruh Bagian 4 dijalankan ulang dari data mentah yang sama sebelum dokumen ini diterima
sebagai acuan. Dokumen yang mengklaim dirinya dapat direproduksi harus benar-benar diuji,
bukan dipercaya karena bunyinya meyakinkan — itu justru kesalahan yang diperingatkan
dokumen ini sendiri di Bagian 5.

**Yang keluar identik** (5.356 hari, 2012-01-02 s/d 2026-08-31):

| Bagian | Status |
|---|---|
| 4.3 event-window, 6 baris | identik sampai 4 desimal |
| 4.4 harmonik, 3 sampel | identik (F = 0,29 · 0,09 · 0,81) |
| 4.5 placebo ±3d | identik (p empiris 0,908) |
| 4.7 volatilitas, 4 ukuran | identik (sd 1,1659 · MAD 1,0524 · mean\|r\| 1,0459 · winsor 1,0125) |
| 4.7 buang 20 hari \|r\| terbesar | **0,9693** — cocok dengan klaim 0,969 |
| 4.7 klaster 2013 | **12** dari 20 hari terbesar jatuh di Apr-2013 dan Nov/Des-2013 (dokumen menyebut 7; jumlah sebenarnya lebih banyak, jadi argumennya lebih kuat, bukan lebih lemah) |
| 4.8 backtest, 3 baris + 363 switch | identik |

**Beda kecil:** placebo ±7d memberi p empiris 0,803 (dokumen: 0,819) dan median \|t\| 0,38
(dokumen: 0,39). Ini variasi Monte Carlo antar-seed, bukan ketidakcocokan.

**Satu koreksi — tabel oktan 4.6 bergantung pada cara membagi bin.** Tabelnya reproduksi
8/8 hanya kalau bin **dimulai** di titik fase (`floor(p*8)`). Dengan bin yang **berpusat**
di titik fase — cara yang lebih wajar untuk melabeli sebuah oktan "New", karena isinya jadi
hari-hari TERDEKAT ke new moon — polanya hilang sama sekali:

| Oktan | bin dimulai | bin berpusat |
|---|---|---|
| New | +0,027 | **−0,085** |
| Full | −0,006 | **+0,361** ← tertinggi |
| Cembung naik | +0,294 | +0,143 |
| Cembung turun | +0,219 | +0,084 |

Pola "New dan Full sama-sama mendekati nol" yang jadi kail narasi Bagian 4.6 **hanya ada di
satu dari dua konvensi**, dan di konvensi satunya Full justru oktan tertinggi.

Ini tidak membantah kesimpulan dokumen — ia **memperkuatnya**, dan dengan cara yang lebih
telak daripada argumen SE di Bagian 4.6: temuan yang nyata tidak berubah tanda hanya karena
batas bin digeser seperdelapan siklus. Yang berubah begitu adalah derau. Bagian 4.6
sebaiknya dibaca sebagai contoh tambahan untuk Bagian 5 mekanisme 3 (data snooping), bukan
sebagai pola yang perlu dijelaskan.

Reproduksi: `python cloud/uji_lunar.py` · perbandingan oktan: `python cloud/uji_lunar.py --oktan`

---

## 5. Mengapa ilusi korelasi muncul

Daftar mekanisme yang menjelaskan kenapa orang (dan model) "melihat" pola ini:

1. **Drift.** BTC naik secara struktural sepanjang sebagian besar sampel (CAGR buy-and-hold 93%).
   Window mana pun rata-ratanya positif. Yang harus diuji adalah **selisih antar fase**, bukan
   return absolut per fase. Banyak backtest ritel gagal di titik ini.
2. **Siklus 29,53 hari ≈ satu bulan kalender.** Fase bulan bergeser pelan terhadap efek bulanan
   nyata: turn-of-month, expiry opsi CME (Jumat terakhir), rebalancing dana, siklus funding rate.
   Korelasi dengan bulan bisa merupakan bayangan dari salah satu ini. Placebo test di Bagian 4.5
   dirancang khusus untuk memisahkannya.
3. **Multiple testing / data snooping.** Ruang pencariannya besar: 8 fase × beberapa panjang window
   × beberapa titik referensi × beberapa subperiode × return vs volatilitas. Dari ~40 kombinasi,
   satu-dua akan lolos p<0,05 murni kebetulan. Perhatikan pola dalam literatur: hasil signifikan
   Kovacs muncul di ±3 hari tapi hilang di ±7, dan dengan arah berlawanan dari teori saham.
4. **Ekor gemuk + klaster peristiwa.** Lihat Bagian 4.7. Beberapa episode krisis dapat mendominasi
   statistik dispersi seluruh sampel.
5. **Confirmation bias visual.** Menandai purnama di chart 181 siklus: sebagian akan jatuh dekat
   titik balik, sisanya tidak menonjol dan tidak terekam ingatan. Otak manusia sangat baik menemukan
   pola pada deret acak.
6. **Survivorship pada backtest yang dipublikasikan.** Backtest lunar yang hasilnya null tidak
   ditulis di blog. Yang beredar adalah hasil yang kebetulan bagus, sering tanpa pembanding
   buy-and-hold.
7. **Tidak ada mekanisme kausal.** BTC diperdagangkan 24/7 secara global oleh partisipan di semua
   zona waktu dan belahan bumi. Cerita "mood investor lokal" bahkan lebih lemah di sini daripada di
   pasar saham nasional yang punya jam buka tetap.

---

## 6. Confounder yang wajib dikontrol jika pengujian diulang

Jika agent atau siapa pun mengulang analisis ini, kontrol berikut tidak opsional:

- Day-of-week effect (terdokumentasi ada di BTC).
- Turn-of-month effect (terdokumentasi ada di BTC, dengan strategi yang dilaporkan mengungguli
  buy-and-hold secara tahunan pada beberapa studi).
- Expiry opsi/futures CME (Jumat terakhir tiap bulan).
- Rezim volatilitas (vol BTC turun drastis: sd harian ~6% di 2012–2015 menjadi ~2,5% di 2023–2026).
- Halving cycle (~4 tahunan) — jangan sampai window lunar tidak seimbang antar fase halving.
- Autokorelasi akibat window tumpang tindih → wajib HAC/Newey–West atau blok bootstrap.
- Ekor gemuk → wajib ukuran robust selain sd.

---

## 7. INSTRUKSI OPERASIONAL UNTUK AGENT ANALIS

**Aturan default:** fase bulan adalah fitur null untuk BTC. Jangan masukkan ke model produksi
sebagai sinyal entry, exit, position sizing, maupun filter regime.

**Jika user bertanya "apakah full moon minggu ini bearish untuk BTC?"**
Jawab: tidak ada bukti bahwa fase bulan memprediksi arah BTC. Sajikan angka kunci dari Bagian 0.
Jangan mengarang narasi kausal. Jangan menghubungkan pergerakan harga aktual dengan fase bulan
secara post-hoc — itu justru mekanisme nomor 5 di Bagian 5.

**Jika user ingin memasukkan moon phase ke model multivariat.**
Boleh diuji sekali, dengan syarat: (a) sebagai sudut fase kontinu cos/sin, bukan dummy biner;
(b) dengan seluruh kontrol di Bagian 6; (c) dengan placebo test wajib. Jika gagal placebo test —
dan berdasarkan hasil di sini kemungkinan besar gagal — buang fiturnya dan jangan uji ulang dengan
spesifikasi yang berbeda-beda sampai lolos. Menguji ulang sampai lolos **adalah** data snooping.

**Jika user menunjukkan backtest lunar dengan hasil bagus.**
Periksa tiga hal, berurutan: (1) Apakah ada pembanding buy-and-hold pada periode yang sama, dengan
penyesuaian risiko? (2) Apakah biaya transaksi dan slippage dimasukkan? (3) Apakah hasilnya bertahan
di hold-out yang belum pernah disentuh? Contoh kasus di Bagian 3 (Patil 2025) melaporkan CAGR 32,2%
yang terkesan hebat tapi risk-adjusted return-nya 65,6% versus buy-and-hold 68% — yaitu kalah.

**Jangan lakukan:**
- Menyajikan efek fase bulan sebagai "kontroversial" atau "diperdebatkan" seolah bukti kedua sisi
  seimbang. Bukti untuk BTC dominan null.
- Menyebut korelasi tanpa menyebut ukuran efek dan standard error.
- Mengutip angka Yuan et al. (3–5% per tahun) sebagai bukti untuk BTC. Itu ekuitas, bukan kripto,
  dan replikasi terbarunya (Kovacs 2025) tidak menemukan efek global yang robust.

**Boleh dilakukan:**
- Menjelaskan literaturnya secara netral jika user bertanya, dengan konteks kritis di Bagian 2.
- Menggunakan kasus ini sebagai contoh pedagogis tentang data snooping, placebo test, dan bahaya
  statistik berbasis sd pada aset berekor gemuk.
- Menerapkan **metodologi placebo test** ke fitur berbasis waktu lain (sesi, day-of-week, jarak ke
  rilis data ekonomi). Ini murah dan sangat efektif membunuh sinyal palsu.

---

## 8. Batasan — apa yang BELUM diuji di sini

Klaim null di dokumen ini berlaku untuk apa yang diuji. Berikut yang **tidak** tercakup:

- **Granularitas intraday.** Semua uji pada return harian close-to-close UTC. Efek intra-hari tidak
  diuji. (Catatan: ada anomali intraday BTC yang terdokumentasi dan jauh lebih kuat — "turn-of-the-
  candle effect", return positif terkonsentrasi di menit 0/15/30/45 tiap jam, t-stat di atas 9;
  Shanaev, Vasenin & Stepanov, *Heliyon* 2023. Itu sinyal nyata, fase bulan bukan.)
- **Variabel lunar lain:** perigee/apogee (jarak bulan), gerhana bulan/matahari, deklinasi lunar,
  supermoon. Tidak diuji. Prior harus tetap sangat rendah karena tidak ada mekanisme.
- **Interaksi dengan variabel lain.** Belum diuji apakah fase bulan punya efek kondisional pada
  rezim tertentu. Peringatan: mencari interaksi setelah efek utama null adalah bentuk klasik dari
  spesifikasi mencari-cari; jika dilakukan, wajib koreksi multiple testing.
- **Volume dan sentimen.** Studi JAFAS 2025 mencatat asosiasi antara fase bulan dan sentimen/volume
  meski tidak dengan return. Belum direplikasi di sini.
- **Altcoin.** Dokumen ini BTC saja.

---

## 9. Reproduksi

**Skrip:** [`cloud/uji_lunar.py`](../uji_lunar.py). Menjalankan seluruh Bagian 4 dari awal.
**Data:** `cloud/data/btc_daily_bitstamp.csv.gz` (ikut di repo), 5.356 baris harian.
**Dependensi:** `pip install pandas numpy statsmodels ephem` (tidak dipasang di runner bot —
skrip ini alat reproduksi, bukan bagian jalur jawaban)
**Perintah:** `python cloud/uji_lunar.py` · `python cloud/uji_lunar.py --oktan`
**Parameter yang dapat diubah:** `--dev-end` (batas split dev/hold-out), `--draws` (jumlah undian
placebo, default 2000).

---

## 10. Daftar sumber

| Sumber | Jenis | Temuan inti |
|---|---|---|
| Dichev & Janes (2003), *J. Private Equity* | Akademik, ekuitas AS | Efek lunar positif; kemudian dipakai sebagai contoh data snooping |
| Yuan, Zheng & Zhu (2006), *J. Empirical Finance* 13(1) | Akademik, 48 negara | Return lebih rendah di sekitar full moon, 3–5%/tahun |
| Brahmana et al. (2014) | Akademik, ekuitas | Full moon negatif, new moon tidak berpengaruh |
| Borowski (2015), Polandia | Akademik, ekuitas | Kebalikannya: new moon positif, full moon tidak berpengaruh |
| Kovacs (2025), SSRN 5867668 | Akademik, ekuitas + 10 kripto | Tidak ada anomali lunar global yang robust; kripto: dukungan lemah pada return, nihil pada volatilitas |
| JAFAS 11(3) 2025, "Astrofinance..." | Akademik, BTC + ETH | Tidak ada korelasi signifikan fase bulan–return harian |
| "Do Lunar Cycles Affect Bitcoin Prices?" | Akademik, BTC | Uji McNemar: tidak signifikan |
| Patil (2025), IJSET 13(3) | Jurnal minor, BTC | CAGR 32,2% tapi risk-adjusted kalah dari buy-and-hold |
| Shanaev et al. (2023), *Heliyon* | Akademik, BTC intraday | Turn-of-the-candle effect — contoh anomali BTC yang justru kuat |
| **Pengujian di Bagian 4 dokumen ini** | **Primer, BTC 2012–2026** | **Null di semua spesifikasi** |

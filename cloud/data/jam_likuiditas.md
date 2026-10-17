# Liquidity & Adoption Clock — hasil uji (15 Okt 2026)

Rancangan: catatan user "Liquidity & Adoption Clock: Rancangan Kuantitatif" (15 Okt 2026).
Kode: `cloud/jam_likuiditas.py`. Uji: `cloud/uji_jam_likuiditas.py` (aturan lolos ditulis di
docstring SEBELUM dijalankan).

## Kesimpulan

- **Skor Liquidity memprediksi return BTC ~12 minggu, bukan 4 minggu.** IC Spearman +0,33
  (p placebo < 0,001), positif di kedua era, dan tetap lolos tanpa NFCI (+0,28).
- **Momentum jarum jam tidak sesuai rancangan.** "Ketat, mulai membaik", yang di rancangan
  disebut titik balik terbaik, ternyata kuadran terburuk. Yang menentukan adalah POSISI skor.
- **Strategi eksposur** menukar return dengan drawdown: CAGR 40% vs 62% beli-tahan, maxDD
  −48% vs −83%, Sharpe 1,17 vs 1,04.
- **Adoption Clock belum diuji.** ETF spot baru ada sejak Jan 2024, dan API hanya memberi
  sekitar 300 hari bursa. Sesuai rancangan, bobot adopsi ditetapkan di awal dan tidak
  dioptimasi.

## Desain uji

| Aspek | Pilihan |
| --- | --- |
| Data | BTC harian Bitstamp (`btc_daily_bitstamp.csv.gz`); FRED fredgraph.csv sejak 2012 |
| Sinyal | Jumat; tiap titik FRED diberi tanggal tersedia = tanggal ukur + `JEDA_RILIS` |
| Masuk | Penutupan candle Sabtu (t+1), sesudah sinyal |
| Ukuran | Spearman skor vs log-return t+1 → t+1+7h, h = 4, 8, 12 minggu |
| Signifikansi | Placebo geser-melingkar 2.000x (geser ≥ 26 minggu), satu sisi |
| Lolos | IC > 0, p < 0,05/3, dan positif di 2015–2020 serta 2021–2026 |

## Hasil utama

Sinyal Jumat 2015-01-02 s/d 2026-09-01, 609 minggu.

| Horizon | IC | p placebo | 2015–20 | 2021–26 | Vonis |
| --- | --- | --- | --- | --- | --- |
| 4 minggu | +0,050 | 0,264 | +0,081 | −0,029 | tidak lolos |
| 8 minggu | +0,217 | 0,020 | +0,200 | +0,191 | tidak lolos (Bonferroni) |
| 12 minggu | +0,333 | < 0,001 | +0,286 | +0,346 | **LOLOS** |

Pemeriksaan bocor: NFCI direvisi setiap minggu, dan ALFRED tidak terjangkau dari jaringan
pengembang. Tanpa L4, h = 12 tetap IC +0,282, p 0,0005, era +0,21 / +0,31.

IC per komponen (h = 8): L1 bunga +0,11 · L2 likuiditas bersih +0,13 · L3 dolar +0,12 ·
L4 NFCI +0,19. Tidak ada satu komponen yang mendominasi.

## Return BTC 12 minggu per kuadran

| Kuadran (posisi, momentum) | N | Median | Naik |
| --- | --- | --- | --- |
| Longgar, mulai melambat | 102 | +32,2% | 78% |
| Longgar & makin longgar | 199 | +17,2% | 66% |
| Ketat & makin ketat | 204 | −0,2% | 50% |
| Ketat, mulai membaik | 92 | −7,5% | 40% |

## Return BTC 12 minggu per tersil skor

| Tersil | Rentang skor | Median | Naik |
| --- | --- | --- | --- |
| Rendah | −0,81 .. −0,09 | −5,8% | 41% |
| Tengah | −0,09 .. +0,11 | +8,0% | 57% |
| Tinggi | +0,11 .. +0,62 | +25,4% | 77% |

## Ketahanan (IC h = 8)

| Lookback | k = 2 | k = 4 | k = 8 |
| --- | --- | --- | --- |
| 52 | +0,10 | +0,16 | +0,32 |
| 104 | +0,16 | +0,22 | +0,36 |
| 156 | +0,18 | +0,23 | +0,38 |

Semua kombinasi parameter positif, jadi hasilnya tidak bergantung pada satu setelan. k = 8
lebih kuat, tetapi parameter rancangan (k = 4, lookback 104) TIDAK diganti sesudah melihat
hasil.

## Batasan

- Satu rezim selama 11,7 tahun. Jendela 12 minggu yang benar-benar independen hanya sekitar 50.
- NFCI memakai vintage terkini. Uji tanpa NFCI menutup sebagian besar risiko ini, tetapi
  tidak seluruhnya.
- Diuji pada BTC, lalu ETH dan SOL (lihat uji lanjutan). Untuk altcoin lain, angka ini hanya konteks.

## Uji lanjutan — `uji_jam_lanjutan.py` (15 Okt 2026, pra-registrasi)

Kriteria lolos ditulis di docstring sebelum dijalankan.

### 1. Liquidity pada altcoin (hanya 12 minggu, Bonferroni 2 aset)

| Aset | N minggu | IC | p placebo | Paruh 1 / 2 | Vonis |
| --- | --- | --- | --- | --- | --- |
| ETH | 454 | +0,297 | 0,0005 | +0,30 / +0,33 | **LOLOS** |
| SOL | 327 | +0,339 | 0,0005 | +0,40 / +0,29 | **LOLOS** |

### 2. Gelombang (funding + Fear & Greed) — hipotesis IC < 0

Skor tersedia sejak 2021-01, 300 minggu. Hipotesis ditolak di semua horizon:

| Horizon | IC | p ekor bawah | 2021–23 | 2024–26 |
| --- | --- | --- | --- | --- |
| 4 minggu | +0,100 | 0,96 | +0,09 | +0,11 |
| 8 minggu | +0,111 | 0,96 | +0,06 | +0,13 |
| 12 minggu | +0,093 | 0,97 | +0,08 | +0,10 |

- **Per komponen (12 minggu):** funding −0,02 (tidak ada sinyal), Fear & Greed +0,23. Sentimen bekerja sebagai momentum, bukan sebagai tanda puncak.
- **Aturan "skor > 0,5 → potong 25 pp":** sesudah minggu-minggu itu, median return 12 minggu +20,1% (N = 32), sedangkan minggu lainnya −0,1%. Aturan ini merugikan, jadi dimatikan (`PAKAI_ATURAN_GELOMBANG = False`).

### 3. Adopsi struktural (A1 + A2, Farside) — cek arah saja

Sampelnya 114 minggu, kira-kira 9 jendela 12 minggu yang independen. Hasilnya:

- IC 4 minggu +0,22, searah dengan teori.
- IC 12 minggu −0,06, berlawanan dengan teori.

Karena itu tidak ada vonis. A3 (13F) dan A4 (treasury) belum punya riwayat yang cukup.

### 4. Strategi pada periode skor adopsi (113 minggu, deskriptif)

| Varian | Hasil | MaxDD |
| --- | --- | --- |
| Liquidity saja | +20,3% | −28% |
| + Struktural | +24,8% | −23% |
| + Struktural + Gelombang | +22,3% | −23% |
| Beli-tahan | +36,0% | — |

## Data A3 — 13F per kuartal (`etf_13f.py`, run 38747445399)

Angka berikut dihitung dari 13F-HR asli dengan pencocokan daftar putih ETF spot. Tanggal datanya dianggap tersedia 45 hari sesudah akhir kuartal.

| Kuartal | Pemegang | Nilai |
| --- | --- | --- |
| 2024-03 | 987 | $11,2 miliar |
| 2024-06 | 1.130 | $10,9 miliar |
| 2024-09 | 1.169 | $12,5 miliar |
| 2024-12 | 1.685 | $27,4 miliar |
| 2025-03 | 1.733 | $21,2 miliar |
| 2025-06 | 2.001 | $33,1 miliar |
| 2025-09 | 2.174 | $38,3 miliar |
| 2025-12 | 2.204 | $28,1 miliar |
| 2026-03 | 2.037 | $19,6 miliar |
| 2026-06 | 1.929 | $17,3 miliar |

- **Tren pemegang:** jumlah pemegang turun dua kuartal berturut-turut sejak puncaknya di Q4 2025.
- **Skor A3:** skala tetap tanh(pertumbuhan / 10%), dipakai karena 10 titik terlalu sedikit untuk z-score bergulir.
- **A4 (treasury):** arsipnya baru dimulai 15 Okt 2026, jadi skornya baru muncul sekitar 30 minggu lagi.

## Pengganti gratis untuk dua bagian yang tadinya tidak bisa (15 Okt 2026)

| Yang dibutuhkan rancangan | Sumber berbayar / tidak ada | Pengganti gratis |
| --- | --- | --- |
| Basis futures CME tahunan (W1) | Data futures CME | Yahoo `BTC=F` dibandingkan spot BTCUSDT per jam dari arsip Binance, tepat pada jam penutupan CME (15:00 Chicago) |
| Jenis pemegang 13F (A3) | 13F tidak punya kolom jenis | CRD / nomor berkas SEC di sampul 13F, dicocokkan dengan Form ADV Item 5.D (berkas IA bulanan SEC) |
| Pemisahan basis trade | — | CFTC Traders in Financial Futures: short bersih leveraged funds di futures BTC CME (standar + mikro) |

### Penyelarasan jam basis

Derau harian basis diukur sebagai simpangan baku perubahan hari ke hari:

| Pembanding spot | Derau | Median basis |
| --- | --- | --- |
| Harian 00:00 UTC | 78 pp | 1,4% |
| Jam 16:00 Chicago | 54 pp | 4,7% |
| Jam 15:00 Chicago | 34 pp | 5,1% |

Jam 15:00 dipilih. Ini kalibrasi penyelarasan data, bukan kalibrasi sinyal.

### 5. Gelombang dengan basis CME (pra-registrasi, kriteria sama dengan #2)

| Horizon | IC | p ekor bawah | 2021–23 | 2024–26 |
| --- | --- | --- | --- | --- |
| 4 minggu | +0,132 | 0,98 | +0,14 | +0,13 |
| 8 minggu | +0,131 | 0,98 | +0,11 | +0,12 |
| 12 minggu | +0,119 | 0,97 | +0,11 | +0,10 |

- Hipotesis tetap ditolak.
- Skor basis sendiri: IC 12 minggu +0,15 (sejak 2018-12).
- Sesudah minggu dengan skor > 0,5, median return 12 minggu +29,8% (N = 28), sedangkan minggu lainnya −0,2%.

### 6. Jejak basis trade

Sampel 141 minggu sejak 2024. Korelasi peringkat antara arus ETF 4 minggu dan perubahan short bersih leveraged funds CFTC 4 minggu adalah **+0,48**. Sebagian besar arus ETF berjalan bersamaan dengan penambahan short futures. Bagian arus itu adalah basis trade yang netral arah, bukan permintaan.

### Jenis pemegang 13F (`etf_13f.py`, run 38757921517)

Klasifikasi memakai tiga jalur, berurutan:

1. Daftar nama eksplisit untuk pemegang besar tanpa Form ADV.
2. CRD atau nomor berkas SEC di sampul 13F, dicocokkan dengan Form ADV Item 5.D (jenis klien dengan aset kelolaan terbesar). Berkas exempt-reporting adviser dimasukkan sebagai dana privat.
3. Nama resmi yang dinormalkan.

Halaman SEC tidak memuat berkas penasihat untuk Jun 2023 – Nov 2025. Kuartal-kuartal itu memakai berkas terdekat, dan nama berkasnya dicatat per kuartal.

Porsi nilai per jenis pemegang:

| Kuartal | Penasihat kekayaan | Hedge fund / dana privat | Pembuat pasar | Bank | Manajer reksa dana | Institusi | Tak terklasifikasi |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2024-03 | 15% | 45% | 21% | 4% | 11% | 2% | 3% |
| 2024-12 | 13% | 49% | 14% | 8% | 7% | 3% | 5% |
| 2025-06 | 16% | 40% | 14% | 10% | 8% | 3% | 9% |
| 2025-12 | 21% | 28% | 13% | 12% | 9% | 4% | 12% |
| 2026-06 | 23% | 15% | 14% | 19% | 12% | 6% | 10% |

- **Hedge fund keluar:** porsi hedge fund turun dari 49% (Q4 2024) menjadi 15% (Q2 2026). Sebaliknya, penasihat kekayaan dan bank naik.
- **Hitungan inti A3:** hanya penasihat kekayaan, bank, institusi, manajer reksa dana, dan lainnya. Hedge fund, pembuat pasar (netral arah), dan yang tak terklasifikasi dikeluarkan.
- **Cek silang dengan CFTC (Q2 2026):** hedge fund memegang ETF setara ±43.700 BTC. Short bersih leveraged funds di CME ±35.900 BTC, atau 82% dari jumlah itu. Kepemilikan ETF oleh hedge fund sebagian besar adalah basis trade.

## Pemicu dan peluang aktif (matriks 16 Okt 2026)

Blok JAM LIKUIDITAS dimuat lewat tiga jalan:

1. Perintah analisa koin.
2. Pesan ngobrol yang menyebut koin kripto.
3. Pesan ngobrol tanpa koin yang cocok dengan `_MINTA_JAM` (`cloud/bot_oneshot.py`), kecuali pertanyaan definisi seperti "apa itu …" atau "jelaskan …".

Peluangnya diukur lewat `bot.process` sungguhan. Set held-out ditulis sebelum diukur dan tidak dipakai untuk menambal putaran yang sama.

| Set | Dipakai untuk | Aktif (seharusnya aktif) | Salah aktif (seharusnya tidak) |
| --- | --- | --- | --- |
| Tuning (70 frasa) | menambal putaran 1 | 49/62 = 79% → 62/62 | 0/8 |
| Held-out 1 (35 frasa) | estimasi, lalu tambal putaran 2 | **18/26 = 69%** | 0/9 |
| Held-out 2 (32 frasa) | estimasi, lalu tambal putaran 3 | **16/24 = 67%** | 1/8* |
| Held-out 3 (32 frasa) | estimasi akhir | **21/24 = 88%** | 0/8 |

\* "apa itu bitcoin halving" aktif lewat jalur koin. Setiap pesan yang menyebut koin selalu menarik data lengkap, termasuk blok ini. Ini perilaku lama, bukan dari pola JAM.

**Perkiraan untuk kalimat baru:** sekitar 85–90% pertanyaan makro/likuiditas tanpa nama koin akan memicu blok ini. Angka ini dari held-out 3, yang diukur sebelum tiga frasa sisanya ikut ditambal. Kata umum dan pertanyaan definisi tidak memicunya (0 salah aktif dari 25).

### Peluang per kelompok kata (sesudah semua putaran)

| Kelompok | Contoh pemicu | Aktif |
| --- | --- | --- |
| Likuiditas | likuiditas, liquidity, net liquidity, uang beredar, M2, money printer | 100% |
| Fed & neraca | fed, the fed, powell, QT, QE, neraca, TGA, RRP, reverse repo, bank sentral | 100% |
| Bunga & FOMC | suku bunga, bunga acuan, rate cut/hike, FOMC, dovish, hawkish, moneter, pelonggaran, pengetatan | 100% |
| Dolar & obligasi | dolar, dollar, USD, DXY, yield, imbal hasil, obligasi, bond | 100% |
| Kondisi keuangan & rezim | kondisi keuangan/finansial, financial conditions, NFCI, spread kredit, rezim, risk on/off, makro, macro, fiskal, stimulus | 100% |
| Resesi & tenaga kerja | resesi, recession, sahm, pengangguran, tenaga kerja, NFP | 100% |
| Adopsi & ETF | etf, arus/aliran etf, inflow, outflow, net flow, 13F, institusi, akumulasi, treasury perusahaan, basis trade | 100% |
| Leverage & sentimen | funding (rate), leverage, overheat, euforia, fear & greed, greed | 100% |
| Nama program & eksposur | jam likuiditas, liquidity/adoption clock, eksposur, porsi/alokasi/persen … kripto | 100% |
| Menyebut koin kripto | btc gimana, eth layak hold?, analisa sol | 100% |

Angka 100% berlaku untuk frasa yang sudah diuji. Untuk frasa baru, pakai perkiraan 85–90% di atas.

### Dua salah-rute yang ketemu lewat matriks ini

Keduanya sudah diperbaiki:

- "jam" terbaca sebagai token JAM, misalnya pada "jam berapa rilis cpi".
- "etf" terbaca sebagai token ETF, misalnya pada "arus masuk etf ethereum" (seharusnya ETH) dan "masih beli etf?".

Semua 164 frasa dikunci di `tests/_frasa_jam.py` dan diuji oleh `test_matriks_pemicu_jam_tanpa_aset`.

## Model kuant penggabung sinyal (`model_kuant.py`, `uji_model_kuant.py`, 16 Okt 2026)

Model ini memindahkan kesimpulan arah dari penimbangan naratif ke hitungan kode. Rancangan dan kriteria lolosnya ditulis di docstring `uji_model_kuant.py` sebelum uji dijalankan.

### Rancangan

- **Fitur:** 12 fitur mingguan point-in-time, masing-masing dinormalkan dengan z-score bergulir 104 minggu.
- **Bobot:** IC Spearman tiap fitur di data latih.
- **Peluang:** skor gabungan diubah menjadi peluang lewat regresi logistik.
- **Pengujian:** walk-forward per tahun 2019–2026. Model dilatih ulang tiap tahun hanya dengan target yang sudah terwujud, dengan jeda selebar horizon.

### Hasil out-of-sample

| Horizon | Versi | IC | p | Brier skill | Tahun positif |
| --- | --- | --- | --- | --- | --- |
| 12 minggu | Gabungan 12 sinyal | +0,110 | 0,26 | −0,014 | 3/8 |
| 12 minggu | **Liquidity saja** | **+0,312** | **0,006** | **+0,111** | **5/8** |
| 4 minggu | Gabungan 12 sinyal | +0,087 | 0,19 | −0,012 | 2/8 |
| 4 minggu | Liquidity saja | +0,015 | 0,38 | −0,003 | 3/8 |

**Vonis:**

- **12 minggu:** model yang dipakai adalah Liquidity saja.
- **4 minggu:** tidak ada model yang lolos, jadi horizon ini tidak diberi peluang.

**Gabungan gagal karena overfitting.** Di data latih, bobot momentum dan teknikal tinggi: mom_26 +0,32, tren MA200 +0,31, jarak puncak +0,30. Bobot itu ditarik oleh beberapa bull run besar dan berbalik di tahun uji (2019 −0,61, 2026 −0,57).

**Keandalan Liquidity saja.** Ramalan peluang naik dibandingkan dengan frekuensi naik yang benar-benar terjadi:

| Ramalan peluang naik | Terjadi naik | N minggu |
| --- | --- | --- |
| < 45% | 33% | 48 |
| 45–55% | 49% | 82 |
| 55–65% | 54% | 89 |
| ≥ 65% | 70% | 175 |

**Pembacaan per 16 Okt 2026:** peluang BTC naik 12 minggu **38%**, dengan laju dasar 58%.

**Belum dicoba, dan harus didaftarkan ulang sebelum diuji:**

- Gabungan yang lebih sempit, misalnya Liquidity + satu faktor momentum.
- Model untuk ETH dan SOL.
- Pengujian dengan biaya transaksi.

## Langkah 2: kalibrasi skor bot dan uji maju (16 Okt 2026)

### Skor 0–100 panggilan bot (`kalibrasi_skor.py`)

| | |
| --- | --- |
| Panggilan tercatat | 19 |
| Episode independen | 15 |
| Episode yang sudah dinilai | 10 |
| Korelasi skor dengan hasil | +0,04 (p permutasi 0,46) |
| Benar, skor 41–60 | 75% (selang 95%: 41–93%, 8 episode) |
| Rentang skor teramati | 43–65 |
| Status | **BELUM TERKALIBRASI**. Laju ±6,8 episode/bulan, jadi butuh ±7 bulan lagi untuk mencapai 60 |

Panggilan aset yang sama dalam 72 jam digabung menjadi satu episode. Pada 9 Agu, NVDA dianalisa tiga kali di harga yang sama. Pada 30 Sep, SOL dianalisa dua kali dalam 13 menit.

Selama belum terkalibrasi, brief memuat larangan menyajikan skor sebagai peluang. Ambang di `analisa.md` tetap keputusan manusia.

### Uji maju model kuant (`model_kuant.py --maju`)

Prediksi pertama dicatat Jumat 16 Okt 2026: peluang BTC naik 12 minggu 38%, laju dasar 58%. Prediksi ini akan dinilai sesudah 9 Jan 2027.

Penilaiannya memakai skor Brier, dibandingkan dengan laju dasar. Karena prediksi 12 minggu saling tumpang tindih, jumlah prediksi yang benar-benar independen hanya sekitar 4 per tahun. Butuh beberapa tahun sebelum uji maju ini bisa memberi vonis yang kuat.

**Aturan vonis — didaftarkan 17 Okt 2026, sebelum satu pun prediksi jatuh tempo.** Berlaku per aset, horizon 12 minggu, Brier model dibanding laju dasar yang dicatat bersama prediksinya:

| Prediksi jatuh tempo | Syarat | Vonis |
|---|---|---|
| < 26 | — | BELUM (angka tetap tampil, berlabel sampel kecil) |
| ≥ 26 | Brier skill < −0,05 | GAGAL (stop dini) |
| ≥ 52 | Brier skill ≤ 0 | GAGAL |
| ≥ 52 | Brier skill > 0 | BERTAHAN = belum terbantah, bukan terbukti (52 prediksi ≈ 13 pengamatan independen) |

GAGAL berlaku otomatis: `peluang_aset` berhenti menampilkan angkanya di bot dan Telegram, dan Telegram menyebut alasannya. Vonis paling cepat Jul 2027 (stop dini) atau Jan 2028 (52 prediksi). ETH ikut dicatat sejak 17 Okt 2026, termasuk minggu yang berlabel "tidak terkalibrasi", karena yang dinilai adalah modelnya.

## Langkah 3: biaya transaksi dan walk-forward (16 Okt 2026)

### Strategi eksposur Jam Likuiditas (`uji_jam_likuiditas.py`)

Biaya 0,15% per sisi dikenakan pada setiap perubahan eksposur. Beli-tahan membayar satu kali biaya masuk.

| 2015–2026, setelah biaya | CAGR | MaxDD | Sharpe |
| --- | --- | --- | --- |
| Strategi Liquidity | 39,8% (tanpa biaya 40,1%) | −48% | 1,17 |
| **Pembanding adil: eksposur tetap 50%** | 34,9% | −54% | 1,04 |
| Beli-tahan | 61,8% | −83% | 1,04 |

- **Biaya kecil:** total 2,8% modal dalam 11,7 tahun, karena eksposur hanya berubah 133 kali.
- **Timing menambah nilai:** strategi unggul atas eksposur tetap dengan rata-rata yang sama di ketiga ukuran. Keunggulannya bukan sekadar karena setengah investasi.
- **Pola per tahun:** strategi tertinggal dari beli-tahan di setiap tahun bull, dan unggul di 2018, 2022, 2025, dan 2026. Ini filter risiko, bukan pengungguli return.

### Uji balik sinyal teknikal (`backtest.py`)

Pengaturan uji:

- Riwayat panjang dari Yahoo, setelah biaya pulang-pergi, horizon 20 hari.
- Pembanding: return masuk kapan saja.
- Sinyal hanya divonis BERTAHAN bila keunggulannya melampaui biaya di kedua paruh waktu.

| Sinyal | BTC (2014–) | ETH (2017–) | SOL (2020–) |
| --- | --- | --- | --- |
| Golden cross 13×21 | tidak bertahan (+0,54) | **bertahan** (+6,0) | tidak bertahan (−4,9) |
| Death cross (hindari) | **bertahan** (+2,8) | tidak bertahan (+2,8) | **bertahan** (+11,9) |
| RSI < 30 | tidak bertahan (+1,7) | tidak bertahan (−9,6) | sampel kecil |
| RSI > 70 (hindari) | **terbalik** (−6,2) | tidak bertahan (−1,3) | **terbalik** (−20,9) |
| Pullback EMA21 | tidak bertahan (+0,1) | **bertahan** (+5,8) | tidak bertahan (+2,3) |

Angka dalam kurung adalah keunggulan dibanding masuk acak, dalam poin persen per 20 hari.

- **Hanya RSI > 70 yang konsisten, dan arahnya terbalik.** Sesudah RSI > 70, return justru lebih tinggi dari rata-rata (momentum). Panduan prompt yang mengajarkan "overbought = hati-hati" untuk kripto sudah diganti.
- **Vonis BERTAHAN lainnya tidak konsisten antar aset.** Dengan 5 sinyal diuji sekaligus, kemungkinan besar itu kebetulan.

## Langkah 4: ukuran posisi berbasis volatilitas (`uji_ukuran_posisi.py`, 16 Okt 2026)

Rancangan dan kriteria lolosnya ditulis di docstring sebelum uji dijalankan:

- **Target volatilitas:** median volatilitas 30 hari dari seluruh riwayat sebelum minggu itu.
- **Pengali:** target ÷ volatilitas sekarang, dibatasi 0–2.
- **Kondisi uji:** semua varian dinilai setelah biaya, pada minggu yang sama.

| Varian | Penuh: CAGR / maxDD / Sharpe | 2015–20: Sharpe | 2021–26: Sharpe / maxDD |
| --- | --- | --- | --- |
| A. Liquidity saja | 39,8% / −48% / **1,167** | 1,565 | **0,611** / −40% |
| B. Volatilitas saja | 33,8% / −55% / 0,970 | 1,445 | 0,450 / −55% |
| C. Liquidity × volatilitas | 38,4% / −47% / 1,091 | 1,573 | 0,522 / −46% |
| Eksposur tetap 50% | 35,0% / −54% / 1,040 | 1,394 | 0,559 / −46% |
| Beli-tahan | 61,8% / −83% / 1,040 | 1,394 | 0,559 / −75% |

**Vonis: TIDAK LOLOS.** C kalah dari A di periode penuh dan di paruh 2021–2026, baik Sharpe maupun drawdown. Pengali volatilitas tidak dipakai, dan target eksposur tetap memakai Liquidity saja.

Penjelasan yang paling mungkin:

- **Waktu pemangkasan buruk.** Volatilitas BTC memuncak saat crash, sehingga pengali memangkas eksposur tepat sebelum pemulihan.
- **Biaya transaksi naik.** Perubahan eksposur bertambah dari 133 menjadi 187 kali, dan biaya naik dari 2,8% menjadi 5,4%.

Volatilitas saja bahkan kalah dari eksposur tetap 50%.

## Model kuant ETH & SOL (`uji_model_kuant_altcoin.py`, 16 Okt 2026)

Rancangan dan kriteria lolosnya ditulis di docstring sebelum uji dijalankan:

- **Versi yang diuji:** hanya Liquidity saja. Versi gabungan sudah gagal di BTC, jadi tidak diuji ulang.
- **Walk-forward:** model dilatih ulang tiap tahun, mulai tahun pertama yang punya ≥100 minggu data latih.
- **Kriteria lolos:** IC > 0 dengan p < 0,025, Brier skill > 0, dan IC positif di ≥60% tahun uji.

| Aset | Tahun uji | IC OOS | p | Brier skill | Tahun positif | Vonis |
| --- | --- | --- | --- | --- | --- | --- |
| ETH | 2020–2026 | +0,298 | 0,016 | +0,070 | 5/7 | **LOLOS** |
| SOL | 2023–2026 | +0,238 | 0,0005 | +0,039 | 2/4 | **TIDAK LOLOS** |

### Keandalan ETH

| Ramalan peluang naik | Terjadi naik | N minggu |
| --- | --- | --- |
| < 45% | **63%** | 126 |
| 45–55% | 48% | 102 |
| 55–65% | 53% | 81 |
| ≥ 65% | 82% | 33 |

- **Masalah yang tidak tertangkap kriteria.** Ramalan rendah untuk ETH justru terbalik. ETH tetap diadopsi karena lolos semua kriteria pra-registrasi.
- **Penjaga penyajian (dibuat sesudah melihat hasil, dicatat terbuka).** Bila keranjang ramalan saat ini terbalik di data uji dengan ≥30 minggu, angkanya tampil berlabel "TIDAK TERKALIBRASI di rentang ini" dan tidak dipakai sebagai arah. Penjaga ini tidak mengubah vonis.
- **Pembacaan 16 Okt 2026:**
  - ETH 37% dengan laju dasar 52%. Angka ini jatuh di keranjang terbalik, jadi bukan arah.
  - BTC 38% dengan laju dasar 58%. Keranjang <45% BTC searah (nyatanya naik 33%), jadi angka ini tetap arah.
- **SOL** tidak ditampilkan. Riwayatnya baru 4 tahun uji, dan IC-nya positif hanya di 2 tahun.

## Gabungan sempit: Liquidity + satu faktor (`uji_model_kuant_sempit.py`, 16 Okt 2026)

Rancangan pra-registrasi:

- **Kandidat:** dipilih dari literatur, bukan dari bobot langkah 1. Momentum deret waktu 12 bulan (Moskowitz-Ooi-Pedersen 2012), jarak ke rata-rata 200 hari, dan Fear & Greed.
- **Koreksi uji berganda:** 3 kandidat × 2 horizon, jadi ambang p diturunkan menjadi 0,0083.
- **Syarat lolos 12 minggu:** gabungan harus mengalahkan Liquidity saja dalam Brier skill, dan IC tahunannya lebih tinggi di ≥6 dari 8 tahun.

| 12 minggu, OOS 2019–2026 | IC | p | Brier skill | Tahun positif | Tahun unggul atas Liquidity |
| --- | --- | --- | --- | --- | --- |
| **Liquidity saja** | **+0,312** | 0,005 | **+0,111** | 5/8 | — |
| + momentum 12 bulan | +0,271 | 0,139 | +0,082 | 4/8 | 3/8 |
| + Fear & Greed | +0,295 | 0,020 | +0,064 | 4/8 | 1/8 |
| + tren MA200 | +0,200 | 0,056 | +0,039 | 3/8 | 1/8 |

Pada horizon 4 minggu, keempat versi punya Brier skill negatif (−0,003 sampai −0,012), jadi tidak ada yang lolos.

**Vonis:** model tetap memakai Liquidity saja. Di data latih, bobot faktor tambahan tampak besar (0,22–0,31), tetapi di tahun yang belum dilihat setiap tambahan memperburuk peluang yang terkalibrasi. Gabungan sempit ini mengulang pelajaran dari gabungan 12 sinyal.

## Skor Liquidity pada aset lain (`uji_likuiditas_aset_lain.py`, 16 Okt 2026)

Rancangan pra-registrasi:

- **Model:** Liquidity saja, dengan kriteria yang sama seperti ETH/SOL. Koreksi uji berganda untuk 3 aset, jadi ambang p diturunkan menjadi 0,0167.
- **Masuk posisi:** penutupan hari bursa pertama sesudah Jumat sinyal.

| Aset | IC OOS 2017–26 | p | Brier skill | Tahun positif | Vonis |
| --- | --- | --- | --- | --- | --- |
| S&P 500 | +0,151 | 0,100 | +0,002 | 5/10 | TIDAK LOLOS |
| Nasdaq-100 | +0,227 | 0,017 | −0,009 | 5/10 | TIDAK LOLOS |
| Emas | +0,127 | 0,135 | +0,029 | 4/10 | TIDAK LOLOS |

- **Arah sesuai hipotesis, tetapi tidak konsisten.** IC positif di ketiga aset, tetapi hanya di separuh tahun uji.
- **Saham tidak terkalibrasi.** Laju dasar naik 12 minggu sekitar 74%, sehingga hampir semua ramalan ≥65% dan skor tidak memisahkan hasil.
- **BTC jauh lebih peka terhadap likuiditas.** Sebagai pembanding, BTC punya IC +0,31, Brier skill +0,11, dan positif di 5 dari 8 tahun.
- **Koreksi rancangan.** Perkiraan "skor sejak ~2008" keliru. Reverse repo (RRPONTSYD) nyaris kosong sebelum 2013, sehingga skor baru tersedia sejak Okt 2014. Kriteria uji tidak diubah.
- **Varian yang belum diuji.** Kemungkinan lanjutan adalah varian yang mengisi RRP = 0 sebelum 2013 agar sampel mulai 2008. Varian ini harus didaftarkan sebagai uji baru, karena keputusan membuatnya diambil sesudah melihat hasil.

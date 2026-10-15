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

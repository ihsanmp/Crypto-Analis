# Gaya Trading "#Kalimasada" — kerangka TA crypto milik mentor user

Diekstrak dari 12 chart TradingView yang dikirim user (2 Sep 2026): ZEC, NEAR, HEMI, TUT,
ZRO, CFX, MEME — semuanya perpetual/USDT, timeframe intraday (rentang 4–10 hari per layar,
konsisten dengan candle 1h–4h).

**Status: kerangka MEMBACA chart, bukan edge yang terbukti.** Lihat bagian pengukuran.

---

## Kerangka setup-nya

**Indikator inti**
- `EMA 13/21 Color Switch` — dua EMA yang berganti warna saat status tren berbalik.
  Biru = fase turun/datar, putih = fase naik. Muncul di ZEC, NEAR, CFX, MEME.
- `Order Block Detector [LuxAlgo]` — zona supply/demand bertumpuk (ZRO).
- Stochastic di panel bawah (CFX).

**Bentuk setup yang berulang di ketujuh chart**

1. **Konsolidasi dulu.** Harga merapat di kotak/range, EMA 13 dan 21 mendatar dan saling
   rapat. Ditandai kotak horizontal (HEMI 0,00700 · NEAR 1,75–1,79 · TUT 0,030–0,035).
2. **Pemicu.** Salah satu dari: EMA berganti warna ke naik, tembus atas range, atau tembus
   garis tren turun (ZRO dan CFX dua-duanya menembus trendline turun berbulan-bulan).
3. **Masuk** di sekitar pemicunya, ditandai `PEMBELIAN` / `PENJUALAN` dan garis harga oranye.
4. **Target** = zona resistensi/order block berikutnya, digambar sebagai panah lengkung.
   Kadang diberi label eksplisit ("Xxx" pada TUT di 0,08787).
5. **Garis tren naik** dipakai sebagai penyangga di bawah harga (HEMI, "Acending").

Arahnya dua sisi — ada `Short` (MEME, 13 Agu) — jadi ini bukan kerangka long-only.

---

## SUDAH DIUKUR — dan hasilnya belum bisa menyimpulkan apa pun

Dua kaki metodenya diuji lewat `cloud/backtest.py` pada ketujuh koin di chart itu.

### Temuan 1: timeframe menentukan segalanya

Candle **harian** crypto dari CoinGecko **tidak punya high/low sungguhan** —
`open=high=low=close` di 366 dari 366 candle, mutu `approx_close_only`. Candle **4 jam**
justru `native` dengan high/low asli 180 dari 180.

Akibatnya sinyal "pullback ke EMA21" — yang menuntut low menyentuh EMA lalu close di
atasnya — **mustahil menyala di harian**, dan selama ini dilaporkan "0 kejadian" seolah
memang tidak pernah terjadi. Nol yang berarti *tidak terukur* jauh lebih menyesatkan
daripada nol yang berarti *tidak ada*.

| | golden cross 13×21 | pullback ke EMA21 |
|---|---|---|
| **Harian** (1 tahun, tanpa high/low) | 28 kejadian, menang 46,4% | **mustahil diukur** |
| **4 jam** (30 hari, high/low asli) | 10 kejadian, menang 90,0% | 70 kejadian, menang 50,0% |

### Temuan 2: angka 4 jam itu TIDAK boleh dibaca sebagai edge

**Ketujuh koin NAIK di jendela 30 hari itu** — ZEC +78%, HEMI +170%, ZRO +44%, TUT +45%,
CFX +15%, NEAR +9%, MEME +5%. Di jendela yang semuanya naik, sinyal long apa pun akan
menang. "Menang 90%" di situ mengukur pasarnya, bukan sinyalnya.

Dan begitu dibandingkan ke **lantai acak** (persentase candle naik di jendela yang sama),
kaki pullback justru **kalah di 4 dari 7 koin**:

| koin | pullback menang | lantai acak | vonis |
|---|---|---|---|
| NEAR | 33,3% | 40,2% | di bawah lantai |
| ZRO | 16,7% | 47,5% | di bawah lantai |
| CFX | 42,9% | 50,8% | di bawah lantai |
| MEME | 36,4% | 48,0% | di bawah lantai |
| ZEC | 76,5% | 51,4% | di atas |
| TUT | 75,0% | 47,5% | di atas |
| HEMI | 55,6% | 54,2% | seri |

Golden cross hanya 10 kejadian di tujuh koin — di bawah ambang 10 yang ditetapkan
`backtest.py` sendiri sebagai batas kebermaknaan, dan itu pun tersebar 1–2 per koin.

### Temuan 3: diuji di pasar TURUN — dan kaki pullback kalah dari masuk acak

Jendela 30 hari tidak bisa menjawab "bagaimana kalau pasar turun". Yang bisa: **BTC harian
Bitstamp, 5.358 candle, 2012–2026, OHLC sungguhan** (5.305 punya high/low asli) — memuat
tiga pasar beruang. Reproduksi: `python cloud/uji_gaya.py --era`.

Tiap sinyal dibandingkan ke **lantai acak di rezim yang sama**: peluang menang kalau masuk
di hari ACAK dalam rezim itu. Rezim = harga vs SMA200. Horizon 20 candle.

| sinyal | rezim | n | menang | lantai acak | selisih | 1 SE |
|---|---|---|---|---|---|---|
| golden cross 13×21 | NAIK | 32 | 59,4% | 58,4% | +1,0 | 8,7 |
| golden cross 13×21 | TURUN | 22 | 59,1% | 52,1% | +7,0 | 10,5 |
| **pullback ke EMA21** | **NAIK** | **344** | **51,7%** | **58,4%** | **−6,6** | **2,7** |
| pullback ke EMA21 | TURUN | 87 | 56,3% | 52,1% | +4,2 | 5,3 |

**Golden cross: tidak ada edge, dua-duanya di dalam derau.** Selisih +7,0 pada n=22 terlihat
besar sampai galat bakunya dilihat — 10,5. Dan tandanya berbalik antar era: 2012–2016 bull
−11,5 · 2021–2026 bull +14,8. Rapuh, bukan temuan.

**Pullback ke EMA21 di pasar NAIK: −6,6 poin, di luar 2 galat baku, dan tandanya BERTAHAN
di ketiga era** (−7,4 · −4,1 · −12,7). Ini satu-satunya hasil di seluruh pengujian yang
lolos ambangnya — dan arahnya negatif: **masuk di pullback saat tren naik lebih buruk
daripada masuk di hari acak.** Masuk akal secara mekanis: pullback terjadi tepat saat
momentum melemah, jadi harga yang "diskon" itu dibayar dengan peluang lanjut yang lebih
kecil.

Di pasar TURUN sebaliknya, +4,2 — tapi di dalam derau dan tandanya berbalik antar era
(−11,8 · +21,0 · −1,8). Tidak ada apa-apa di sana.

**Batas temuan ini, dan penting:** yang diukur adalah PELUANG MENANG pada horizon tetap
**tanpa stop maupun target**. Metode mentornya punya target eksplisit (zona order block
berikutnya) dan hampir pasti punya stop. Sinyal dengan peluang menang rendah masih bisa
berharapan positif kalau imbalan:risikonya cukup besar — itu belum diuji di sini, dan
menguji­nya butuh aturan keluar yang eksplisit. Dan ini **BTC saja**, bukan altcoin yang
justru diperdagangkan mentornya.

### Vonis

**Golden cross: tidak ada edge arah yang bisa dipisahkan dari derau.** Baik di pasar naik
maupun turun, baik di 4 jam maupun harian.

**Pullback ke EMA21 sebagai ENTRY BERDIRI SENDIRI di tren naik: lebih buruk daripada masuk
acak**, bertahan di ketiga era pada 14 tahun data BTC. Sebagai bagian dari setup lengkap
dengan target dan stop, belum diuji.

Sebelum ini yang bisa dikatakan hanya: Yang bisa dikatakan jujur: 30 hari riwayat di
pasar yang seluruhnya naik tidak cukup untuk menetapkan maupun menolak edge. Yang berubah
adalah pullback kini BISA diukur; sebelumnya tidak.

**Cara memakainya di jawaban:** perlakukan sebagai **kerangka membaca chart** — konsolidasi,
pemicu, target di zona berikutnya — bukan sebagai sinyal dengan tingkat kemenangan. Kalau
user bertanya "sesuai gaya mentor saya, gimana?", boleh membaca strukturnya dengan kerangka
ini; JANGAN menempelkan angka kemenangan padanya, dan JANGAN menyebutnya teruji.

---

## Setup "DEVIATION" — dari 10 chart 13 Sep 2026 (TAO, NEAR, CHIP, DXY)

Ini yang mengisi celah terbesar catatan di atas: **setup dengan stop dan target eksplisit**,
jadi yang diukur bukan lagi sekadar peluang menang melainkan **ekspektansi dalam R**.

**Bentuknya:** range di atas satu zona support yang disentuh berkali-kali → harga menembus
ke BAWAH zona itu (menyapu stop & likuiditas) → harga close lagi di ATAS zona = masuk →
stop di bawah low deviasi → target di swing high range. Konfirmasi yang terlihat di
chartnya: EMA 13/21 direbut kembali, Stoch RSI berbalik dari oversold (TAO), OI + volume
naik (panel CoinGlass TAO).

Dikodekan di `cloud/deviasi.py` — **fungsi yang sama** dipakai analisa langsung dan
backtest, supaya yang dipakai bot persis yang teruji.

### Divalidasi dulu ke chart mentornya sendiri

| chart mentor | deteksi kode | hasil |
|---|---|---|
| NEAR daily, deviasi ~3 minggu Agustus | terpicu 20 Agu, zona 1,723, low 1,538, target 2,389 | kena target **+2,63R** |
| TAO H4, mangkuk 2-3 Sep, low ~214,5 | terpicu 3 Sep 04:00, zona 218,7, low 214,9, target 261,3 | kena target **+4,99R** |

Versi pertama aturannya hanya mengenali sapuan dalam 5 candle dan **gagal** di sini: ia
menangkap lantai kecil 1,571 di DALAM mangkuk NEAR, bukan zona range Juni-Juli. Diperbaiki
**sebelum** satu pun angka backtest dilihat.

### Hasil uji: 20 koin, OHLC asli Binance, biaya 0,1% pulang-pergi

Reproduksi: `python cloud/uji_deviasi.py`

| timeframe | n | menang | ekspektansi | galat baku | pembanding* | vonis |
|---|---|---|---|---|---|---|
| **daily** (2020-2026) | 516 | 33,3% | **+0,150R** | 0,083 | +0,014R | lemah positif, belum meyakinkan |
| **H4** (2022-2026) | 2.884 | 30,7% | **-0,006R** | 0,031 | -0,118R | impas setelah biaya |
| **H1** (2024-2026) | 5.968 | 29,2% | **-0,112R** | 0,021 | -0,131R | **rugi** |

\* pembanding = entri TANPA pemicu deviasi memakai geometri yang SAMA (range sama, stop di
bawah low 5 candle, target di swing high, R:R >= 1). Tanpa pembanding ini, ekspektansi
positif bisa saja datang dari bentuk R:R-nya saja, bukan dari deviasinya.

**Daily: +0,150R, tapi selisihnya terhadap pembanding cuma ~1,5 galat baku** — belum lolos
ambang. Dan tidak stabil antar tahun: 2021 +0,88 · **2022 -0,31** · 2023 +0,49 · 2024 +0,16
· **2025 -0,07** · 2026 +0,13. Per koin 14 dari 20 positif.

**H4: pemicunya JELAS menambah sesuatu** (-0,006R vs pembanding -0,118R, selisih ~3,5 galat
baku) — tapi hasil akhirnya tetap impas. Polanya membawa informasi; informasi itu habis
dimakan biaya.

**H1: rugi, dan bukan karena biaya.** Tanpa biaya sekalipun -0,062R. 19 dari 20 koin
negatif, tiap tahun negatif. Range 40 candle di H1 cuma 40 jam — jauh lebih pendek daripada
range ~5 hari yang digambar mentor di chart H1-nya. **Jumlah candle yang sama tidak berarti
struktur yang sama antar timeframe.**

### Menang 1 dari 3 — dan itu memang bentuk normalnya

Tingkat menang 30-33% di ketiga timeframe. Yang membuat daily positif adalah rata-rata
pemenangnya besar (target sering 2-5R). Artinya **dua dari tiga setup kena stop**. Chart
yang dibagikan mentor semuanya contoh yang berhasil — yang gagal tidak diposting — jadi
deretan chart itu tidak bisa dipakai menilai seberapa sering setup ini jalan.

### Konfirmasi: yang menambah dan yang tidak

| konfirmasi | daily dengan / tanpa | H4 dengan / tanpa |
|---|---|---|
| volume di atas median | +0,221 / -0,010 | +0,049 / -0,111 |
| Stoch RSI dari oversold | +0,250 / -0,082 | -0,009 / +0,002 |
| harga merebut EMA 13/21 | +0,145 / +0,150 | -0,022 / -0,004 |

**Merebut EMA menaikkan tingkat menang tapi TIDAK menaikkan ekspektansi** (daily 42,7% vs
31,4% menang, ekspektansi sama) — masuk lebih lambat, jadi pemenangnya lebih kecil. Volume
di atas median satu-satunya yang searah di daily dan H4. Semua ini **eksploratif**: banyak
pembandingan diuji sekaligus, jadi perlakukan sebagai petunjuk, bukan aturan.

**OI (panel CoinGlass di chart TAO) TIDAK diuji** — arsip candle tidak memuatnya.

### Batas yang wajib disebut saat mengutip

- Koinnya dipilih hari ini dari yang masih likuid — koin yang mati dan delisting tidak ikut,
  dan itu memihak setup long.
- Semua koin bergerak bersama pasar: transaksi di tanggal berdekatan tidak independen, jadi
  galat baku di atas **terlalu optimistis**.
- Spot Binance, bukan perpetual: **funding tidak dihitung**.
- Stop dan target di candle yang sama dihitung **kena stop** — dari OHLC tidak bisa
  diketahui mana yang duluan.

### Cara memakainya di jawaban

Sebut setup deviation hanya kalau `deviasi.py` melaporkan `setup_aktif` — **jangan
menggambar setupnya sendiri dari chart**, karena pola "turun lalu naik" adalah yang paling
mudah ditemukan dengan mata di chart mana pun. Kutip ekspektansinya apa adanya, termasuk
bahwa H1 rugi dan daily belum meyakinkan.

---

## Yang perlu diuji kalau mau dilanjutkan

- Riwayat 4h lebih panjang dari 30 hari (butuh sumber lain; CoinGecko hanya menyimpan ~30).
- Pembanding beli-dan-tahan pada tiap sinyal, bukan hanya persentase menang.
- ~~Jendela yang memuat pasar TURUN~~ — **sudah, lihat Temuan 3.**
- ~~Ekspektansi dengan stop & target eksplisit~~ — **sudah, lihat bagian Setup DEVIATION.**
- Altcoin dengan OHLC asli riwayat panjang — pengujian pasar turun di atas BTC saja.
- Biaya: perpetual punya funding, dan setup intraday berpindah posisi jauh lebih sering.

⚠️ Materi acuan, bukan nasihat keuangan.

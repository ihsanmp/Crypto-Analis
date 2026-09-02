# Bot Riset Pasar (Telegram + Claude Code, jalan di Cloud)

Sistem riset **crypto · forex & emas · saham AS**, plus pemantauan perkembangan AI.
Jalan **24 jam di GitHub Actions — tanpa perlu laptop menyala**, dipicu langsung oleh pesan
Telegram lewat Cloudflare Worker.

Khusus spot: tidak memberi saran short/leverage/futures; data derivatif dipakai hanya
sebagai sentimen timing.

## Cara pakai di Telegram

| Ketik | Yang terjadi |
|---|---|
| `analisa sol` · `analisa gold` · `analisa nvda` | Analisa lengkap terstruktur: skor 0–100, fundamental + teknikal, proyeksi berhorizon, rencana akumulasi |
| `solana berpotensi naik sampai $200?` | Target yang kamu ajukan **diuji**, bukan diiyakan — berapa ATR jauhnya, berapa persen jendela historis pernah mencapainya |
| `carikan koin dengan narasi privacy yang menarik` | Screening satu narasi: cari koin di dalamnya, cek katalisnya, nilai kesehatan narasinya |
| `carikan koin narasi yang menarik` | Bot memetakan sendiri sektor yang sedang bergerak, lalu pilih koin terbaik |
| ngobrol bebas | "menurutmu btc gimana?" — jawaban santai, tetap berbasis data yang ditarik saat itu |
| **kirim FOTO/screenshot** + caption | Mode analis visual: baca chart/pengumuman, cari kaitannya, gali data, beri penilaian |
| `carikan informasi menarik dari telegram saya` | Membaca grup Telegram-mu sendiri, **memeriksa** temuannya ke data, lalu melapor. Hanya yang **baru sejak terakhir kali diminta** |
| `apa yang menarik di tele seminggu terakhir` | Sama, tapi rentangnya kamu yang tentukan — mengalahkan penanda batas |
| `/help` | Bantuan |

> Riset grup hanya berjalan kalau pesanmu memuat kata **"telegram"** atau **"tele"**.
> Gerbangnya sengaja sempit: membaca grup pribadi karena salah tangkap jauh lebih buruk
> daripada sesekali harus menyebut kata pemicunya. Kalimat yang MENGOPERASIKAN Telegram
> ("kirim update ke telegram", "check telegram bot status", "update webhook") dikecualikan
> — itu soal pipa botnya sendiri, bukan permintaan membaca grup.

**Campur bahasa didukung di seluruh jalur.** Pemicunya mengerti dua sisi sekaligus, karena
begitulah kalimatnya benar-benar ditulis: *"bagaimana pergerakan btc untuk full moon
nanti"*, *"anything interesting on my telegram"*, *"apa yang menarik di telegram past
month"*, *"where will btc be in 3 months"*. Rentang waktu terbaca di kedua bahasa
(`seminggu` = `last week`, `sebulan ini` = `this month`, `kemarin` = `yesterday`).

---

## Konsep yang membentuk sistem ini

Tiga prinsip yang menjelaskan hampir semua keputusan desain di repo ini.

### 1. Data dikumpulkan KODE, bukan kepatuhan model

Tahap pengumpulan data **tidak diminta** ke model. `bot_oneshot.py` menjalankan sendiri
script yang relevan lalu menyusun DATA BRIEF, dan model hanya menafsirkannya.

Alasannya konkret: dulu tahap gather pernah mengembalikan brief 759 karakter untuk
`analisa gold` padahal keempat scriptnya sehat dan menghasilkan ~20 rb karakter — modelnya
saja yang tidak menjalankan langkahnya. Selama pengumpulan data bergantung pada kepatuhan,
kegagalan diam-diam seperti itu akan terulang.

Konsekuensinya: pada mode ngobrol yang briefnya sudah ada, model dijalankan **tanpa akses
shell** sama sekali. Kalau sebuah angka perlu ada, kodelah yang harus menyediakannya.

### 2. Proyeksi boleh, ramalan tidak

Menyebut angka target itu boleh — asal disertai **metode, horizon, rentang, pembatal, dan
basis kejadian**. Yang dilarang adalah angka telanjang.

```
❌ "Solana berpotensi naik sampai $200."
✅ "Horizon 60 hari: rentang wajar $75–$93 (p10–p90 dari 306 jendela, Ags 2025–Ags 2026).
    $200 berjarak +164% atau 120 ATR — 0 dari 306 jendela pernah mencapainya; gerakan
    60-hari terbesar dalam rentang itu +41,5%. Batal kalau close harian di bawah $62."
```

Keduanya menyebut $200. Hanya yang kedua bisa dinilai benar atau salah.

### 3. Temuan wajib lolos uji ketahanan

Angka gabungan belasan tahun bisa sepenuhnya disetir satu rezim lalu tampil seolah berlaku
umum. Setiap studi reaksi rilis karena itu dipotong tiga cara — kronologis, tingkat inflasi,
dan besar kejutan — dan **tandanya harus bertahan**.

Ini bukan hiasan. Contoh nyata yang ditemukan lewat uji itu: reaksi emas terhadap kejutan
CPI di H+5 terlihat −0,30% saat digabung, tapi begitu dipotong ternyata **berbalik tanda**
(2013–2017 +0,25 · 2017–2022 +0,19 · 2022–2026 −2,06). Temuan itu artefak periode, bukan
sifat emas — dan seed melarangnya dipakai untuk memperkirakan arah.

Lebih jauh lagi: arah efek CPI **berbeda tergantung ekspektasi siapa** yang dipakai sebagai
pembanding (nowcast model −0,17% vs konsensus pasar +0,20%, dua-duanya "konsisten" di
ketujuh potongan). Kesimpulan yang berlaku sekarang: **CPI tidak punya edge arah untuk
emas, titik.**

### 4. Ketidakpastian disebut, bukan dihaluskan

Kalau sebuah jawaban bertumpu pada sesuatu yang tidak kokoh — datanya cuma sebagian,
sumbernya satu, datanya lebih lama dari peristiwanya, angkanya dekat tapi tidak persis,
kesimpulannya bergantung pada yang belum terjadi — itu ditulis **di baris pernyataannya**,
bukan sebagai penutup "DYOR" yang dilewati mata.

Aturannya berakhir dengan satu kalimat: *kalau ragu antara menyebut ragu atau tidak,
sebutkan.* Jawaban yang menyebut keraguannya bisa dipakai untuk memutuskan seberapa besar
risiko yang diambil; jawaban yang terdengar sama pastinya di semua bagian tidak bisa — dan
biayanya ditanggung pembacanya.

Pagarnya dua arah. Menempelkan "mungkin" pada angka yang jelas terbaca dari data membuat
seluruh peringatan sungguhan ikut jadi derau yang dilewati.

---

## Arsitektur

```
Telegram ("analisa gold")
   │
   ▼
Cloudflare Worker  ── memverifikasi secret + chat ID (fail-closed)
   │  repository_dispatch (pesan ikut di payload — tanpa polling sama sekali)
   ▼
GitHub Actions  →  cloud/bot_oneshot.py
   │
   ├─ TAHAP 1  pengumpulan data OLEH KODE (paralel, 2 pekerja)
   │    crypto : indicators · backtest · proyeksi · etf(BTC/ETH)
   │             onchain · fundamentals · investors · sentiment · memori
   │    forex  : market · backtest · proyeksi · kejutan(CPI/FOMC/NFP) · jadwal
   │             makro · memori
   │    saham  : market · backtest · proyeksi · kejutan(CPI) · stockfund
   │             konteks · earnings · memori
   │         └─ model murah (haiku) hanya untuk bagian yang butuh PENILAIAN:
   │            mencari berita & katalis terbaru
   │
   ├─ TAHAP 2  sintesis oleh model pintar (opus) — TANPA tool
   │    seed peran (inti · analis · risk · portofolio · trader · prediktor)
   │    + DATA BRIEF + metodologi skor
   │
   └─ AUDIT sebelum kirim: keterlacakan angka, kesegaran data, asal data,
      imbalan:risiko, kelengkapan bukti — lalu KAKI SUMBER disusun kode
        └─ peringatan disisipkan ke balasan bila ada yang mencurigakan
   │
   ▼
Balasan ke Telegram
```

### Cabang riset grup Telegram

Jalur terpisah, dipicu hanya oleh kata "telegram"/"tele", dan **dipecah tiga proses**
karena session Telegram memberi akses PENUH ke akun — tidak ada versi read-only.

```
   ┌─ PENGINTIP   bot_oneshot.py --minta-telegram
   │    tanpa kredensial APA PUN. Menentukan perlu-tidaknya, kategori grup,
   │    dan rentang jam yang disebut user ("sebulan ini" -> 720)
   │
   ├─ PEMBACA     tgbaca.py --sejak-terakhir --rentang N
   │    SATU-SATUNYA pemegang TELEGRAM_SESSION. Tidak menjalankan model,
   │    tidak memanggil MCP, tidak menyentuh jaringan selain Telegram.
   │    Hanya grup & kanal — DM tidak pernah dibaca.
   │      penyaringan di sisi KODE: pesan pendek · tautan telanjang · daftar
   │      harga bot ticker · ekor promo kanal · duplikat lintas grup
   │
   └─ PENGANALISA bot_oneshot.py   (TANPA TELEGRAM_SESSION di environment-nya)
        pemulung (haiku) -> kurator (haiku) -> pemeriksa (sonnet)
        + [DATA UNTUK MEMERIKSA KLAIM] yang diambil KODE lebih dulu
```

Injeksi prompt dari isi grup berakhir di proses yang **tidak punya kredensial apa pun**
untuk dijangkau. Dan pemeriksa sengaja **tidak diberi shell**: model yang sedang membaca
teks dari orang tak dikenal tidak boleh berada di lingkungan yang bisa menjalankan
perintah — jadi kode yang mengambil datanya, model yang membandingkan.

**Tidak ada duplikasi.** Tiap grup punya penanda batas berupa ID pesan terakhir yang
pernah diambil (`cloud/data/tg_batas.json`). Permintaan pertama membuka 2 bulan penuh;
sesudahnya hanya yang lebih baru. Rentang yang **disebut user** mengalahkan penanda —
tapi rentang yang lebih pendek daripada yang tertunda tidak memajukannya, supaya "24 jam
terakhir" tidak menghanguskan dua bulan yang belum sempat dibaca.

Penandanya baru **berlaku** setelah user benar-benar menerima jawabannya: pembaca menulis
calon, workflow mempromosikannya hanya kalau step analisa sukses. Bukan kehati-hatian
teoretis — run pertama mengumpulkan 35 rb karakter lalu mati karena kuota model habis.

**Empat jenis temuan, empat perlakuan.** `[KLAIM]` dicocokkan ke data · `[ANALISA]`
dasarnya diperiksa dan kesimpulannya dinisbahkan ke penulisnya · `[PELUANG]` dilaporkan
berikut apa yang TIDAK disebutkan pengumumannya · `[OBROLAN]` apa adanya dengan
hitungannya, dan dilarang dinaikkan jadi sinyal beli/jual. Tiap temuan wajib membawa
**nama grup dan tanggalnya**.

---

**Penjenjangan model.** `MODEL_GATHER=claude-haiku-4-5` (mekanis) · `MODEL_SYNTH=claude-opus-5`
(analisa) · `MODEL_NARASI=claude-sonnet-5` (screening) · `MODEL_RINGAN=claude-sonnet-5`
(sapaan & pertanyaan konseptual). Mode ngobrol memilih tingkatnya sendiri dari isi pesan,
jadi "halo" tidak membayar harga yang sama dengan "bandingkan btc dan eth secara detail".

Ukuran muatan sintesis saat ini: **crypto ~76 rb · forex ~109 rb · saham ~90 rb karakter**.

---

## Seed peran

Sembilan berkas di `cloud/prompts/peran/`, dirakit sesuai sektor dan sesuai pertanyaan —
analisa crypto tidak ikut membawa aturan risiko forex, dan tiga seed terakhir hanya dimuat
untuk riset grup Telegram.

| Seed | Isi |
|---|---|
| `inti.md` | Aturan kalibrasi keras: data tidak ada → tulis tidak ada · konviksi maks 60 bila <3 kategori searah · bukti kontra tidak boleh kosong · label FAKTA/INFERENSI/SPEKULASI · **hipotesis user DIUJI, bukan divalidasi** |
| `analis.md` | Struktur tesis 6 komponen, top-down, pembaruan Bayesian |
| `risk.md` | Matematika drawdown, risk of ruin, VaR vs CVaR |
| `portofolio.md` | Expectancy, sizing, korelasi palsu |
| `trader.md` | Edge, R-multiple, biaya eksekusi |
| `prediktor.md` | **FORECASTER** — lima syarat proyeksi, protokol per pasar, dan catatan temuan yang sudah teruji (mana yang bertahan, mana yang gugur) |
| `pemulung.md` | **Riset grup, tahap 1** (haiku) — memungut tanpa menilai. Empat jenis temuan, asal & tanggal wajib, upaya manipulasi ditandai bukan dijalankan |
| `kurator.md` | **Riset grup, tahap 2** (haiku) — memilih maks 14 yang layak dibayar untuk diperiksa, dengan **jatah per jenis** supaya isinya tidak selalu klaim berangka |
| `pemeriksa.md` | **Riset grup, tahap 3** (sonnet) — memvonis tiap temuan terhadap data. Tidak punya shell, dan itu disengaja |

---

## File

### Otak & alur

| File | Fungsi |
|---|---|
| [cloud/bot_oneshot.py](cloud/bot_oneshot.py) | Bot "sekali jalan": ambil pesan, routing, kumpulkan data lewat kode, sintesis, audit, balas, keluar |
| [cloud/bot_daemon.py](cloud/bot_daemon.py) | Alternatif polling untuk server always-on (balasan hitungan detik) |
| [cloud/memori.py](cloud/memori.py) | **Ingatan terverifikasi** — fakta yang sudah dicek disimpan dengan jenis (`volatil`/`semi`/`stabil`) yang menentukan kapan wajib dicek ulang; saat dipanggil divonis SEGAR / MULAI TUA / KEDALUWARSA. Data pribadi (alamat dompet, saldo) **ditolak di level kode** karena repo publik |
| `cloud/data/tg_batas.json` | **Penanda batas baca grup Telegram** — ID pesan terakhir per grup, supaya permintaan berikutnya tidak mengulang isi yang sama. Nama grup TIDAK ditulis: kuncinya HMAC dengan `TELEGRAM_API_HASH`, karena repo ini publik dan nama grup adalah tebakan pendek yang bisa dibalik dari hash telanjang |
| `cloud/data/percakapan.json` | Ingatan percakapan pendek — 3 pasang tanya-jawab terakhir per chat (kedaluwarsa 6 jam). Chat ID di-hash bersama garam dari token bot |
| [cloud/rapor.py](cloud/rapor.py) | **Rapor rekomendasi** — mencatat panggilan bot lalu menilainya terhadap harga yang benar-benar terjadi. Dinilai terhadap **alpha** — return dikurangi return pasar (BTC untuk crypto, SPY untuk saham) pada jendela yang sama; tanpa itu, di pasar naik hampir semua panggilan AKUMULASI otomatis tercatat benar tanpa keahlian apa pun. Melaporkan keberhasilan per bias, per jenis aset, dan **per rentang skor**: kalau panggilan berskor 75 tidak lebih sering benar daripada yang 45, sistem skornya belum bermakna |

### Harga, indikator, proyeksi

| File | Fungsi |
|---|---|
| [cloud/indicators.py](cloud/indicators.py) | Penarik OHLC + kalkulator indikator deterministik (EMA/RSI/Stoch/BB/ATR/SuperTrend/Pivot/Fibonacci untuk 1w/1d/4h). Sumber Binance→Kraken→Coinbase→OKX→CoinGecko; weekly dibangun eksak dari candle harian. Kualitas `approx_close_only` ditandai saat high/low bukan angka asli |
| [cloud/market.py](cloud/market.py) | OHLC + indikator **saham & forex** (Yahoo, tanpa key), memakai ulang mesin `indicators.py` apa adanya |
| [cloud/proyeksi.py](cloud/proyeksi.py) | **Proyeksi target dari data**: sebaran gerakan N hari (p10–p90 untuk puncak tercapai, dasar tercapai, harga penutup), ATR, level struktural, ekstensi Fibonacci — sudah dalam satuan harga. `--target` **menguji harga yang diajukan user**: jarak dalam ATR, peluang historis, jendela yang diuji, gerakan terekstrem yang pernah terjadi |
| [cloud/banding.py](cloud/banding.py) | **Perbandingan 2–4 aset** dalam metrik yang dijamin setara — tiap aset dilewatkan jalur yang sama persis, sehingga tabelnya apples-to-apples. Menandai sendiri saat panjang riwayat antar-aset timpang atau kualitas sumbernya campur. Jauh lebih kecil daripada menempelkan dua brief penuh (~2 rb vs ~50 rb karakter) |
| [cloud/backtest.py](cloud/backtest.py) | Uji balik sinyal terhadap riwayat aset itu sendiri (golden/death cross, RSI ekstrem, pullback EMA21) + tolok ukur beli-dan-tahan. Kejadian <10 ditandai sampel kecil **`--tf 4h` penting untuk crypto:** candle harian CoinGecko tidak punya high/low sama sekali (open=high=low=close di 366/366), jadi sinyal yang menuntut sentuhan level tidak pernah bisa menyala di sana; candle 4 jam `native` dengan high/low asli |

### Rilis ekonomi & reaksi harga

| File | Fungsi |
|---|---|
| [cloud/kejutan.py](cloud/kejutan.py) | **Studi peristiwa** — reaksi harga dipisah menurut arah KEJUTAN, lengkap dengan **uji ketahanan per rezim**. Tiga sumber: konsensus pasar SoSoValue (CPI/Core CPI/PPI/NFP, sejak 2010) · nowcast Cleveland Fed (cadangan otomatis) · seri SF Fed Bauer-Swanson untuk FOMC (kejutan dalam basis poin, **berakhir 2023-12**). Menandai sendiri saat irisan data terlalu pendek atau berkasnya basi |
| [cloud/jadwal.py](cloud/jadwal.py) | **Jadwal rilis RESMI tanpa API key**: kalender ICS BLS (NFP/CPI/PPI), tanggal keputusan FOMC beserta penanda rapat berproyeksi, dan angka aktual NFP/PPI dari BLS |
| [cloud/kalender.py](cloud/kalender.py) | Konsensus & jadwal Forex Factory. **Tidak lagi ikut di brief** (konsensusnya kini dari SoSoValue) — dijalankan mingguan lewat `rapor.yml` untuk menumbuhkan arsip |
| [cloud/arsip.py](cloud/arsip.py) | **Arsip konsensus independen** — merekam konsensus & aktual Forex Factory setiap kali kalender ditarik, karena feed itu membuang pekan yang sudah lewat. Gunanya mengaudit angka SoSoValue yang tidak punya jejak vintage. Aktual yang sudah terisi TIDAK PERNAH tertimpa kosong |
| [cloud/makro.py](cloud/makro.py) | Data makro AS dari FRED (resmi, tanpa key): CPI, Core PCE, NFP, pengangguran, Fed Funds, yield 2y/10y, DXY, kurva 10y-2y — beserta arah dampaknya ke emas dan **persentil** terhadap sejarahnya |
| [cloud/data/gaya_kalimasada.md](cloud/data/gaya_kalimasada.md) | **Kerangka TA crypto milik mentor user**, diekstrak dari 12 chart TradingView: konsolidasi -> pemicu (EMA 13/21 ganti warna, tembus range, atau tembus trendline turun) -> target di order block berikutnya. Diuji: kaki pullback **mustahil diukur di candle harian** karena crypto CoinGecko tidak punya high/low, dan angka 4 jam-nya berasal dari 30 hari di mana KETUJUH koin naik — jadi belum terbukti dan belum terbantah. Dipakai sebagai kerangka membaca chart, BUKAN sinyal bertingkat kemenangan |
| [cloud/data/moon_phase_btc.md](cloud/data/moon_phase_btc.md) | **Acuan fase bulan × BTC** — tinjauan literatur + uji primer 5.356 hari, direproduksi di repo ini (Bagian 4.9). Kesimpulan: **fitur null**, jangan dipakai sebagai sinyal entry/exit/sizing/filter regime. Isinya masuk prompt lewat blok `fase-bulan`, tidak dibaca utuh saat menjawab |
| `cloud/data/btc_daily_bitstamp.csv.gz` | Data harian BTC/USD Bitstamp 2012–2026 (5.356 baris) yang dipakai `uji_lunar.py`. Satu bursa konsisten sepanjang periode, supaya tidak ada artefak penyambungan antar-bursa |
| [cloud/data/gold_drivers.md](cloud/data/gold_drivers.md) | Acuan analisa emas: data penggerak, arah dampak saat actual > forecast, dan dua pengecualian arah yang sering tertukar |

### Crypto

| File | Fungsi |
|---|---|
| [cloud/etf.py](cloud/etf.py) | **Arus dana ETF spot AS** (BTC & ETH saja) — kategori sinyal INSTITUSIONAL yang tidak tertangkap chart, on-chain, maupun sentimen. Yang paling bernilai bukan angka arusnya melainkan **divergensi harga vs arus**: harga naik + arus keluar = distribusi; harga turun + arus masuk = akumulasi. Besaran dinilai lewat persentil, bukan angka dolar telanjang |
| [cloud/onchain.py](cloud/onchain.py) | Valuasi on-chain (CoinMetrics Community, tanpa key): MVRV + zona siklus, alamat aktif, tren 30 hari. Metrik yang tak ada di tier gratis dilaporkan kosong, tidak dikarang |
| [cloud/fundamentals.py](cloud/fundamentals.py) | "Laporan keuangan" protokol dari DefiLlama: revenue & fees per bulan/kuartal, pertumbuhan MoM/QoQ/YoY, TVL, rasio MC/TVL & P/S & P/F. DefiLlama sering mengembalikan mcap kosong (melekat pada token induk), jadi mcap diambil dari CoinGecko lewat `kategori.py` dan dioper sebagai `--mcap` — tanpa itu keempat rasio valuasi keluar `n/a` |
| [cloud/investors.py](cloud/investors.py) | Kepemilikan on-chain multi-chain: 10 holder teratas + kategori otomatis + konsentrasi riil. Ethereum via Ethplorer (tanpa key); chain lain via Moralis |
| [cloud/wallet.py](cloud/wallet.py) | Pelacak wallet address: isi dompet, nilai USD, % portofolio, identitas alamat bila dikenal |
| [cloud/whaleflow.py](cloud/whaleflow.py) | Whale Sentiment Index + top-10 token dengan arah akumulasi/distribusi whale 24 jam (ETH saja) |
| [cloud/statistik.py](cloud/statistik.py) | **Statistik jejak rekam** (dari `crates/analysis` nautilus_trader): ekspektansi, faktor untung, rasio imbalan, penurunan maksimum, dan rasio imbalan:risiko per panggilan. Memisahkan *seberapa sering benar* dari *seberapa menguntungkan* — dua hal yang bisa berlawanan arah |
| [cloud/sebab.py](cloud/sebab.py) | **Dekomposisi sebab** untuk pertanyaan "kenapa naik/turun": memisahkan gerakan jadi tiga lapis — milik seluruh pasar, milik selera risiko luas (QQQ · emas · Indeks Dolar · imbal hasil 10 tahun), dan sisanya yang khas aset itu. Berita yang terbit di pekan yang sama bukan bukti sebab; kalau seluruh pasar naik serupa, berita itu penumpang. Plus **korelasi imbal hasil** 30/90 hari terhadap keempatnya, selalu disertai jumlah hari yang benar-benar berpasangan. Gratis tanpa key |
| [cloud/tgbaca.py](cloud/tgbaca.py) | **Pembaca grup Telegram** (Telethon). Sengaja TANPA model, tool, maupun MCP — itu syarat pemisahannya: session memberi akses penuh ke akun, jadi ia hanya boleh berada di proses yang tidak menjalankan LLM. Hanya grup & kanal, **DM tidak pernah dibaca**. Grup forum ditangani per topik dengan jatah sendiri, supaya topik ramai tidak menutupi topik pengumuman. Nomor telepon, undangan, email, dan alamat dompet diredaksi sebelum keluar. **Penanda batas per grup** (`--sejak-terakhir`) supaya tiap permintaan hanya membawa yang baru, dan `--rentang` untuk rentang yang disebut user. Saringan sisi kode juga membuang daftar harga bot ticker dan ekor promo yang diulang kanal di tiap unggahan |
| [cloud/tgsesi.py](cloud/tgsesi.py) | **Pembuat session string** — dijalankan di komputermu sendiri, sekali. Tidak menulis berkas `.session` ke disk (itu cara termudah kredensial ikut ter-commit) |
| [cloud/uji_sebaran.py](cloud/uji_sebaran.py) | **Menguji metode sebaran `proyeksi.py`** — puncak & dasar yang tercapai, bukan harga penutup. Hasil 25 Agu 2026: sebaran empiris **kalah di keenam pengukuran** dari jalan acak asas pantulan. Tapi TIDAK diganti: cakupan gauss di sisi bawah justru lebih buruk (65–67% vs 72–74%), dan sisi itulah yang menetapkan invalidasi. Yang dipakai: **kalibrasi terukur** ikut dilaporkan — interval p10–p90 hanya memuat hasilnya ~72–80% kali, bukan 80% |
| [cloud/uji_gaya.py](cloud/uji_gaya.py) | **Menguji sinyal gaya mentor user** (EMA 13/21 cross & pullback ke EMA21) pada BTC harian Bitstamp 2012-2026 — OHLC SUNGGUHAN, memuat tiga pasar beruang. Tiap sinyal dibanding **lantai acak di rezim yang sama** (harga vs SMA200), lengkap galat baku dan uji ketahanan per era. **Hasil: golden cross tidak punya edge di kedua rezim; pullback ke EMA21 saat tren naik justru −6,6 poin DI BAWAH masuk acak, bertahan di ketiga era** |
| [cloud/uji_lunar.py](cloud/uji_lunar.py) | **Menguji fase bulan terhadap return BTC** — event-window ±3d/±7d dengan HAC, uji harmonik sudut fase kontinu, dan 2.000 siklus PALSU berperiode 29,53 hari sebagai placebo. **Hasil: null di semua spesifikasi**, dan bulan asli menjelaskan return BTC *lebih buruk* daripada median siklus palsu (p empiris 0,908). Alat reproduksi, bukan bagian jalur jawaban — kesimpulannya sudah tetap dan tertulis di acuan |
| [cloud/uji_timesfm.py](cloud/uji_timesfm.py) | **Harness uji TimesFM** (Google Research) terhadap base rate dan jalan acak, walk-forward tanpa look-ahead. **Hasil 25 Agu 2026: KALAH di ketiga aset** — model 200 juta parameter 6–11% lebih buruk pada pinball daripada interval ±1,28σ√h, dan cakupannya 73–77% (target 80%) yang berarti terlalu percaya diri. **Tidak dipasang ke produksi.** Disimpan sebagai catatan supaya tidak dicari ulang |
| [cloud/cmc.py](cloud/cmc.py) | **Pemeriksa akses CoinMarketCap.** Temuannya menutup satu jalur: API CMC **tidak punya satu pun** endpoint funding, open interest, likuidasi, atau perpetual — nol dari 51. Angka itu di CMC AI berasal dari data internal, bukan API yang dijual. Yang justru berguna: `--dominasi` memberi **riwayat** dominasi BTC, satu-satunya cara menyusun "dominasi naik dari 58,4% ke 59,5%" — CoinGecko hanya memberi angka saat ini. `--periksa` menembak tiap endpoint kandidat karena paket gratis memblokir sebagian dan mana yang diblokir tidak bisa ditebak dari dokumentasi. Hasil 24 Agu 2026: **8 terbuka, 3 tertutup** |
| [cloud/coinalyze.py](cloud/coinalyze.py) | **Likuidasi, riwayat OI, rasio long/short & funding** (Coinalyze, API gratis, perlu `COINALYZE_API_KEY`). Menutup celah terakhir: likuidasi tidak ada di sumber keyless mana pun. Riwayat harian utuh **400 hari** — diuji, bukan diasumsikan — sehingga arah OI langsung tersedia tanpa menunggu arsip tumbuh. `--periksa` memeriksa akses tiap endpoint lebih dulu, karena "gratis" di dokumentasi belum tentu "terbuka untuk kunci ini" |
| [cloud/derivatif.py](cloud/derivatif.py) | **Funding rate & open interest lintas bursa** (CoinGecko `/derivatives` + Hyperliquid, gratis tanpa key). Bursa langsung tidak bisa dipakai: Binance/Bybit/OKX memblokir datacenter AS, tempat runner Actions berada. Funding ditimbang volume dari 150 kontrak BTC di 100 bursa — hasilnya +0,0079% saat CMC AI melaporkan +0,0080%. Menumbuhkan arsip OI harian sendiri, karena CoinGecko hanya memberi snapshot. **Likuidasi tidak tersedia** di sumber keyless mana pun dan dinyatakan begitu, bukan dikarang |
| [cloud/pasarglobal.py](cloud/pasarglobal.py) | **Denyut pasar keseluruhan** (CoinGecko `/global`, gratis tanpa key): dominasi BTC & ETH, mcap total, dan gerakan BTC 24j/7h/30h. `--koin` menghitung **isolasi** — selisih koin terhadap BTC dalam poin persen. Tanpa ini "naik 18% sepekan" terdengar seperti prestasi koinnya, padahal kalau BTC naik 24% di pekan yang sama koin itu tertinggal dan kesimpulannya berbalik |
| [cloud/kategori.py](cloud/kategori.py) | **Peta sektor/narasi** (CoinGecko, gratis tanpa key) — pengganti `cryptoCategories` CoinMarketCap yang membalas 403 di paket gratis, sehingga peta narasi dulu terpaksa disusun manual dari top-150 dan sektor kecil tak pernah terlihat. 749 kategori disaring mcap >$100 juta, plus isi tiap kategori dengan perubahan 7 & 30 hari dan jarak dari ATH. Balasan mentah 358 rb karakter dipangkas jadi ~1,6 rb. `--koin <id>` mengambil **data pasar satu koin**: mcap, FDV, volume, pasokan beredar/total/maksimum, plus rasio FDV/MC, volume/mcap, dan % beredar — inilah sumber mcap yang dioper ke `fundamentals.py` |
| [cloud/sentiment.py](cloud/sentiment.py) | Fear & Greed + sentimen komunitas, ukuran audiens, aktivitas developer |
| [cloud/ainews.py](cloud/ainews.py) | Perkembangan AI dari RSS resmi (OpenAI, DeepMind, HF, TechCrunch AI, dll) — katalis sektor AI sering lahir di dunia AI, bukan crypto |

### Saham

| File | Fungsi |
|---|---|
| [cloud/stockfund.py](cloud/stockfund.py) | Fundamental dari SEC EDGAR (resmi, tanpa key): revenue, laba, EPS, aset, ekuitas, arus kas — kuartalan & tahunan + pertumbuhan, plus P/E & P/S. Pertumbuhan TIDAK dihitung saat deret periodenya berlubang |
| [cloud/konteks.py](cloud/konteks.py) | Konteks pasar & sektor: indeks + VIX, peringkat 11 ETF sektor berdasar kinerja RELATIF terhadap S&P, pemetaan emiten ke sektor lewat kode SIC. Kode di luar peta dilaporkan tidak terpetakan |
| [cloud/earnings.py](cloud/earnings.py) | Jadwal & kejutan earnings + emiten sebanding (Finnhub, key opsional). Tanpa kunci, bagian ini dilaporkan tidak tersedia dan analisa saham tetap jalan |
| [cloud/sec_tickers.py](cloud/sec_tickers.py) | Cache peta ticker → CIK dari SEC (7 hari, ikut di-commit). Dulu diunduh ulang tiap analisa — terukur 42,9 detik di runner |

### Sumber berbayar-opsional

| File | Fungsi |
|---|---|
| [cloud/sosovalue.py](cloud/sosovalue.py) | **Adapter tunggal SoSoValue** — semua akses lewat sini supaya kalau tier gratisnya dicabut, yang dibuang cukup satu berkas. Menarik riwayat konsensus (disimpan jadi berkas, sehingga `kejutan.py` tidak butuh kunci saat analisa) dan arus ETF. Kunci tidak pernah masuk keluaran mana pun — repo ini publik dan log Actions ikut terbaca publik |
| [cloud/.mcp.cloud.json](cloud/.mcp.cloud.json) | Konfigurasi MCP: CoinMarketCap, CoinGlass, TradingView-data, Blockscout |

### Prompt & tes

| File | Fungsi |
|---|---|
| [cloud/prompts/analisa.md](cloud/prompts/analisa.md) | Metodologi skor 0–100, aturan veto, setting indikator |
| [cloud/prompts/analisa_pasar.md](cloud/prompts/analisa_pasar.md) | Metodologi untuk forex/emas/saham |
| [cloud/prompts/analisa_sumber.md](cloud/prompts/analisa_sumber.md) | Instruksi sumber data — sengaja dipisah supaya tidak ikut terkirim ke tahap sintesis yang tidak punya tool |
| [cloud/prompts/chat.md](cloud/prompts/chat.md) | Mode ngobrol, berblok: aturan domain dimuat hanya bila pemicunya cocok |
| [cloud/prompts/narasi.md](cloud/prompts/narasi.md) · [foto.md](cloud/prompts/foto.md) | Mode screening narasi & mode analis visual |
| [tests/test_routing.py](tests/test_routing.py) | **446 tes** (pytest, tabel, hermetis — jaringan diblokir): routing, bobot, perakitan prompt, audit angka, penyaring privasi, uji rezim, label divergensi, dan **penjaga struktural** seperti "aturan keras tidak boleh berada di field yang dibuang `--ringkas`". Job CI-nya SENGAJA merah kalau ada yang gagal |

---

## Workflow

| Workflow | Pemicu | Tugas |
|---|---|---|
| [bot.yml](.github/workflows/bot.yml) | `repository_dispatch` (webhook) + manual | Menjalankan bot. **Tidak ada cron** — lihat catatan hosting di bawah. Riset grup Telegram dipecah tiga step (pengintip → pembaca → penganalisa) supaya session tidak pernah berada di proses yang menjalankan model; penanda batas baca dipromosikan di step tersendiri, hanya kalau analisanya sukses |
| [tes.yml](.github/workflows/tes.yml) | push & PR | Seluruh suite tes + penjaga "berkas hanya-tambah tidak boleh menyusut" |
| [rapor.yml](.github/workflows/rapor.yml) | Senin 09:00 WIB + manual | Menilai panggilan lama, menyusun rapor, dan mengarsipkan konsensus mingguan |
| [uji-timesfm.yml](.github/workflows/uji-timesfm.yml) | manual saja | Menjalankan evaluasi walk-forward TimesFM. Terpisah dari produksi: torch ~200 MB + bobot ~800 MB diunduh tiap run |
| [periksa-coinalyze.yml](.github/workflows/periksa-coinalyze.yml) | manual saja | Memeriksa akses tiap endpoint Coinalyze. Hasil 24 Agu 2026: **7 terbuka, 0 tertutup** |
| [periksa-cmc.yml](.github/workflows/periksa-cmc.yml) | manual saja | Menembak tiap endpoint CoinMarketCap dan melaporkan mana yang terbuka untuk kunci kita. Sekali jawab, bukan berkala — kuncinya hanya ada di Secrets, jadi harus dijalankan di sana |
| [periksa-sosovalue.yml](.github/workflows/periksa-sosovalue.yml) | Minggu 12:00 WIB + manual | Menyegarkan riwayat konsensus & data ETF, lalu commit balik |
| [mcp-security-scan.yml](.github/workflows/mcp-security-scan.yml) | terjadwal + manual | Audit keamanan konfigurasi MCP |

> **Catatan hosting.** Awalnya memakai cron GitHub Actions, tapi GitHub **tidak menjamin
> jadwal**: `*/5` kenyataannya berjalan ~1 jam sekali, kadang 3 jam, sehingga balasan
> terasa hilang. Cron dibuang dan diganti **webhook**: Telegram → Cloudflare Worker →
> langsung memicu Actions. Tanpa server, tetap gratis, balasan datang beberapa menit
> setelah kamu kirim.

## Deploy: Webhook + Actions (cara utama, gratis, tanpa server)

Alur: Telegram → Cloudflare Worker (gratis) → `repository_dispatch` → workflow jalan
**saat itu juga**. Pesannya ikut dikirim lewat payload, jadi tidak ada polling sama sekali.

### 1. Buat GitHub Personal Access Token

[Settings → Developer settings → Personal access tokens → Fine-grained tokens](https://github.com/settings/personal-access-tokens/new)
- Repository access: **Only select repositories** → `Crypto-Analis`
- Permissions → Repository permissions → **Contents: Read and write** (izin minimum
  yang dibutuhkan untuk memicu `repository_dispatch`)
- Salin token-nya (`github_pat_...`)

### 2. Buat Cloudflare Worker

1. Daftar gratis di [dash.cloudflare.com](https://dash.cloudflare.com) (tidak perlu kartu)
2. **Compute (Workers)** → **Create** → **Start from Hello World** → beri nama, **Deploy**
3. Klik **Edit code**, hapus isinya, tempel seluruh isi
   [deploy/cloudflare-worker.js](deploy/cloudflare-worker.js), lalu **Deploy**
4. Buka **Settings → Variables and Secrets**, tambahkan 4 variabel (pilih tipe **Secret**
   untuk dua yang pertama):

   | Nama | Isi |
   |---|---|
   | `GITHUB_TOKEN` | token dari langkah 1 |
   | `TELEGRAM_SECRET` | string acak buatanmu (mis. hasil `openssl rand -hex 16`) |
   | `GITHUB_REPO` | `ihsanmp/Crypto-Analis` |
   | `ALLOWED_CHAT_IDS` | chat ID kamu |

5. Salin URL Worker-nya (mis. `https://xxx.workers.dev`)

### 3. Daftarkan webhook ke Telegram

```bash
bash deploy/set-webhook.sh https://xxx.workers.dev RAHASIA_YANG_SAMA_DENGAN_TELEGRAM_SECRET
```

Cek hasilnya: `bash deploy/set-webhook.sh --status` — kalau `"url"` sudah terisi dan
`"pending_update_count"` kecil, berarti sudah aktif.

> ⚠️ Selama webhook aktif, Telegram **menonaktifkan** `getUpdates`. Jadi mode polling
> (`workflow_dispatch` manual) tidak akan menemukan pesan. Kalau mau kembali ke polling:
> `bash deploy/set-webhook.sh --delete`.

### 4. Isi GitHub Secrets

Settings → Secrets and variables → Actions → **New repository secret**:

| Nama secret | Wajib? | Isi |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | **wajib** | Token dari @BotFather |
| `TELEGRAM_CHAT_ID` | **wajib** | Chat ID kamu. Bot menolak jalan tanpa ini (fail-closed), supaya orang lain yang menemukan bot tidak bisa menghabiskan kuota Claude-mu |
| `CLAUDE_CODE_OAUTH_TOKEN` | **wajib** | Hasil `claude setup-token` (butuh Claude Pro/Max) |
| `COINMARKETCAP_API_KEY` | **wajib** | Gratis di [pro.coinmarketcap.com](https://pro.coinmarketcap.com/signup) — paket Basic ~10.000 kredit/bulan |
| `TELEGRAM_SESSION` | opsional | **Akses PENUH ke akun Telegram-mu** — bukan API key, tidak ada versi read-only. Dibuat lokal dengan `cloud/tgsesi.py`, tidak pernah lewat chat. Hanya dipakai step `Baca grup Telegram`; step yang menjalankan model TIDAK memilikinya. Tanpa ini: riset grup tidak tersedia, sisanya jalan normal |
| `TELEGRAM_GRUP` | opsional | **Daftar grup pilihan**, JSON per kategori: `{"crypto":[...],"forex":[...],"kerja":[...]}`. Di Secret, BUKAN di repo — repo ini publik, dan daftar grup yang diikuti seseorang mengungkap komunitas, minat, bahkan kota. Kategorinya dipilih dari pertanyaan: grup forex hanya dibaca saat menanyakan forex/emas, grup lowongan hanya saat menanyakan pekerjaan. Tanpa ini: seluruh grup dibaca, dan dengan puluhan grup jatah 200 pesan habis sebelum yang berisi sempat terbaca |
| `TELEGRAM_API_ID` | opsional | Dari [my.telegram.org](https://my.telegram.org). Dibutuhkan bersama `TELEGRAM_SESSION` |
| `TELEGRAM_API_HASH` | opsional | Dari my.telegram.org, pasangan `TELEGRAM_API_ID` |
| `SOSOVALUE_API_KEY` | opsional | Gratis di [sosovalue.com/developer/dashboard](https://sosovalue.com/developer/dashboard). Tanpa ini: arus ETF tidak tersedia, dan studi kejutan jatuh ke nowcast Cleveland Fed |
| `FINNHUB_API_KEY` | opsional | Gratis. Tanpa ini: jadwal earnings & daftar peer tidak tersedia, analisa saham tetap jalan |
| `MORALIS_API_KEY` | opsional | Gratis, 40.000 CU/hari. Dibutuhkan untuk holder/wallet **selain** Ethereum |
| `COINGLASS_API_KEY` | opsional | Tanpa ini: funding/OI/likuidasi dilewati, analisa spot tetap penuh |

> Pakai repo **PUBLIC** supaya menit GitHub Actions gratis tanpa batas. Rahasia tetap aman
> karena disimpan di GitHub Secrets (bukan di kode); `.gitignore` menahan `.env`.
>
> Semua kunci opsional memakai pola yang sama: **tanpa kunci, bagian itu dilaporkan tidak
> tersedia — bukan dikarang, dan bukan mematikan analisa.**

---

## Alternatif: Deploy ke Server (balasan hitungan detik)

Butuh satu VPS Linux kecil (Ubuntu/Debian). 1 vCPU / 1 GB RAM sudah cukup.

```bash
# 1) Login ke server, ambil kodenya
git clone https://github.com/ihsanmp/Crypto-Analis.git
cd Crypto-Analis

# 2) Pasang semua kebutuhan (Python, Node, Claude CLI, server MCP)
bash deploy/setup-server.sh

# 3) Isi kredensial
nano .env        # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                 # COINMARKETCAP_API_KEY, CLAUDE_CODE_OAUTH_TOKEN

# 4) Uji jalan dulu di depan mata (Ctrl+C untuk berhenti)
python3 cloud/bot_daemon.py

# 5) Kalau sudah benar, jadikan service
bash deploy/install-service.sh
```

```bash
sudo journalctl -u crypto-analis -f      # lihat log langsung
sudo systemctl restart crypto-analis     # restart
```

> ⚠️ **Jangan jalankan daemon dan webhook bersamaan** — keduanya berebut membaca pesan
> Telegram yang sama sehingga pesan bisa hilang acak.

---

## Catatan

- **Maksimal 2 pesan per run** (job Actions dibatasi 30 menit, satu analisa bisa 15 menit).
  Pesan berlebih tetap mengantre dan dikerjakan run berikutnya.
- **Audit sebelum kirim.** Tiap balasan diperiksa: apakah angkanya terlacak ke data yang
  dikumpulkan, apakah datanya masih segar, apakah sumbernya disebut. Bila mencurigakan,
  peringatan disisipkan ke balasan yang kamu terima — bukan disembunyikan di log.
- **Berkas data punya umur.** Riwayat konsensus disegarkan mingguan; kalau jadwalnya mati
  diam-diam, keluaran menandai sendiri bahwa datanya sudah lebih dari 14 hari. Data ETF
  tertinggal beberapa hari dari harga (hari bursa + jeda pelaporan) dan umurnya selalu
  dicetak.
- **Batas yang disebut apa adanya, bukan disembunyikan:** riwayat harian crypto gratis
  hanya ~1 tahun untuk koin di luar BTC/ETH · seri kejutan FOMC berakhir 2023-12 · konsensus
  SoSoValue tidak punya jejak vintage · ETF spot hanya ada untuk BTC dan ETH.
- Kalau ada Secret wajib yang kosong, workflow berhenti tenang (exit 0) dengan pesan jelas
  di log, bukan gagal merah.
- Workflow terjadwal otomatis nonaktif kalau repo 60 hari tanpa aktivitas — cukup push
  commit apa saja untuk mengaktifkan lagi.
- Konfigurasi MCP sengaja **tidak memakai blok `env` dengan `${...}`**. Kalau variabelnya
  tidak di-set, Claude Code meneruskan teks harfiah `${NAMA}` sebagai nilai dan server MCP
  gagal dengan error auth yang menyesatkan. Semua kunci diwariskan lewat environment job.
- **Kalau menguji di Windows lokal**, dua jebakan yang tidak ada di GitHub Actions:
  `python` sering mengarah ke alias Microsoft Store (MCP diam-diam tidak muncul, tanpa
  error), dan `npm install -g` bisa gagal separuh jalan karena cache terkunci (EPERM).
- Metodologi analisa (bobot skor, threshold, aturan veto) ada di
  [cloud/prompts/analisa.md](cloud/prompts/analisa.md) — semua ambang batas adalah titik
  awal wajar dan sebaiknya dikalibrasi ulang lewat backtest.

⚠️ Output bot adalah riset pasar berbasis data, bukan saran keuangan. DYOR.

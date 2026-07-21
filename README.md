# Bot Riset Koin (Telegram + Claude Code, jalan di Cloud)

Sistem riset crypto **spot** jangka menengah (daily/weekly, analisa multi-timeframe),
jalan **24 jam di GitHub Actions — tanpa perlu laptop menyala**. Khusus spot: tidak
memberi saran short/leverage/futures; data derivatif dipakai hanya sebagai sentimen timing.

Dua cara pakai di Telegram:
- `analisa <koin>` → analisa lengkap terstruktur (skor 0-100, fundamental+teknikal, rencana entry/stop/target)
- ngobrol bebas, mis. "bagaimana pendapatmu tentang bitcoin?" → jawaban santai tapi tetap berbasis data
- `/help` → bantuan

Claude menarik data CoinMarketCap, CoinGlass, berita web, dan indikator teknikal yang
dihitung sendiri (EMA/RSI/Stoch/Fibonacci multi-timeframe), lalu membalas ke Telegram.

## Arsitektur

```
Telegram ("analisa sol")
   │
   ▼
GitHub Actions (cron tiap 5 menit)
   ├─ cek dulu: ada perintah "analisa" baru? (cepat, ~20 detik; kalau kosong berhenti)
   └─ kalau ada → claude -p (Claude Code headless)
        ├─ cloud/indicators.py  ← SUMBER UTAMA TEKNIKAL (dihitung dengan kode,
        │     EMA13/21 · RSI14 · Stoch 5,3,3 · Fibonacci · struktur, untuk 1w/1d/4h;
        │     OHLC dari Binance→Kraken→Coinbase→OKX→CoinGecko, weekly dibangun
        │     eksak dari candle harian)
        ├─ MCP tradingview    (versi data — cross-check arah saja)
        ├─ MCP coinmarketcap  (harga, mcap, FDV, volume, kategori, listings/top movers,
        │     Fear & Greed, global metrics) — shinzo-labs/coinmarketcap-mcp, butuh API key gratis
        ├─ MCP coinglass   (funding, OI, long/short, likuidasi) — butuh API key
        ├─ DefiLlama API   (TVL, fees, revenue — pengganti Token Terminal)
        └─ WebSearch       (berita & katalis)
   │
   ▼
Hasil analisa dikirim balik ke Telegram (~5-15 menit setelah kamu ketik)
```

> Catatan: teknikal pakai MCP TradingView versi data
> ([atilaahmettaner/tradingview-mcp](https://github.com/atilaahmettaner/tradingview-mcp)),
> bukan aplikasi TradingView Desktop — karena cloud tidak punya layar/GUI. Fundamental
> fees/revenue/TVL diambil dari DefiLlama (gratis), pengganti Token Terminal.

## File

| File | Fungsi |
|---|---|
| [.github/workflows/bot.yml](.github/workflows/bot.yml) | Workflow cron: cek Telegram tiap 5 menit, jalankan analisa |
| [cloud/bot_oneshot.py](cloud/bot_oneshot.py) | Bot "sekali jalan": ambil pesan tertunda, proses, balas, keluar |
| [cloud/indicators.py](cloud/indicators.py) | Penarik OHLC + kalkulator indikator deterministik (EMA/RSI/Stoch/Fibonacci untuk 1w/1d/4h). Tanpa dependensi eksternal |
| [cloud/.mcp.cloud.json](cloud/.mcp.cloud.json) | Konfigurasi MCP (TradingView-data + CoinGecko + CoinGlass) |
| [cloud/prompts/analisa.md](cloud/prompts/analisa.md) | **Mesin metodologi analisa** — sistem skor 0–100 (fundamental+teknikal), aturan veto, dan setting indikator persis punyamu (EMA 13/21, RSI 14, Stoch 5,3,3, Fibonacci Golden Pocket) |
| [cloud/prompts/chat.md](cloud/prompts/chat.md) | Prompt mode NGOBROL — jawaban santai untuk pertanyaan bebas, tetap ambil data sebelum berpendapat |

## Deploy (sekali saja)

### 1. Kredensial yang perlu disiapkan

- **Token bot Telegram**: chat @BotFather → `/newbot` → salin token.
- **Chat ID**: kirim pesan apa saja ke bot barumu, buka
  `https://api.telegram.org/bot<TOKEN>/getUpdates` di browser → catat `chat.id`.
- **API key CoinGlass**: daftar di https://www.coinglass.com/pricing (paket Hobbyist
  cukup). Boleh dikosongkan kalau tak butuh data futures (funding/OI/likuidasi).
- **Token langganan Claude** (butuh Claude Pro/Max). Di terminal yang sudah login
  Claude Code, jalankan `claude setup-token`, salin token yang keluar.

### 2. Push ke repo GitHub

```powershell
cd D:\Screening
git init
git add .
git commit -m "Bot riset koin"
git branch -M main
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

> Pakai repo **PUBLIC** supaya menit GitHub Actions gratis tanpa batas. Rahasia tetap
> aman karena disimpan di GitHub Secrets (bukan di kode); `.gitignore` menahan `.env`.

### 3. Isi GitHub Secrets

Settings → Secrets and variables → Actions → **New repository secret**:

| Nama secret | Isi |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token dari @BotFather — **wajib** |
| `TELEGRAM_CHAT_ID` | chat ID kamu — **wajib**. Bot menolak jalan tanpa ini (fail-closed), supaya orang lain yang menemukan bot tidak bisa menghabiskan kuota Claude-mu |
| `COINGLASS_API_KEY` | API key CoinGlass (boleh dikosongkan; tanpa ini sentimen derivatif — funding/OI — dilewati, analisa spot tetap jalan penuh) |
| `COINMARKETCAP_API_KEY` | **Wajib** — ambil gratis di https://pro.coinmarketcap.com/signup (paket Basic gratis, ~10.000 kredit/bulan). Tanpa ini semua data pasar tidak jalan |
| `CLAUDE_CODE_OAUTH_TOKEN` | token dari `claude setup-token` — **wajib** |

### 4. Aktifkan & pakai

- Buka tab **Actions** di repo, izinkan workflow jalan.
- Tes langsung: pilih workflow "Bot Riset Koin (Telegram)" → **Run workflow**.
- Di Telegram ketik `analisa (nama koin)`, contoh:
  - `analisa` — scan pasar, cari 3-5 koin menarik, pilih 1-2 setup terbaik
  - `analisa sol` — analisa mendalam satu koin

Balasan datang ~5-15 menit setelah kamu ketik (sesuai jadwal cron per-5-menit).

## Catatan

- Jadwal cron GitHub kadang meleset beberapa menit saat jam sibuk — normal.
- Maksimal **2 pesan per run** (job Actions dibatasi 30 menit, satu analisa bisa 15 menit).
  Pesan berlebih tidak hilang — tetap mengantre dan dikerjakan run berikutnya.
- **Mode ngobrol bersifat single-turn** — tiap pesan diproses independen tanpa memori
  percakapan sebelumnya (GitHub Actions stateless). Pertanyaan lanjutan sebaiknya menyebut
  ulang koin yang dimaksud.
- Kalau ada Secret wajib yang kosong, workflow berhenti tenang (exit 0) dengan pesan
  jelas di log, bukan gagal merah tiap 5 menit.
- **Kalau menguji di Windows lokal**, ada dua jebakan yang TIDAK ada di GitHub Actions:
  1. `python` sering mengarah ke alias Microsoft Store — Claude Code tidak bisa
     menjalankannya sebagai server MCP (MCP-nya diam-diam tidak muncul, tanpa error).
     Pakai path Python asli atau venv.
  2. `npm install -g` bisa gagal separuh jalan karena cache npm terkunci (EPERM) —
     shim terbuat tapi paketnya kosong. Install ke direktori bersih dengan
     `--cache <folder-lain>`, atau panggil langsung `node <path>/index.js`.
- Konfigurasi MCP sengaja **tidak memakai blok `env` dengan `${...}`**. Kalau variabelnya
  tidak di-set, Claude Code meneruskan teks harfiah `${NAMA}` sebagai nilai, dan server MCP
  menganggapnya kunci sungguhan lalu gagal dengan error auth yang menyesatkan. Semua kunci
  diwariskan lewat environment job di `bot.yml`.
- Workflow terjadwal otomatis nonaktif kalau repo 60 hari tanpa aktivitas — cukup push
  commit apa saja untuk mengaktifkan lagi.
- Mau lebih jarang/hemat? Ubah `cron: "*/5 * * * *"` di `bot.yml` (mis. `*/15`).
- Metodologi analisa (bobot skor, threshold, aturan veto, setting indikator) ada di
  [cloud/prompts/analisa.md](cloud/prompts/analisa.md) — semua ambang batas adalah titik
  awal wajar dan sebaiknya dikalibrasi ulang lewat backtest pada koin yang kamu analisa.

⚠️ Output bot adalah riset pasar berbasis data, bukan saran keuangan. DYOR.

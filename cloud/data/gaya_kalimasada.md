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

### Vonis

**Belum terbukti, dan belum terbantah.** Yang bisa dikatakan jujur: 30 hari riwayat di
pasar yang seluruhnya naik tidak cukup untuk menetapkan maupun menolak edge. Yang berubah
adalah pullback kini BISA diukur; sebelumnya tidak.

**Cara memakainya di jawaban:** perlakukan sebagai **kerangka membaca chart** — konsolidasi,
pemicu, target di zona berikutnya — bukan sebagai sinyal dengan tingkat kemenangan. Kalau
user bertanya "sesuai gaya mentor saya, gimana?", boleh membaca strukturnya dengan kerangka
ini; JANGAN menempelkan angka kemenangan padanya, dan JANGAN menyebutnya teruji.

---

## Yang perlu diuji kalau mau dilanjutkan

- Riwayat 4h lebih panjang dari 30 hari (butuh sumber lain; CoinGecko hanya menyimpan ~30).
- Pembanding beli-dan-tahan pada tiap sinyal, bukan hanya persentase menang.
- Jendela yang memuat pasar TURUN — seluruh pengukuran di atas berasal dari pasar naik.
- Biaya: perpetual punya funding, dan setup intraday berpindah posisi jauh lebih sering.

⚠️ Materi acuan, bukan nasihat keuangan.

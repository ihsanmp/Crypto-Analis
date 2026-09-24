# Pola double bottom / double top — dideteksi kode, diuji pada BTC harian 2012–2026

Asal: gambar ketiga materi Astronacci yang dikirim user (BTC Weekly, 21 Sep 2026) —
"Double Bottom ... neckline di area 83.000 ... target 98.000 dan 127.000 ... support
57.500". Goal user: outlook seperti itu. Kode: `cloud/pola.py`.

## Definisi (ditetapkan sebelum melihat hasil)

| | Harian | Mingguan |
|---|---|---|
| Fraktal pivot | 3 | 2 |
| Jeda antar-lembah | 10–120 candle | 4–40 candle |
| Tembus neckline | ≤ 60 candle sesudah lembah kedua | ≤ 16 |

Dua lembah berbeda maks 5%; neckline minimal 8% di atas lembah terdalam. Neckline =
puncak tertinggi di antara kedua lembah. Target ukur = neckline + (neckline − lembah
terdalam). Invalid = lembah terdalam. Double top = cerminnya.

## Reproduksi independen klaim Astronacci

Dijalankan pada data s.d. 1 Sep 2026, tanpa diberi tahu apa pun tentang gambarnya:

| | Astronacci | Kode |
|---|---|---|
| Lembah | ~Mar & Agu 2026 | 23 Mar 2026 $64.955 · 3 Agu 2026 $62.216 |
| **Neckline** | **83.000** | **$82.833** |
| Target | 98.000 / 127.000 | ukur $103.450 |
| Support / invalid | 57.500 | $62.216 |

Neckline cocok dalam 0,2%. Target 98.000/127.000 tidak dihasilkan cara ukur baku (dengan
lembah ~62 rb, target ukurnya ~103 rb), jadi sumbernya tidak bisa direproduksi.

## Uji: setelah tembus, target ukur dulu atau dasar pola dulu?

Pembanding: dari setiap hari, peluang BTC menyentuh +x% sebelum −x% dengan jarak PERSIS
sama seperti kasusnya (horizon 180 hari). Candle yang menyentuh keduanya = gagal.

| Harian | n | Target dulu | Pembanding |
|---|---|---|---|
| Double bottom | 133 | 77,4% | 66,9% (z=+2,64, p=0,008) |
| Double top | 112 | 50,0% | 49,9% |

Mingguan: double bottom 81,8% vs 76,3% (n=11), double top 46,2% vs 51,4% (n=13) —
sampel terlalu kecil untuk disimpulkan.

### Dipotong kronologis — di sinilah kesimpulannya berubah

| Double bottom harian | n | Target dulu | Pembanding | p |
|---|---|---|---|---|
| 2012–2016 | 39 | 97,4% | 65,1% | < 0,001 |
| 2017–2021 | 40 | 80,0% | 71,7% | 0,23 |
| 2022–2026 | 54 | 61,1% | 64,6% | 0,59 |
| 2012–2018 | 51 | 94,1% | 66,7% | < 0,001 |
| **2019–2026** | **82** | **67,1%** | **67,0%** | **0,99** |

**Seluruh keunggulan itu milik era awal BTC.** Di tujuh tahun terakhir pola double bottom
tidak menambah informasi apa pun: target ukurnya tercapai lebih dulu dengan peluang yang
sama persis dengan hari mana pun pada jarak yang sama. Angka gabungan 77,4% vs 66,9% akan
membuat pola ini tampak bekerja — persis jebakan yang diperingatkan prinsip 3 README.

Median jarak ke target ukur saat tembus: 9,2% (p10 4,0%, p90 18,5%).

## Aturan untuk agent

- Pola dari blok `POLA (pola.py)` boleh dinamai beserta neckline, target ukur, dan
  invalid-nya — sebagai deskripsi struktur.
- Peluang target = peluang dasar (~2 dari 3 untuk double bottom, ~1 dari 2 untuk double
  top). **Dilarang** menaikkannya karena polanya.
- Pola yang tidak ada di blok tidak boleh dinamai.
- Diuji pada BTC saja; untuk koin lain, peluangnya belum diuji.

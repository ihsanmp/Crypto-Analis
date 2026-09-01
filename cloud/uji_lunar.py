"""
btc_lunar_test.py
=================
Uji hipotesis: apakah fase bulan punya efek terukur pada return harian BTC?

Rancangan uji (semuanya dijalankan pada data yang sama):
  1. Event-window test   : return di window +/-3d dan +/-7d sekitar new moon vs full moon,
                           OLS dengan HAC (Newey-West) + kontrol day-of-week & turn-of-month.
  2. Harmonic test       : sudut fase kontinu (cos/sin, 2 harmonik) -- menangkap efek mulus
                           di seluruh siklus, bukan cuma di dua titik yang dipilih manual.
  3. Placebo test        : ulangi (1) dengan 2000 siklus PALSU berperiode 29,53 hari tapi
                           offset fase acak. Kalau efek "asli" tidak berada di ekor distribusi
                           placebo, tidak ada apa-apa di sana. Ini mengontrol seluruh musiman
                           bulanan (turn-of-month, expiry, funding cycle) sekaligus.
  4. Volatility test     : sd / MAD / mean|r| di window ekstrem vs sisanya, + winsorize + drop
                           outlier, untuk memisahkan efek nyata dari beberapa hari ekor gemuk.
  5. Split dev/hold-out  : dev 2012-2021, hold-out 2022-2026 (tidak dipakai untuk tuning).
  6. Backtest naif       : long selama paruh waxing vs waning vs buy & hold, biaya 0,1%/switch.

Data default: Bitstamp 1-min OHLC (repo publik ff137/bitstamp-btcusd-minute-data),
diagregasi ke harian UTC. Bisa diganti CSV sendiri lewat --csv (butuh kolom dt, close).

Dependensi: pip install pandas numpy statsmodels ephem
Jalankan   : python cloud/uji_lunar.py            (data ikut di repo, terkompresi)

DIREPRODUKSI 2 Sep 2026 di repo ini; hasilnya dicatat di cloud/data/moon_phase_btc.md
Bagian 4.9. Seluruh angka Bagian 4.3-4.5, 4.7, dan 4.8 keluar identik. Satu koreksi
ditemukan: tabel oktan 4.6 hanya reproduksi kalau binnya DIMULAI di titik fase; dengan bin
yang BERPUSAT di titik fase, pola "New dan Full sama-sama nol" hilang sama sekali dan Full
justru jadi oktan tertinggi. Lihat --oktan.

Berkas ini alat REPRODUKSI, bukan bagian jalur jawaban. Bot tidak menjalankannya saat
menjawab: kesimpulannya sudah tetap, dan fase bulan adalah fitur null untuk BTC.
"""
import argparse
import os
import numpy as np
import pandas as pd
import ephem
import statsmodels.api as sm

SYNODIC = 29.530588853  # panjang bulan sinodis rata-rata (hari)


# --------------------------------------------------------------------------- data
def load(csv):
    d = pd.read_csv(csv, parse_dates=['dt']).set_index('dt')
    if 'n' in d.columns:                     # buang hari yang barnya tidak lengkap
        d = d[d['n'] >= 1000]
    d['r'] = np.log(d['close']).diff()
    return d.dropna(subset=['r'])


def phase_frac(ts):
    """Fraksi perjalanan dalam siklus sinodis. 0.0 = new moon, 0.5 = full moon."""
    dt = ephem.Date(ts.to_pydatetime().replace(tzinfo=None))
    prev_new, next_new = ephem.previous_new_moon(dt), ephem.next_new_moon(dt)
    return (dt - prev_new) / (next_new - prev_new)


def add_phase(d):
    d = d.copy()
    d['p'] = [phase_frac(t + pd.Timedelta(hours=12)) for t in d.index]
    d['d_new'] = np.minimum(d['p'], 1 - d['p']) * SYNODIC      # jarak (hari) ke new moon
    d['d_full'] = np.abs(d['p'] - 0.5) * SYNODIC               # jarak (hari) ke full moon
    return d


def controls(d):
    dow = pd.get_dummies(d.index.dayofweek, prefix='dow', drop_first=True).astype(float)
    dow.index = d.index
    tom = pd.Series(((d.index.day <= 3) |
                     (d.index.day >= d.index.days_in_month - 1)).astype(float),
                    index=d.index, name='tom')
    return pd.concat([dow, tom], axis=1)


# ------------------------------------------------------------------- uji utama
def event_test(d, halfwin, ctrl):
    """Return di window new moon vs full moon. HAC lags = panjang window."""
    NEW = (d['d_new'] <= halfwin).astype(float).rename('NEW')
    FULL = (d['d_full'] <= halfwin).astype(float).rename('FULL')
    X = sm.add_constant(pd.concat([NEW, FULL, ctrl], axis=1))
    m = sm.OLS(d['r'], X).fit(cov_type='HAC', cov_kwds={'maxlags': 2 * halfwin + 1})
    c = np.zeros(len(m.params))
    c[list(m.params.index).index('NEW')] = 1
    c[list(m.params.index).index('FULL')] = -1
    t = m.t_test(c)
    return dict(new=m.params['NEW'], full=m.params['FULL'],
                diff=float(np.ravel(t.effect)[0]),
                tstat=float(np.ravel(t.tvalue)[0]),
                pval=float(np.ravel(t.pvalue)[0]))


def harmonic_test(d, ctrl, K=2):
    """Regresi harmonik pada sudut fase kontinu; uji F gabungan semua suku cos/sin."""
    H = pd.DataFrame(index=d.index)
    for k in range(1, K + 1):
        H[f'cos{k}'] = np.cos(2 * np.pi * k * d['p'])
        H[f'sin{k}'] = np.sin(2 * np.pi * k * d['p'])
    X = sm.add_constant(pd.concat([H, ctrl], axis=1))
    m = sm.OLS(d['r'], X).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
    R = np.zeros((len(H.columns), len(m.params)))
    for i, c in enumerate(H.columns):
        R[i, list(m.params.index).index(c)] = 1
    w = m.f_test(R)
    amp = np.hypot(m.params['cos1'], m.params['sin1'])
    return dict(F=float(w.fvalue), pval=float(w.pvalue), amp1=amp)


def placebo(d, ctrl, halfwin, n_draws=2000, seed=42):
    """Distribusi null: siklus 29,53 hari dengan offset fase acak."""
    rng = np.random.default_rng(seed)
    dn = (d.index - d.index[0]).days.values.astype(float)
    y = d['r'].values
    C = ctrl.values.astype(float)
    ones = np.ones((len(d), 1))
    out = []
    for _ in range(n_draws):
        p = ((dn + rng.uniform(0, SYNODIC)) % SYNODIC) / SYNODIC
        NEW = (np.minimum(p, 1 - p) * SYNODIC <= halfwin).astype(float)
        FULL = (np.abs(p - 0.5) * SYNODIC <= halfwin).astype(float)
        X = np.column_stack([ones, NEW, FULL, C])
        m = sm.OLS(y, X).fit(cov_type='HAC', cov_kwds={'maxlags': 2 * halfwin + 1})
        c = np.zeros(X.shape[1]); c[1], c[2] = 1, -1
        out.append(float(np.ravel(m.t_test(c).tvalue)[0]))
    return np.array(out)


def vol_test(d, halfwin=3, n_draws=3000, seed=11):
    """Rasio dispersi window ekstrem (new ATAU full) vs sisanya, + cek ketahanan outlier."""
    rng = np.random.default_rng(seed)
    dn = (d.index - d.index[0]).days.values.astype(float)
    mad = lambda x: np.median(np.abs(x - np.median(x)))

    def ratio(p, r, fn):
        e = (np.minimum(p, 1 - p) * SYNODIC <= halfwin) | (np.abs(p - 0.5) * SYNODIC <= halfwin)
        return fn(r[e]) / fn(r[~e])

    r = d['r'].values
    lo, hi = np.percentile(r, [1, 99])
    variants = [('sd (mentah)', r, np.std),
                ('MAD (robust)', r, mad),
                ('mean |r|', r, lambda x: np.mean(np.abs(x))),
                ('sd, winsorize 1/99%', np.clip(r, lo, hi), np.std)]
    res = []
    for name, rr, fn in variants:
        real = ratio(d['p'].values, rr, fn)
        null = np.array([ratio(((dn + rng.uniform(0, SYNODIC)) % SYNODIC) / SYNODIC, rr, fn)
                         for _ in range(n_draws)])
        res.append((name, real, (null >= real).mean()))
    return res


def backtest(d, fee=0.001):
    waxing = (d['p'] < 0.5).astype(float)          # new -> full
    sw = waxing.diff().abs().fillna(0)
    logfee = np.log(1 - fee)

    def stats(r, name):
        ann, vol = r.mean() * 365, r.std() * np.sqrt(365)
        eq = r.cumsum()
        dd = (eq - eq.cummax()).min()
        return (name, np.expm1(ann) * 100, vol * 100, ann / vol, np.expm1(dd) * 100)

    return [stats(d['r'], 'Buy & hold'),
            stats(d['r'] * waxing + sw * logfee, 'Long waxing (new->full)'),
            stats(d['r'] * (1 - waxing) + sw * logfee, 'Long waning (full->new)')]


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'data',
        'btc_daily_bitstamp.csv.gz'))
    ap.add_argument('--dev-end', default='2021-12-31')
    ap.add_argument('--draws', type=int, default=2000)
    ap.add_argument('--oktan', action='store_true',
                    help='bandingkan dua cara membagi oktan fase')
    a = ap.parse_args()

    d = add_phase(load(a.csv))
    print(f"Data: {len(d)} hari, {d.index[0].date()} .. {d.index[-1].date()}\n")

    samples = {'FULL': d, 'DEV': d.loc[:a.dev_end], 'HOLDOUT': d.loc[a.dev_end:][1:]}

    print("=== 1. EVENT-WINDOW TEST (new vs full, HAC + kontrol DOW/TOM) ===")
    for name, s in samples.items():
        c = controls(s)
        for hw in (3, 7):
            r = event_test(s, hw, c)
            print(f"  {name:<8} +/-{hw}d  new={r['new']*100:+.4f}%/d  full={r['full']*100:+.4f}%/d"
                  f"  selisih={r['diff']*100:+.4f}%/d  t={r['tstat']:+.2f}  p={r['pval']:.3f}")

    print("\n=== 2. HARMONIC TEST (sudut fase kontinu) ===")
    for name, s in samples.items():
        r = harmonic_test(s, controls(s))
        print(f"  {name:<8} F={r['F']:.2f}  p={r['pval']:.3f}  amplitudo harmonik-1={r['amp1']*100:.4f}%/hari")

    print(f"\n=== 3. PLACEBO TEST ({a.draws} siklus palsu 29,53 hari) ===")
    c = controls(d)
    for hw in (3, 7):
        t_real = event_test(d, hw, c)['tstat']
        null = placebo(d, c, hw, a.draws)
        print(f"  +/-{hw}d  |t| asli={abs(t_real):.2f}   placebo median={np.median(abs(null)):.2f}"
              f"  p95={np.percentile(abs(null), 95):.2f}   p empiris={(abs(null) >= abs(t_real)).mean():.3f}")

    print("\n=== 4. VOLATILITAS (window ekstrem vs sisanya) ===")
    for name, real, p in vol_test(d):
        print(f"  {name:<24} rasio={real:.4f}  p={p:.4f}")

    if a.oktan:
        print("\n=== 4b. OKTAN FASE - DUA CARA MEMBAGI, DUA CERITA ===")
        nama = ['New', 'Sabit naik', 'Kuartal I', 'Cembung naik',
                'Full', 'Cembung turun', 'Kuartal III', 'Sabit turun']
        r, p = d['r'].values, d['p'].values
        for judul, okt in (('bin DIMULAI di titik fase', np.floor(p * 8).astype(int) % 8),
                           ('bin BERPUSAT di titik fase',
                            np.floor(((p + 1 / 16) % 1) * 8).astype(int) % 8)):
            print(f"  {judul}")
            for i, n in enumerate(nama):
                x = r[okt == i] * 100
                print(f"    {n:<15} {x.mean():+7.3f}%/hari  SE={x.std(ddof=1)/np.sqrt(len(x)):5.3f}  n={len(x)}")
        print(f"    {chr(40)}keseluruhan{chr(41)}   {r.mean()*100:+7.3f}%/hari")
        print("  Pola New & Full sama-sama nol HANYA muncul di cara pertama. Itu"
              " sendiri bukti bahwa polanya derau: temuan nyata tidak bergantung"
              " pada di mana batas bin kebetulan diletakkan.")

    print("\n=== 5. BACKTEST NAIF (biaya 0,1% per switch) ===")
    for name, cagr, vol, sharpe, dd in backtest(d):
        print(f"  {name:<26} CAGR={cagr:7.1f}%  vol={vol:5.1f}%  Sharpe={sharpe:5.2f}  maxDD={dd:6.1f}%")


if __name__ == '__main__':
    main()

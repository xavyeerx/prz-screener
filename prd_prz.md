# PRD: PRZ Buy Zone Scanner (LQ45)

## 1. Tujuan

Tool Python standalone (jalan lokal) yang men-scan seluruh saham LQ45, mendeteksi pola harmonic XABCD (Gartley, Bat, Butterfly, Crab, Shark) yang sedang membentuk **PRZ (Potential Reversal Zone) arah BUY**, dan mengeluarkan:
1. Chart PNG per saham yang lolos filter (candlestick + garis XABCD + box PRZ + label rasio)
2. Ringkasan teks/tabel semua saham yang match, terurut berdasarkan skor/kedekatan ke PRZ

Ini adalah port dari logika "Harmonic PRZ Scanner v9" (Pine Script, sudah diuji coba dan terbukti bekerja di TradingView) ke Python, supaya bisa scan banyak saham sekaligus (Pine Script hanya jalan 1 chart per waktu).

---

## 2. Scope & Non-Goals

**In scope:**
- Deteksi XABCD pattern (5 tipe) pada data candle historis
- Multi-timeframe: Daily dan 4H (dipilih via parameter)
- Multi-depth zigzag (replikasi 5 depth dari Pine: 5/8/12/20/34)
- Filter arah BUY saja (PRZ di/mendekati bawah harga saat ini)
- Output PNG chart + summary
- Watchlist default: LQ45

**Out of scope (v1):**
- Bukan bot berjalan otomatis / cron / Telegram — dijalankan manual saat dibutuhkan
- Tidak digabungkan dengan bandarmology/broksum scoring — tool ini murni technical/harmonic
- Tidak ada backtesting/alerting historis, hanya kondisi "saat ini"

---

## 3. Sumber Data

- **Library**: `yfinance`
- **Ticker format**: `<KODE>.JK` (contoh: `BBCA.JK`)
- **Timeframe Daily**: `interval='1d'`, `period` cukup panjang (mis. `2y`) agar zigzag depth besar (34) punya cukup pivot
- **Timeframe 4H**: `interval='4h'` (catatan: yfinance intraday untuk `.JK` bisa terbatas history-nya — biasanya hanya ~60 hari terakhir tersedia untuk interval < 1 hari, dan ketersediaan `4h` native perlu dicek langsung karena kadang yfinance hanya expose interval seperti `60m`/`90m`/`1h` bukan `4h`. **Perlu divalidasi saat implementasi**; kalau `4h` tidak didukung langsung, fallback: ambil `1h` lalu resample ke 4H).
- **Rate limiting**: LQ45 = 45 ticker → butuh jeda antar-request atau batching (`yf.download()` multi-ticker sekali panggil) untuk hindari throttle.

---

## 4. Konsep Inti (Port dari Pine Script v9)

### 4.0 Prinsip Utama: Formula HARUS Identik dengan Pine Script v9

Pine Script ini sudah diuji coba dan terbukti bekerja di chart — jadi Python **bukan reimplementasi bebas**, tapi **port matematis 1:1**. Setiap konstanta, formula, dan urutan logika harus ditelusuri baris demi baris dari source Pine dan direplikasi persis, termasuk:

- **Tabel rasio pattern** — nilai `pBLo/pBHi/pCLo/pCHi/pDLo/pDHi/pBcLo/pBcHi` untuk kelima pattern harus disalin persis, bukan didekati dari sumber lain (walaupun secara umum ini rasio Fibonacci standar, versi Pine ini punya angka spesifik seperti Bat `pDLo=pDHi=0.886`, Shark `pCLo=1.130`, dll — itu harus dipakai apa adanya).
- **Formula PRZ**: proyeksi `dxa1/dxa2` (dari XA), `dbc` (dari BC extension via `refD`), `dcd` (dari CD extension via `refD`) — termasuk urutan `refD = (dxa1+dxa2)/2` dulu baru dipakai untuk clamp `bcExt` dan `cdExt` — ini bukan cara umum menghitung PRZ harmonic (banyak referensi lain menghitung 3 proyeksi independen), jadi harus ikut persis logika `refD` sebagai pivot referensi seperti di kode.
- **`f_powerNear()`** (kedekatan ke "power zone" 0.886–1.13 dari XA) dan bobot skor `0.42/0.28/0.12/0.06/0.12` — dipakai persis, bukan diganti bobot lain.
- **Validitas (`valid`)**: cek breakout PRZ dari `minC`/`maxC` sejak titik C sampai bar terakhir dengan `tol_break`, arah bull cek `minC < przLo*(1-tol/100)`, bear cek `maxC > przHi*(1+tol/100)` — logika arah ini harus sama, jangan dibalik.
- **Filter arah BUY** (`sideOK` di `f_pickBest`): BUY hanya valid kalau `przLo <= close` (PRZ di/bawah harga) — bukan "harga mendekati dari mana saja".
- **Zigzag**: definisi pivot Pine pakai `ta.pivothigh(high, depth, depth)` — window kiri **dan** kanan sama besar `depth`, artinya sebuah pivot baru dikonfirmasi `depth` bar **setelah** titik itu terjadi (lookahead-safe, tidak repaint ke depan tapi ada delay konfirmasi). Ini harus direplikasi persis di Python (jangan pakai pivot yang "melihat ke depan" tanpa delay, dan jangan pula pakai window asimetris).
- **ABCD (4 titik)**: tabel resiprokal `abcdRetr`/`abcdExt` dan pemilihan `f_nearestIdx` (nearest-neighbor lookup) disalin persis (tetap default OFF sesuai Pine, hanya aktif kalau `use_abcd=True`).

### 4.0.1 Yang Boleh Direvisi/Ditambah (opsional, ditandai jelas terpisah)

Karena scanner Python beroperasi lintas-saham (bukan 1 chart interaktif), boleh ada penyesuaian **selama tidak mengubah hasil deteksi pattern itu sendiri** — harus didokumentasikan terpisah di kode/README sebagai "deviasi dari Pine", contoh yang mungkin relevan:
- Parameter `proximity_pct` (konsep baru, tidak ada di Pine — Pine hanya gambar semua PRZ yang lolos `sideOK`, tidak ada ambang "mendekati dari atas")
- Cara render chart (mplfinance vs Pine drawing) — bebas, karena ini presentasi bukan matematika
- Efisiensi fetch data (batching yfinance) — bebas, tidak menyentuh formula
- Struktur file/kode — bebas

Kalau ada revisi matematis lain yang diusulkan Claude Code (misal simplifikasi rumus), **wajib ditandai eksplisit dan minta konfirmasi**, bukan diam-diam diganti.

### 4.1 Zigzag Multi-Depth

Replikasi `f_zz()`: pivot high/low dengan window depth tertentu (default: 5, 8, 12, 20, 34), disimpan sebagai list titik `(price, bar_index, is_high)`. Setara `ta.pivothigh`/`ta.pivotlow`: cek local max/min dalam window `depth` bar ke kiri **dan** kanan (simetris, delay konfirmasi `depth` bar — lihat §4.0).

### 4.2 Deteksi XABCD

Untuk tiap depth, ambil 5 titik pivot berurutan yang alternating (X-A-B-C-D arah naik-turun berselang-seling), lalu:
- Hitung `AB/XA` (retracement B) dan `BC/AB` (retracement C)
- Cocokkan ke tabel rasio 5 pattern (Gartley, Bat, Butterfly, Crab, Shark) — tabel rasio persis sama seperti di Pine (`pBLo/pBHi`, `pCLo/pCHi`, `pDLo/pDHi`, `pBcLo/pBcHi`)
- Toleransi: Strict (default 5%) dan Loose (default 10%), keduanya bisa dicek

### 4.3 Hitung PRZ (Potential Reversal Zone)

- Proyeksi D dari 3 sumber: retracement XA, extension BC (via `refD`), extension AB/CD (via `refD`)
- PRZ = rentang antara proyeksi-proyeksi tersebut yang saling berdekatan (konvergensi)
- Filter lebar PRZ maksimal (`prz_maxw`, default 6% dari mid price) — PRZ yang terlalu lebar dibuang (tidak presisi)
- Filter jarak PRZ dari harga saat ini (`max_dist`, default 50%)

### 4.4 Validitas Pattern

- Pattern dianggap **valid** jika sejak titik C terbentuk, harga close belum pernah menembus PRZ melebihi toleransi (`tol_break`, default 1.5%)
- Pattern **invalid** jika sudah pernah ditembus signifikan

### 4.5 Skor Kualitas

Formula sama seperti Pine:
```
score = 100 * (0.42*fidelity + 0.28*confluence + 0.12*strictness + 0.06*psy_level_bonus + 0.12*sweet_spot)
```
- `fidelity`: seberapa dekat rasio B dan C ke rasio ideal pattern
- `confluence`: seberapa sempit PRZ (proyeksi berkumpul rapat)
- `sweet spot` (`f_powerNear`): kedekatan proyeksi D ke rasio "power zone" 0.886–1.13 dari XA

---

## 5. Logika Filter "Mendekati PRZ Buy"

Parameter kunci: `proximity_pct` (default disepakati, misal 3%) — **catatan: ini konsep tambahan di luar Pine, lihat §4.0.1.**

Kondisi saham **lolos filter** jika:
1. Ada minimal 1 pattern **bullish** (arah BUY) — **valid maupun invalid**, DAN
2. Harga close terakhir **sudah berada di dalam PRZ**, ATAU berada **di atas PRZ dalam jarak ≤ proximity_pct** menuju PRZ (mendekat dari atas, belum masuk)

Status `valid`/`invalid` **tetap dihitung dan ditampilkan** (di summary maupun chart, lihat §6), tapi **bukan syarat lolos filter**. Alasannya: pattern yang baru saja invalid (baru tertembus tipis) atau BUY zone yang masih dalam pembentukan tetap relevan untuk dipantau — bukan hanya yang sudah "confirmed valid". Filter murni soal *kedekatan harga ke PRZ*, bukan status validitasnya.

Prioritas pemilihan pattern terbaik per saham (jika lebih dari satu match), sama seperti logika `f_pickBest` di Pine:
1. Valid > invalid
2. Lebih dekat ke harga saat ini
3. XABCD (5 titik) > ABCD (4 titik) — ABCD opsional, default off sesuai Pine
4. Skor tertinggi

> Catatan: prioritas "valid > invalid" di atas hanya berlaku untuk **memilih pattern mana yang direpresentasikan sebagai "best buy"** ketika ada lebih dari satu kandidat bullish pada saham yang sama (mengikuti `f_pickBest`/`gateValid` di Pine) — ini bukan syarat lolos-tidaknya saham dari filter proximity.

> **Penting — filter vs tampilan chart adalah dua hal terpisah:**
> Kriteria **lolos filter** di atas murni berdasarkan PRZ **BUY** (saham masuk daftar hanya karena ada zona beli yang relevan). Namun begitu saham lolos filter, **chart PNG yang di-generate untuk saham tersebut harus menampilkan SEMUA PRZ yang terdeteksi pada saham itu — baik BUY maupun SELL (jika ada)** — bukan cuma PRZ buy yang menjadi alasan ia lolos filter. Ini konsisten dengan perilaku Pine Script asli, di mana `mode_best` selalu menggambar `bestBuy` **dan** `bestSell` sekaligus dalam satu chart (lihat blok akhir Pine: `f_select(cands, true, ...)` dan `f_select(cands, false, ...)` dua-duanya dipanggil, lalu semua `drawList` digambar). Jangan buat versi chart yang hanya menggambar sisi buy saja; filter hanya menentukan *saham mana yang di-generate chart-nya*, bukan *apa yang ditampilkan di dalam chart itu*.

---

## 6. Output

### 6.1 Chart PNG (per saham yang lolos)

- Candlestick chart (pakai `mplfinance`)
- **Menampilkan semua PRZ yang terdeteksi pada saham tersebut — BUY dan SELL (jika ada keduanya)** — bukan hanya PRZ buy yang menjadi alasan saham ini lolos filter (lihat catatan §5)
- Overlay garis X-A-B-C-D (dan garis bantu XB, AC putus-putus) untuk tiap pattern yang ditampilkan
- Box PRZ (area shading) dengan label: nama pattern, arah (▲BUY / ▼SELL), range harga, status valid/invalid — warna/style berbeda untuk buy vs sell agar mudah dibedakan
- Garis target (TP1/TP2/TP3) dan stop loss, sama seperti Pine
- Filename: `{TICKER}_{TIMEFRAME}_{TANGGAL}.png` (tidak menyertakan nama pattern tunggal di filename karena chart bisa memuat lebih dari satu pattern/arah)
- Disimpan ke folder lokal, misal `./output/`

### 6.2 Summary

Tabel/teks berisi semua saham yang lolos, kolom:
- Ticker
- Pattern (Gartley/Bat/Butterfly/Crab/Shark)
- Timeframe
- PRZ range (low–high)
- Jarak harga ke PRZ (%)
- Status (masuk PRZ / mendekati)
- Valid/Invalid
- Skor
- Target TP1/TP2/TP3, Stop

Terurut dari yang paling dekat/paling tinggi skor.

---

## 7. Parameter Konfigurasi (semua bisa diatur di awal script/CLI)

| Parameter | Default | Keterangan |
|---|---|---|
| `watchlist` | LQ45 | List ticker, override manual bisa |
| `timeframe` | `1d` | `1d` atau `4h` |
| `depths` | [5,8,12,20,34] | Zigzag depth |
| `tol_strict` | 5.0 | Toleransi strict (%) |
| `tol_loose` | 10.0 | Toleransi loose (%) |
| `max_dist` | 50.0 | Max jarak PRZ dari harga (%) |
| `prz_maxw` | **15.0** (diubah dari default Pine 6.0, lihat catatan di bawah) | Max lebar PRZ (%) |
| `tol_break` | 1.5 | Toleransi invalidasi PRZ (%) |
| `proximity_pct` | 3.0 | Ambang "mendekati" PRZ dari atas (konsep baru, lihat §4.0.1); tetap dibuat sebagai parameter yang bisa diubah-ubah, 3.0 hanya titik awal |
| `patterns_enabled` | semua 5 aktif | Bisa toggle per pattern |
| `use_abcd` | **True** | Pattern 4 titik tambahan — **diaktifkan** (berbeda dari default Pine yang OFF). Konsekuensi: jumlah kandidat pattern per saham meningkat signifikan karena AB=CD (4 titik) jauh lebih sering terbentuk dibanding XABCD (5 titik). Prioritas seleksi tetap XABCD > ABCD bila jarak ke harga mirip (lihat §5), jadi ABCD hanya "mengisi" saat XABCD tidak tersedia atau lebih jauh. |

> **Catatan perubahan dari default Pine:**
> - `prz_maxw` diubah dari 6.0% (default Pine) menjadi **15.0%**. Ini melebarkan syarat lolos filter "PRZ tidak terlalu lebar" — lebih banyak pattern akan lolos tahap ini, termasuk yang konvergensinya kurang rapat dibanding standar Pine asli.
> - Konsekuensi ikutan: karena PRZ jadi lebih lebar, ambang `proximity_pct` (2-5%) jadi jauh lebih mudah tercapai (zona buy-nya sendiri lebih gemuk), dan skor `confluence` (komponen skor kualitas) rata-rata akan lebih tinggi karena syarat kesempitan lebih longgar — **skor hasil setting ini tidak bisa dibandingkan apple-to-apple dengan skor dari setting Pine default (`prz_maxw=6`)**.
> - Ini murni perubahan nilai parameter (bukan perubahan formula), jadi tetap konsisten dengan prinsip port 1:1 di §4.0 — parameter memang didesain configurable di Pine aslinya.

---

## 8. Struktur Kode yang Disarankan

```
prz_scanner/
├── config.py           # semua parameter + watchlist LQ45
├── zigzag.py           # deteksi pivot multi-depth
├── patterns.py         # tabel rasio + deteksi XABCD/ABCD + PRZ calc + skor
├── data_fetch.py        # yfinance wrapper + fallback 4H
├── scanner.py          # loop watchlist, filter proximity, pilih best per saham
├── chart_render.py       # mplfinance chart + overlay pattern
├── main.py             # entrypoint CLI
└── output/              # hasil PNG + summary.csv / .txt
```

---

## 9. Hal yang Perlu Divalidasi Saat Implementasi (Claude Code)

1. **Interval 4H di yfinance** — konfirmasi apakah `4h` didukung native untuk `.JK`, atau perlu resample dari `1h`/`60m`. Juga cek limit history-nya (biasanya intraday yfinance dibatasi ~60 hari terakhir).
2. **Rate limit yfinance** — untuk 45 ticker, mungkin perlu `time.sleep()` antar request atau gunakan `yf.download()` batch multi-ticker sekali panggil (lebih efisien dari loop satu-satu).
3. **Ticker LQ45 list** — komposisi LQ45 berubah tiap periode (Februari & Agustus review IDX) — sebaiknya list ini bisa di-update manual di `config.py`, bukan hardcode permanen.
4. **Data kosong/delisting** — handle ticker yang gagal fetch (skip + log, jangan crash seluruh scan).
5. **Unit test kecocokan**: sebelum dipakai untuk scan LQ45, jalankan Python scanner dan Pine Script pada **saham & timeframe & tanggal yang sama**, bandingkan manual apakah PRZ range, pattern terdeteksi, dan status valid/invalid **sama persis**. Kalau beda, cari selisih logikanya sebelum lanjut — jangan asumsikan "cukup mirip".

---

## 10. Referensi Source Asli

Source lengkap Pine Script v9 ("Harmonic PRZ Scanner v9") menjadi acuan matematis wajib untuk implementasi ini — semua fungsi (`f_zz`, `f_collect`, `f_collectABCD`, `f_pickBest`, `f_select`, `f_powerNear`, `f_inRange`, `f_clamp`, `f_nearestIdx`) harus ditelusuri dan diporting sesuai §4.0.

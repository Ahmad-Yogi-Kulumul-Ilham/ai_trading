# Trading AI (Desktop)

Aplikasi desktop Python untuk riset strategi trading di **crypto, saham US, dan forex**:
backtest, optimasi parameter, paper trading (simulasi), trading uang asli di **Indodax**,
dan asisten analisis berbasis Claude.

> Secara bawaan aplikasi berjalan di **mode simulasi**. Order sungguhan hanya dikirim setelah kamu memilih
> mode "Indodax (UANG ASLI)" dan mengetik konfirmasi. AI berperan sebagai analis, bukan eksekutor.
> Hasil backtest tidak menjamin hasil masa depan.

## Fitur

- **Data pasar** dari Yahoo Finance (gratis, tanpa API key) untuk crypto (`BTC-USD`), saham US (`AAPL`), dan forex (`EURUSD=X`), serta data Rupiah langsung dari Indodax (`BTC/IDR`). Interval 1m sampai 1 minggu, dengan cache lokal.
- **Chart candlestick** interaktif (pyqtgraph) dengan overlay indikator, panel RSI/MACD/probabilitas, dan penanda entry/exit.
- **Strategi bawaan**: SMA Crossover, EMA Crossover, RSI Mean Reversion, MACD Trend, Bollinger Breakout, ML Prediksi Arah (Gradient Boosting, evaluasi out-of-sample), Buy & Hold.
- **Backtester** realistis: eksekusi di open bar berikutnya, fee, slippage, stop loss / take profit intrabar. Metrik: return, CAGR, Sharpe, Sortino, max drawdown, win rate, profit factor, dll.
- **Optimasi parameter** grid search (dibatasi 150 kombinasi, minimal 5 trade agar tidak overfit pada 1-2 trade).
- **Paper trading** otomatis: cek sinyal tiap N menit, order simulasi disimpan di SQLite, dengan stop loss, take profit, dan batas rugi harian. Juga ada beli/jual manual.
- **Trading uang asli di Indodax**: order market lewat API, batas nilai per order, konfirmasi berlapis, dan tombol STOP DARURAT.
- **Asisten AI (Claude)**: analisis kondisi pasar, evaluasi strategi, dan saran perbaikan berdasarkan data, indikator, hasil backtest, dan berita terbaru.

## Instalasi

```bash
cd trading_ai
python -m pip install -r requirements.txt
```

Butuh Python 3.10+ (diuji di Python 3.13, Windows 11).

## Menjalankan

```bash
python main.py
```

atau klik dua kali `run.bat`.

### Mengisi API key (Claude dan Indodax)

Buka menu **Pengaturan > API Key Claude & Indodax**, atau klik **Atur API Key Claude** di panel Asisten AI.
Isi key, klik tombol **Tes**, lalu **Simpan**. Key langsung berlaku tanpa membuka ulang aplikasi.

Key disimpan sebagai environment variable pengguna Windows (`ANTHROPIC_API_KEY`, `INDODAX_API_KEY`,
`INDODAX_SECRET_KEY`), bukan di folder proyek, jadi tidak ikut ter-commit. Tanpa key Claude, semua fitur
lain tetap berjalan.

## Trading uang asli di Indodax

1. **Buat API key lewat browser** di [indodax.com/trade_api](https://indodax.com/trade_api). Menu ini tidak ada di aplikasi Android.
   Centang **Aktifkan Pembacaan** dan **Aktifkan Trading Spot**. Jangan centang **Penarikan IDR & Kripto**,
   supaya dana tidak bisa ditarik walaupun key bocor. Aktifkan key lewat tautan di email.
2. **Isi key di aplikasi** lewat menu *Pengaturan > API Key Claude & Indodax*, klik **Tes Key Indodax**, lalu **Simpan**.
   Jangan bagikan key ke siapa pun.

   Key baru Indodax adalah key **Trade API 2.0** dan hanya bekerja di `api.indodax.com/api/v2`.
   Aplikasi memakai API ini langsung. Library ccxt hanya dipakai untuk data publik, karena ccxt masih memakai
   endpoint lama `/tapi` yang menolak key baru dengan error `invalid_version_key`.
3. Klik **Tes Koneksi Indodax** untuk melihat saldo Rupiah. Mode masih simulasi.
4. Pilih pasar **Crypto Indodax (IDR)**, misalnya `BTC/IDR`, lalu backtest dengan fee sekitar 0,3%.
5. Atur **Maks per order** (bawaan Rp 50.000). Minimal order Indodax sekitar Rp 10.000.
6. Pilih mode **Indodax (UANG ASLI)** dan ketik `SAYA PAHAM`. Judul jendela berubah menjadi *MODE UANG ASLI*.
7. Pakai **Beli/Jual Manual** atau **Mulai Otomatis**. Setiap order manual meminta konfirmasi.
8. **STOP DARURAT** menghentikan bot dan menawarkan untuk menjual semua posisi milik bot.

Aturan keamanan yang dipakai:

- Bot hanya menjual koin yang ia beli sendiri. Koin yang sudah kamu punya sebelumnya tidak ikut terjual.
- Setiap order beli dibatasi nilai maksimum per order dan saldo Rupiah yang tersedia.
- Harga dan jumlah terisi dihitung dari perubahan saldo, jadi fee Indodax sudah ikut terhitung.
- Order yang ditolak exchange dicatat sebagai `ERROR` di log. Bot tetap berjalan di langkah berikutnya.
- Bot hanya berjalan selama aplikasi terbuka dan laptop menyala. Stop loss dicek setiap kali bot mengecek sinyal.
- Riwayat order uang asli disimpan terpisah di `data/live_indodax.db`.

Pada uji Oktober 2026 di data BTC/IDR, semua strategi di interval 1 jam rugi besar karena fee.
Interval harian jauh lebih masuk akal untuk modal kecil.

## Alur kerja yang disarankan

1. Pilih pasar, simbol, interval, rentang data. Klik **Ambil Data & Backtest**.
2. Lihat tab **Chart**, **Equity**, **Metrik**, **Trade**. Bandingkan dengan return buy & hold.
3. Klik **Optimasi Parameter**, terapkan baris terbaik, lalu **uji ulang di rentang data lain atau simbol lain** untuk mendeteksi overfitting.
4. Tanya **Asisten AI** untuk evaluasi dan saran.
5. Jika puas, jalankan **Paper Trading otomatis** minimal beberapa minggu sebelum mempertimbangkan modal sungguhan.

## Struktur kode

```
main.py                  entry point GUI
app/config.py            pengaturan (disimpan di data/settings.json)
app/data/fetcher.py      ambil data yfinance + cache
app/data/symbols.py      preset simbol, interval, anualisasi
app/indicators.py        SMA, EMA, RSI, MACD, Bollinger, ATR, fitur ML
app/strategies/          strategi (classic.py, ml.py), registry di __init__.py
app/backtest/engine.py   backtester event-based
app/backtest/metrics.py  metrik performa
app/backtest/optimizer.py grid search
app/paper/broker.py      broker simulasi (SQLite: data/paper.db)
app/paper/trader.py      loop trading + manajemen risiko (dipakai simulasi dan uang asli)
app/live/indodax_broker.py broker Indodax uang asli (SQLite: data/live_indodax.db)
app/live/indodax_v2.py   klien Indodax Trade API 2.0 (saldo dan order)
app/secrets_store.py     simpan dan tes API key (environment Windows)
app/ai/advisor.py        integrasi Claude (Anthropic SDK)
app/ui/                  PySide6 GUI (main_window.py, chart.py, workers.py)
tests/                   pytest (tanpa koneksi internet, broker Indodax diuji dengan exchange palsu)
tests/gui_smoke.py       smoke test GUI (butuh internet)
tests/gui_live_smoke.py  smoke test mode uang asli dengan exchange palsu
tests/gui_keys_smoke.py  smoke test dialog API key (offline)
```

## Menambah strategi sendiri

Buat kelas turunan `Strategy` di `app/strategies/`, isi `name`, `description`, `params`, dan
`generate_signals(df)` yang mengembalikan Series 0/1 (flat/long). Daftarkan di `app/strategies/__init__.py`.
Sinyal dihitung dari close bar saat ini dan dieksekusi di open bar berikutnya, jadi jangan memakai data masa depan.

## Menjalankan tes

```bash
python -m pytest -q
```

## Jika scikit-learn diblokir Windows Smart App Control

Di beberapa PC Windows 11, Smart App Control memblokir DLL scikit-learn dengan pesan
`An Application Control policy has blocked this file`. Aplikasi tetap berjalan: strategi ML otomatis
memakai regresi logistik numpy (terlihat di baris `ML: backend` pada tab Metrik). Jika ingin memakai
Gradient Boosting, matikan Smart App Control di *Windows Security > App & browser control > Smart App Control*
(perubahan ini tidak bisa dibatalkan tanpa instal ulang Windows), atau jalankan aplikasi dari lingkungan lain
seperti WSL / Docker.

## Catatan & batasan

- Data Yahoo Finance bisa tertunda ~15 menit untuk saham dan punya batas riwayat untuk interval kecil (1m hanya 7 hari).
- Backtester long-only. Short selling belum didukung.
- Paper trading memakai harga terakhir dari Yahoo, bukan order book sungguhan; slippage disimulasikan dengan persentase tetap.
- Trading uang asli baru tersedia untuk Indodax dan hanya posisi beli (long). Exchange lain bisa ditambahkan dengan broker baru berantarmuka sama seperti `PaperBroker`.

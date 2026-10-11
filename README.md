# Trading AI (Desktop)

Aplikasi desktop Python untuk riset strategi trading di **crypto, saham US, dan forex**:
backtest, optimasi parameter, paper trading (simulasi), dan asisten analisis berbasis Claude.

> Aplikasi ini **tidak** mengirim order ke exchange/broker sungguhan. Semua eksekusi adalah simulasi (paper trading).
> AI berperan sebagai analis, bukan eksekutor. Hasil backtest tidak menjamin hasil masa depan.

## Fitur

- **Data pasar** dari Yahoo Finance (gratis, tanpa API key) untuk crypto (`BTC-USD`), saham US (`AAPL`), dan forex (`EURUSD=X`). Interval 1m sampai 1 minggu, dengan cache lokal.
- **Chart candlestick** interaktif (pyqtgraph) dengan overlay indikator, panel RSI/MACD/probabilitas, dan penanda entry/exit.
- **Strategi bawaan**: SMA Crossover, EMA Crossover, RSI Mean Reversion, MACD Trend, Bollinger Breakout, ML Prediksi Arah (Gradient Boosting, evaluasi out-of-sample), Buy & Hold.
- **Backtester** realistis: eksekusi di open bar berikutnya, fee, slippage, stop loss / take profit intrabar. Metrik: return, CAGR, Sharpe, Sortino, max drawdown, win rate, profit factor, dll.
- **Optimasi parameter** grid search (dibatasi 150 kombinasi, minimal 5 trade agar tidak overfit pada 1-2 trade).
- **Paper trading** otomatis: cek sinyal tiap N menit, order simulasi disimpan di SQLite, dengan stop loss, take profit, dan batas rugi harian. Juga ada beli/jual manual.
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

### Mengaktifkan asisten AI (opsional)

Set API key Anthropic sebagai environment variable sebelum membuka aplikasi:

```powershell
setx ANTHROPIC_API_KEY "sk-ant-..."
```

Tutup dan buka ulang terminal/aplikasi setelah `setx`. Tanpa key, semua fitur lain tetap berjalan.

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
app/paper/trader.py      loop paper trading + manajemen risiko
app/ai/advisor.py        integrasi Claude (Anthropic SDK)
app/ui/                  PySide6 GUI (main_window.py, chart.py, workers.py)
tests/                   pytest (tanpa koneksi internet)
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
- Untuk koneksi ke exchange sungguhan di masa depan (misal Binance via `ccxt` atau Alpaca untuk saham US), tambahkan implementasi broker baru dengan antarmuka yang sama seperti `PaperBroker`.

"""Smoke test GUI end-to-end (butuh internet). Jalankan manual:

    set QT_QPA_PLATFORM=offscreen
    python -m tests.gui_smoke

Langkah dijalankan lewat QTimer di dalam app.exec(). Jangan memakai loop QTest.qWait() untuk menunggu
worker: itu menahan GIL dan membuat thread worker Python tampak macet.
"""
from __future__ import annotations

import logging
import pathlib
import sys
import tempfile
import time

from PySide6 import QtCore, QtWidgets

import app.config as cfg
from app.paper.broker import PaperBroker
from app.ui import main_window as mw


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    db = pathlib.Path(tempfile.mkdtemp()) / "paper.db"
    mw.PaperBroker = lambda **kw: PaperBroker(db, **kw)
    errors: list[str] = []
    QtWidgets.QMessageBox.critical = staticmethod(lambda *a, **k: errors.append(a[2][:300]) or print("CRITICAL:", a[2][:300]))
    QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: print("WARNING:", a[2][:200]))
    QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: print("INFO:", a[2][:200]))
    QtWidgets.QMessageBox.question = staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Yes)
    # jangan menimpa settings pengguna
    cfg.Settings.save = lambda self: None

    app = QtWidgets.QApplication(sys.argv)
    w = mw.MainWindow()
    w.show()

    def setup(market, symbol, interval, period, strategy):
        def _():
            w.cb_market.setCurrentText(market); w.cb_symbol.setCurrentText(symbol)
            w.cb_interval.setCurrentText(interval); w.cb_period.setCurrentText(period)
            w.cb_strategy.setCurrentText(strategy)
        return _

    def report(label, fn):
        def _():
            print(f"  {label}: {fn()}", flush=True)
        return _

    steps = [
        ("Crypto BTC-USD 1h 3mo SMA", setup("Crypto", "BTC-USD", "1h", "3mo", "SMA Crossover")),
        ("backtest", w.run_backtest),
        ("cek", report("bar/trade/metrik/overlay/marker", lambda: (len(w.df), w.tbl_trades.rowCount(), w.tbl_metrics.rowCount(), len(w.chart._overlay_items), len(w.chart._trade_items)))),
        ("optimasi", w.run_optimize),
        ("cek", report("baris optimasi", lambda: w.tbl_optim.rowCount())),
        ("terapkan baris terbaik", lambda: (w.tbl_optim.selectRow(0), w.apply_optim_row())),
        ("cek", report("parameter baru", w._read_params)),
        ("paper step", w.run_paper_step),
        ("cek", report("log paper", lambda: w.txt_paper_log.toPlainText().splitlines()[-1][-120:])),
        ("beli manual", lambda: w.manual_order("BUY")),
        ("cek", report("posisi/order", lambda: (w.tbl_positions.rowCount(), w.tbl_orders.rowCount()))),
        ("jual manual", lambda: w.manual_order("SELL")),
        ("cek", report("posisi/order", lambda: (w.tbl_positions.rowCount(), w.tbl_orders.rowCount()))),
        ("reset", w.reset_paper),
        ("Saham AAPL 1d 5y ML", setup("Saham US", "AAPL", "1d", "5y", "ML Prediksi Arah")),
        ("backtest ML", w.run_backtest),
        ("cek", report("ML backend/akurasi", lambda: [(w.tbl_metrics.item(r, 0).text(), w.tbl_metrics.item(r, 1).text()) for r in range(w.tbl_metrics.rowCount()) if w.tbl_metrics.item(r, 0).text().startswith("ML: ") and "feature" not in w.tbl_metrics.item(r, 0).text()])),
        ("optimasi ML", w.run_optimize),
        ("cek", report("baris optimasi ML", lambda: w.tbl_optim.rowCount())),
        ("Forex EURUSD 1h 1mo MACD", setup("Forex", "EURUSD=X", "1h", "1mo", "MACD Trend")),
        ("backtest forex", w.run_backtest),
        ("cek", report("trade/panel", lambda: (w.tbl_trades.rowCount(), len(w.chart._panel_items)))),
        ("tanya AI", w.ask_ai),
    ]
    state = {"i": 0, "t": time.time()}

    def tick():
        if any(x.isRunning() for x in w._workers):
            if time.time() - state["t"] > 180:
                print("TIMEOUT pada langkah", steps[state["i"] - 1][0]); errors.append("timeout"); app.quit()
            return
        if state["i"] >= len(steps):
            timer.stop(); w.close(); app.quit(); return
        name, fn = steps[state["i"]]
        state["i"] += 1
        if name != "cek":
            print(f"[{time.time() - t0:5.1f}s] {name}", flush=True)
        state["t"] = time.time()
        fn()

    t0 = time.time()
    timer = QtCore.QTimer()
    timer.timeout.connect(tick)
    timer.start(150)
    app.exec()
    print("HASIL:", "GAGAL" if errors else "OK", errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

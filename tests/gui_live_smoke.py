"""Smoke test GUI mode uang asli memakai exchange PALSU (tidak ada order sungguhan). Butuh internet untuk data harga.

    set QT_QPA_PLATFORM=offscreen
    python -m tests.gui_live_smoke
"""
from __future__ import annotations

import logging
import os
import pathlib
import sys
import tempfile
import time

from PySide6 import QtCore, QtWidgets

import app.config as cfg
from app.live import indodax_broker as ib
from app.paper.broker import PaperBroker
from app.ui import main_window as mw
from tests.test_indodax_broker import FakeIndodax


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    tmp = pathlib.Path(tempfile.mkdtemp())
    fake = FakeIndodax(idr=98_335.0)
    mw.PaperBroker = lambda **kw: PaperBroker(tmp / "paper.db", **kw)
    mw.IndodaxBroker = lambda key, secret, **kw: ib.IndodaxBroker(key, secret, db_path=tmp / "live.db",
                                                                  exchange=fake, fill_timeout_s=0, **kw)
    cfg.Settings.save = lambda self: None
    errors: list[str] = []
    answers = {"confirm_text": "SAYA PAHAM"}
    QtWidgets.QMessageBox.critical = staticmethod(lambda *a, **k: errors.append(a[2][:300]) or print("CRITICAL:", a[2][:300]))
    QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: print("  WARNING:", a[2].splitlines()[0][:150]))
    QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: print("  INFO:", a[2].splitlines()[0][:150]))
    QtWidgets.QMessageBox.question = staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Yes)
    QtWidgets.QInputDialog.getText = staticmethod(lambda *a, **k: (answers["confirm_text"], True))

    app = QtWidgets.QApplication(sys.argv)
    w = mw.MainWindow()
    w.show()
    checks: list[tuple[str, bool]] = []

    def check(label, cond_fn):
        def _():
            ok = bool(cond_fn())
            checks.append((label, ok))
            print(f"  {'OK ' if ok else 'GAGAL'} {label}", flush=True)
        return _

    def choose_live():
        w.cb_exec_mode.setCurrentIndex(1)
        w._on_exec_mode_changed(1)

    def no_env():
        os.environ.pop(ib.ENV_KEY, None); os.environ.pop(ib.ENV_SECRET, None)

    def set_env():
        os.environ[ib.ENV_KEY] = "kunci-palsu"; os.environ[ib.ENV_SECRET] = "secret-palsu"

    def wrong_text():
        answers["confirm_text"] = "ya"

    def right_text():
        answers["confirm_text"] = "SAYA PAHAM"

    def select_idr():
        w.cb_market.setCurrentText("Crypto Indodax (IDR)")
        w.cb_symbol.setCurrentText("BTC/IDR"); w.cb_interval.setCurrentText("1h"); w.cb_period.setCurrentText("3mo")
        w.cb_strategy.setCurrentText("SMA Crossover")

    def select_usd():
        w.cb_market.setCurrentText("Crypto"); w.cb_symbol.setCurrentText("BTC-USD")

    steps = [
        ("pilih BTC/IDR dari Indodax", select_idr),
        ("backtest data Indodax", w.run_backtest),
        ("cek", check("backtest memakai data Rupiah", lambda: w.df is not None and w.df["close"].iloc[-1] > 1e8)),
        ("tanpa API key, aktifkan mode asli", lambda: (no_env(), choose_live())),
        ("cek", check("tanpa key tetap simulasi", lambda: not w.exec_live and w.cb_exec_mode.currentIndex() == 0)),
        ("salah ketik konfirmasi", lambda: (set_env(), wrong_text(), choose_live())),
        ("cek", check("konfirmasi salah tetap simulasi", lambda: not w.exec_live)),
        ("tes koneksi", lambda: (right_text(), w.test_connection())),
        ("cek", check("tes koneksi tidak mengaktifkan uang asli", lambda: w.live_broker is not None and not w.exec_live)),
        ("aktifkan mode asli", choose_live),
        ("cek", check("mode uang asli aktif", lambda: w.exec_live and "UANG ASLI" in w.windowTitle())),
        ("cek", check("saldo Rupiah tampil", lambda: "98,335" in w.lbl_live_status.text())),
        ("pilih simbol USD saat mode asli", select_usd),
        ("beli manual di simbol USD", lambda: w.manual_order("BUY")),
        ("cek", check("order USD ditolak", lambda: fake.orders == [])),
        ("pilih BTC/IDR lagi", select_idr),
        ("beli manual", lambda: w.manual_order("BUY")),
        ("cek", check("order beli dibatasi Rp 50.000", lambda: len(fake.orders) == 1 and fake.orders[0][2]["cost"] == 50_000)),
        ("cek", check("posisi bot tercatat", lambda: w.tbl_positions.rowCount() == 1)),
        ("reset akun saat mode asli", w.reset_paper),
        ("cek", check("reset tidak menghapus riwayat asli", lambda: w.tbl_orders.rowCount() == 1)),
        ("satu langkah bot", w.run_paper_step),
        ("cek", check("langkah bot tercatat di log", lambda: "[ASLI]" in w.txt_paper_log.toPlainText())),
        ("mulai otomatis", w.toggle_paper_auto),
        ("cek", check("timer otomatis jalan", lambda: w.paper_timer.isActive())),
        ("STOP DARURAT", w.emergency_stop),
        ("cek", check("timer berhenti", lambda: not w.paper_timer.isActive())),
        ("cek", check("posisi bot terjual", lambda: w.live_broker.positions() == [] and fake.orders[-1][0] == "sell")),
        ("kembali ke simulasi", lambda: (w.cb_exec_mode.setCurrentIndex(0), w._on_exec_mode_changed(0))),
        ("cek", check("mode simulasi lagi", lambda: not w.exec_live and "UANG ASLI" not in w.windowTitle())),
    ]
    state = {"i": 0, "t": time.time()}
    t0 = time.time()

    def tick():
        if any(x.isRunning() for x in w._workers):
            if time.time() - state["t"] > 180:
                errors.append("timeout"); app.quit()
            return
        if state["i"] >= len(steps):
            timer.stop(); w.close(); app.quit(); return
        name, fn = steps[state["i"]]
        state["i"] += 1
        if name != "cek":
            print(f"[{time.time() - t0:5.1f}s] {name}", flush=True)
        state["t"] = time.time()
        fn()

    timer = QtCore.QTimer()
    timer.timeout.connect(tick)
    timer.start(150)
    app.exec()
    failed = [c for c, ok in checks if not ok]
    print("HASIL:", "GAGAL" if (failed or errors) else "OK", failed, errors, "| order palsu:", len(fake.orders))
    return 1 if failed or errors else 0


if __name__ == "__main__":
    sys.exit(main())

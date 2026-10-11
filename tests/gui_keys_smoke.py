"""Smoke test dialog API key (offline). Registry Windows dan API sungguhan tidak dipakai.

    set QT_QPA_PLATFORM=offscreen
    python -m tests.gui_keys_smoke
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

from PySide6 import QtCore, QtWidgets

import app.config as cfg
from app import secrets_store as ss
from app.paper.broker import PaperBroker
from app.ui import api_keys_dialog as akd
from app.ui import main_window as mw


def main() -> int:
    for k in (ss.CLAUDE_KEY, ss.INDODAX_KEY, ss.INDODAX_SECRET):
        os.environ.pop(k, None)
    saved: dict[str, str] = {}

    def fake_save(name, value):
        saved[name] = value
        if value:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)

    ss.save = fake_save
    ss.test_claude = lambda key: "Key Claude valid. Model tersedia: claude-opus-5-5" if key.startswith("sk-ant-") else (_ for _ in ()).throw(RuntimeError("API key Claude ditolak."))
    tmp = pathlib.Path(tempfile.mkdtemp())
    mw.PaperBroker = lambda **kw: PaperBroker(tmp / "paper.db", **kw)
    cfg.Settings.save = lambda self: None
    QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: None)

    app = QtWidgets.QApplication(sys.argv)
    w = mw.MainWindow()
    w.show()
    results: list[tuple[str, bool]] = []

    def check(label, ok):
        results.append((label, bool(ok)))
        print(f"  {'OK ' if ok else 'GAGAL'} {label}", flush=True)

    check("menu Pengaturan ada", any(a.text() == "Pengaturan" for a in w.menuBar().actions()))
    check("status awal: key Claude belum diisi", "belum diisi" in w.lbl_ai_status.text())

    dlg = akd.ApiKeysDialog(w, focus="claude")
    dlg.show()
    check("kolom key tersembunyi", dlg.claude.edit.echoMode() == QtWidgets.QLineEdit.Password)
    dlg.claude.btn_show.setChecked(True)
    check("tombol tampilkan bekerja", dlg.claude.edit.echoMode() == QtWidgets.QLineEdit.Normal)

    state = {"step": 0}

    def wait_worker(next_fn):
        def poll():
            if dlg._worker is not None and dlg._worker.isRunning():
                QtCore.QTimer.singleShot(50, poll)
            else:
                QtCore.QTimer.singleShot(100, next_fn)
        QtCore.QTimer.singleShot(50, poll)

    def step_bad_key():
        dlg.claude.edit.setText("kunci-salah")
        dlg.test_claude()
        wait_worker(step_good_key)

    def step_good_key():
        check("key salah ditandai gagal", "ditolak" in dlg.lbl_status.text())
        dlg.claude.edit.setText("sk-ant-api03-contoh-1234")
        dlg.test_claude()
        wait_worker(step_save)

    def step_save():
        check("key benar ditandai valid", "valid" in dlg.lbl_status.text())
        dlg.save()
        check("hanya key Claude yang disimpan", saved == {ss.CLAUDE_KEY: "sk-ant-api03-contoh-1234"})
        check("key langsung aktif di proses", os.environ.get(ss.CLAUDE_KEY) == "sk-ant-api03-contoh-1234")

        class Accepting:
            def __init__(self, parent=None, focus="claude"):
                self.changed = {ss.CLAUDE_KEY}

            def exec(self):
                return QtWidgets.QDialog.Accepted

        mw.ApiKeysDialog = Accepting
        w.open_api_keys("claude")
        check("status AI diperbarui dengan key tersamar", "sk-a...1234" in w.lbl_ai_status.text())
        w.close()
        app.quit()

    QtCore.QTimer.singleShot(100, step_bad_key)
    app.exec()
    failed = [l for l, ok in results if not ok]
    print("HASIL:", "GAGAL" if failed else "OK", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

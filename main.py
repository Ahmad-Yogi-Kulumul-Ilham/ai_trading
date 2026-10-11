"""Entry point aplikasi desktop Trading AI.

Jalankan:  python main.py
"""
from __future__ import annotations

import logging
import sys


def _apply_dark_palette(app) -> None:
    """Tema gelap sederhana agar serasi dengan chart."""
    from PySide6 import QtGui
    from PySide6.QtGui import QPalette

    p = QPalette()
    bg, base, text, hl = QtGui.QColor("#1e2227"), QtGui.QColor("#161a1f"), QtGui.QColor("#e6edf3"), QtGui.QColor("#2f81f7")
    p.setColor(QPalette.Window, bg)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, bg)
    p.setColor(QPalette.ToolTipBase, base)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, bg)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.Highlight, hl)
    p.setColor(QPalette.HighlightedText, QtGui.QColor("#ffffff"))
    p.setColor(QPalette.Disabled, QPalette.Text, QtGui.QColor("#6e7681"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QtGui.QColor("#6e7681"))
    app.setPalette(p)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from PySide6 import QtWidgets
    from app.ui.main_window import MainWindow

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Trading AI")
    app.setStyle("Fusion")
    _apply_dark_palette(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

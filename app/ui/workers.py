"""Worker thread generik supaya GUI tidak membeku saat fetch data / backtest / panggil API."""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6 import QtCore


class Worker(QtCore.QThread):
    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    progress = QtCore.Signal(int, int)

    def __init__(self, fn: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{exc}\n\n{traceback.format_exc(limit=3)}")
            return
        self.done.emit(result)

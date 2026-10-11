"""Dialog pengaturan API key Claude dan Indodax."""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app import secrets_store as ss
from app.ui.workers import Worker


class _KeyField(QtWidgets.QWidget):
    """Kolom isian key yang tersembunyi, dengan tombol tampilkan."""

    def __init__(self, env_name: str, placeholder: str, parent=None):
        super().__init__(parent)
        self.env_name = env_name
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QtWidgets.QLineEdit()
        self.edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setText(ss.get(env_name))
        self.btn_show = QtWidgets.QToolButton()
        self.btn_show.setText("Tampilkan")
        self.btn_show.setCheckable(True)
        self.btn_show.toggled.connect(
            lambda on: (self.edit.setEchoMode(QtWidgets.QLineEdit.Normal if on else QtWidgets.QLineEdit.Password),
                        self.btn_show.setText("Sembunyikan" if on else "Tampilkan")))
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.btn_show)

    def value(self) -> str:
        return self.edit.text().strip()


class ApiKeysDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, focus: str = "claude"):
        super().__init__(parent)
        self.setWindowTitle("Pengaturan API Key")
        self.setMinimumWidth(560)
        self.changed: set[str] = set()
        self._worker: Worker | None = None
        root = QtWidgets.QVBoxLayout(self)

        # ---- Claude
        g = QtWidgets.QGroupBox("Claude (Asisten AI)")
        f = QtWidgets.QFormLayout(g)
        self.claude = _KeyField(ss.CLAUDE_KEY, "sk-ant-...")
        info = QtWidgets.QLabel('Buat key di <a href="https://console.anthropic.com/settings/keys">console.anthropic.com</a>. '
                                "Pemakaian Claude ditagih ke akun Anthropic-mu.")
        info.setOpenExternalLinks(True); info.setWordWrap(True)
        self.btn_test_claude = QtWidgets.QPushButton("Tes Key Claude")
        f.addRow("API key", self.claude)
        f.addRow(info)
        f.addRow(self.btn_test_claude)
        root.addWidget(g)

        # ---- Indodax
        g = QtWidgets.QGroupBox("Indodax (trading uang asli)")
        f = QtWidgets.QFormLayout(g)
        self.idx_key = _KeyField(ss.INDODAX_KEY, "API key Trade API 2.0")
        self.idx_secret = _KeyField(ss.INDODAX_SECRET, "Secret key")
        info2 = QtWidgets.QLabel('Buat key di <a href="https://indodax.com/trade_api">indodax.com/trade_api</a> lewat browser. '
                                 "Centang Pembacaan dan Trading Spot saja, jangan centang Penarikan.")
        info2.setOpenExternalLinks(True); info2.setWordWrap(True)
        self.btn_test_idx = QtWidgets.QPushButton("Tes Key Indodax (baca saldo saja)")
        f.addRow("API key", self.idx_key)
        f.addRow("Secret key", self.idx_secret)
        f.addRow(info2)
        f.addRow(self.btn_test_idx)
        root.addWidget(g)

        self.lbl_status = QtWidgets.QLabel("Key disimpan di environment Windows milik akunmu, bukan di folder proyek.")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color: #8b949e;")
        root.addWidget(self.lbl_status)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Save).setText("Simpan")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("Batal")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.btn_test_claude.clicked.connect(self.test_claude)
        self.btn_test_idx.clicked.connect(self.test_indodax)
        (self.idx_key if focus == "indodax" else self.claude).edit.setFocus()

    # ---------------------------------------------------------------- aksi
    def _run(self, fn, *args):
        if self._worker is not None and self._worker.isRunning():
            return
        self.lbl_status.setStyleSheet("color: #8b949e;")
        self.lbl_status.setText("Mengecek...")
        for b in (self.btn_test_claude, self.btn_test_idx):
            b.setEnabled(False)
        w = Worker(fn, *args)
        w.done.connect(lambda msg: self._show(msg, ok=True))
        w.failed.connect(lambda msg: self._show(msg.strip().split("\n\n")[0], ok=False))
        w.finished.connect(lambda: [b.setEnabled(True) for b in (self.btn_test_claude, self.btn_test_idx)])
        self._worker = w
        w.start()

    def _show(self, msg: str, ok: bool):
        self.lbl_status.setStyleSheet("color: #26a69a;" if ok else "color: #ef5350;")
        self.lbl_status.setText(msg)

    def test_claude(self):
        if not self.claude.value():
            self._show("Isi API key Claude dulu.", ok=False)
            return
        self._run(ss.test_claude, self.claude.value())

    def test_indodax(self):
        if not (self.idx_key.value() and self.idx_secret.value()):
            self._show("Isi API key dan secret key Indodax dulu.", ok=False)
            return
        self._run(ss.test_indodax, self.idx_key.value(), self.idx_secret.value())

    def save(self):
        for field in (self.claude, self.idx_key, self.idx_secret):
            if field.value() != ss.get(field.env_name):
                ss.save(field.env_name, field.value())
                self.changed.add(field.env_name)
        self.accept()

    def done(self, result):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(25_000)
        super().done(result)

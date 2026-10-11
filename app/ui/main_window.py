"""Jendela utama aplikasi Trading AI."""
from __future__ import annotations

import html
import logging
from datetime import datetime

import pandas as pd
from PySide6 import QtCore, QtGui, QtWidgets

from app.ai.advisor import MarketAdvisor, build_context, credentials_available
from app.backtest.engine import BacktestConfig, BacktestResult, run_backtest
from app.backtest.metrics import metrics_table
from app.backtest.optimizer import optimize
from app.config import RiskSettings, Settings
from app.data.fetcher import fetch_ohlcv, latest_price, recent_news
from app.data.symbols import INTERVAL_PERIODS, MARKETS, bars_per_year, market_of
from app.paper.broker import PaperBroker
from app.paper.trader import PaperTrader
from app.strategies import STRATEGIES, make_strategy
from app.strategies.base import Strategy
from app.ui.chart import ChartWidget, EquityWidget
from app.ui.workers import Worker

log = logging.getLogger(__name__)

AI_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]
EFFORTS = ["low", "medium", "high"]


def _table(headers: list[str]) -> QtWidgets.QTableWidget:
    t = QtWidgets.QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setStretchLastSection(True)
    t.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
    t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    t.setAlternatingRowColors(True)
    return t


def _fill(table: QtWidgets.QTableWidget, rows: list[list]) -> None:
    table.setRowCount(0)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            item = QtWidgets.QTableWidgetItem(str(val))
            if isinstance(val, (int, float)):
                item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            table.setItem(r, c, item)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trading AI - Backtest, Paper Trading & Asisten AI")
        self.resize(1480, 900)

        self.settings = Settings.load()
        self.broker = PaperBroker(initial_cash=self.settings.initial_cash,
                                  fee_pct=self.settings.risk.fee_pct, slippage_pct=self.settings.risk.slippage_pct)
        self.df: pd.DataFrame | None = None
        self.result: BacktestResult | None = None
        self.strategy: Strategy | None = None
        self.optim_table: pd.DataFrame | None = None
        self.ai_history: list[dict] = []
        self.ai_chat_md: list[str] = []
        self._workers: list[Worker] = []
        self._param_widgets: dict[str, QtWidgets.QWidget] = {}

        self.paper_timer = QtCore.QTimer(self)
        self.paper_timer.timeout.connect(self.run_paper_step)

        self._build_ui()
        self._restore_settings()
        self.refresh_paper_tables()
        self.log("Aplikasi siap. Pilih pasar, simbol, strategi, lalu klik 'Ambil Data & Backtest'.")

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)

        # ---------- panel kiri ----------
        left_container = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(left_container)
        left.setContentsMargins(4, 4, 4, 4)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left_container)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(400)
        root.addWidget(scroll)

        # Pasar & data
        g = QtWidgets.QGroupBox("1. Pasar & Data")
        f = QtWidgets.QFormLayout(g)
        self.cb_market = QtWidgets.QComboBox(); self.cb_market.addItems(list(MARKETS))
        self.cb_symbol = QtWidgets.QComboBox(); self.cb_symbol.setEditable(True)
        self.cb_interval = QtWidgets.QComboBox(); self.cb_interval.addItems(list(INTERVAL_PERIODS))
        self.cb_period = QtWidgets.QComboBox()
        self.btn_backtest = QtWidgets.QPushButton("Ambil Data & Backtest")
        self.btn_backtest.setStyleSheet("font-weight: bold; padding: 6px;")
        f.addRow("Pasar", self.cb_market)
        f.addRow("Simbol", self.cb_symbol)
        f.addRow("Interval", self.cb_interval)
        f.addRow("Rentang", self.cb_period)
        f.addRow(self.btn_backtest)
        left.addWidget(g)

        # Strategi
        g = QtWidgets.QGroupBox("2. Strategi")
        v = QtWidgets.QVBoxLayout(g)
        self.cb_strategy = QtWidgets.QComboBox(); self.cb_strategy.addItems(list(STRATEGIES))
        self.lbl_strategy_desc = QtWidgets.QLabel(); self.lbl_strategy_desc.setWordWrap(True)
        self.lbl_strategy_desc.setStyleSheet("color: #8b949e;")
        self.params_form = QtWidgets.QFormLayout()
        self.btn_optimize = QtWidgets.QPushButton("Optimasi Parameter (grid search)")
        v.addWidget(self.cb_strategy); v.addWidget(self.lbl_strategy_desc)
        v.addLayout(self.params_form); v.addWidget(self.btn_optimize)
        left.addWidget(g)

        # Modal & risiko
        g = QtWidgets.QGroupBox("3. Modal & Manajemen Risiko")
        f = QtWidgets.QFormLayout(g)
        self.sp_cash = self._dspin(100, 1e9, 1000, 2, " USD")
        self.sp_fee = self._dspin(0, 5, 0.01, 3, " %")
        self.sp_slip = self._dspin(0, 5, 0.01, 3, " %")
        self.sp_pos = self._dspin(1, 100, 5, 0, " %")
        self.sp_sl = self._dspin(0, 50, 0.5, 2, " %")
        self.sp_tp = self._dspin(0, 200, 0.5, 2, " %")
        self.sp_daily = self._dspin(0, 50, 0.5, 2, " %")
        f.addRow("Modal awal", self.sp_cash)
        f.addRow("Fee per transaksi", self.sp_fee)
        f.addRow("Slippage", self.sp_slip)
        f.addRow("Porsi modal per posisi", self.sp_pos)
        f.addRow("Stop loss (0 = off)", self.sp_sl)
        f.addRow("Take profit (0 = off)", self.sp_tp)
        f.addRow("Batas rugi harian (paper)", self.sp_daily)
        left.addWidget(g)

        # Paper trading
        g = QtWidgets.QGroupBox("4. Paper Trading (simulasi)")
        f = QtWidgets.QFormLayout(g)
        self.sp_paper_min = QtWidgets.QSpinBox(); self.sp_paper_min.setRange(1, 1440); self.sp_paper_min.setSuffix(" menit")
        self.btn_paper_auto = QtWidgets.QPushButton("Mulai Otomatis")
        self.btn_paper_step = QtWidgets.QPushButton("Jalankan 1 Langkah Sekarang")
        hb = QtWidgets.QHBoxLayout()
        self.btn_buy = QtWidgets.QPushButton("Beli Manual"); self.btn_sell = QtWidgets.QPushButton("Jual Manual")
        hb.addWidget(self.btn_buy); hb.addWidget(self.btn_sell)
        self.btn_reset = QtWidgets.QPushButton("Reset Akun Paper")
        f.addRow("Cek sinyal setiap", self.sp_paper_min)
        f.addRow(self.btn_paper_auto)
        f.addRow(self.btn_paper_step)
        f.addRow(hb)
        f.addRow(self.btn_reset)
        left.addWidget(g)

        # AI
        g = QtWidgets.QGroupBox("5. Asisten AI (Claude)")
        f = QtWidgets.QFormLayout(g)
        self.cb_ai_model = QtWidgets.QComboBox(); self.cb_ai_model.addItems(AI_MODELS)
        self.cb_ai_effort = QtWidgets.QComboBox(); self.cb_ai_effort.addItems(EFFORTS)
        self.ed_question = QtWidgets.QLineEdit()
        self.ed_question.setPlaceholderText("Mis: Apakah strategi ini layak untuk pasar saat ini?")
        self.btn_ask = QtWidgets.QPushButton("Tanya AI")
        self.lbl_ai_status = QtWidgets.QLabel(); self.lbl_ai_status.setWordWrap(True)
        self.lbl_ai_status.setStyleSheet("color: #8b949e;")
        f.addRow("Model", self.cb_ai_model)
        f.addRow("Effort", self.cb_ai_effort)
        f.addRow("Pertanyaan", self.ed_question)
        f.addRow(self.btn_ask)
        f.addRow(self.lbl_ai_status)
        left.addWidget(g)
        left.addStretch(1)

        # ---------- tab kanan ----------
        self.tabs = QtWidgets.QTabWidget()
        root.addWidget(self.tabs, 1)

        self.chart = ChartWidget()
        self.tabs.addTab(self.chart, "Chart")

        self.equity_widget = EquityWidget()
        self.tabs.addTab(self.equity_widget, "Equity")

        self.tbl_metrics = _table(["Metrik", "Nilai"])
        self.tabs.addTab(self.tbl_metrics, "Metrik")

        self.tbl_trades = _table(["Masuk", "Keluar", "Harga masuk", "Harga keluar", "Qty", "PnL", "PnL %", "Bar", "Alasan"])
        self.tabs.addTab(self.tbl_trades, "Trade")

        optim_w = QtWidgets.QWidget(); ov = QtWidgets.QVBoxLayout(optim_w)
        self.lbl_optim = QtWidgets.QLabel("Belum ada hasil optimasi. Jalankan backtest dulu, lalu klik 'Optimasi Parameter'.")
        self.tbl_optim = _table(["-"])
        self.btn_apply_optim = QtWidgets.QPushButton("Terapkan parameter baris terpilih & backtest ulang")
        ov.addWidget(self.lbl_optim); ov.addWidget(self.tbl_optim); ov.addWidget(self.btn_apply_optim)
        self.tabs.addTab(optim_w, "Optimasi")

        paper_w = QtWidgets.QWidget(); pv = QtWidgets.QVBoxLayout(paper_w)
        self.lbl_paper_summary = QtWidgets.QLabel(); self.lbl_paper_summary.setStyleSheet("font-size: 11pt;")
        pv.addWidget(self.lbl_paper_summary)
        pv.addWidget(QtWidgets.QLabel("Posisi terbuka"))
        self.tbl_positions = _table(["Simbol", "Qty", "Harga rata-rata", "Dibuka"])
        self.tbl_positions.setMaximumHeight(140)
        pv.addWidget(self.tbl_positions)
        pv.addWidget(QtWidgets.QLabel("Riwayat order"))
        self.tbl_orders = _table(["Waktu (UTC)", "Simbol", "Sisi", "Qty", "Harga", "Fee", "PnL", "Catatan"])
        pv.addWidget(self.tbl_orders)
        pv.addWidget(QtWidgets.QLabel("Log paper trading"))
        self.txt_paper_log = QtWidgets.QPlainTextEdit(); self.txt_paper_log.setReadOnly(True)
        self.txt_paper_log.setMaximumHeight(160)
        pv.addWidget(self.txt_paper_log)
        self.tabs.addTab(paper_w, "Paper Trading")

        self.txt_ai = QtWidgets.QTextBrowser()
        self.txt_ai.setOpenExternalLinks(True)
        self.tabs.addTab(self.txt_ai, "Asisten AI")

        self.txt_log = QtWidgets.QPlainTextEdit(); self.txt_log.setReadOnly(True)
        self.tabs.addTab(self.txt_log, "Log")

        self.status = self.statusBar()
        self.progress = QtWidgets.QProgressBar(); self.progress.setMaximumWidth(220); self.progress.hide()
        self.status.addPermanentWidget(self.progress)

        # ---------- sinyal ----------
        self.cb_market.currentTextChanged.connect(self._on_market_changed)
        self.cb_interval.currentTextChanged.connect(self._on_interval_changed)
        self.cb_strategy.currentTextChanged.connect(self._on_strategy_changed)
        self.btn_backtest.clicked.connect(self.run_backtest)
        self.btn_optimize.clicked.connect(self.run_optimize)
        self.btn_apply_optim.clicked.connect(self.apply_optim_row)
        self.btn_paper_auto.clicked.connect(self.toggle_paper_auto)
        self.btn_paper_step.clicked.connect(self.run_paper_step)
        self.btn_buy.clicked.connect(lambda: self.manual_order("BUY"))
        self.btn_sell.clicked.connect(lambda: self.manual_order("SELL"))
        self.btn_reset.clicked.connect(self.reset_paper)
        self.btn_ask.clicked.connect(self.ask_ai)
        self.ed_question.returnPressed.connect(self.ask_ai)

    @staticmethod
    def _dspin(lo, hi, step, decimals, suffix) -> QtWidgets.QDoubleSpinBox:
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(lo, hi); s.setSingleStep(step); s.setDecimals(decimals); s.setSuffix(suffix)
        return s

    # ------------------------------------------------------------ settings
    def _restore_settings(self):
        s = self.settings
        self.cb_market.setCurrentText(s.market)
        self._on_market_changed(s.market)
        self.cb_symbol.setCurrentText(s.symbol)
        self.cb_interval.setCurrentText(s.interval)
        self._on_interval_changed(s.interval)
        if s.period in [self.cb_period.itemText(i) for i in range(self.cb_period.count())]:
            self.cb_period.setCurrentText(s.period)
        self.cb_strategy.setCurrentText(s.strategy)
        self._on_strategy_changed(s.strategy, s.strategy_params)
        self.sp_cash.setValue(s.initial_cash)
        r = s.risk
        self.sp_fee.setValue(r.fee_pct * 100); self.sp_slip.setValue(r.slippage_pct * 100)
        self.sp_pos.setValue(r.position_pct * 100); self.sp_sl.setValue(r.stop_loss_pct * 100)
        self.sp_tp.setValue(r.take_profit_pct * 100); self.sp_daily.setValue(r.daily_loss_limit_pct * 100)
        self.sp_paper_min.setValue(s.paper_interval_min)
        self.cb_ai_model.setCurrentText(s.ai_model); self.cb_ai_effort.setCurrentText(s.ai_effort)
        self.lbl_ai_status.setText("Kredensial Anthropic terdeteksi." if credentials_available()
                                   else "Belum ada kredensial. Set ANTHROPIC_API_KEY di environment lalu buka ulang aplikasi.")

    def _collect_settings(self) -> Settings:
        s = self.settings
        s.market = self.cb_market.currentText()
        s.symbol = self.cb_symbol.currentText().strip().upper()
        s.interval = self.cb_interval.currentText()
        s.period = self.cb_period.currentText()
        s.strategy = self.cb_strategy.currentText()
        s.strategy_params = self._read_params()
        s.initial_cash = self.sp_cash.value()
        s.paper_interval_min = self.sp_paper_min.value()
        s.ai_model = self.cb_ai_model.currentText()
        s.ai_effort = self.cb_ai_effort.currentText()
        s.risk = RiskSettings(
            position_pct=self.sp_pos.value() / 100, stop_loss_pct=self.sp_sl.value() / 100,
            take_profit_pct=self.sp_tp.value() / 100, daily_loss_limit_pct=self.sp_daily.value() / 100,
            fee_pct=self.sp_fee.value() / 100, slippage_pct=self.sp_slip.value() / 100,
        )
        self.broker.fee_pct = s.risk.fee_pct
        self.broker.slippage_pct = s.risk.slippage_pct
        return s

    def closeEvent(self, event):
        try:
            self._collect_settings().save()
        except Exception as exc:  # noqa: BLE001
            log.warning("Gagal simpan settings: %s", exc)
        self.paper_timer.stop()
        for w in self._workers:
            w.wait(2000)
        self.broker.close()
        super().closeEvent(event)

    # ----------------------------------------------------------- handlers
    def _on_market_changed(self, market: str):
        current = self.cb_symbol.currentText()
        self.cb_symbol.clear()
        self.cb_symbol.addItems(MARKETS.get(market, []))
        if current and market_of(current) == market:
            self.cb_symbol.setCurrentText(current)

    def _on_interval_changed(self, interval: str):
        current = self.cb_period.currentText()
        self.cb_period.clear()
        periods = INTERVAL_PERIODS.get(interval, ["1y"])
        self.cb_period.addItems(periods)
        self.cb_period.setCurrentText(current if current in periods else periods[min(len(periods) - 1, 3)])

    def _on_strategy_changed(self, name: str, saved: dict | None = None):
        cls = STRATEGIES.get(name)
        if not cls:
            return
        self.lbl_strategy_desc.setText(cls.description)
        while self.params_form.rowCount():
            self.params_form.removeRow(0)
        self._param_widgets.clear()
        for prm in cls.params:
            if prm.kind == "float":
                w = QtWidgets.QDoubleSpinBox(); w.setDecimals(3)
                w.setRange(prm.min if prm.min is not None else -1e9, prm.max if prm.max is not None else 1e9)
                w.setSingleStep(prm.step or 0.1)
            else:
                w = QtWidgets.QSpinBox()
                w.setRange(int(prm.min) if prm.min is not None else -10**9, int(prm.max) if prm.max is not None else 10**9)
                w.setSingleStep(int(prm.step or 1))
            val = (saved or {}).get(prm.name, prm.default)
            w.setValue(val)
            self.params_form.addRow(prm.label, w)
            self._param_widgets[prm.name] = w

    def _read_params(self) -> dict:
        return {k: w.value() for k, w in self._param_widgets.items()}

    def _make_strategy(self) -> Strategy | None:
        STRATEGIES[self.cb_strategy.currentText()].prepare()  # harus di thread utama
        strat = make_strategy(self.cb_strategy.currentText(), **self._read_params())
        err = strat.validate()
        if err:
            QtWidgets.QMessageBox.warning(self, "Parameter tidak valid", err)
            return None
        return strat

    def _bt_config(self, s: Settings) -> BacktestConfig:
        return BacktestConfig(
            initial_cash=s.initial_cash, fee_pct=s.risk.fee_pct, slippage_pct=s.risk.slippage_pct,
            position_pct=s.risk.position_pct, stop_loss_pct=s.risk.stop_loss_pct, take_profit_pct=s.risk.take_profit_pct,
            bars_per_year=bars_per_year(market_of(s.symbol), s.interval),
        )

    # -------------------------------------------------------------- utils
    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt_log.appendPlainText(f"[{ts}] {msg}")
        self.status.showMessage(msg, 8000)
        log.info(msg)

    def _start_worker(self, fn, on_done, *args, progress_slot=None, **kwargs) -> Worker:
        w = Worker(fn, *args, **kwargs)
        if progress_slot is not None:
            # fn menerima kwarg progress(i, n) yang aman dipanggil dari thread worker
            w.progress.connect(progress_slot)
            w.kwargs["progress"] = w.progress.emit
        self._workers.append(w)

        def _cleanup():
            if w in self._workers:
                self._workers.remove(w)
            self._set_busy(False)

        w.done.connect(on_done)
        w.failed.connect(self._on_worker_failed)
        w.finished.connect(_cleanup)
        self._set_busy(True)
        w.start()
        return w

    def _on_worker_failed(self, msg: str):
        self.progress.hide()
        first = msg.strip().splitlines()[0] if msg.strip() else "Terjadi kesalahan"
        self.log(f"Gagal: {first}")
        QtWidgets.QMessageBox.critical(self, "Terjadi kesalahan", msg)

    def _set_busy(self, busy: bool):
        for b in (self.btn_backtest, self.btn_optimize, self.btn_paper_step, self.btn_buy, self.btn_sell, self.btn_ask, self.btn_apply_optim):
            b.setEnabled(not busy)
        if busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.BusyCursor)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()

    # ----------------------------------------------------------- backtest
    def run_backtest(self):
        s = self._collect_settings()
        if not s.symbol:
            QtWidgets.QMessageBox.warning(self, "Simbol kosong", "Masukkan simbol, mis. BTC-USD, AAPL, EURUSD=X")
            return
        strat = self._make_strategy()
        if not strat:
            return
        cfg = self._bt_config(s)
        self.log(f"Mengambil data {s.symbol} {s.interval} ({s.period}) dan menjalankan {strat.name} [{strat.describe_params()}]...")

        def job():
            df = fetch_ohlcv(s.symbol, s.interval, s.period)
            sig = strat.generate_signals(df)
            res = run_backtest(df, sig, cfg)
            overlays = strat.overlays(df)
            panels = strat.panels(df)
            return df, strat, res, overlays, panels

        self._start_worker(job, self._on_backtest_done)

    def _on_backtest_done(self, payload):
        df, strat, res, overlays, panels = payload
        self.df, self.strategy, self.result = df, strat, res
        s = self.settings
        s.save()
        title = f"{s.symbol}  {s.interval}  |  {strat.name} ({strat.describe_params()})"
        self.chart.set_data(df, s.interval, overlays, panels, res.trades_frame(), title)
        self.equity_widget.set_curves(res.equity, res.buy_hold, s.interval)
        rows = [[k, v] for k, v in metrics_table(res.metrics)]
        rows.insert(0, ["Data", f"{len(df)} bar, {df.index[0]:%Y-%m-%d} s/d {df.index[-1]:%Y-%m-%d %H:%M} UTC"])
        report = getattr(strat, "last_report", None)
        if report:
            for k, v in report.items():
                rows.append([f"ML: {k}", v])
        _fill(self.tbl_metrics, rows)
        tf = res.trades_frame()
        _fill(self.tbl_trades, [[
            f"{t.entry_time:%Y-%m-%d %H:%M}", f"{t.exit_time:%Y-%m-%d %H:%M}" if t.exit_time is not None else "-",
            f"{t.entry_price:.6g}", f"{t.exit_price:.6g}" if t.exit_price is not None else "-",
            f"{t.qty:.6g}", f"{t.pnl:,.2f}", f"{t.pnl_pct * 100:.2f}%", t.bars, t.reason,
        ] for t in res.trades])
        m = res.metrics
        self.log(f"Backtest selesai: return {m['total_return']*100:.2f}% (buy&hold {m['buy_hold_return']*100:.2f}%), "
                 f"Sharpe {m['sharpe']:.2f}, max DD {m['max_drawdown']*100:.2f}%, {m['n_trades']} trade, win rate {m['win_rate']*100:.1f}%.")
        if m["n_trades"] < 5:
            self.log("Peringatan: jumlah trade sangat sedikit, hasil belum bisa dipercaya secara statistik.")
        self.tabs.setCurrentIndex(0)

    # ---------------------------------------------------------- optimizer
    def run_optimize(self):
        if self.df is None:
            QtWidgets.QMessageBox.information(self, "Belum ada data", "Jalankan backtest dulu agar data tersedia.")
            return
        s = self._collect_settings()
        cls = STRATEGIES[s.strategy]
        cls.prepare()  # harus di thread utama
        if not cls.params:
            QtWidgets.QMessageBox.information(self, "Tidak ada parameter", "Strategi ini tidak punya parameter untuk dioptimasi.")
            return
        cfg = self._bt_config(s)
        df = self.df
        self.progress.setRange(0, 100); self.progress.setValue(0); self.progress.show()
        self.log(f"Optimasi {cls.name} dimulai (maks 150 kombinasi)...")

        def job(progress=None):
            return optimize(df, cls, cfg, objective="sharpe", max_combos=150, progress=progress)

        self._start_worker(job, self._on_optimize_done,
                           progress_slot=lambda i, n: self.progress.setValue(int(i / max(n, 1) * 100)))

    def _on_optimize_done(self, table: pd.DataFrame):
        self.progress.hide()
        self.optim_table = table
        if table is None or table.empty:
            self.lbl_optim.setText("Optimasi tidak menghasilkan kombinasi valid.")
            return
        show = table.drop(columns=["score"]).head(50)
        cols = list(show.columns)
        self.tbl_optim.setColumnCount(len(cols)); self.tbl_optim.setHorizontalHeaderLabels(cols)
        rows = []
        for _, r in show.iterrows():
            row = []
            for c in cols:
                v = r[c]
                if c in ("total_return", "max_drawdown", "win_rate"):
                    row.append(f"{v*100:.2f}%")
                elif c == "sharpe":
                    row.append(f"{v:.2f}")
                elif c == "n_trades":
                    row.append(int(v))
                else:
                    row.append(v if isinstance(v, (int, str)) else (int(v) if float(v).is_integer() else round(float(v), 4)))
            rows.append(row)
        _fill(self.tbl_optim, rows)
        best = table.iloc[0]
        self.lbl_optim.setText(f"{len(table)} kombinasi diuji, diurutkan berdasarkan Sharpe (minimal 5 trade). "
                               f"Terbaik: Sharpe {best['sharpe']:.2f}, return {best['total_return']*100:.2f}%. "
                               "Hati-hati overfitting: uji ulang parameter terbaik di rentang data / simbol lain.")
        self.tabs.setCurrentWidget(self.tbl_optim.parentWidget())
        self.log("Optimasi selesai. Lihat tab Optimasi.")

    def apply_optim_row(self):
        if self.optim_table is None or self.optim_table.empty:
            return
        row = self.tbl_optim.currentRow()
        if row < 0:
            row = 0
        rec = self.optim_table.iloc[row]
        for name, w in self._param_widgets.items():
            if name in rec.index:
                w.setValue(rec[name])
        self.run_backtest()

    # ------------------------------------------------------ paper trading
    def toggle_paper_auto(self):
        if self.paper_timer.isActive():
            self.paper_timer.stop()
            self.btn_paper_auto.setText("Mulai Otomatis")
            self.log("Paper trading otomatis dihentikan.")
            return
        s = self._collect_settings()
        strat = self._make_strategy()
        if not strat:
            return
        self.paper_timer.start(s.paper_interval_min * 60 * 1000)
        self.btn_paper_auto.setText("Stop Otomatis")
        self.log(f"Paper trading otomatis aktif: {s.symbol} {s.interval} dengan {strat.name}, cek setiap {s.paper_interval_min} menit.")
        self.run_paper_step()

    def run_paper_step(self):
        if any(w.isRunning() for w in self._workers):
            self.log("Masih ada proses berjalan, langkah paper trading dilewati.")
            return
        s = self._collect_settings()
        strat = self._make_strategy()
        if not strat:
            return
        trader = PaperTrader(self.broker, s.risk)
        self._start_worker(trader.step, self._on_paper_step_done, s.symbol, s.interval, strat)

    def _on_paper_step_done(self, res):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {res.symbol} @ {res.price:,.4f} | sinyal={res.signal} | {res.action}: {res.message} | equity {res.equity:,.2f}"
        self.txt_paper_log.appendPlainText(line)
        self.log(f"Paper: {res.action} - {res.message}")
        self.refresh_paper_tables(res.price, res.symbol)

    def refresh_paper_tables(self, price: float | None = None, symbol: str | None = None):
        positions = self.broker.positions()
        prices = {p["symbol"]: (price if symbol == p["symbol"] and price else p["avg_price"]) for p in positions}
        equity = self.broker.equity(prices)
        init = self.broker.initial_cash
        pnl = equity - init
        color = "#26a69a" if pnl >= 0 else "#ef5350"
        self.lbl_paper_summary.setText(
            f"Cash: <b>{self.broker.cash:,.2f}</b> &nbsp;|&nbsp; Equity: <b>{equity:,.2f}</b> &nbsp;|&nbsp; "
            f"PnL total: <b style='color:{color}'>{pnl:+,.2f} ({pnl / init * 100:+.2f}%)</b> &nbsp;|&nbsp; Modal awal: {init:,.2f}")
        _fill(self.tbl_positions, [[p["symbol"], f"{p['qty']:.6g}", f"{p['avg_price']:,.4f}", p["opened_at"]] for p in positions])
        _fill(self.tbl_orders, [[o["ts"], o["symbol"], o["side"], f"{o['qty']:.6g}", f"{o['price']:,.4f}", f"{o['fee']:.2f}",
                                 "" if o["pnl"] is None else f"{o['pnl']:+,.2f}", o["note"] or ""] for o in self.broker.orders()])

    def manual_order(self, side: str):
        s = self._collect_settings()
        symbol = s.symbol
        if side == "SELL" and not self.broker.position(symbol):
            QtWidgets.QMessageBox.information(self, "Tidak ada posisi", f"Tidak ada posisi {symbol} untuk dijual.")
            return

        def job():
            price = latest_price(symbol)
            if side == "BUY":
                budget = min(self.broker.cash, self.broker.equity({symbol: price}) * s.risk.position_pct)
                qty = budget / (price * (1 + self.broker.fee_pct + self.broker.slippage_pct))
                return self.broker.buy(symbol, qty, price, note="manual")
            return self.broker.sell(symbol, None, price, note="manual")

        def done(r):
            msg = f"{r['side']} manual {r['symbol']} {r['qty']:.6g} @ {r['price']:,.4f}"
            if "pnl" in r:
                msg += f", PnL {r['pnl']:+,.2f}"
            self.txt_paper_log.appendPlainText(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")
            self.log(msg)
            self.refresh_paper_tables(r["price"], r["symbol"])

        self._start_worker(job, done)

    def reset_paper(self):
        s = self._collect_settings()
        ans = QtWidgets.QMessageBox.question(self, "Reset akun paper",
                                             f"Hapus semua posisi dan riwayat order, lalu set modal ke {s.initial_cash:,.2f}?")
        if ans != QtWidgets.QMessageBox.Yes:
            return
        self.paper_timer.stop(); self.btn_paper_auto.setText("Mulai Otomatis")
        self.broker.reset(s.initial_cash)
        self.txt_paper_log.clear()
        self.refresh_paper_tables()
        self.log("Akun paper trading direset.")

    # ------------------------------------------------------------------ AI
    def ask_ai(self):
        if self.df is None or self.strategy is None:
            QtWidgets.QMessageBox.information(self, "Belum ada data", "Jalankan backtest dulu supaya AI punya konteks data pasar.")
            return
        if not credentials_available():
            QtWidgets.QMessageBox.warning(self, "Kredensial AI belum ada",
                                          "Set environment variable ANTHROPIC_API_KEY (atau jalankan `ant auth login`) lalu buka ulang aplikasi.")
            return
        s = self._collect_settings()
        question = self.ed_question.text().strip() or "Analisis kondisi pasar saat ini dan evaluasi strategi yang sedang diuji."
        df, strat, res = self.df, self.strategy, self.result
        extra = {}
        pos = self.broker.position(s.symbol)
        if pos:
            extra["posisi_paper_terbuka"] = {"qty": pos["qty"], "harga_rata": pos["avg_price"]}
        report = getattr(strat, "last_report", None)
        if report:
            extra["laporan_ml"] = report
        extra["pengaturan_risiko"] = {"stop_loss": s.risk.stop_loss_pct, "take_profit": s.risk.take_profit_pct,
                                      "porsi_posisi": s.risk.position_pct, "fee": s.risk.fee_pct}
        advisor = MarketAdvisor(model=s.ai_model, effort=s.ai_effort)
        history = self.ai_history[-6:]
        self._append_chat("Kamu", question)
        self.ed_question.clear()
        self.tabs.setCurrentWidget(self.txt_ai)
        self.log(f"Bertanya ke {s.ai_model}...")

        def job():
            news = recent_news(s.symbol)
            ctx = build_context(s.symbol, s.interval, df, strat.name, strat.describe_params(),
                                res.metrics if res else None, news, extra)
            return advisor.ask(ctx, question, history), question

        def done(payload):
            result, q = payload
            self.ai_history.append({"role": "user", "content": q})
            self.ai_history.append({"role": "assistant", "content": result.text})
            self._append_chat(f"AI ({result.model})", result.text)
            self.log("Jawaban AI diterima." if not result.refused else "Model menolak menjawab.")

        self._start_worker(job, done)

    def _append_chat(self, who: str, text: str):
        ts = datetime.now().strftime("%H:%M")
        self.ai_chat_md.append(f"**{who}** · {ts}\n\n{text}\n\n---\n")
        self.txt_ai.setMarkdown("\n".join(self.ai_chat_md))
        self.txt_ai.verticalScrollBar().setValue(self.txt_ai.verticalScrollBar().maximum())

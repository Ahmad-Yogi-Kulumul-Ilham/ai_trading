"""Backtester event-based sederhana (long-only).

Aturan eksekusi:
- Sinyal dihitung di close bar i, dieksekusi di OPEN bar i+1 (plus slippage).
- Stop loss / take profit dicek intrabar memakai low/high; eksekusi di harga stop.
- Fee dikenakan di setiap transaksi (beli dan jual).
- Equity dihitung mark-to-market di close setiap bar.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from app.backtest.metrics import compute_metrics


@dataclass
class BacktestConfig:
    initial_cash: float = 10_000.0
    fee_pct: float = 0.001
    slippage_pct: float = 0.0005
    position_pct: float = 0.95
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
    bars_per_year: float = 365.0


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp | None
    entry_price: float
    exit_price: float | None
    qty: float
    pnl: float
    pnl_pct: float
    bars: int
    reason: str  # signal | stop_loss | take_profit | end

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestResult:
    equity: pd.Series
    buy_hold: pd.Series
    positions: pd.Series
    trades: list[Trade]
    metrics: dict = field(default_factory=dict)
    config: BacktestConfig | None = None

    def trades_frame(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(columns=["entry_time", "exit_time", "entry_price", "exit_price", "qty", "pnl", "pnl_pct", "bars", "reason"])
        return pd.DataFrame([t.as_dict() for t in self.trades])


def run_backtest(df: pd.DataFrame, signals: pd.Series, cfg: BacktestConfig) -> BacktestResult:
    if len(df) < 2:
        raise ValueError("Data terlalu sedikit untuk backtest")
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    sig = signals.reindex(df.index).fillna(0).astype(int).to_numpy()
    n = len(df)

    cash = float(cfg.initial_cash)
    qty = 0.0
    entry_price = 0.0
    entry_i = -1
    equity = np.empty(n)
    pos = np.zeros(n, dtype=int)
    trades: list[Trade] = []

    def close_position(i: int, price: float, reason: str):
        nonlocal cash, qty, entry_price, entry_i
        proceeds = qty * price
        fee = proceeds * cfg.fee_pct
        cash += proceeds - fee
        cost = qty * entry_price
        pnl = proceeds - fee - cost - cost * cfg.fee_pct
        trades.append(Trade(
            entry_time=df.index[entry_i], exit_time=df.index[i],
            entry_price=entry_price, exit_price=price, qty=qty,
            pnl=pnl, pnl_pct=pnl / cost if cost else 0.0,
            bars=i - entry_i, reason=reason,
        ))
        qty = 0.0
        entry_price = 0.0
        entry_i = -1

    equity[0] = cash
    for i in range(1, n):
        target = sig[i - 1]
        # 1) eksekusi sinyal bar sebelumnya di open bar ini
        if target == 1 and qty == 0:
            price = o[i] * (1 + cfg.slippage_pct)
            budget = cash * cfg.position_pct
            q = budget / (price * (1 + cfg.fee_pct))
            if q > 0:
                cash -= q * price * (1 + cfg.fee_pct)
                qty = q
                entry_price = price
                entry_i = i
        elif target == 0 and qty > 0:
            close_position(i, o[i] * (1 - cfg.slippage_pct), "signal")

        # 2) cek stop loss / take profit intrabar
        if qty > 0 and i != entry_i:
            if cfg.stop_loss_pct > 0:
                stop = entry_price * (1 - cfg.stop_loss_pct)
                if l[i] <= stop:
                    close_position(i, min(stop, o[i]) * (1 - cfg.slippage_pct), "stop_loss")
            if qty > 0 and cfg.take_profit_pct > 0:
                tp = entry_price * (1 + cfg.take_profit_pct)
                if h[i] >= tp:
                    close_position(i, max(tp, o[i]) * (1 - cfg.slippage_pct), "take_profit")

        pos[i] = 1 if qty > 0 else 0
        equity[i] = cash + qty * c[i]

    # tutup posisi terbuka di akhir (hanya untuk pelaporan, pakai close terakhir)
    if qty > 0:
        close_position(n - 1, c[-1], "end")
        equity[-1] = cash

    eq = pd.Series(equity, index=df.index, name="equity")
    bh_qty = cfg.initial_cash * (1 - cfg.fee_pct) / o[1] if o[1] > 0 else 0
    bh = pd.Series(bh_qty * c, index=df.index, name="buy_hold")
    bh.iloc[0] = cfg.initial_cash
    result = BacktestResult(equity=eq, buy_hold=bh, positions=pd.Series(pos, index=df.index), trades=trades, config=cfg)
    result.metrics = compute_metrics(result, cfg.bars_per_year)
    return result

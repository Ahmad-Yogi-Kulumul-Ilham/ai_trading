"""Metrik performa backtest."""
from __future__ import annotations

import numpy as np
import pandas as pd

METRIC_LABELS = {
    "total_return": "Total return",
    "buy_hold_return": "Return buy & hold",
    "cagr": "CAGR (tahunan)",
    "sharpe": "Sharpe ratio",
    "sortino": "Sortino ratio",
    "max_drawdown": "Max drawdown",
    "calmar": "Calmar ratio",
    "volatility": "Volatilitas tahunan",
    "n_trades": "Jumlah trade",
    "win_rate": "Win rate",
    "profit_factor": "Profit factor",
    "avg_trade_pct": "Rata-rata PnL per trade",
    "avg_win_pct": "Rata-rata win",
    "avg_loss_pct": "Rata-rata loss",
    "exposure": "Waktu di pasar",
    "final_equity": "Equity akhir",
}

PCT_METRICS = {"total_return", "buy_hold_return", "cagr", "max_drawdown", "volatility",
               "win_rate", "avg_trade_pct", "avg_win_pct", "avg_loss_pct", "exposure"}


def compute_metrics(result, bars_per_year: float) -> dict:
    eq = result.equity
    initial = float(eq.iloc[0])
    final = float(eq.iloc[-1])
    rets = eq.pct_change().dropna()
    n_bars = max(len(eq) - 1, 1)
    years = n_bars / bars_per_year if bars_per_year else np.nan

    total_return = final / initial - 1 if initial else 0.0
    cagr = (final / initial) ** (1 / years) - 1 if years and years > 0 and final > 0 and initial > 0 else np.nan
    vol = rets.std(ddof=0) * np.sqrt(bars_per_year) if len(rets) > 1 else np.nan
    sharpe = (rets.mean() / rets.std(ddof=0)) * np.sqrt(bars_per_year) if len(rets) > 1 and rets.std(ddof=0) > 0 else 0.0
    downside = rets[rets < 0]
    sortino = (rets.mean() / downside.std(ddof=0)) * np.sqrt(bars_per_year) if len(downside) > 1 and downside.std(ddof=0) > 0 else 0.0
    running_max = eq.cummax()
    dd = (eq / running_max - 1)
    max_dd = float(dd.min()) if len(dd) else 0.0
    calmar = cagr / abs(max_dd) if max_dd < 0 and not np.isnan(cagr) else 0.0

    trades = result.trades
    pnls = np.array([t.pnl for t in trades]) if trades else np.array([])
    pnl_pcts = np.array([t.pnl_pct for t in trades]) if trades else np.array([])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    win_rate = len(wins) / len(pnls) if len(pnls) else 0.0
    profit_factor = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else (np.inf if len(wins) else 0.0)

    bh_final = float(result.buy_hold.iloc[-1]) if len(result.buy_hold) else initial

    return {
        "total_return": total_return,
        "buy_hold_return": bh_final / initial - 1 if initial else 0.0,
        "cagr": cagr,
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_drawdown": max_dd,
        "calmar": float(calmar),
        "volatility": float(vol) if vol == vol else 0.0,
        "n_trades": int(len(trades)),
        "win_rate": win_rate,
        "profit_factor": float(profit_factor) if np.isfinite(profit_factor) else 999.0,
        "avg_trade_pct": float(pnl_pcts.mean()) if len(pnl_pcts) else 0.0,
        "avg_win_pct": float(pnl_pcts[pnl_pcts > 0].mean()) if (pnl_pcts > 0).any() else 0.0,
        "avg_loss_pct": float(pnl_pcts[pnl_pcts <= 0].mean()) if (pnl_pcts <= 0).any() else 0.0,
        "exposure": float(result.positions.mean()) if len(result.positions) else 0.0,
        "final_equity": final,
    }


def format_metric(key: str, value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "-"
    if key in PCT_METRICS:
        return f"{value * 100:.2f}%"
    if key == "n_trades":
        return str(int(value))
    if key == "final_equity":
        return f"{value:,.2f}"
    return f"{value:.2f}"


def metrics_table(metrics: dict) -> list[tuple[str, str]]:
    return [(METRIC_LABELS.get(k, k), format_metric(k, v)) for k, v in metrics.items()]

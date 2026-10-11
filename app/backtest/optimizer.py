"""Grid search parameter strategi. Dibatasi jumlah kombinasi agar tetap cepat."""
from __future__ import annotations

import itertools
from typing import Callable

import numpy as np
import pandas as pd

from app.backtest.engine import BacktestConfig, run_backtest
from app.strategies.base import Param, Strategy


def _grid_values(prm: Param, max_points: int) -> list:
    if prm.min is None or prm.max is None:
        return [prm.default]
    step = prm.step or (1 if prm.kind == "int" else (prm.max - prm.min) / 10)
    vals = np.arange(prm.min, prm.max + step * 0.5, step)
    if len(vals) > max_points:
        vals = np.linspace(prm.min, prm.max, max_points)
    if prm.kind == "int":
        vals = sorted(set(int(round(v)) for v in vals))
    else:
        vals = sorted(set(round(float(v), 4) for v in vals))
    return list(vals)


def optimize(df: pd.DataFrame, strategy_cls: type[Strategy], cfg: BacktestConfig,
             objective: str = "sharpe", max_combos: int = 150,
             progress: Callable[[int, int], None] | None = None) -> pd.DataFrame:
    params = [p for p in strategy_cls.params if p.name not in ("n_estimators",)]
    if not params:
        return pd.DataFrame()
    # tentukan jumlah titik per parameter agar total <= max_combos
    per_param = max(2, int(round(max_combos ** (1 / len(params)))))
    grids = {p.name: _grid_values(p, per_param) for p in params}
    combos = list(itertools.product(*grids.values()))
    if len(combos) > max_combos:
        rng = np.random.default_rng(0)
        idx = rng.choice(len(combos), size=max_combos, replace=False)
        combos = [combos[i] for i in sorted(idx)]

    rows = []
    for k, combo in enumerate(combos):
        kwargs = dict(zip(grids.keys(), combo))
        strat = strategy_cls(**kwargs)
        if strat.validate():
            continue
        try:
            sig = strat.generate_signals(df)
            res = run_backtest(df, sig, cfg)
        except Exception:
            continue
        row = dict(kwargs)
        row.update({
            "sharpe": res.metrics["sharpe"],
            "total_return": res.metrics["total_return"],
            "max_drawdown": res.metrics["max_drawdown"],
            "n_trades": res.metrics["n_trades"],
            "win_rate": res.metrics["win_rate"],
        })
        rows.append(row)
        if progress:
            progress(k + 1, len(combos))
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    # abaikan hasil dengan terlalu sedikit trade (overfitting pada 1-2 trade)
    out["score"] = out[objective].where(out["n_trades"] >= 5, -np.inf)
    return out.sort_values("score", ascending=False).reset_index(drop=True)

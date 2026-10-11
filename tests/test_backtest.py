import numpy as np
import pandas as pd
import pytest

from app.backtest.engine import BacktestConfig, run_backtest
from app.backtest.optimizer import optimize
from app.strategies import STRATEGIES, make_strategy


def make_df(n=500, seed=1, drift=0.0005):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.005, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.005, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 1000.0}, index=idx)


def test_buy_and_hold_matches_reference():
    df = make_df()
    cfg = BacktestConfig(initial_cash=1000, fee_pct=0.0, slippage_pct=0.0, position_pct=1.0, bars_per_year=8760)
    sig = pd.Series(1, index=df.index)
    res = run_backtest(df, sig, cfg)
    expected = 1000 * df["close"].iloc[-1] / df["open"].iloc[1]
    assert abs(res.equity.iloc[-1] - expected) < 1e-6
    assert len(res.trades) == 1 and res.trades[0].reason == "end"


def test_signal_executes_next_bar_open():
    df = make_df(50)
    cfg = BacktestConfig(initial_cash=1000, fee_pct=0.0, slippage_pct=0.0, position_pct=1.0, bars_per_year=8760)
    sig = pd.Series(0, index=df.index)
    sig.iloc[10:20] = 1  # sinyal long di close bar 10..19, kembali 0 di close bar 20
    res = run_backtest(df, sig, cfg)
    assert len(res.trades) == 1
    t = res.trades[0]
    # masuk di open bar 11 (sinyal bar 10), keluar di open bar 21 (sinyal 0 pertama di bar 20)
    assert t.entry_time == df.index[11]
    assert t.exit_time == df.index[21]
    assert t.entry_price == df["open"].iloc[11]
    assert t.exit_price == df["open"].iloc[21]


def test_stop_loss_triggers():
    df = make_df(30)
    df.loc[df.index[12], "low"] = df["open"].iloc[11] * 0.9  # crash intrabar
    cfg = BacktestConfig(initial_cash=1000, fee_pct=0.0, slippage_pct=0.0, position_pct=1.0, stop_loss_pct=0.05, bars_per_year=8760)
    sig = pd.Series(1, index=df.index)
    sig.iloc[:10] = 0
    res = run_backtest(df, sig, cfg)
    assert res.trades[0].reason == "stop_loss"
    assert res.trades[0].exit_time == df.index[12]
    assert abs(res.trades[0].pnl_pct + 0.05) < 1e-6 or res.trades[0].exit_price <= df["open"].iloc[11] * 0.95 + 1e-9


def test_fees_reduce_equity():
    df = make_df()
    sig = make_strategy("SMA Crossover", fast=10, slow=30).generate_signals(df)
    a = run_backtest(df, sig, BacktestConfig(fee_pct=0.0, slippage_pct=0.0, bars_per_year=8760))
    b = run_backtest(df, sig, BacktestConfig(fee_pct=0.002, slippage_pct=0.0, bars_per_year=8760))
    assert b.equity.iloc[-1] < a.equity.iloc[-1]
    assert a.metrics["n_trades"] == b.metrics["n_trades"] > 0


def test_metrics_keys_and_drawdown_range():
    df = make_df()
    sig = make_strategy("RSI Mean Reversion").generate_signals(df)
    res = run_backtest(df, sig, BacktestConfig(bars_per_year=8760))
    for k in ("total_return", "sharpe", "max_drawdown", "n_trades", "win_rate"):
        assert k in res.metrics
    assert -1 <= res.metrics["max_drawdown"] <= 0


@pytest.mark.parametrize("name", [n for n in STRATEGIES if n != "ML Prediksi Arah"])
def test_all_classic_strategies_produce_binary_signals(name):
    df = make_df(400)
    sig = make_strategy(name).generate_signals(df)
    assert len(sig) == len(df)
    assert set(sig.unique()).issubset({0, 1})


def test_ml_strategy_only_signals_out_of_sample():
    df = make_df(600)
    strat = make_strategy("ML Prediksi Arah", n_estimators=30, train_fraction=0.6)
    sig = strat.generate_signals(df)
    assert sig.iloc[: int(600 * 0.6)].sum() == 0
    assert "oos_accuracy" in strat.last_report
    assert "backend" in strat.last_report


def test_ml_numpy_fallback_runs():
    from app.strategies.ml import MLDirection, _NumpyLogistic
    df = make_df(500)
    strat = MLDirection(train_fraction=0.6)
    strat._make_model = lambda: (_NumpyLogistic(epochs=100), "numpy")
    sig = strat.generate_signals(df)
    assert set(sig.unique()).issubset({0, 1})
    assert strat.last_report["backend"] == "numpy"
    assert 0 <= strat.last_report["oos_accuracy"] <= 1


def test_optimizer_returns_sorted_table():
    df = make_df(400)
    table = optimize(df, STRATEGIES["SMA Crossover"], BacktestConfig(bars_per_year=8760), max_combos=12)
    assert not table.empty
    assert "sharpe" in table.columns
    assert table["score"].is_monotonic_decreasing

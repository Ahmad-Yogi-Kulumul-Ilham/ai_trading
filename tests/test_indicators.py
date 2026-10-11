import numpy as np
import pandas as pd

from app import indicators as ind


def _series(n=200, seed=0):
    rng = np.random.default_rng(seed)
    return pd.Series(100 + rng.normal(0, 1, n).cumsum(), index=pd.date_range("2024-01-01", periods=n, freq="h"))


def test_sma_matches_rolling_mean():
    s = _series()
    out = ind.sma(s, 10)
    assert np.isnan(out.iloc[8])
    assert abs(out.iloc[-1] - s.iloc[-10:].mean()) < 1e-9


def test_rsi_bounds_and_warmup():
    s = _series()
    r = ind.rsi(s, 14)
    assert r.iloc[:13].isna().all()
    valid = r.dropna()
    assert ((valid >= 0) & (valid <= 100)).all()


def test_rsi_monotonic_up_is_100():
    s = pd.Series(np.arange(1.0, 60.0))
    r = ind.rsi(s, 14)
    assert abs(r.iloc[-1] - 100) < 1e-6


def test_bollinger_order():
    s = _series()
    lo, mid, hi = ind.bollinger(s, 20, 2)
    v = ~lo.isna()
    assert (lo[v] <= mid[v]).all() and (mid[v] <= hi[v]).all()


def test_feature_frame_no_lookahead():
    s = _series(300)
    df = pd.DataFrame({"open": s, "high": s + 1, "low": s - 1, "close": s, "volume": 1000.0})
    f_full = ind.feature_frame(df)
    f_cut = ind.feature_frame(df.iloc[:250])
    # fitur bar ke-249 harus identik walau data setelahnya dibuang
    a = f_full.iloc[249].to_numpy()
    b = f_cut.iloc[249].to_numpy()
    assert np.allclose(a, b, equal_nan=True)

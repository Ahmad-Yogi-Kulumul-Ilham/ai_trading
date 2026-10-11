"""Registry strategi."""
from __future__ import annotations

from app.strategies.base import Param, Strategy
from app.strategies.classic import (
    BollingerBreakout, BuyAndHold, EmaCross, MacdTrend, RsiReversion, SmaCross,
)
from app.strategies.ml import MLDirection

STRATEGIES: dict[str, type[Strategy]] = {
    cls.name: cls
    for cls in (SmaCross, EmaCross, RsiReversion, MacdTrend, BollingerBreakout, MLDirection, BuyAndHold)
}


def make_strategy(name: str, **params) -> Strategy:
    cls = STRATEGIES.get(name)
    if cls is None:
        raise KeyError(f"Strategi tidak dikenal: {name}")
    return cls(**params)


__all__ = ["STRATEGIES", "make_strategy", "Strategy", "Param"]

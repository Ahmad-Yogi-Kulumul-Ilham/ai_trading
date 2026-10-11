"""Loop paper trading: ambil data terbaru, hitung sinyal strategi, eksekusi order simulasi."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config import RiskSettings
from app.data.fetcher import fetch_ohlcv, latest_price
from app.data.symbols import PAPER_PERIODS
from app.paper.broker import PaperBroker
from app.strategies.base import Strategy

log = logging.getLogger(__name__)


@dataclass
class StepResult:
    symbol: str
    price: float
    signal: int
    action: str            # BUY | SELL | HOLD | SKIP
    message: str
    equity: float
    details: dict = field(default_factory=dict)


class PaperTrader:
    def __init__(self, broker: PaperBroker, risk: RiskSettings):
        self.broker = broker
        self.risk = risk

    def step(self, symbol: str, interval: str, strategy: Strategy) -> StepResult:
        period = PAPER_PERIODS.get(interval, "1y")
        df = fetch_ohlcv(symbol, interval, period, use_cache=True)
        signals = strategy.generate_signals(df)
        # sinyal dari bar terakhir yang SUDAH tutup (bar terakhir di data sering masih berjalan)
        signal = int(signals.iloc[-2]) if len(signals) >= 2 else 0
        try:
            price = latest_price(symbol)
        except Exception:
            price = float(df["close"].iloc[-1])

        pos = self.broker.position(symbol)
        prices = {p["symbol"]: price if p["symbol"] == symbol else p["avg_price"] for p in self.broker.positions()}
        equity = self.broker.equity(prices)
        day_start = self.broker.day_start_equity(equity)
        daily_dd = equity / day_start - 1 if day_start else 0.0

        details = {"last_bar": str(df.index[-1]), "daily_change": daily_dd}

        # 1) proteksi posisi terbuka: stop loss / take profit
        if pos:
            change = price / pos["avg_price"] - 1
            if self.risk.stop_loss_pct > 0 and change <= -self.risk.stop_loss_pct:
                r = self.broker.sell(symbol, None, price, note=f"stop loss {change:.2%}")
                equity = self.broker.equity(prices)
                self.broker.record_equity(equity)
                return StepResult(symbol, price, signal, "SELL", f"Stop loss kena ({change:.2%}), posisi ditutup. PnL {r['pnl']:,.2f}", equity, details)
            if self.risk.take_profit_pct > 0 and change >= self.risk.take_profit_pct:
                r = self.broker.sell(symbol, None, price, note=f"take profit {change:.2%}")
                equity = self.broker.equity(prices)
                self.broker.record_equity(equity)
                return StepResult(symbol, price, signal, "SELL", f"Take profit kena ({change:.2%}), posisi ditutup. PnL {r['pnl']:,.2f}", equity, details)

        # 2) batas rugi harian: tidak buka posisi baru
        if self.risk.daily_loss_limit_pct > 0 and daily_dd <= -self.risk.daily_loss_limit_pct and not pos:
            self.broker.record_equity(equity)
            return StepResult(symbol, price, signal, "SKIP",
                              f"Batas rugi harian tercapai ({daily_dd:.2%}). Tidak membuka posisi baru hari ini.", equity, details)

        # 3) ikuti sinyal
        if signal == 1 and not pos:
            budget = equity * self.risk.position_pct
            budget = min(budget, self.broker.cash)
            qty = budget / (price * (1 + self.broker.fee_pct + self.broker.slippage_pct))
            if qty <= 0:
                return StepResult(symbol, price, signal, "SKIP", "Cash tidak cukup untuk membuka posisi.", equity, details)
            r = self.broker.buy(symbol, qty, price, note=f"sinyal {strategy.name}")
            equity = self.broker.equity({**prices, symbol: price})
            self.broker.record_equity(equity)
            return StepResult(symbol, price, signal, "BUY", f"BUY {qty:.6f} @ {r['price']:,.4f} (fee {r['fee']:,.2f})", equity, details)
        if signal == 0 and pos:
            r = self.broker.sell(symbol, None, price, note=f"sinyal {strategy.name}")
            equity = self.broker.equity(prices)
            self.broker.record_equity(equity)
            return StepResult(symbol, price, signal, "SELL", f"SELL {r['qty']:.6f} @ {r['price']:,.4f}, PnL {r['pnl']:,.2f}", equity, details)

        self.broker.record_equity(equity)
        state = "long" if pos else "flat"
        return StepResult(symbol, price, signal, "HOLD", f"Tidak ada perubahan (posisi {state}, sinyal {signal}).", equity, details)

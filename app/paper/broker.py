"""Broker simulasi (paper trading) dengan penyimpanan SQLite."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, date
from pathlib import Path

from app.config import PAPER_DB


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class PaperBroker:
    def __init__(self, db_path: Path = PAPER_DB, initial_cash: float = 10_000.0,
                 fee_pct: float = 0.001, slippage_pct: float = 0.0005):
        self.db_path = Path(db_path)
        self.fee_pct = fee_pct
        self.slippage_pct = slippage_pct
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db(initial_cash)

    # ---------- skema ----------
    def _init_db(self, initial_cash: float) -> None:
        cur = self.conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK (id = 1), cash REAL NOT NULL, initial_cash REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, qty REAL NOT NULL, avg_price REAL NOT NULL, opened_at TEXT);
            CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT, side TEXT, qty REAL, price REAL, fee REAL, pnl REAL, note TEXT);
            CREATE TABLE IF NOT EXISTS equity_history (ts TEXT, equity REAL);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        """)
        if cur.execute("SELECT COUNT(*) FROM account").fetchone()[0] == 0:
            cur.execute("INSERT INTO account (id, cash, initial_cash) VALUES (1, ?, ?)", (initial_cash, initial_cash))
        self.conn.commit()

    def reset(self, initial_cash: float) -> None:
        cur = self.conn.cursor()
        cur.executescript("DELETE FROM positions; DELETE FROM orders; DELETE FROM equity_history; DELETE FROM meta;")
        cur.execute("UPDATE account SET cash = ?, initial_cash = ? WHERE id = 1", (initial_cash, initial_cash))
        self.conn.commit()

    # ---------- state ----------
    @property
    def cash(self) -> float:
        return float(self.conn.execute("SELECT cash FROM account WHERE id = 1").fetchone()[0])

    @property
    def initial_cash(self) -> float:
        return float(self.conn.execute("SELECT initial_cash FROM account WHERE id = 1").fetchone()[0])

    def _set_cash(self, value: float) -> None:
        self.conn.execute("UPDATE account SET cash = ? WHERE id = 1", (value,))

    def position(self, symbol: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,)).fetchone()
        return dict(row) if row else None

    def positions(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM positions ORDER BY symbol")]

    def orders(self, limit: int = 200) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))]

    def equity(self, prices: dict[str, float]) -> float:
        total = self.cash
        for p in self.positions():
            total += p["qty"] * prices.get(p["symbol"], p["avg_price"])
        return total

    def record_equity(self, equity: float) -> None:
        self.conn.execute("INSERT INTO equity_history (ts, equity) VALUES (?, ?)", (_now(), equity))
        self.conn.commit()

    def equity_history(self) -> list[tuple[str, float]]:
        return [(r[0], r[1]) for r in self.conn.execute("SELECT ts, equity FROM equity_history ORDER BY ts")]

    # ---------- batas rugi harian ----------
    def day_start_equity(self, current_equity: float) -> float:
        today = date.today().isoformat()
        row = self.conn.execute("SELECT value FROM meta WHERE key = 'day_start'").fetchone()
        if row:
            d, eq = row[0].split("|")
            if d == today:
                return float(eq)
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('day_start', ?)", (f"{today}|{current_equity}",))
        self.conn.commit()
        return current_equity

    # ---------- order ----------
    def buy(self, symbol: str, qty: float, price: float, note: str = "") -> dict:
        if qty <= 0:
            raise ValueError("Qty harus > 0")
        fill = price * (1 + self.slippage_pct)
        cost = qty * fill
        fee = cost * self.fee_pct
        if cost + fee > self.cash + 1e-9:
            raise ValueError(f"Cash tidak cukup: butuh {cost + fee:,.2f}, tersedia {self.cash:,.2f}")
        pos = self.position(symbol)
        if pos:
            new_qty = pos["qty"] + qty
            avg = (pos["qty"] * pos["avg_price"] + qty * fill) / new_qty
            self.conn.execute("UPDATE positions SET qty = ?, avg_price = ? WHERE symbol = ?", (new_qty, avg, symbol))
        else:
            self.conn.execute("INSERT INTO positions (symbol, qty, avg_price, opened_at) VALUES (?, ?, ?, ?)", (symbol, qty, fill, _now()))
        self._set_cash(self.cash - cost - fee)
        self.conn.execute("INSERT INTO orders (ts, symbol, side, qty, price, fee, pnl, note) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                          (_now(), symbol, "BUY", qty, fill, fee, note))
        self.conn.commit()
        return {"side": "BUY", "symbol": symbol, "qty": qty, "price": fill, "fee": fee}

    def sell(self, symbol: str, qty: float | None, price: float, note: str = "") -> dict:
        pos = self.position(symbol)
        if not pos:
            raise ValueError(f"Tidak ada posisi {symbol}")
        qty = pos["qty"] if qty is None else min(qty, pos["qty"])
        if qty <= 0:
            raise ValueError("Qty harus > 0")
        fill = price * (1 - self.slippage_pct)
        proceeds = qty * fill
        fee = proceeds * self.fee_pct
        pnl = proceeds - fee - qty * pos["avg_price"]
        remaining = pos["qty"] - qty
        if remaining <= 1e-12:
            self.conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
        else:
            self.conn.execute("UPDATE positions SET qty = ? WHERE symbol = ?", (remaining, symbol))
        self._set_cash(self.cash + proceeds - fee)
        self.conn.execute("INSERT INTO orders (ts, symbol, side, qty, price, fee, pnl, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (_now(), symbol, "SELL", qty, fill, fee, pnl, note))
        self.conn.commit()
        return {"side": "SELL", "symbol": symbol, "qty": qty, "price": fill, "fee": fee, "pnl": pnl}

    def close(self) -> None:
        self.conn.close()

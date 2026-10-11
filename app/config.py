"""Konfigurasi aplikasi: disimpan sebagai JSON di folder data/."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
SETTINGS_FILE = DATA_DIR / "settings.json"
PAPER_DB = DATA_DIR / "paper.db"

DATA_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)


@dataclass
class RiskSettings:
    position_pct: float = 0.95        # porsi equity per posisi (0..1)
    stop_loss_pct: float = 0.03       # 3% stop loss, 0 = nonaktif
    take_profit_pct: float = 0.0      # 0 = nonaktif
    daily_loss_limit_pct: float = 0.05  # berhenti trading hari ini jika rugi > 5%
    fee_pct: float = 0.001            # 0.1% per transaksi
    slippage_pct: float = 0.0005      # 0.05%


@dataclass
class Settings:
    market: str = "Crypto"
    symbol: str = "BTC-USD"
    interval: str = "1h"
    period: str = "1y"
    strategy: str = "SMA Crossover"
    strategy_params: dict = field(default_factory=dict)
    initial_cash: float = 10_000.0
    paper_interval_min: int = 5
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"
    risk: RiskSettings = field(default_factory=RiskSettings)

    @classmethod
    def load(cls) -> "Settings":
        if not SETTINGS_FILE.exists():
            return cls()
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            risk = RiskSettings(**raw.pop("risk", {}))
            known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
            return cls(risk=risk, **known)
        except Exception:
            return cls()

    def save(self) -> None:
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

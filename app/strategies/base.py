"""Kelas dasar strategi. Strategi menghasilkan target posisi per bar: 1 = long, 0 = flat."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class Param:
    name: str
    label: str
    default: Any
    min: Any = None
    max: Any = None
    step: Any = None
    kind: str = "int"  # int | float


class Strategy:
    name: str = "Base"
    description: str = ""
    params: list[Param] = []
    # porsi awal data yang dianggap "pemanasan" (tidak ada sinyal), untuk ML = porsi training
    warmup_fraction: float = 0.0

    def __init__(self, **kwargs: Any):
        self.p: dict[str, Any] = {prm.name: prm.default for prm in self.params}
        for k, v in kwargs.items():
            if k in self.p:
                self.p[k] = v

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Kembalikan Series target posisi (0/1) sepanjang df. Dihitung dari data close bar yang sama,
        backtester akan mengeksekusi di open bar berikutnya sehingga tidak ada lookahead."""
        raise NotImplementedError

    def overlays(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        """Garis indikator yang digambar di atas chart harga."""
        return {}

    def panels(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        """Indikator yang digambar di panel terpisah (RSI, MACD, dll)."""
        return {}

    def validate(self) -> str | None:
        return None

    @classmethod
    def prepare(cls) -> None:
        """Hook opsional: persiapan yang harus terjadi di thread utama (mis. memuat library berat)."""
        return None

    def describe_params(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in self.p.items())

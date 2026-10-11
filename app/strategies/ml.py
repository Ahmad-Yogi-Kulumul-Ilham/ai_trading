"""Strategi machine learning: memprediksi arah bar berikutnya.

Backend utama: GradientBoostingClassifier (scikit-learn). Jika scikit-learn tidak bisa dimuat
(misalnya DLL-nya diblokir Windows Smart App Control), otomatis memakai regresi logistik numpy murni
sehingga strategi tetap berjalan.

Model dilatih pada porsi awal data (train_fraction) lalu dipakai untuk sisa data (out-of-sample).
Sinyal pada porsi training selalu 0 sehingga metrik backtest hanya mencerminkan data yang belum dilihat model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.indicators import feature_frame
from app.strategies.base import Param, Strategy


_SKLEARN_OK: bool | None = None


def probe_sklearn() -> bool:
    """Cek apakah scikit-learn bisa dimuat (DLL-nya bisa diblokir Windows Smart App Control). Hasil di-cache.

    GUI memanggil ini di thread utama sebelum backtest supaya impor library berat tidak terjadi di worker.
    """
    global _SKLEARN_OK
    if _SKLEARN_OK is None:
        try:
            from sklearn.ensemble import GradientBoostingClassifier  # noqa: F401
            _SKLEARN_OK = True
        except Exception:  # ImportError atau DLL diblokir
            _SKLEARN_OK = False
    return _SKLEARN_OK


def _sklearn_available() -> bool:
    return probe_sklearn()


class _NumpyLogistic:
    """Regresi logistik L2 sederhana dengan gradient descent, API mirip sklearn."""

    def __init__(self, epochs: int = 400, lr: float = 0.1, l2: float = 1e-3):
        self.epochs, self.lr, self.l2 = epochs, lr, l2
        self.w: np.ndarray | None = None
        self.b = 0.0
        self.mu: np.ndarray | None = None
        self.sd: np.ndarray | None = None

    def _scale(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mu) / self.sd

    def fit(self, X: np.ndarray, y: np.ndarray):
        self.mu = X.mean(axis=0)
        self.sd = X.std(axis=0) + 1e-9
        Xs = self._scale(X)
        n, d = Xs.shape
        self.w = np.zeros(d)
        self.b = 0.0
        for _ in range(self.epochs):
            z = Xs @ self.w + self.b
            p = 1 / (1 + np.exp(-z))
            g = p - y
            self.w -= self.lr * (Xs.T @ g / n + self.l2 * self.w)
            self.b -= self.lr * g.mean()
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        z = self._scale(X) @ self.w + self.b
        p = 1 / (1 + np.exp(-z))
        return np.column_stack([1 - p, p])

    @property
    def feature_importances_(self) -> np.ndarray:
        a = np.abs(self.w)
        return a / a.sum() if a.sum() else a


class MLDirection(Strategy):
    name = "ML Prediksi Arah"
    description = ("Model ML memprediksi probabilitas bar berikutnya naik (Gradient Boosting; fallback regresi logistik "
                   "jika scikit-learn tidak tersedia). Long jika probabilitas di atas ambang. Sinyal hanya pada data out-of-sample.")
    params = [
        Param("train_fraction", "Porsi data training", 0.6, 0.3, 0.8, 0.05, "float"),
        Param("threshold", "Ambang probabilitas long", 0.55, 0.5, 0.7, 0.01, "float"),
        Param("n_estimators", "Jumlah tree (GBM)", 150, 50, 500, 50),
        Param("max_depth", "Kedalaman tree (GBM)", 3, 2, 6, 1),
        Param("horizon", "Horizon prediksi (bar)", 1, 1, 10, 1),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_report: dict = {}
        self._proba: pd.Series | None = None

    @classmethod
    def prepare(cls) -> None:
        """Dipanggil GUI di thread utama sebelum strategi dijalankan di worker."""
        probe_sklearn()

    def _make_model(self):
        if _sklearn_available():
            from sklearn.ensemble import GradientBoostingClassifier
            return GradientBoostingClassifier(
                n_estimators=int(self.p["n_estimators"]), max_depth=int(self.p["max_depth"]),
                learning_rate=0.05, subsample=0.8, random_state=42,
            ), "sklearn GradientBoosting"
        return _NumpyLogistic(), "numpy LogisticRegression (scikit-learn tidak tersedia)"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        feats = feature_frame(df)
        horizon = int(self.p["horizon"])
        future_ret = df["close"].shift(-horizon) / df["close"] - 1
        target = (future_ret > 0).astype(int)

        valid = feats.notna().all(axis=1)
        n = len(df)
        split = int(n * float(self.p["train_fraction"]))
        if split < 100 or n - split < 20:
            self.last_report = {"error": "Data terlalu sedikit untuk ML (butuh ratusan bar)."}
            self._proba = pd.Series(np.nan, index=df.index)
            return pd.Series(0, index=df.index)

        # target bar terakhir di training harus sudah "terjadi" sebelum split (tanpa kebocoran)
        train_mask = valid & (np.arange(n) < split - horizon)
        X_train = feats[train_mask].to_numpy(float)
        y_train = target[train_mask].to_numpy()

        model, backend = self._make_model()
        model.fit(X_train, y_train)

        proba = np.full(n, np.nan)
        test_mask = valid & (np.arange(n) >= split)
        if test_mask.any():
            proba[test_mask.to_numpy()] = model.predict_proba(feats[test_mask].to_numpy(float))[:, 1]

        sig = pd.Series(0, index=df.index)
        with np.errstate(invalid="ignore"):
            sig[np.nan_to_num(proba, nan=0.0) > float(self.p["threshold"])] = 1

        eval_mask = test_mask & (np.arange(n) < n - horizon)
        report = {"backend": backend, "train_bars": int(train_mask.sum()), "test_bars": int(test_mask.sum())}
        if eval_mask.any():
            pred = (proba[eval_mask.to_numpy()] > 0.5).astype(int)
            acc = float((pred == target[eval_mask].to_numpy()).mean())
            report["oos_accuracy"] = round(acc, 4)
            report["feature_importance"] = dict(sorted(
                zip(feats.columns, np.round(model.feature_importances_, 4).tolist()),
                key=lambda kv: -kv[1])[:6])
        self.last_report = report
        self._proba = pd.Series(proba, index=df.index)
        return sig

    def panels(self, df):
        if self._proba is None:
            self.generate_signals(df)
        return {"Prob. naik": self._proba}


# alias kompatibilitas
GradientBoostingDirection = MLDirection

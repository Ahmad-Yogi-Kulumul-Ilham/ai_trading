"""Chart candlestick berbasis pyqtgraph dengan overlay indikator, panel bawah, dan penanda trade."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

pg.setConfigOptions(antialias=False, background="#111418", foreground="#c9d1d9")

UP = "#26a69a"
DOWN = "#ef5350"
OVERLAY_COLORS = ["#ffb74d", "#64b5f6", "#ba68c8", "#aed581", "#f06292", "#4dd0e1"]


class IndexDateAxis(pg.AxisItem):
    """Sumbu X memakai index integer (tanpa gap akhir pekan) tapi label berupa tanggal."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timestamps: list[pd.Timestamp] = []
        self.fmt = "%d %b %H:%M"

    def set_timestamps(self, ts: pd.DatetimeIndex, interval: str):
        self.timestamps = list(ts)
        self.fmt = "%d %b %Y" if interval in ("1d", "1wk") else ("%d %b %H:%M" if interval in ("1h", "30m") else "%H:%M")

    def tickStrings(self, values, scale, spacing):
        out = []
        n = len(self.timestamps)
        for v in values:
            i = int(round(v))
            if 0 <= i < n:
                out.append(self.timestamps[i].strftime(self.fmt))
            else:
                out.append("")
        return out


class CandlestickItem(pg.GraphicsObject):
    def __init__(self, df: pd.DataFrame):
        super().__init__()
        self.picture = QtGui.QPicture()
        self._rect = QtCore.QRectF()
        self.set_data(df)

    def set_data(self, df: pd.DataFrame):
        self.picture = QtGui.QPicture()
        if df is None or df.empty:
            self._rect = QtCore.QRectF()
            self.update()
            return
        p = QtGui.QPainter(self.picture)
        w = 0.35
        o = df["open"].to_numpy(); c = df["close"].to_numpy()
        h = df["high"].to_numpy(); l = df["low"].to_numpy()
        pen_up, pen_down = pg.mkPen(UP, width=1), pg.mkPen(DOWN, width=1)
        brush_up, brush_down = pg.mkBrush(UP), pg.mkBrush(DOWN)
        for i in range(len(df)):
            up = c[i] >= o[i]
            p.setPen(pen_up if up else pen_down)
            p.setBrush(brush_up if up else brush_down)
            p.drawLine(QtCore.QPointF(i, l[i]), QtCore.QPointF(i, h[i]))
            body = c[i] - o[i]
            if abs(body) < 1e-12:
                p.drawLine(QtCore.QPointF(i - w, o[i]), QtCore.QPointF(i + w, o[i]))
            else:
                p.drawRect(QtCore.QRectF(i - w, o[i], 2 * w, body))
        p.end()
        self._rect = QtCore.QRectF(-1, float(l.min()), len(df) + 1, float(h.max() - l.min()))
        self.prepareGeometryChange()
        self.update()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return self._rect


class ChartWidget(QtWidgets.QWidget):
    """Plot harga (candlestick + overlay + trade) dan panel indikator opsional di bawahnya."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.glw = pg.GraphicsLayoutWidget()
        layout.addWidget(self.glw)

        self.axis_price = IndexDateAxis(orientation="bottom")
        self.price_plot: pg.PlotItem = self.glw.addPlot(row=0, col=0, axisItems={"bottom": self.axis_price})
        self.price_plot.showGrid(x=True, y=True, alpha=0.15)
        self.price_plot.addLegend(offset=(10, 10))
        self.price_plot.setDownsampling(mode="peak")
        self.price_plot.setClipToView(True)

        self.axis_panel = IndexDateAxis(orientation="bottom")
        self.panel_plot: pg.PlotItem = self.glw.addPlot(row=1, col=0, axisItems={"bottom": self.axis_panel})
        self.panel_plot.showGrid(x=True, y=True, alpha=0.15)
        self.panel_plot.setXLink(self.price_plot)
        self.panel_plot.addLegend(offset=(10, 10))
        self.glw.ci.layout.setRowStretchFactor(0, 4)
        self.glw.ci.layout.setRowStretchFactor(1, 1)
        self.panel_plot.hide()

        self.candles = CandlestickItem(pd.DataFrame())
        self.price_plot.addItem(self.candles)
        self._overlay_items: list = []
        self._panel_items: list = []
        self._trade_items: list = []

        # crosshair + label
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#888", style=QtCore.Qt.DashLine))
        self.hline = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("#888", style=QtCore.Qt.DashLine))
        self.price_plot.addItem(self.vline, ignoreBounds=True)
        self.price_plot.addItem(self.hline, ignoreBounds=True)
        self.label = pg.TextItem(anchor=(0, 1), color="#e6edf3", fill=pg.mkBrush(0, 0, 0, 160))
        self.price_plot.addItem(self.label, ignoreBounds=True)
        self.proxy = pg.SignalProxy(self.price_plot.scene().sigMouseMoved, rateLimit=40, slot=self._on_mouse)
        self.df: pd.DataFrame | None = None

    def _on_mouse(self, evt):
        if self.df is None or self.df.empty:
            return
        pos = evt[0]
        if not self.price_plot.sceneBoundingRect().contains(pos):
            return
        mp = self.price_plot.vb.mapSceneToView(pos)
        i = int(round(mp.x()))
        self.vline.setPos(mp.x())
        self.hline.setPos(mp.y())
        if 0 <= i < len(self.df):
            row = self.df.iloc[i]
            ts = self.df.index[i].strftime("%Y-%m-%d %H:%M")
            self.label.setHtml(
                f"<span style='font-size:9pt'>{ts}<br>O {row['open']:.4g}  H {row['high']:.4g}  "
                f"L {row['low']:.4g}  C {row['close']:.4g}<br>Vol {row['volume']:,.0f}</span>")
            vr = self.price_plot.vb.viewRange()
            self.label.setPos(vr[0][0], vr[1][1])

    def clear_dynamic(self):
        for it in self._overlay_items + self._trade_items:
            self.price_plot.removeItem(it)
        for it in self._panel_items:
            self.panel_plot.removeItem(it)
        self._overlay_items, self._panel_items, self._trade_items = [], [], []
        self.price_plot.legend.clear()
        self.panel_plot.legend.clear()

    def set_data(self, df: pd.DataFrame, interval: str, overlays: dict[str, pd.Series] | None = None,
                 panels: dict[str, pd.Series] | None = None, trades: pd.DataFrame | None = None, title: str = ""):
        self.df = df
        self.clear_dynamic()
        self.candles.set_data(df)
        self.axis_price.set_timestamps(df.index, interval)
        self.axis_panel.set_timestamps(df.index, interval)
        self.price_plot.setTitle(title)
        x = np.arange(len(df))

        for k, (name, series) in enumerate((overlays or {}).items()):
            y = series.reindex(df.index).to_numpy(float)
            item = self.price_plot.plot(x, y, pen=pg.mkPen(OVERLAY_COLORS[k % len(OVERLAY_COLORS)], width=1.3), name=name, connect="finite")
            self._overlay_items.append(item)

        if panels:
            self.panel_plot.show()
            for k, (name, series) in enumerate(panels.items()):
                y = series.reindex(df.index).to_numpy(float)
                item = self.panel_plot.plot(x, y, pen=pg.mkPen(OVERLAY_COLORS[(k + 1) % len(OVERLAY_COLORS)], width=1.2), name=name, connect="finite")
                self._panel_items.append(item)
                lname = name.lower()
                if "rsi" in lname:
                    for lvl in (30, 70):
                        ln = pg.InfiniteLine(pos=lvl, angle=0, pen=pg.mkPen("#666", style=QtCore.Qt.DotLine))
                        self.panel_plot.addItem(ln); self._panel_items.append(ln)
                elif "prob" in lname:
                    ln = pg.InfiniteLine(pos=0.5, angle=0, pen=pg.mkPen("#666", style=QtCore.Qt.DotLine))
                    self.panel_plot.addItem(ln); self._panel_items.append(ln)
                elif "macd" in lname:
                    ln = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#666", style=QtCore.Qt.DotLine))
                    self.panel_plot.addItem(ln); self._panel_items.append(ln)
        else:
            self.panel_plot.hide()

        if trades is not None and not trades.empty:
            pos_map = {ts: i for i, ts in enumerate(df.index)}
            ex = [pos_map.get(t) for t in trades["entry_time"]]
            ey = trades["entry_price"].to_numpy(float)
            xx = [pos_map.get(t) for t in trades["exit_time"]]
            xy = trades["exit_price"].to_numpy(float)
            ok_e = [i for i, v in enumerate(ex) if v is not None]
            ok_x = [i for i, v in enumerate(xx) if v is not None]
            if ok_e:
                sc = pg.ScatterPlotItem([ex[i] for i in ok_e], ey[ok_e] * 0.995, symbol="t1", size=11,
                                        brush=pg.mkBrush(UP), pen=pg.mkPen("w", width=0.5), name="Entry")
                self.price_plot.addItem(sc); self._trade_items.append(sc)
            if ok_x:
                sc = pg.ScatterPlotItem([xx[i] for i in ok_x], xy[ok_x] * 1.005, symbol="t", size=11,
                                        brush=pg.mkBrush(DOWN), pen=pg.mkPen("w", width=0.5), name="Exit")
                self.price_plot.addItem(sc); self._trade_items.append(sc)

        n = len(df)
        if n:
            lo = float(df["low"].iloc[-300:].min()); hi = float(df["high"].iloc[-300:].max())
            self.price_plot.setXRange(max(0, n - 300), n + 2, padding=0)
            self.price_plot.setYRange(lo, hi, padding=0.05)
            self.price_plot.vb.setLimits(xMin=-5, xMax=n + 50)


class EquityWidget(pg.PlotWidget):
    def __init__(self, parent=None):
        super().__init__(parent, axisItems={"bottom": IndexDateAxis(orientation="bottom")})
        self.showGrid(x=True, y=True, alpha=0.15)
        self.addLegend(offset=(10, 10))
        self.setLabel("left", "Equity")

    def set_curves(self, equity: pd.Series, buy_hold: pd.Series | None, interval: str):
        self.clear()
        self.plotItem.legend.clear()
        axis = self.getAxis("bottom")
        if isinstance(axis, IndexDateAxis):
            axis.set_timestamps(equity.index, interval)
        x = np.arange(len(equity))
        self.plot(x, equity.to_numpy(float), pen=pg.mkPen("#4dd0e1", width=2), name="Strategi")
        if buy_hold is not None:
            self.plot(x, buy_hold.reindex(equity.index).to_numpy(float), pen=pg.mkPen("#9e9e9e", width=1.2, style=QtCore.Qt.DashLine), name="Buy & Hold")
        dd = equity / equity.cummax() - 1
        self.plot(x, equity.iloc[0] * (1 + dd.to_numpy(float)), pen=pg.mkPen("#ef5350", width=1), name="Drawdown (skala equity awal)")
        self.autoRange()

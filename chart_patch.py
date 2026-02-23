# chart_patch.py
"""
차트 렌더링 패치 — 이 파일만 수정하면 차트가 바뀜.
perf_real.py, Perf_Test.py 수정 불필요.
"""

def apply():
    """Perf_Test.ChartSubWindow.add_candle을 런타임 패치"""
    try:
        import Perf_Test as pt
        import pyqtgraph as pg
        import numpy as np
    except ImportError:
        print("[chart_patch] import failed — skipping")
        return

    def add_candle(self, o, h, l, c, v, idx):
        o, h, l, c, v = abs(o), abs(h), abs(l), abs(c), abs(v)
        if c <= 0:
            return
        if o <= 0:
            o = c
        if h <= 0:
            h = max(o, c)
        if l <= 0:
            l = min(o, c)
        h = max(h, o, c)
        l = min(l, o, c)

        self._candles.append(
            {"o": o, "h": h, "l": l, "c": c, "v": v, "idx": idx})

        color = pt.Theme.BULL if c >= o else pt.Theme.BEAR

        # 심지
        wick = pg.PlotDataItem(
            [idx, idx], [l, h], pen=pg.mkPen(color, width=1))
        self.chart_widget.addItem(wick)

        # 몸통
        bb = min(o, c)
        bh = abs(c - o)
        if bh < (h - l) * 0.01 + 0.5:
            bh = max(1.0, (h - l) * 0.03, h * 0.0003)
            bb = c - bh / 2

        body = pg.BarGraphItem(
            x=[idx], height=[bh], width=0.6, y0=[bb],
            brush=pg.mkBrush(color),
            pen=pg.mkPen(color, width=0.5))
        self.chart_widget.addItem(body)
        self._candle_items.append((wick, body))

        # 오래된 캔들 제거
        while len(self._candles) > self._max_candles:
            self._candles.pop(0)
            ow, ob = self._candle_items.pop(0)
            self.chart_widget.removeItem(ow)
            self.chart_widget.removeItem(ob)

        # 거래량
        try:
            self.volume_bars.setOpts(
                x=[c_["idx"] for c_ in self._candles],
                height=[c_["v"] for c_ in self._candles],
                width=0.6)
        except Exception:
            pass

        # 이동평균
        try:
            closes = [c_["c"] for c_ in self._candles]
            idxs = [c_["idx"] for c_ in self._candles]
            for period, mi in self.ma_lines.items():
                if len(closes) >= period:
                    ma = np.convolve(
                        closes, np.ones(period) / period, "valid")
                    start = len(closes) - len(ma)
                    mi["line"].setData(idxs[start:], list(ma))
        except Exception:
            pass

        # 자동 범위 — 최근 60봉
        try:
            vis = self._candles[-min(60, len(self._candles)):]
            if vis:
                mn = min(c_["l"] for c_ in vis)
                mx = max(c_["h"] for c_ in vis)
                mg = (mx - mn) * 0.05 + 1
                self.chart_widget.setXRange(
                    vis[0]["idx"] - 2, vis[-1]["idx"] + 5, padding=0)
                self.chart_widget.setYRange(
                    mn - mg, mx + mg, padding=0)
        except Exception:
            pass

        # 가격 라벨
        self.lbl_price.setText(f"{c:,.0f}")
        cp = (c - o) / o * 100 if o else 0
        self.lbl_change.setText(f"{cp:+.2f}%")
        self.lbl_change.setStyleSheet(
            f"color: {pt.Theme.BULL if cp > 0 else pt.Theme.BEAR};")

    pt.ChartSubWindow.add_candle = add_candle
    print("[chart_patch] applied")

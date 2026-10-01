"""Right column: true-peak bar meters (dBTP) and the mid/side triangle display."""
from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ..dsp.loudness import Snapshot
from . import theme
from .theme import NEG_INF, font

SCALE_LABELS = [0, -6, -12, -18, -24, -30, -40, -50, -60]
FALL_DB_PER_S = 24.0
HOLD_S = 1.5
HOLD_FALL_DB_PER_S = 12.0


def yfrac(db: float) -> float:
    """Map dBTP to 0 (top, 0 dB) .. 1 (bottom, -60 dB): 0..-30 uses 2/3 of the height."""
    if db == NEG_INF:
        return 1.0
    if db >= -30.0:
        f = (0.0 - db) / 30.0 * (2.0 / 3.0)
    else:
        f = 2.0 / 3.0 + (-30.0 - db) / 30.0 / 3.0
    return max(0.0, min(1.0, f))


class TruePeakBars(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.snap = Snapshot()
        self.peak_alert_dbtp = -1.0
        self.names = ["L", "R"]
        self.level = [NEG_INF, NEG_INF]
        self.hold = [NEG_INF, NEG_INF]
        self.hold_time = [0.0, 0.0]
        self._last = time.monotonic()
        self.setMinimumWidth(150)

    def set_mono(self, mono: bool) -> None:
        self.names = ["M"] if mono else ["L", "R"]
        self.update()

    def set_snapshot(self, snap: Snapshot) -> None:
        now = time.monotonic()
        dt = max(0.0, min(0.5, now - self._last))
        self._last = now
        recent = snap.true_peak_recent_ch
        for i in range(len(self.names)):
            v = float(recent[i]) if i < len(recent) else NEG_INF
            fallen = self.level[i] - FALL_DB_PER_S * dt if self.level[i] != NEG_INF else NEG_INF
            self.level[i] = max(v, fallen)
            if v != NEG_INF and v >= self.hold[i]:
                self.hold[i] = v
                self.hold_time[i] = now
            elif now - self.hold_time[i] > HOLD_S and self.hold[i] != NEG_INF:
                self.hold[i] -= HOLD_FALL_DB_PER_S * dt
            if self.hold[i] < -60:
                self.hold[i] = NEG_INF
            if self.level[i] < -60:
                self.level[i] = NEG_INF
        self.snap = snap
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), theme.BG)
        scale = min(w / 300.0, h / 400.0)
        label_w = 52 * scale
        top = 36 * scale
        bottom = h - 16 * scale
        bar_area_left = label_w + 10 * scale
        bar_area_right = w - 16 * scale
        n = len(self.names)
        slot = (bar_area_right - bar_area_left) / n
        bar_w = slot * 0.55

        # Header
        p.setPen(theme.TEXT)
        p.setFont(font(16 * scale))
        p.drawText(QRectF(4 * scale, 6 * scale, label_w, 24 * scale),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "dBTP")
        for i, name in enumerate(self.names):
            cx = bar_area_left + slot * (i + 0.5)
            p.drawText(QRectF(cx - 20 * scale, 6 * scale, 40 * scale, 24 * scale),
                       int(Qt.AlignmentFlag.AlignCenter), name)

        # Scale labels + ticks
        p.setFont(font(14 * scale))
        for db in SCALE_LABELS:
            y = top + yfrac(db) * (bottom - top)
            p.setPen(theme.TEXT)
            p.drawText(QRectF(0, y - 10 * scale, label_w, 20 * scale),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"{db}")
            p.setPen(QPen(theme.DIM, 1))
            p.drawLine(QPointF(label_w + 3 * scale, y), QPointF(label_w + 8 * scale, y))

        for i in range(n):
            cx = bar_area_left + slot * (i + 0.5)
            x0 = cx - bar_w / 2
            # Background track with minor ticks
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.PANEL_LINE)
            p.drawRect(QRectF(x0, top, bar_w, bottom - top))
            p.setPen(QPen(theme.DIMMER, 1))
            for db in range(-60, 1, 2):
                y = top + yfrac(db) * (bottom - top)
                p.drawLine(QPointF(x0 + bar_w, y), QPointF(x0 + bar_w + 4 * scale, y))
            # Level
            lvl = self.level[i]
            if lvl != NEG_INF:
                y_lvl = top + yfrac(lvl) * (bottom - top)
                y_alert = top + yfrac(self.peak_alert_dbtp) * (bottom - top)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.YELLOW)
                p.drawRect(QRectF(x0, max(y_lvl, y_alert), bar_w, bottom - max(y_lvl, y_alert)))
                if y_lvl < y_alert:
                    p.setBrush(theme.RED)
                    p.drawRect(QRectF(x0, y_lvl, bar_w, y_alert - y_lvl))
                # Segment lines for the LED look
                p.setPen(QPen(theme.BG, 1))
                yy = bottom
                while yy > y_lvl:
                    p.drawLine(QPointF(x0, yy), QPointF(x0 + bar_w, yy))
                    yy -= 4 * scale
            # Hold marker
            hold = self.hold[i]
            if hold != NEG_INF:
                y_hold = top + yfrac(hold) * (bottom - top)
                color = theme.RED if hold > self.peak_alert_dbtp else theme.TEXT
                p.setPen(QPen(color, max(1.0, 2.0 * scale)))
                p.drawLine(QPointF(x0, y_hold), QPointF(x0 + bar_w, y_hold))
        p.end()


class MidSideWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.snap = Snapshot()
        self.setMinimumHeight(120)

    def set_snapshot(self, snap: Snapshot) -> None:
        self.snap = snap
        self.update()

    @staticmethod
    def _frac(db: float) -> float:
        if db == NEG_INF:
            return 0.0
        return max(0.0, min(1.0, (db + 60.0) / 60.0))

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), theme.BG)
        scale = min(w / 300.0, h / 230.0)
        cx = w / 2
        base_y = h - 26 * scale
        R = min(w * 0.30, base_y - 34 * scale)

        p.setPen(theme.TEXT)
        p.setFont(font(15 * scale))
        p.drawText(QRectF(cx - 80 * scale, 6 * scale, 160 * scale, 22 * scale),
                   int(Qt.AlignmentFlag.AlignCenter), "Mid/Side")
        p.drawText(QRectF(cx - R - 70 * scale, base_y - 40 * scale, 60 * scale, 22 * scale),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), "Left")
        p.drawText(QRectF(cx + R + 10 * scale, base_y - 40 * scale, 60 * scale, 22 * scale),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "Right")

        # Semicircle and baseline
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.DIM, max(1.0, 1.2 * scale)))
        p.drawArc(QRectF(cx - R, base_y - R, 2 * R, 2 * R), 0, 180 * 16)
        p.drawLine(QPointF(cx - R, base_y), QPointF(cx + R, base_y))

        # Triangle: height = mid level, half-width = side level, lean = balance
        mid = self._frac(self.snap.mid_db)
        side = self._frac(self.snap.side_db)
        half = max(2.0 * scale, side * R * 0.7)
        apex_x = cx + max(-1.0, min(1.0, self.snap.balance)) * R * 0.6
        apex_y = base_y - mid * R
        half = min(half, R - abs(apex_x - cx))
        p.setPen(QPen(theme.YELLOW, max(1.0, 2.0 * scale)))
        p.drawPolyline(QPolygonF([QPointF(apex_x - half, base_y), QPointF(apex_x, apex_y),
                                  QPointF(apex_x + half, base_y)]))
        p.end()

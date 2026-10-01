"""Loudness radar: short-term history sweeping around a target ring,
with a momentary loudness arc on the outer scale, Peak/Loud lamps,
preset name and elapsed time, in the style of the TC Electronic Clarity M."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..dsp.loudness import Snapshot
from . import theme
from .theme import NEG_INF, fmt, font, hms, pt, text_at

HOLE = 0.2  # inner dead zone as a fraction of radar radius
BAND_EDGES = [0.0, 0.4, 0.6, 0.8, 1.0, 1.22]  # bands: <-18, -18..-12, -12..-6, -6..0, >0 LU rel. target
RING_START_DEG = 180.0  # momentary arc starts at 6 o'clock
RING_SPAN_DEG = 300.0
RING_LOW_LU = -36
RING_HIGH_LU = 18


class RadarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.snap = Snapshot()
        self.target = -24.0
        self.preset_name = "ATSC A/85"
        self.paused = False
        self.setMinimumSize(360, 280)

    def set_snapshot(self, snap: Snapshot) -> None:
        self.snap = snap
        self.update()

    # ------------------------------------------------------------------ helpers
    def _rfrac(self, values: np.ndarray) -> np.ndarray:
        lo = self.target - 24.0
        f = HOLE + (1.0 - HOLE) * (values - lo) / 24.0
        f = np.where(np.isfinite(values), f, 0.0)
        return np.clip(f, 0.0, BAND_EDGES[-1])

    def _ring_angle(self, lufs: float) -> float:
        """Outer scale angle: target sits at 12 o'clock, RING_LOW_LU at 6 o'clock,
        RING_HIGH_LU at the end of the span (about 4 o'clock)."""
        lu = max(RING_LOW_LU, min(RING_HIGH_LU, lufs - self.target))
        below_span = 360.0 - RING_START_DEG
        above_span = RING_SPAN_DEG - below_span
        if lu <= 0:
            return 360.0 + lu / (-RING_LOW_LU) * below_span
        return 360.0 + lu / RING_HIGH_LU * above_span

    # ------------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), theme.BG)

        scale = min(w / 640.0, h / 700.0)
        cx = w * 0.46
        cy = h * 0.50
        ring_r = min(w * 0.34, h * 0.39)
        radar_r = ring_r * 0.78

        self._draw_fill(p, cx, cy, radar_r)
        self._draw_grid(p, cx, cy, radar_r, scale)
        self._draw_momentary_ring(p, cx, cy, ring_r, scale)
        self._draw_lamps(p, w, h, scale)
        self._draw_footer(p, w, h, scale)
        p.end()

    @staticmethod
    def _smooth(rf: np.ndarray, width: int = 5) -> np.ndarray:
        """Circular moving average of the radius profile, ignoring empty slots."""
        valid = (rf > 0).astype(float)
        kernel = np.ones(width)
        num = np.convolve(np.concatenate([rf[-width:], rf, rf[:width]]) * np.concatenate(
            [valid[-width:], valid, valid[:width]]), kernel, mode="same")[width:-width]
        den = np.convolve(np.concatenate([valid[-width:], valid, valid[:width]]), kernel,
                          mode="same")[width:-width]
        out = np.where(den > 0, num / np.maximum(den, 1e-9), 0.0)
        return np.where(valid > 0, out, 0.0)

    def _draw_fill(self, p: QPainter, cx: float, cy: float, R: float) -> None:
        radar = self.snap.radar
        n = len(radar)
        if n == 0:
            return
        rf = self._smooth(self._rfrac(radar))
        # Blank a small wedge just ahead of the sweep head.
        head_frac = self.snap.radar_head
        head = int(head_frac * n) % n
        gap = max(2, n // 72)
        idx = (head + 1 + np.arange(gap)) % n
        rf[idx] = 0.0

        theta = np.arange(n) / n * 2.0 * math.pi
        sx = np.sin(theta)
        sy = -np.cos(theta)
        p.setPen(Qt.PenStyle.NoPen)
        for k in range(len(BAND_EDGES) - 1):
            lo, hi = BAND_EDGES[k], BAND_EDGES[k + 1]
            r = np.clip(rf, lo, hi)
            if not (r > lo + 1e-9).any():
                continue
            ox = cx + r * R * sx
            oy = cy + r * R * sy
            path = QPainterPath(QPointF(ox[0], oy[0]))
            for i in range(1, n):
                path.lineTo(ox[i], oy[i])
            if lo > 0:
                # Return along the inner circle counter-clockwise back to the top.
                qt_angle = 90.0 - (n - 1) / n * 360.0
                path.arcTo(QRectF(cx - lo * R, cy - lo * R, 2 * lo * R, 2 * lo * R),
                           qt_angle, 360.0 - (360.0 / n))
            else:
                path.lineTo(cx, cy)
            path.closeSubpath()
            p.setBrush(QBrush(theme.RADAR_BANDS[k]))
            p.drawPath(path)
        # Sweep head line
        p.setPen(QPen(QColor(255, 255, 255, 90), max(1.0, R * 0.004)))
        p.drawLine(pt(cx, cy, HOLE * R, head_frac * 360.0), pt(cx, cy, R * BAND_EDGES[-1], head_frac * 360.0))

    def _draw_grid(self, p: QPainter, cx: float, cy: float, R: float, scale: float) -> None:
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Spokes
        p.setPen(QPen(QColor(255, 255, 255, 40), max(1.0, 1.0 * scale)))
        for deg in range(0, 360, 30):
            p.drawLine(pt(cx, cy, HOLE * R, deg), pt(cx, cy, R, deg))
        # Rings
        for frac in (0.4, 0.6, 0.8):
            p.setPen(QPen(QColor(255, 255, 255, 60), max(1.0, 1.0 * scale)))
            p.drawEllipse(QPointF(cx, cy), frac * R, frac * R)
        p.setPen(QPen(theme.BLUE, max(1.0, 1.5 * scale)))
        p.drawEllipse(QPointF(cx, cy), R, R)
        # Centre hole
        p.setPen(QPen(QColor("#3a3a3a"), max(1.0, 1.0 * scale)))
        p.setBrush(QBrush(QColor("#050505")))
        p.drawEllipse(QPointF(cx, cy), HOLE * R, HOLE * R)
        # Ring labels along the 12 o'clock spoke
        p.setFont(font(15 * scale))
        for frac, lu, color in ((1.0, 0, theme.BLUE), (0.8, -6, theme.DIM), (0.6, -12, theme.DIM)):
            p.setPen(color)
            text_at(p, cx - 22 * scale, cy - (frac - 0.07) * R, f"{self.target + lu:.0f}",
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, w=80 * scale)

    def _draw_momentary_ring(self, p: QPainter, cx: float, cy: float, R: float, scale: float) -> None:
        m = self.snap.momentary
        value_angle = self._ring_angle(m) if m != NEG_INF else RING_START_DEG
        target_angle = self._ring_angle(self.target)
        tick_len = R * 0.045
        p.setBrush(Qt.BrushStyle.NoBrush)
        step = 1.5
        deg = RING_START_DEG
        while deg <= RING_START_DEG + RING_SPAN_DEG + 1e-6:
            if m != NEG_INF and deg <= value_angle:
                color = theme.YELLOW if deg > target_angle else theme.BLUE
                width = 3.0 * scale
            else:
                color = theme.TICK
                width = 2.0 * scale
            p.setPen(QPen(color, max(1.0, width)))
            p.drawLine(pt(cx, cy, R - tick_len, deg), pt(cx, cy, R + tick_len, deg))
            deg += step
        # Scale labels every 6 LU
        p.setPen(theme.TEXT)
        p.setFont(font(17 * scale))
        for lu in range(RING_LOW_LU, RING_HIGH_LU + 1, 6):
            deg = self._ring_angle(self.target + lu)
            pos = pt(cx, cy, R * 1.16, deg)
            text_at(p, pos.x(), pos.y(), f"{self.target + lu:.0f}", w=90 * scale, h=30 * scale)

    def _draw_lamps(self, p: QPainter, w: int, h: int, scale: float) -> None:
        size = 14 * scale
        p.setFont(font(17 * scale))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.RED if self.snap.peak_alert else theme.RED_OFF)
        p.drawRect(QRectF(18 * scale, 20 * scale, size, size))
        p.setPen(theme.TEXT)
        p.drawText(QRectF(18 * scale + size + 8 * scale, 14 * scale, 120 * scale, 26 * scale),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "Peak")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.RED if self.snap.loud_alert else theme.RED_OFF)
        p.drawRect(QRectF(w - 18 * scale - size, 20 * scale, size, size))
        p.setPen(theme.TEXT)
        p.drawText(QRectF(w - 18 * scale - size - 128 * scale, 14 * scale, 120 * scale, 26 * scale),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), "Loud")

    def _draw_footer(self, p: QPainter, w: int, h: int, scale: float) -> None:
        # Preset (bottom-left)
        p.setPen(theme.TEXT)
        p.setFont(font(15 * scale))
        p.drawText(QRectF(18 * scale, h - 62 * scale, 300 * scale, 22 * scale),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   "Paused:" if self.paused else "Preset:")
        p.setFont(font(21 * scale))
        p.drawText(QRectF(18 * scale, h - 40 * scale, 360 * scale, 28 * scale),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self.preset_name)
        # LUFS + elapsed time (bottom-right)
        right = w - 22 * scale
        p.setPen(theme.DIM)
        p.setFont(font(30 * scale))
        p.drawText(QRectF(right - 260 * scale, h - 118 * scale, 260 * scale, 36 * scale),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), "LUFS")
        p.setPen(theme.TEXT)
        p.setFont(font(34 * scale))
        p.drawText(QRectF(right - 260 * scale, h - 84 * scale, 260 * scale, 40 * scale),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), hms(self.snap.elapsed_s))
        p.setPen(theme.DIM)
        p.setFont(font(13 * scale, QFont.Weight.Bold))
        p.drawText(QRectF(right - 260 * scale, h - 44 * scale, 260 * scale, 18 * scale),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), "DANTE LUFS")
        p.setFont(font(10 * scale))
        p.drawText(QRectF(right - 260 * scale, h - 28 * scale, 260 * scale, 16 * scale),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                   f"STEREO LOUDNESS METER  ·  S {fmt(self.snap.short_term)}")

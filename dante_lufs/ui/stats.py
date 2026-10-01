"""Centre column: input name, numeric loudness readouts and the correlation meter."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..dsp.loudness import Snapshot
from . import theme
from .theme import fmt, font


class StatsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.snap = Snapshot()
        self.source_name = "No input"
        self.source_ok = False
        self.mono = False
        self.setMinimumWidth(220)

    def set_snapshot(self, snap: Snapshot) -> None:
        self.snap = snap
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), theme.BG)
        scale = min(w / 330.0, h / 640.0)
        left = 14 * scale
        right = w - 14 * scale

        # Header: source indicator
        y = 14 * scale
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.GREEN if self.source_ok else theme.RED)
        p.drawRect(QRectF(left, y + 6 * scale, 14 * scale, 14 * scale))
        p.setPen(theme.TEXT)
        p.setFont(font(19 * scale))
        p.drawText(QRectF(left + 24 * scale, y, right - left - 24 * scale, 26 * scale),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   p.fontMetrics().elidedText(self.source_name, Qt.TextElideMode.ElideRight,
                                              int(right - left - 24 * scale)))

        s = self.snap
        # (label, value, unit, big). Live values (M/S) share one compact row so the
        # long-term readouts keep the Clarity M layout.
        rows = [
            ("Program Loudness", fmt(s.integrated), "LUFS", True),
            ("Short-term  /  Momentary", f"{fmt(s.short_term)}  /  {fmt(s.momentary)}", "LUFS", False),
            ("True-peak Max", fmt(s.true_peak_max), "dBTP", True),
            ("Loudness Max (M)", fmt(s.max_momentary), "LUFS", True),
            ("Loudness Range", fmt(s.lra), "LU", True),
            ("Peak to Loudness", fmt(s.plr), "dB", True),
        ]
        top = 50 * scale
        corr_h = 96 * scale
        weights = [1.0 if big else 0.72 for _, _, _, big in rows]
        unit_h = (h - top - corr_h) / sum(weights)
        unit_w = 64 * scale
        ry = top
        for (label, value, unit, big), wgt in zip(rows, weights):
            row_h = unit_h * wgt
            p.setPen(theme.TEXT)
            p.setFont(font(17 * scale))
            p.drawText(QRectF(left, ry + 4 * scale, right - left, 24 * scale),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
            p.setPen(theme.YELLOW if big else theme.TEXT)
            size = min(44 * scale, row_h * 0.52) if big else min(26 * scale, row_h * 0.5)
            p.setFont(font(size, QFont.Weight.Light if big else QFont.Weight.Normal))
            p.drawText(QRectF(left, ry + 26 * scale, right - left - unit_w, row_h - 30 * scale),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), value)
            p.setPen(theme.DIM)
            p.setFont(font(16 * scale))
            p.drawText(QRectF(right - unit_w + 6 * scale, ry + 26 * scale, unit_w - 6 * scale, row_h - 30 * scale),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), unit)
            p.setPen(QPen(theme.PANEL_LINE, 1))
            p.drawLine(QRectF(left, ry + row_h - 1, right - left, 1).topLeft(),
                       QRectF(left, ry + row_h - 1, right - left, 1).topRight())
            ry += row_h

        self._draw_correlation(p, left, right, h - corr_h, corr_h, scale)
        p.end()

    def _draw_correlation(self, p: QPainter, left: float, right: float, top: float,
                          height: float, scale: float) -> None:
        p.setPen(theme.TEXT)
        p.setFont(font(17 * scale))
        p.drawText(QRectF(left, top + 6 * scale, right - left, 24 * scale),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "Correlation")
        if self.mono:
            p.setPen(theme.DIM)
            p.setFont(font(14 * scale))
            p.drawText(QRectF(left, top + 34 * scale, right - left, 40 * scale),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                       "Mono input, metered as dual-mono (EBU Tech 3343)")
            return
        label_w = 36 * scale
        bar_left = left
        bar_right = right - label_w
        mid = (bar_left + bar_right) / 2
        # Scale line
        y_scale = top + 40 * scale
        p.setPen(theme.DIM)
        p.setFont(font(13 * scale))
        p.drawText(QRectF(bar_left - 4 * scale, y_scale - 10 * scale, 20 * scale, 16 * scale),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "-")
        p.drawText(QRectF(mid - 10 * scale, y_scale - 10 * scale, 20 * scale, 16 * scale),
                   int(Qt.AlignmentFlag.AlignCenter), "0")
        p.drawText(QRectF(bar_right - 14 * scale, y_scale - 10 * scale, 20 * scale, 16 * scale),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), "+")
        p.setPen(QPen(theme.DIMMER, 1))
        for k in range(-4, 5):
            x = mid + k * (bar_right - bar_left) / 8
            p.drawLine(int(x), int(y_scale + 7 * scale), int(x), int(y_scale + 9 * scale))
        # Segments
        n_half = 16
        seg_w = (bar_right - bar_left) / (2 * n_half + 1)
        y_bar = y_scale + 12 * scale
        bar_h = 12 * scale
        corr = max(-1.0, min(1.0, self.snap.correlation))
        active = int(round(abs(corr) * n_half))
        p.setPen(Qt.PenStyle.NoPen)
        for k in range(-n_half, n_half + 1):
            x = mid + k * seg_w - seg_w / 2
            if k == 0:
                color = theme.TEXT
            elif k > 0 and corr > 0 and k <= active:
                color = theme.CYAN
            elif k < 0 and corr < 0 and -k <= active:
                color = theme.ORANGE
            else:
                color = theme.PANEL_LINE
            p.setBrush(color)
            p.drawRect(QRectF(x + 1, y_bar, max(1.0, seg_w - 2), bar_h))
        p.setPen(theme.DIM)
        p.setFont(font(13 * scale))
        p.drawText(QRectF(bar_right + 4 * scale, y_bar - 2 * scale, label_w, bar_h + 4 * scale),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "L/R")

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
        rows = [
            ("Program Loudness", fmt(s.integrated), "LUFS"),
            ("True-peak Max", fmt(s.true_peak_max), "dBTP"),
            ("Loudness Max", fmt(s.max_momentary), "LUFS"),
            ("Loudness Range", fmt(s.lra), "LU"),
            ("Peak to Loudness", fmt(s.plr), "dB"),
        ]
        top = 50 * scale
        corr_h = 96 * scale
        row_h = (h - top - corr_h) / len(rows)
        unit_w = 64 * scale
        for i, (label, value, unit) in enumerate(rows):
            ry = top + i * row_h
            p.setPen(theme.TEXT)
            p.setFont(font(17 * scale))
            p.drawText(QRectF(left, ry + 4 * scale, right - left, 24 * scale),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
            p.setPen(theme.YELLOW)
            p.setFont(font(min(44 * scale, row_h * 0.52), QFont.Weight.Light))
            p.drawText(QRectF(left, ry + 26 * scale, right - left - unit_w, row_h - 30 * scale),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), value)
            p.setPen(theme.DIM)
            p.setFont(font(16 * scale))
            p.drawText(QRectF(right - unit_w + 6 * scale, ry + 26 * scale, unit_w - 6 * scale, row_h - 30 * scale),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), unit)
            p.setPen(QPen(theme.PANEL_LINE, 1))
            p.drawLine(QRectF(left, ry + row_h - 1, right - left, 1).topLeft(),
                       QRectF(left, ry + row_h - 1, right - left, 1).topRight())

        self._draw_correlation(p, left, right, h - corr_h, corr_h, scale)
        p.end()

    def _draw_correlation(self, p: QPainter, left: float, right: float, top: float,
                          height: float, scale: float) -> None:
        p.setPen(theme.TEXT)
        p.setFont(font(17 * scale))
        p.drawText(QRectF(left, top + 6 * scale, right - left, 24 * scale),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "Correlation")
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

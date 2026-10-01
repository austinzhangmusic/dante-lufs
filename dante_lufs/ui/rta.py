"""1/3-octave real-time analyser shown in place of the radar when RTA is toggled."""
from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..dsp.loudness import Snapshot
from . import theme
from .theme import NEG_INF, font

CENTRES = [25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800,
           1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000]
LABELS = {31.5: "31", 63: "63", 125: "125", 250: "250", 500: "500", 1000: "1k", 2000: "2k",
          4000: "4k", 8000: "8k", 16000: "16k"}
DB_MIN, DB_MAX = -60.0, 0.0
FALL_DB_PER_S = 20.0
HOLD_S = 1.0


def third_octave_levels(x: np.ndarray, fs: int) -> np.ndarray:
    """Band levels in dBFS (0 dB = full-scale sine) for CENTRES."""
    n = len(x)
    win = np.hanning(n)
    spec = np.fft.rfft(x * win)
    amp = 2.0 * np.abs(spec) / win.sum()  # sine amplitude per bin
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    out = np.full(len(CENTRES), NEG_INF)
    edge = 2 ** (1 / 6)
    for i, fc in enumerate(CENTRES):
        lo, hi = fc / edge, fc * edge
        mask = (freqs >= lo) & (freqs < hi)
        if mask.any():
            power = float(np.sum(amp[mask] ** 2))
            out[i] = 10.0 * np.log10(power) if power > 1e-24 else NEG_INF
    return out


class RtaWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.levels = np.full(len(CENTRES), NEG_INF)
        self.holds = np.full(len(CENTRES), NEG_INF)
        self.hold_time = np.zeros(len(CENTRES))
        self._last = time.monotonic()
        self.setMinimumSize(360, 280)

    def set_snapshot(self, snap: Snapshot) -> None:
        now = time.monotonic()
        dt = max(0.0, min(0.5, now - self._last))
        self._last = now
        fresh = third_octave_levels(snap.spectrum_buffer, snap.fs)
        fallen = np.where(np.isfinite(self.levels), self.levels - FALL_DB_PER_S * dt, NEG_INF)
        self.levels = np.maximum(fresh, fallen)
        rise = fresh >= self.holds
        self.holds = np.where(rise, fresh, self.holds)
        self.hold_time = np.where(rise, now, self.hold_time)
        decay = (now - self.hold_time) > HOLD_S
        self.holds = np.where(decay & np.isfinite(self.holds), self.holds - FALL_DB_PER_S * dt, self.holds)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), theme.BG)
        scale = min(w / 640.0, h / 700.0)
        left = 56 * scale
        right = w - 24 * scale
        top = 40 * scale
        bottom = h - 48 * scale
        n = len(CENTRES)
        slot = (right - left) / n
        bar_w = slot * 0.7

        p.setPen(theme.TEXT)
        p.setFont(font(17 * scale))
        p.drawText(QRectF(left, 8 * scale, 300 * scale, 24 * scale),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "RTA  1/3 octave  dBFS")

        p.setFont(font(13 * scale))
        for db in range(int(DB_MIN), int(DB_MAX) + 1, 10):
            y = top + (DB_MAX - db) / (DB_MAX - DB_MIN) * (bottom - top)
            p.setPen(QPen(theme.PANEL_LINE, 1))
            p.drawLine(QPointF(left, y), QPointF(right, y))
            p.setPen(theme.DIM)
            p.drawText(QRectF(0, y - 10 * scale, left - 8 * scale, 20 * scale),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"{db}")

        for i, fc in enumerate(CENTRES):
            x0 = left + slot * i + (slot - bar_w) / 2
            lvl = self.levels[i]
            if np.isfinite(lvl) and lvl > DB_MIN:
                y = top + (DB_MAX - min(lvl, DB_MAX)) / (DB_MAX - DB_MIN) * (bottom - top)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.YELLOW if lvl < -6 else theme.RED)
                p.drawRect(QRectF(x0, y, bar_w, bottom - y))
                p.setPen(QPen(theme.BG, 1))
                yy = bottom
                while yy > y:
                    p.drawLine(QPointF(x0, yy), QPointF(x0 + bar_w, yy))
                    yy -= 4 * scale
            hold = self.holds[i]
            if np.isfinite(hold) and hold > DB_MIN:
                y = top + (DB_MAX - min(hold, DB_MAX)) / (DB_MAX - DB_MIN) * (bottom - top)
                p.setPen(QPen(theme.TEXT, max(1.0, 2.0 * scale)))
                p.drawLine(QPointF(x0, y), QPointF(x0 + bar_w, y))
            if fc in LABELS:
                p.setPen(theme.DIM)
                p.drawText(QRectF(x0 + bar_w / 2 - 30 * scale, bottom + 6 * scale, 60 * scale, 20 * scale),
                           int(Qt.AlignmentFlag.AlignCenter), LABELS[fc])
        p.end()

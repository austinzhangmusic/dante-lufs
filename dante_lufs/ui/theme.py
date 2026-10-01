"""Colours, fonts and small drawing helpers shared by the meter widgets."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter

BG = QColor("#070707")
PANEL_LINE = QColor("#262626")
TEXT = QColor("#e8e8e8")
DIM = QColor("#8c8c8c")
DIMMER = QColor("#4a4a4a")
YELLOW = QColor("#ffe12b")
GREEN = QColor("#34e05a")
BLUE = QColor("#3f84e6")
CYAN = QColor("#27c3d6")
ORANGE = QColor("#f08a1e")
RED = QColor("#e8262a")
RED_OFF = QColor("#4a1013")
TICK = QColor("#333333")

RADAR_BANDS = [
    QColor("#1b3b86"),
    QColor("#2560c4"),
    QColor("#22b2c7"),
    QColor("#34e05a"),
    QColor("#ffe12b"),
]

FAMILIES = ["Helvetica Neue", "SF Pro Display", "Segoe UI", "Roboto", "Arial", "sans-serif"]

NEG_INF = float("-inf")


def font(px: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies(FAMILIES)
    f.setPixelSize(max(6, int(round(px))))
    f.setWeight(weight)
    return f


def fmt(v: float, decimals: int = 1) -> str:
    if v is None or v == NEG_INF or (isinstance(v, float) and math.isnan(v)):
        return "---"
    return f"{v:.{decimals}f}"


def pt(cx: float, cy: float, r: float, deg: float) -> QPointF:
    """Point at radius r, angle in degrees clockwise from 12 o'clock."""
    a = math.radians(deg)
    return QPointF(cx + r * math.sin(a), cy - r * math.cos(a))


def text_at(p: QPainter, x: float, y: float, text: str, align=Qt.AlignmentFlag.AlignCenter,
            w: float = 200.0, h: float = 40.0) -> None:
    """Draw text with its anchor box centred on (x, y) using the given alignment."""
    p.drawText(QRectF(x - w / 2, y - h / 2, w, h), int(align), text)


def hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s // 60) % 60:02d}:{s % 60:02d}"

"""Main window: Clarity M style screen with radar, readouts, bars and the bottom button bar."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..audio.engine import AudioEngine, find_device, list_input_devices
from .bars import MidSideWidget, TruePeakBars
from .radar import RadarWidget
from .rta import RtaWidget
from .settings import SettingsDialog
from .stats import StatsPanel

TARGET_PRESETS = [
    ("ATSC A/85 (TV, US)", -24.0),
    ("EBU R128 (TV, EU)", -23.0),
    ("Netflix / OTT dialogue", -27.0),
    ("Podcast / Apple", -16.0),
    ("Spotify / YouTube", -14.0),
    ("Amazon / Tidal", -14.0),
    ("Club / loud master", -9.0),
]

BUTTON_STYLE = """
QToolButton {
    color: #c8c8c8; background: transparent; border: none;
    font-size: %dpx; padding: 6px 18px; font-family: "Helvetica Neue", "Segoe UI", Arial;
}
QToolButton:hover { color: #ffffff; }
QToolButton:pressed { color: #ffe12b; }
QToolButton#reset { color: #ffe12b; }
QToolButton#rta[active="true"] { color: #ffe12b; }
QToolButton::menu-indicator { image: none; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dante LUFS")
        self.settings = QSettings("dante-lufs", "DanteLUFS")
        self.engine = AudioEngine()
        self.config = self._load_config()
        self._build_ui()
        self._apply_target_labels()

        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.toggle_pause)
        QShortcut(QKeySequence("R"), self, activated=self.reset)
        QShortcut(QKeySequence("F"), self, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._exit_fullscreen)

        self.resize(1280, 800)
        QTimer.singleShot(0, self._start_audio)

    # ---------------------------------------------------------------- config
    def _load_config(self) -> dict:
        s = self.settings
        return {
            "target_lufs": float(s.value("target_lufs", -24.0)),
            "preset_name": str(s.value("preset_name", "ATSC A/85 (TV, US)")),
            "device_key": s.value("device_key", None),
            "first_channel": int(s.value("first_channel", 0)),
            "samplerate": int(s.value("samplerate", 0)),
            "radar_seconds": int(s.value("radar_seconds", 60)),
            "peak_alert_dbtp": float(s.value("peak_alert_dbtp", -1.0)),
            "loud_alert_margin_lu": float(s.value("loud_alert_margin_lu", 5.0)),
        }

    def _save_config(self) -> None:
        for k, v in self.config.items():
            self.settings.setValue(k, v)
        self.settings.sync()

    # -------------------------------------------------------------------- ui
    def _build_ui(self) -> None:
        root = QWidget()
        root.setStyleSheet("background: #070707;")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 10, 10, 6)
        outer.setSpacing(0)

        screen = QFrame()
        screen.setStyleSheet("QFrame#screen { border: 1px solid #2a2a2a; }")
        screen.setObjectName("screen")
        row = QHBoxLayout(screen)
        row.setContentsMargins(1, 1, 1, 1)
        row.setSpacing(0)

        self.radar = RadarWidget()
        self.rta = RtaWidget()
        self.left_stack = QStackedWidget()
        self.left_stack.addWidget(self.radar)
        self.left_stack.addWidget(self.rta)
        self.left_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        row.addWidget(self.left_stack, 50)
        row.addWidget(self._vline())

        self.stats = StatsPanel()
        row.addWidget(self.stats, 24)
        row.addWidget(self._vline())

        right = QWidget()
        col = QVBoxLayout(right)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.bars = TruePeakBars()
        self.midside = MidSideWidget()
        col.addWidget(self.bars, 62)
        col.addWidget(self.midside, 38)
        row.addWidget(right, 26)

        outer.addWidget(screen, 1)
        outer.addWidget(self._build_bottom_bar())

    @staticmethod
    def _vline() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setStyleSheet("color: #2a2a2a;")
        return line

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(64)
        bar.setStyleSheet(BUTTON_STYLE % 22)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 4, 12, 4)

        self.pause_btn = QToolButton(text="❚❚")
        self.pause_btn.clicked.connect(self.toggle_pause)
        reset_btn = QToolButton(text="RESET")
        reset_btn.setObjectName("reset")
        reset_btn.clicked.connect(self.reset)
        self.rta_btn = QToolButton(text="RTA")
        self.rta_btn.setObjectName("rta")
        self.rta_btn.setProperty("active", "false")
        self.rta_btn.clicked.connect(self.toggle_rta)
        self.target_btn = QToolButton()
        self.target_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.target_btn.setMenu(self._build_target_menu())
        sys_btn = QToolButton(text="SYS")
        sys_btn.clicked.connect(self.open_settings)

        for b in (self.pause_btn, reset_btn, self.rta_btn, self.target_btn, sys_btn):
            lay.addWidget(b)
            lay.addStretch(1)
        lay.takeAt(lay.count() - 1)
        return bar

    def _build_target_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background: #151515; color: #e8e8e8; font-size: 15px; }"
                           "QMenu::item:selected { background: #2f5fb0; }")
        for name, value in TARGET_PRESETS:
            act = QAction(f"{value:.0f} LUFS   {name}", self)
            act.triggered.connect(lambda checked=False, n=name, v=value: self.set_target(v, n))
            menu.addAction(act)
        menu.addSeparator()
        custom = QAction("Custom…", self)
        custom.triggered.connect(self._custom_target)
        menu.addAction(custom)
        return menu

    def _apply_target_labels(self) -> None:
        t = self.config["target_lufs"]
        self.target_btn.setText(f"Target  {t:.0f} LUFS")
        self.radar.target = t
        self.radar.preset_name = self.config["preset_name"]
        self.bars.peak_alert_dbtp = self.config["peak_alert_dbtp"]

    # ----------------------------------------------------------------- audio
    def _start_audio(self) -> None:
        devices = list_input_devices()
        device = find_device(devices, self.config.get("device_key"))
        if device is None:
            self.stats.source_name = "No stereo input found"
            self.stats.source_ok = False
            return
        try:
            self.engine.start(
                device,
                first_channel=self.config["first_channel"],
                samplerate=self.config["samplerate"] or None,
                radar_seconds=self.config["radar_seconds"],
                target_lufs=self.config["target_lufs"],
                peak_alert_dbtp=self.config["peak_alert_dbtp"],
                loud_alert_margin_lu=self.config["loud_alert_margin_lu"],
            )
        except Exception as exc:
            self.stats.source_name = f"Input error: {exc}"
            self.stats.source_ok = False
            return
        self.config["device_key"] = device.key
        self._save_config()
        pair = f"{self.engine.first_channel + 1}-{self.engine.first_channel + 2}"
        self.stats.source_name = f"{device.name} {pair} · {device.hostapi} · {self.engine.samplerate // 1000}k"
        self.stats.setToolTip(f"{device.label}\nchannels {pair}, {self.engine.samplerate} Hz")
        self.stats.source_ok = True
        self.engine.paused = False
        self.pause_btn.setText("❚❚")
        self.radar.paused = False

    def _tick(self) -> None:
        meter = self.engine.meter
        if meter is None:
            return
        snap = meter.snapshot()
        if self.left_stack.currentWidget() is self.rta:
            self.rta.set_snapshot(snap)
        else:
            self.radar.set_snapshot(snap)
        self.stats.set_snapshot(snap)
        self.bars.set_snapshot(snap)
        self.midside.set_snapshot(snap)

    # --------------------------------------------------------------- actions
    def toggle_pause(self) -> None:
        self.engine.paused = not self.engine.paused
        self.pause_btn.setText("▶" if self.engine.paused else "❚❚")
        self.radar.paused = self.engine.paused
        self.radar.update()

    def reset(self) -> None:
        self.engine.reset()

    def toggle_rta(self) -> None:
        showing = self.left_stack.currentWidget() is self.rta
        self.left_stack.setCurrentWidget(self.radar if showing else self.rta)
        self.rta_btn.setProperty("active", "false" if showing else "true")
        self.rta_btn.style().unpolish(self.rta_btn)
        self.rta_btn.style().polish(self.rta_btn)

    def set_target(self, value: float, name: str) -> None:
        self.config["target_lufs"] = float(value)
        self.config["preset_name"] = name
        self._save_config()
        self._apply_target_labels()
        if self.engine.meter is not None:
            self.engine.meter.target_lufs = float(value)
            self.engine.meter.loud_alert = False

    def _custom_target(self) -> None:
        value, ok = QInputDialog.getDouble(self, "Custom target", "Target loudness (LUFS):",
                                           self.config["target_lufs"], -40.0, 0.0, 1)
        if ok:
            self.set_target(value, "Custom")

    def _rescan_devices(self):
        """Stop the stream (PortAudio must be idle) and re-detect devices."""
        self.engine.stop()
        return list_input_devices(rescan=True)

    def open_settings(self) -> None:
        devices = list_input_devices()
        dlg = SettingsDialog(self, devices, self.config, on_rescan=self._rescan_devices)
        if dlg.exec() != SettingsDialog.DialogCode.Accepted:
            if not self.engine.running:  # a rescan stopped the stream
                self._start_audio()
            return
        self.config.update(dlg.values())
        self._save_config()
        self._apply_target_labels()
        self.engine.stop()
        self._start_audio()
        if not self.engine.running and self.engine.error:
            QMessageBox.warning(self, "Input", f"Could not open the input:\n{self.engine.error}")

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _exit_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.timer.stop()
        self.engine.stop()
        super().closeEvent(event)

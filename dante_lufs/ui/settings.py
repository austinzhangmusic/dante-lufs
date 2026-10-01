"""SYS dialog: input device, stereo pair, sample rate, radar time and alert thresholds."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..audio.engine import InputDevice, list_input_devices

RADAR_CHOICES = [("1 min", 60), ("2 min", 120), ("3 min", 180), ("5 min", 300),
                 ("10 min", 600), ("20 min", 1200), ("30 min", 1800)]
RATE_CHOICES = [("Device default", 0), ("44100", 44100), ("48000", 48000),
                ("88200", 88200), ("96000", 96000), ("192000", 192000)]


class SettingsDialog(QDialog):
    def __init__(self, parent, devices: list[InputDevice], config: dict, on_rescan=None):
        super().__init__(parent)
        self.setWindowTitle("System settings")
        self.setMinimumWidth(520)
        self.devices = devices
        self.config = dict(config)
        self._on_rescan = on_rescan

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.device_box = QComboBox()
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.setToolTip("Re-detect devices (stops the current measurement)")
        self.rescan_btn.clicked.connect(self._rescan)
        row = QHBoxLayout()
        row.addWidget(self.device_box, 1)
        row.addWidget(self.rescan_btn)
        form.addRow("Input device", row)

        self.pair_box = QComboBox()
        form.addRow("Stereo pair", self.pair_box)

        self.rate_box = QComboBox()
        for label, value in RATE_CHOICES:
            self.rate_box.addItem(label, value)
        form.addRow("Sample rate", self.rate_box)

        self.radar_box = QComboBox()
        for label, value in RADAR_CHOICES:
            self.radar_box.addItem(label, value)
        form.addRow("Radar time (one revolution)", self.radar_box)

        self.peak_spin = QDoubleSpinBox()
        self.peak_spin.setRange(-20.0, 0.0)
        self.peak_spin.setSingleStep(0.5)
        self.peak_spin.setSuffix(" dBTP")
        form.addRow("Peak alert above", self.peak_spin)

        self.loud_spin = QDoubleSpinBox()
        self.loud_spin.setRange(0.0, 24.0)
        self.loud_spin.setSingleStep(0.5)
        self.loud_spin.setSuffix(" LU")
        form.addRow("Loud alert: short-term above target by", self.loud_spin)

        note = QLabel("ASIO (Windows) and Core Audio (macOS) devices are listed first. "
                      "Dante Virtual Soundcard appears as an ASIO / Core Audio device.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #8c8c8c;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.device_box.currentIndexChanged.connect(self._fill_pairs)
        self._fill_devices()
        self._select(self.rate_box, self.config.get("samplerate", 0))
        self._select(self.radar_box, self.config.get("radar_seconds", 60))
        self.peak_spin.setValue(float(self.config.get("peak_alert_dbtp", -1.0)))
        self.loud_spin.setValue(float(self.config.get("loud_alert_margin_lu", 5.0)))

    @staticmethod
    def _select(box: QComboBox, value) -> None:
        idx = box.findData(value)
        box.setCurrentIndex(idx if idx >= 0 else 0)

    def _fill_devices(self) -> None:
        self.device_box.blockSignals(True)
        self.device_box.clear()
        for d in self.devices:
            self.device_box.addItem(d.label, d.key)
        self.device_box.blockSignals(False)
        self._select(self.device_box, self.config.get("device_key"))
        self._fill_pairs()

    def _fill_pairs(self) -> None:
        self.pair_box.clear()
        d = self.current_device()
        if d is None:
            return
        for first in range(0, d.channels - 1, 2):
            self.pair_box.addItem(f"{first + 1}-{first + 2}", first)
        if d.channels % 2 == 1 and d.channels > 2:
            self.pair_box.addItem(f"{d.channels - 1}-{d.channels}", d.channels - 2)
        self._select(self.pair_box, self.config.get("first_channel", 0))

    def _rescan(self) -> None:
        if self._on_rescan is not None:
            self.devices = self._on_rescan()
        else:
            self.devices = list_input_devices(rescan=True)
        self._fill_devices()

    def current_device(self) -> InputDevice | None:
        key = self.device_box.currentData()
        for d in self.devices:
            if d.key == key:
                return d
        return None

    def values(self) -> dict:
        d = self.current_device()
        return {
            "device_key": d.key if d else None,
            "first_channel": int(self.pair_box.currentData() or 0),
            "samplerate": int(self.rate_box.currentData() or 0),
            "radar_seconds": int(self.radar_box.currentData() or 60),
            "peak_alert_dbtp": float(self.peak_spin.value()),
            "loud_alert_margin_lu": float(self.loud_spin.value()),
        }

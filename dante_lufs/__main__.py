"""Entry point: ``python -m dante_lufs`` or the ``dante-lufs`` console script.

    dante-lufs                      launch the meter
    dante-lufs --measure FILE.wav   print loudness of a WAV file (no GUI)
    dante-lufs --devices            list stereo-capable input devices
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    os.environ.setdefault("SD_ENABLE_ASIO", "1")  # before sounddevice is imported anywhere
    parser = argparse.ArgumentParser(prog="dante-lufs", description="Stereo LUFS meter")
    parser.add_argument("--measure", metavar="WAV", nargs="+", help="measure WAV file(s) and exit")
    parser.add_argument("--devices", action="store_true", help="list input devices and exit")
    args = parser.parse_args()

    if args.measure:
        from .measure import format_report, measure

        for path in args.measure:
            print(format_report(measure(path)))
        return 0

    if args.devices:
        from .audio.engine import list_input_devices

        for d in list_input_devices():
            print(f"{d.index:3d}  {d.label}  ({d.channels} in, {d.default_samplerate:.0f} Hz)")
        return 0

    from PySide6.QtWidgets import QApplication

    from .ui.app import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Dante LUFS")
    app.setOrganizationName("dante-lufs")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

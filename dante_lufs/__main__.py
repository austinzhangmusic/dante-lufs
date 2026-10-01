"""Entry point: ``python -m dante_lufs`` or the ``dante-lufs`` console script."""
from __future__ import annotations

import os
import sys


def main() -> int:
    os.environ.setdefault("SD_ENABLE_ASIO", "1")  # before sounddevice is imported anywhere
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

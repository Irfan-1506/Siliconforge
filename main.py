"""Entry point for SiliconForge VLSI Studio."""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from vlsi_studio.theme import apply_dark_theme
from vlsi_studio.ui.main_window import MainWindow


def _resource_path(rel: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / rel


def main() -> int:
    app = QApplication(sys.argv)
    ico = _resource_path("assets/siliconforge.ico")
    if ico.exists():
        app.setWindowIcon(QIcon(str(ico)))
    apply_dark_theme(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

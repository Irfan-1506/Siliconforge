"""Dark EDA theme styling inspired by Vivado, ModelSim, and Magic VLSI."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# Core Palette Colors
BG_DARK = "#12151B"
BG_PANEL = "#1A1E26"
BG_SURFACE = "#222732"
BG_HOVER = "#2C3342"
BORDER_COLOR = "#323A4A"
TEXT_PRIMARY = "#E6EDF3"
TEXT_SECONDARY = "#8B949E"
ACCENT_BLUE = "#3B82F6"
ACCENT_CYAN = "#06B6D4"
ACCENT_GREEN = "#10B981"
ACCENT_AMBER = "#F59E0B"
ACCENT_RED = "#EF4444"
ACCENT_PURPLE = "#8B5CF6"

APP_STYLESHEET = f"""
QMainWindow, QDialog {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
}}
QWidget {{
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}}
QMenuBar {{
    background-color: {BG_PANEL};
    border-bottom: 1px solid {BORDER_COLOR};
    padding: 2px 6px;
}}
QMenuBar::item:selected {{
    background-color: {BG_HOVER};
    border-radius: 4px;
}}
QMenu {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER_COLOR};
}}
QMenu::item:selected {{
    background-color: {ACCENT_BLUE};
}}
QToolBar {{
    background-color: {BG_PANEL};
    border-bottom: 1px solid {BORDER_COLOR};
    spacing: 6px;
    padding: 4px 8px;
}}
QToolButton {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER_COLOR};
    border-radius: 4px;
    padding: 5px 10px;
    color: {TEXT_PRIMARY};
}}
QToolButton:hover {{
    background-color: {BG_HOVER};
    border-color: {ACCENT_BLUE};
}}
QToolButton:checked {{
    background-color: {ACCENT_BLUE};
    border-color: {ACCENT_BLUE};
    color: #FFFFFF;
}}
QPushButton {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER_COLOR};
    border-radius: 4px;
    padding: 5px 12px;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {ACCENT_BLUE};
}}
QPushButton#primaryBtn {{
    background-color: {ACCENT_BLUE};
    border-color: {ACCENT_BLUE};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton#primaryBtn:hover {{
    background-color: #2563EB;
}}
QDockWidget::title {{
    background-color: {BG_PANEL};
    padding: 6px 8px;
    border-bottom: 1px solid {BORDER_COLOR};
    font-weight: 600;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER_COLOR};
    background-color: {BG_DARK};
}}
QTabBar::tab {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER_COLOR};
    border-bottom: none;
    padding: 7px 14px;
    margin-right: 2px;
    color: {TEXT_SECONDARY};
}}
QTabBar::tab:selected {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
    border-top: 2px solid {ACCENT_CYAN};
    font-weight: 600;
}}
QTreeWidget, QListWidget, QTableWidget {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER_COLOR};
    alternate-background-color: {BG_SURFACE};
}}
QHeaderView::section {{
    background-color: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    padding: 4px 8px;
    border: 1px solid {BORDER_COLOR};
    font-weight: 600;
}}
QPlainTextEdit, QTextEdit, QLineEdit, QSpinBox, QComboBox {{
    background-color: {BG_DARK};
    border: 1px solid {BORDER_COLOR};
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: {ACCENT_BLUE};
}}
QPlainTextEdit#codeEditor {{
    font-family: "Consolas", "Cascadia Mono", "Courier New", monospace;
    font-size: 10pt;
    padding: 0px;
    border: none;
}}
QSplitter::handle {{
    background-color: {BORDER_COLOR};
}}
QStatusBar {{
    background-color: {BG_PANEL};
    border-top: 1px solid {BORDER_COLOR};
    color: {TEXT_SECONDARY};
}}
"""


def apply_dark_theme(app: QApplication) -> None:
    """Apply dark palette and stylesheet to the QApplication."""
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG_DARK))
    palette.setColor(QPalette.WindowText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Base, QColor(BG_PANEL))
    palette.setColor(QPalette.AlternateBase, QColor(BG_SURFACE))
    palette.setColor(QPalette.Text, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Button, QColor(BG_SURFACE))
    palette.setColor(QPalette.ButtonText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Highlight, QColor(ACCENT_BLUE))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)
    app.setStyleSheet(APP_STYLESHEET)

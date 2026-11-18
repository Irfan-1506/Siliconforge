"""ModelSim-style interactive digital waveform viewer with VCD export."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vlsi_studio.verilog.simulator import WaveSignal, WaveTrace


def _format_val(val: int, width: int, radix: str) -> str:
    masked = val & ((1 << width) - 1)
    if radix == "Bin":
        return format(masked, f"0{width}b")
    if radix == "Dec":
        return str(masked)
    digits = max(1, (width + 3) // 4)
    return f"0x{format(masked, f'0{digits}x').upper()}"


def _value_at(sig: WaveSignal, t: int) -> int:
    val = 0
    for ts, v in sig.transitions:
        if ts <= t:
            val = v
        else:
            break
    return val


class _WaveformCanvas(QWidget):
    ROW_H = 34
    HEADER_H = 28
    NAME_COL_W = 240

    def __init__(self, parent=None):
        super().__init__(parent)
        self.trace: WaveTrace | None = None
        self.px_per_ns: float = 8.0
        self.cursor_ns: int = 0
        self.radix: str = "Hex"
        self.on_cursor_changed = None
        self.setMinimumSize(600, 260)

    def set_trace(self, trace: WaveTrace) -> None:
        self.trace = trace
        self.cursor_ns = 0
        self.zoom_fit()

    def zoom_fit(self) -> None:
        if not self.trace or self.trace.end_time <= 0:
            self.px_per_ns = 8.0
        else:
            avail = max(300, self.parentWidget().width() - self.NAME_COL_W - 40 if self.parentWidget() else 600)
            self.px_per_ns = max(1.0, min(40.0, avail / max(1, self.trace.end_time)))
        self._update_size()
        self.update()

    def zoom_in(self) -> None:
        self.px_per_ns = min(80.0, self.px_per_ns * 1.35)
        self._update_size()
        self.update()

    def zoom_out(self) -> None:
        self.px_per_ns = max(0.5, self.px_per_ns / 1.35)
        self._update_size()
        self.update()

    def _update_size(self) -> None:
        n_sigs = len(self.trace.signals) if self.trace else 0
        end_t = max(20, self.trace.end_time) if self.trace else 100
        w = int(self.NAME_COL_W + end_t * self.px_per_ns + 60)
        h = max(220, self.HEADER_H + n_sigs * self.ROW_H + 20)
        self.setMinimumSize(w, h)
        self.resize(w, h)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.trace:
            x = event.position().x() - self.NAME_COL_W
            if x >= 0:
                self.cursor_ns = max(0, min(self.trace.end_time, round(x / self.px_per_ns)))
                if self.on_cursor_changed:
                    self.on_cursor_changed(self.cursor_ns)
                self.update()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.fillRect(self.rect(), QColor("#0F1218"))

        if not self.trace or not self.trace.signals:
            p.setPen(QColor("#8B949E"))
            p.drawText(self.rect(), Qt.AlignCenter, "No simulation waveform yet.\nClick 'Run Simulation' to simulate your Verilog testbench.")
            return

        end_t = max(10, self.trace.end_time)
        mono = QFont("Consolas", 9)
        p.setFont(mono)

        # Header / Time Ruler
        p.fillRect(0, 0, self.width(), self.HEADER_H, QColor("#1A1E26"))
        p.setPen(QColor("#323A4A"))
        p.drawLine(0, self.HEADER_H, self.width(), self.HEADER_H)
        p.drawLine(self.NAME_COL_W, 0, self.NAME_COL_W, self.height())

        p.setPen(QColor("#E6EDF3"))
        p.drawText(10, 0, self.NAME_COL_W - 16, self.HEADER_H, Qt.AlignVCenter, "Signal [Cursor Val]")

        # Adaptive tick step
        step = 10
        for candidate in (1, 2, 5, 10, 20, 50, 100, 200, 500):
            if candidate * self.px_per_ns >= 55:
                step = candidate
                break

        for t in range(0, end_t + step, step):
            x = int(self.NAME_COL_W + t * self.px_per_ns)
            p.setPen(QColor("#232936"))
            p.drawLine(x, self.HEADER_H, x, self.height())
            p.setPen(QColor("#9CA3AF"))
            p.drawLine(x, self.HEADER_H - 6, x, self.HEADER_H)
            p.drawText(x + 3, 2, 60, self.HEADER_H - 8, Qt.AlignVCenter, f"{t}ns")

        # Signal rows
        for idx, (name, sig) in enumerate(self.trace.signals.items()):
            y_top = self.HEADER_H + idx * self.ROW_H
            y_bot = y_top + self.ROW_H
            if idx % 2 == 1:
                p.fillRect(0, y_top, self.width(), self.ROW_H, QColor("#141821"))

            p.setPen(QColor("#232936"))
            p.drawLine(0, y_bot, self.width(), y_bot)

            # Signal Name & Value at Cursor
            cval = _value_at(sig, self.cursor_ns)
            val_str = _format_val(cval, sig.width, self.radix)
            short_name = name if len(name) <= 20 else "…" + name[-19:]
            p.setPen(QColor("#E6EDF3"))
            p.drawText(8, y_top, 145, self.ROW_H, Qt.AlignVCenter, short_name)
            p.setPen(QColor("#38BDF8"))
            p.drawText(155, y_top, self.NAME_COL_W - 162, self.ROW_H, Qt.AlignVCenter | Qt.AlignRight, val_str)

            # Draw waveform transitions
            y_hi = y_top + 6
            y_lo = y_bot - 6
            y_mid = (y_hi + y_lo) // 2

            pts = sig.transitions
            if sig.width == 1:
                p.setPen(QPen(QColor("#10B981"), 2))
                for i, (t, v) in enumerate(pts):
                    t_next = pts[i + 1][0] if i + 1 < len(pts) else end_t
                    x1 = int(self.NAME_COL_W + t * self.px_per_ns)
                    x2 = int(self.NAME_COL_W + max(t, t_next) * self.px_per_ns)
                    y = y_hi if (v & 1) else y_lo
                    p.drawLine(x1, y, x2, y)
                    if i + 1 < len(pts) and (pts[i + 1][1] & 1) != (v & 1):
                        p.drawLine(x2, y_hi, x2, y_lo)
            else:
                p.setPen(QPen(QColor("#06B6D4"), 1.5))
                for i, (t, v) in enumerate(pts):
                    t_next = pts[i + 1][0] if i + 1 < len(pts) else end_t
                    x1 = self.NAME_COL_W + t * self.px_per_ns
                    x2 = self.NAME_COL_W + max(t, t_next) * self.px_per_ns
                    bev = min(4.0, max(1.0, (x2 - x1) / 4.0))
                    if x2 - x1 >= 3:
                        poly = QPolygonF()
                        from PySide6.QtCore import QPointF
                        poly.append(QPointF(x1, y_mid))
                        poly.append(QPointF(x1 + bev, y_hi))
                        poly.append(QPointF(x2 - bev, y_hi))
                        poly.append(QPointF(x2, y_mid))
                        poly.append(QPointF(x2 - bev, y_lo))
                        poly.append(QPointF(x1 + bev, y_lo))
                        poly.append(QPointF(x1, y_mid))
                        p.drawPolyline(poly)
                        if x2 - x1 > 28:
                            p.setPen(QColor("#E6EDF3"))
                            p.drawText(
                                int(x1 + 4), y_hi, int(x2 - x1 - 8), y_lo - y_hi,
                                Qt.AlignCenter, _format_val(v, sig.width, self.radix),
                            )
                            p.setPen(QPen(QColor("#06B6D4"), 1.5))

        # Measurement Cursor
        cx = int(self.NAME_COL_W + self.cursor_ns * self.px_per_ns)
        p.setPen(QPen(QColor("#FACC15"), 1.5, Qt.DashLine))
        p.drawLine(cx, self.HEADER_H, cx, self.height())


class WaveformViewer(QWidget):
    """Complete Waveform Viewer widget with toolbar and scroll area."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 6)
        self.btn_zoom_in = QPushButton("Zoom +")
        self.btn_zoom_out = QPushButton("Zoom -")
        self.btn_zoom_fit = QPushButton("Fit")
        self.radix_combo = QComboBox()
        self.radix_combo.addItems(["Hex", "Bin", "Dec"])
        self.cursor_lbl = QLabel("Cursor: 0 ns")
        self.cursor_lbl.setStyleSheet("color: #FACC15; font-weight: 600; padding: 0 8px;")
        self.btn_vcd = QPushButton("Export VCD...")

        bar.addWidget(self.btn_zoom_in)
        bar.addWidget(self.btn_zoom_out)
        bar.addWidget(self.btn_zoom_fit)
        bar.addWidget(QLabel("Radix:"))
        bar.addWidget(self.radix_combo)
        bar.addWidget(self.cursor_lbl)
        bar.addStretch()
        bar.addWidget(self.btn_vcd)
        layout.addLayout(bar)

        self.canvas = _WaveformCanvas()
        self.canvas.on_cursor_changed = lambda t: self.cursor_lbl.setText(f"Cursor: {t} ns")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.canvas)
        layout.addWidget(scroll)

        self.btn_zoom_in.clicked.connect(self.canvas.zoom_in)
        self.btn_zoom_out.clicked.connect(self.canvas.zoom_out)
        self.btn_zoom_fit.clicked.connect(self.canvas.zoom_fit)
        self.radix_combo.currentTextChanged.connect(self._on_radix)
        self.btn_vcd.clicked.connect(self._export_vcd)

    def _on_radix(self, r: str) -> None:
        self.canvas.radix = r
        self.canvas.update()

    def set_trace(self, trace: WaveTrace) -> None:
        self.canvas.set_trace(trace)
        self.cursor_lbl.setText("Cursor: 0 ns")

    def _export_vcd(self) -> None:
        if not self.canvas.trace or not self.canvas.trace.signals:
            QMessageBox.information(self, "Export VCD", "Run a simulation first to generate waveform data.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export VCD", "simulation.vcd", "VCD Files (*.vcd)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.canvas.trace.to_vcd())

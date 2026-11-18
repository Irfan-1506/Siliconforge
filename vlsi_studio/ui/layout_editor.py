"""Magic-style 2D SCMOS VLSI Layout Editor with DRC overlay and SPICE extraction."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vlsi_studio.layout.drc import DRCViolation, run_drc
from vlsi_studio.layout.extractor import extract_netlist
from vlsi_studio.layout.layers import LAYER_MAP, LAYERS, LayoutCell, LayoutLabel, LayoutRect
from vlsi_studio.layout.mag_io import load_mag, save_mag
from vlsi_studio.layout.presets import create_cmos_inverter, create_cmos_nand2

LAMBDA_PX = 16


class _LayoutCanvas(QGraphicsView):
    coordsChanged = Signal(int, int)
    cellModified = Signal()

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QBrush(QColor("#0B0E14")))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

        self.cell: LayoutCell = create_cmos_inverter()
        self.active_layer: str = "metal1"
        self.tool_mode: str = "paint"  # "paint", "erase", "label", "pan"
        self.visible_layers: set[str] = {l.name for l in LAYERS}
        self.violations: list[DRCViolation] = []

        self._drag_start: tuple[int, int] | None = None
        self._preview_item: QGraphicsRectItem | None = None
        self._panning = False
        self._pan_start = None

    def _to_lambda(self, scene_pos) -> tuple[int, int]:
        lx = round(scene_pos.x() / LAMBDA_PX)
        ly = round(-scene_pos.y() / LAMBDA_PX)
        return lx, ly

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        # Draw 1-lambda minor grid and 5-lambda major grid
        left = int(rect.left() // LAMBDA_PX) - 1
        right = int(rect.right() // LAMBDA_PX) + 1
        top = int(rect.top() // LAMBDA_PX) - 1
        bottom = int(rect.bottom() // LAMBDA_PX) + 1

        minor_pen = QPen(QColor("#1A202C"), 0)
        major_pen = QPen(QColor("#2D3748"), 0)

        for gx in range(left, right + 1):
            painter.setPen(major_pen if gx % 5 == 0 else minor_pen)
            painter.drawLine(gx * LAMBDA_PX, top * LAMBDA_PX, gx * LAMBDA_PX, bottom * LAMBDA_PX)
        for gy in range(top, bottom + 1):
            painter.setPen(major_pen if gy % 5 == 0 else minor_pen)
            painter.drawLine(left * LAMBDA_PX, gy * LAMBDA_PX, right * LAMBDA_PX, gy * LAMBDA_PX)

        # Origin axes
        painter.setPen(QPen(QColor("#475569"), 0))
        painter.drawLine(0, top * LAMBDA_PX, 0, bottom * LAMBDA_PX)
        painter.drawLine(left * LAMBDA_PX, 0, right * LAMBDA_PX, 0)

    def rebuild_scene(self) -> None:
        self.scene().clear()
        self._preview_item = None

        for r in self.cell.rects:
            if r.layer not in self.visible_layers:
                continue
            ldef = LAYER_MAP.get(r.layer)
            if ldef is None:
                continue
            col = QColor(ldef.color_hex)
            fill = QColor(col.red(), col.green(), col.blue(), ldef.alpha)
            sx = r.x1 * LAMBDA_PX
            sy = -r.y2 * LAMBDA_PX
            sw = r.width * LAMBDA_PX
            sh = r.height * LAMBDA_PX

            item = QGraphicsRectItem(sx, sy, sw, sh)
            style = Qt.SolidPattern
            if ldef.hatch == "diag":
                style = Qt.BDiagPattern
            elif ldef.hatch == "cross":
                style = Qt.DiagCrossPattern
            item.setBrush(QBrush(fill, style))
            item.setPen(QPen(col.lighter(120), 1))
            item.setZValue(ldef.z_order)
            self.scene().addItem(item)

        # Labels
        lbl_font = QFont("Consolas", 9, QFont.Bold)
        for lbl in self.cell.labels:
            if lbl.layer not in self.visible_layers:
                continue
            t_item = QGraphicsSimpleTextItem(lbl.text)
            t_item.setFont(lbl_font)
            t_item.setBrush(QBrush(QColor("#FFFFFF")))
            t_item.setPos(lbl.x * LAMBDA_PX, -lbl.y * LAMBDA_PX - 12)
            t_item.setZValue(20)
            self.scene().addItem(t_item)

        # DRC Violation overlays
        drc_pen = QPen(QColor("#EF4444"), 2, Qt.DashLine)
        drc_fill = QBrush(QColor(239, 68, 68, 55), Qt.FDiagPattern)
        for v in self.violations:
            sx = v.x1 * LAMBDA_PX
            sy = -v.y2 * LAMBDA_PX
            sw = max(LAMBDA_PX, (v.x2 - v.x1) * LAMBDA_PX)
            sh = max(LAMBDA_PX, (v.y2 - v.y1) * LAMBDA_PX)
            v_item = QGraphicsRectItem(sx, sy, sw, sh)
            v_item.setPen(drc_pen)
            v_item.setBrush(drc_fill)
            v_item.setToolTip(f"[{v.rule}] {v.message}")
            v_item.setZValue(30)
            self.scene().addItem(v_item)

    def fit_layout(self) -> None:
        if self.cell.rects:
            br = self.scene().itemsBoundingRect().adjusted(-60, -60, 60, 60)
            self.fitInView(br, Qt.KeepAspectRatio)
        else:
            self.setSceneRect(-400, -400, 800, 800)

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and self.tool_mode == "pan"):
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            return

        lx, ly = self._to_lambda(self.mapToScene(event.position().toPoint()))
        if event.button() == Qt.LeftButton:
            if self.tool_mode == "paint":
                self._drag_start = (lx, ly)
                self._preview_item = QGraphicsRectItem(lx * LAMBDA_PX, -ly * LAMBDA_PX, 0, 0)
                self._preview_item.setPen(QPen(QColor("#FFFFFF"), 1.5, Qt.DashLine))
                self._preview_item.setZValue(25)
                self.scene().addItem(self._preview_item)
            elif self.tool_mode == "erase":
                self._erase_at(lx, ly)
            elif self.tool_mode == "label":
                text, ok = QInputDialog.getText(self, "Add Net Label", "Label text (e.g. IN, OUT, VDD):")
                if ok and text.strip():
                    self.cell.labels.append(LayoutLabel(text.strip(), self.active_layer, lx, ly))
                    self.violations.clear()
                    self.rebuild_scene()
                    self.cellModified.emit()

    def mouseMoveEvent(self, event) -> None:
        if self._panning and self._pan_start is not None:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            return

        lx, ly = self._to_lambda(self.mapToScene(event.position().toPoint()))
        self.coordsChanged.emit(lx, ly)

        if self._drag_start is not None and self._preview_item is not None:
            x0, y0 = self._drag_start
            x1, x2 = min(x0, lx), max(x0, lx)
            y1, y2 = min(y0, ly), max(y0, ly)
            self._preview_item.setRect(
                x1 * LAMBDA_PX,
                -y2 * LAMBDA_PX,
                (x2 - x1) * LAMBDA_PX,
                (y2 - y1) * LAMBDA_PX,
            )

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            return

        if event.button() == Qt.LeftButton and self._drag_start is not None:
            lx, ly = self._to_lambda(self.mapToScene(event.position().toPoint()))
            x0, y0 = self._drag_start
            self._drag_start = None
            if abs(lx - x0) >= 1 and abs(ly - y0) >= 1:
                self.cell.rects.append(LayoutRect(self.active_layer, x0, y0, lx, ly))
                self.violations.clear()
                self.cellModified.emit()
            self.rebuild_scene()

    def _erase_at(self, lx: int, ly: int) -> None:
        # Remove topmost matching visible rectangle under cursor
        for i in range(len(self.cell.rects) - 1, -1, -1):
            r = self.cell.rects[i]
            if r.layer in self.visible_layers and r.x1 <= lx <= r.x2 and r.y1 <= ly <= r.y2:
                self.cell.rects.pop(i)
                self.violations.clear()
                self.rebuild_scene()
                self.cellModified.emit()
                return


class LayoutEditor(QWidget):
    """Magic-style Layout Editor with layer palette, DRC, LVS, and SPICE extraction."""

    logMessage = Signal(str)
    lvsRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 6)

        self.btn_paint = QToolButton()
        self.btn_paint.setText("Paint Rect")
        self.btn_paint.setCheckable(True)
        self.btn_paint.setChecked(True)

        self.btn_erase = QToolButton()
        self.btn_erase.setText("Erase")
        self.btn_erase.setCheckable(True)

        self.btn_label = QToolButton()
        self.btn_label.setText("Label")
        self.btn_label.setCheckable(True)

        self.btn_pan = QToolButton()
        self.btn_pan.setText("Pan")
        self.btn_pan.setCheckable(True)

        tool_group = QButtonGroup(self)
        for b in (self.btn_paint, self.btn_erase, self.btn_label, self.btn_pan):
            tool_group.addButton(b)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Preset: CMOS Inverter", "Preset: CMOS NAND2", "Blank Cell"])
        self.btn_drc = QPushButton("Run DRC")
        self.btn_drc.setObjectName("primaryBtn")
        self.btn_lvs = QPushButton("Run LVS")
        self.btn_extract = QPushButton("Extract SPICE")
        self.btn_import_mag = QPushButton("Import .mag")
        self.btn_export_mag = QPushButton("Export .mag")
        self.coord_lbl = QLabel("0λ, 0λ")
        self.coord_lbl.setStyleSheet("color: #38BDF8; font-family: Consolas; padding: 0 8px;")

        for w in (
            self.btn_paint, self.btn_erase, self.btn_label, self.btn_pan,
            self.preset_combo, self.btn_drc, self.btn_lvs, self.btn_extract,
            self.btn_import_mag, self.btn_export_mag,
        ):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.coord_lbl)
        root.addLayout(bar)

        # Main Splitter: Layer Palette + Canvas
        splitter = QSplitter(Qt.Horizontal)

        palette_panel = QWidget()
        pal_layout = QVBoxLayout(palette_panel)
        pal_layout.setContentsMargins(8, 8, 8, 8)
        pal_hdr = QLabel("SCMOS Layers (λ)")
        pal_hdr.setStyleSheet("font-weight: 600; color: #38BDF8;")
        pal_layout.addWidget(pal_hdr)

        self.layer_group = QButtonGroup(self)
        for ldef in LAYERS:
            row = QHBoxLayout()
            vis_cb = QCheckBox()
            vis_cb.setChecked(True)
            vis_cb.toggled.connect(lambda checked, ln=ldef.name: self._toggle_layer(ln, checked))

            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(f"background-color: {ldef.color_hex}; border: 1px solid #94A3B8;")

            radio = QRadioButton(ldef.display_name)
            radio.setToolTip(f"Min Width: {ldef.min_width}λ | Min Spacing: {ldef.min_spacing}λ")
            if ldef.name == "metal1":
                radio.setChecked(True)
            radio.toggled.connect(lambda checked, ln=ldef.name: self._select_layer(ln, checked))
            self.layer_group.addButton(radio)

            row.addWidget(vis_cb)
            row.addWidget(swatch)
            row.addWidget(radio)
            row.addStretch()
            pal_layout.addLayout(row)

        pal_layout.addStretch()
        palette_panel.setMinimumWidth(210)
        palette_panel.setMaximumWidth(250)
        splitter.addWidget(palette_panel)

        self.scene = QGraphicsScene()
        self.canvas = _LayoutCanvas(self.scene)
        splitter.addWidget(self.canvas)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 5)
        root.addWidget(splitter)

        # Connections
        self.btn_paint.clicked.connect(lambda: setattr(self.canvas, "tool_mode", "paint"))
        self.btn_erase.clicked.connect(lambda: setattr(self.canvas, "tool_mode", "erase"))
        self.btn_label.clicked.connect(lambda: setattr(self.canvas, "tool_mode", "label"))
        self.btn_pan.clicked.connect(lambda: setattr(self.canvas, "tool_mode", "pan"))
        self.preset_combo.currentIndexChanged.connect(self._load_preset)
        self.btn_drc.clicked.connect(self.run_drc_check)
        self.btn_lvs.clicked.connect(self.lvsRequested.emit)
        self.btn_extract.clicked.connect(self.run_extract)
        self.btn_import_mag.clicked.connect(self._import_mag)
        self.btn_export_mag.clicked.connect(self._export_mag)
        self.canvas.coordsChanged.connect(lambda x, y: self.coord_lbl.setText(f"{x}λ, {y}λ"))

        self.canvas.rebuild_scene()
        self.canvas.fit_layout()

    def set_cell(self, cell: LayoutCell) -> None:
        self.canvas.cell = cell
        self.canvas.violations.clear()
        self.canvas.rebuild_scene()
        self.canvas.fit_layout()

    def _toggle_layer(self, layer_name: str, visible: bool) -> None:
        if visible:
            self.canvas.visible_layers.add(layer_name)
        else:
            self.canvas.visible_layers.discard(layer_name)
        self.canvas.rebuild_scene()

    def _select_layer(self, layer_name: str, checked: bool) -> None:
        if checked:
            self.canvas.active_layer = layer_name

    def _load_preset(self, idx: int) -> None:
        if idx == 0:
            self.set_cell(create_cmos_inverter())
        elif idx == 1:
            self.set_cell(create_cmos_nand2())
        else:
            self.set_cell(LayoutCell(name="custom_cell"))

    def run_drc_check(self) -> list[DRCViolation]:
        violations = run_drc(self.canvas.cell)
        self.canvas.violations = violations
        self.canvas.rebuild_scene()
        if not violations:
            self.logMessage.emit(f"[Magic DRC] PASS: 0 violations in '{self.canvas.cell.name}'.")
        else:
            self.logMessage.emit(f"[Magic DRC] FAIL: {len(violations)} violation(s) found:")
            for v in violations:
                self.logMessage.emit(f"  - [{v.rule}] {v.message} at ({v.x1},{v.y1})..({v.x2},{v.y2})λ")
        return violations

    def run_extract(self) -> None:
        res = extract_netlist(self.canvas.cell)
        self.logMessage.emit(
            f"[Magic Extract] Extracted {len(res.mosfets)} MOSFET(s) and {len(res.nets)} net(s) from '{res.cell_name}'."
        )
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Extracted SPICE Netlist — {res.cell_name}")
        dlg.resize(520, 340)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"Transistors: {len(res.mosfets)} | Nets: {len(res.nets)}"))
        txt = QPlainTextEdit(res.spice_text)
        txt.setReadOnly(True)
        txt.setFont(QFont("Consolas", 10))
        lay.addWidget(txt)
        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
        dlg.exec()

    def _import_mag(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Magic .mag", "", "Magic Layout (*.mag)")
        if path:
            with open(path, "r", encoding="utf-8") as f:
                cell = load_mag(f.read(), cell_name=path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].removesuffix(".mag"))
            self.set_cell(cell)
            self.logMessage.emit(f"[Magic] Imported '{path}' ({len(cell.rects)} shapes).")

    def _export_mag(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Magic .mag", f"{self.canvas.cell.name}.mag", "Magic Layout (*.mag)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(save_mag(self.canvas.cell))
            self.logMessage.emit(f"[Magic] Exported '{path}'.")

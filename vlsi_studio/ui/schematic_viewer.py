"""Vivado-style interactive RTL Schematic & Utilization Report viewer."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vlsi_studio.synth.synthesizer import Netlist

_NODE_COLORS = {
    "INPUT": "#10B981",
    "OUTPUT": "#3B82F6",
    "DFF": "#8B5CF6",
    "MUX": "#F59E0B",
    "ADD": "#EC4899",
    "SUB": "#EC4899",
    "CONST": "#64748B",
}


class _SchematicGraphicsView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QBrush(QColor("#0F1218")))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


class SchematicViewer(QWidget):
    """Vivado-style Elaborated/Synthesized Schematic + Resource Utilization."""

    COL_SPACING = 210
    ROW_SPACING = 90
    BOX_W = 120
    BOX_H = 48

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 6)
        self.title_lbl = QLabel("Synthesized Schematic: (none)")
        self.title_lbl.setStyleSheet("font-weight: 600;")
        self.btn_fit = QPushButton("Fit Schematic")
        bar.addWidget(self.title_lbl)
        bar.addStretch()
        bar.addWidget(self.btn_fit)
        root.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)
        self.scene = QGraphicsScene()
        self.view = _SchematicGraphicsView(self.scene)
        splitter.addWidget(self.view)

        # Right Utilization Panel
        util_panel = QWidget()
        util_layout = QVBoxLayout(util_panel)
        util_layout.setContentsMargins(8, 8, 8, 8)
        util_hdr = QLabel("Resource Utilization")
        util_hdr.setStyleSheet("font-weight: 600; color: #38BDF8;")
        util_layout.addWidget(util_hdr)

        self.util_table = QTableWidget(0, 2)
        self.util_table.setHorizontalHeaderLabels(["Resource", "Count"])
        self.util_table.horizontalHeader().setStretchLastSection(True)
        self.util_table.verticalHeader().setVisible(False)
        util_layout.addWidget(self.util_table)
        util_panel.setMinimumWidth(230)
        util_panel.setMaximumWidth(320)
        splitter.addWidget(util_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter)
        self.btn_fit.clicked.connect(self.fit_view)

    def fit_view(self) -> None:
        if not self.scene.items():
            return
        self.view.fitInView(self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)

    def set_netlist(self, netlist: Netlist) -> None:
        self.scene.clear()
        self.title_lbl.setText(f"Synthesized Schematic: {netlist.module_name}")

        node_pos: dict[str, tuple[float, float]] = {}
        font_title = QFont("Segoe UI", 9, QFont.Bold)
        font_sub = QFont("Consolas", 8)

        for nid, node in netlist.nodes.items():
            x = node.col * self.COL_SPACING
            y = node.row * self.ROW_SPACING
            node_pos[nid] = (x, y)

            accent = QColor(_NODE_COLORS.get(node.kind, "#06B6D4"))
            rect = QGraphicsRectItem(x, y, self.BOX_W, self.BOX_H)
            rect.setBrush(QBrush(QColor("#1A1E26")))
            rect.setPen(QPen(accent, 2))
            self.scene.addItem(rect)

            # Header strip
            hdr = QGraphicsRectItem(x, y, self.BOX_W, 18)
            hdr.setBrush(QBrush(accent))
            hdr.setPen(QPen(Qt.NoPen))
            self.scene.addItem(hdr)

            k_txt = QGraphicsSimpleTextItem(node.kind)
            k_txt.setFont(font_title)
            k_txt.setBrush(QBrush(QColor("#0F1218")))
            k_txt.setPos(x + 6, y + 1)
            self.scene.addItem(k_txt)

            lbl_txt = QGraphicsSimpleTextItem(node.label)
            lbl_txt.setFont(font_sub)
            lbl_txt.setBrush(QBrush(QColor("#E6EDF3")))
            lbl_txt.setPos(x + 6, y + 23)
            self.scene.addItem(lbl_txt)

        # Draw edges
        wire_pen = QPen(QColor("#64748B"), 1.8)
        for edge in netlist.edges:
            if edge.src_id not in node_pos or edge.dst_id not in node_pos:
                continue
            sx, sy = node_pos[edge.src_id]
            dx, dy = node_pos[edge.dst_id]
            p1x, p1y = sx + self.BOX_W, sy + self.BOX_H / 2
            p2x, p2y = dx, dy + self.BOX_H / 2
            mid_x = (p1x + p2x) / 2

            path = QPainterPath()
            path.moveTo(p1x, p1y)
            path.cubicTo(mid_x, p1y, mid_x, p2y, p2x, p2y)
            item = QGraphicsPathItem(path)
            item.setPen(wire_pen)
            item.setZValue(-1)
            self.scene.addItem(item)

        self._populate_utilization(netlist)
        self.fit_view()

    def _populate_utilization(self, netlist: Netlist) -> None:
        rep = netlist.report
        rows = [
            ("Bonded IOBs (In)", str(rep.inputs)),
            ("Bonded IOBs (Out)", str(rep.outputs)),
            ("LUTs / Logic Gates", str(rep.luts_and_gates)),
            ("Flip-Flops (DFF)", str(rep.flip_flops)),
            ("Adders / Sub", str(rep.adders)),
            ("Multiplexers", str(rep.muxes)),
            ("Logic Depth", f"{rep.logic_depth} levels"),
        ]
        for k, v in sorted(rep.cell_breakdown.items()):
            rows.append((f"  Cell: {k}", str(v)))

        self.util_table.setRowCount(len(rows))
        for r_idx, (name, val) in enumerate(rows):
            self.util_table.setItem(r_idx, 0, QTableWidgetItem(name))
            self.util_table.setItem(r_idx, 1, QTableWidgetItem(val))

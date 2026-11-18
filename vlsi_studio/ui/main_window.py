"""Main unified IDE window combining ModelSim, Vivado, and Magic workflows."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vlsi_studio.layout import generate_layout_from_netlist, run_drc, run_lvs
from vlsi_studio.models.project import VLSIProject
from vlsi_studio.synth.synthesizer import synthesize_module
from vlsi_studio.ui.layout_editor import LayoutEditor
from vlsi_studio.ui.rtl_editor import CodeEditor
from vlsi_studio.ui.schematic_viewer import SchematicViewer
from vlsi_studio.ui.waveform_viewer import WaveformViewer
from vlsi_studio.verilog.parser import VerilogSyntaxError, parse_verilog
from vlsi_studio.verilog.simulator import VerilogSimulator


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SiliconForge VLSI Studio — RTL · Synthesis · Layout")
        self.resize(1380, 860)

        self.project = VLSIProject.sample_full_adder()
        self.current_file_group: str = "rtl"  # "rtl" or "tb"
        self.current_file_name: str = ""

        self._build_central_tabs()
        self._build_docks()
        self._build_menus_and_toolbar()
        self._load_project(self.project)

    def _build_central_tabs(self) -> None:
        self.tabs = QTabWidget()

        # Tab 0: RTL / Testbench Editor
        editor_wrap = QWidget()
        ed_lay = QVBoxLayout(editor_wrap)
        ed_lay.setContentsMargins(0, 0, 0, 0)
        ed_lay.setSpacing(0)
        self.editor_header = QLabel("Editing: (none)")
        self.editor_header.setStyleSheet("background-color: #1A1E26; padding: 6px 10px; font-weight: 600;")
        self.code_editor = CodeEditor()
        self.code_editor.textChanged.connect(self._on_code_changed)
        ed_lay.addWidget(self.editor_header)
        ed_lay.addWidget(self.code_editor)

        self.waveform_viewer = WaveformViewer()
        self.schematic_viewer = SchematicViewer()
        self.layout_editor = LayoutEditor()
        self.layout_editor.logMessage.connect(self.log)
        self.layout_editor.lvsRequested.connect(self.run_lvs_check)

        self.tabs.addTab(editor_wrap, "1. RTL / Testbench")
        self.tabs.addTab(self.waveform_viewer, "2. Waveforms (ModelSim)")
        self.tabs.addTab(self.schematic_viewer, "3. Schematic & Synthesis (Vivado)")
        self.tabs.addTab(self.layout_editor, "4. Physical Layout & DRC (Magic)")
        self.setCentralWidget(self.tabs)

    def _build_docks(self) -> None:
        # Left Dock: Project Explorer + Flow Navigator
        left_dock = QDockWidget("Project & Flow Navigator", self)
        left_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        left_w = QWidget()
        left_l = QVBoxLayout(left_w)
        left_l.setContentsMargins(6, 6, 6, 6)

        self.proj_tree = QTreeWidget()
        self.proj_tree.setHeaderHidden(True)
        self.proj_tree.itemClicked.connect(self._on_tree_clicked)
        left_l.addWidget(self.proj_tree, stretch=2)

        flow_lbl = QLabel("EDA Flow Actions")
        flow_lbl.setStyleSheet("font-weight: 600; color: #38BDF8; margin-top: 6px;")
        left_l.addWidget(flow_lbl)

        btn_sim = QPushButton("▶ Run Simulation (ModelSim)")
        btn_sim.setObjectName("primaryBtn")
        btn_sim.clicked.connect(self.run_simulation)

        btn_synth = QPushButton("⚙ Synthesize & Schematic (Vivado)")
        btn_synth.clicked.connect(self.run_synthesis)

        btn_gen_lay = QPushButton("🧱 Generate Layout from RTL (PnR)")
        btn_gen_lay.clicked.connect(self.run_layout_gen)

        btn_drc = QPushButton("✓ Run Layout DRC (Magic)")
        btn_drc.clicked.connect(self.run_drc)

        btn_lvs = QPushButton("⇄ Run LVS Check (Layout vs Schematic)")
        btn_lvs.clicked.connect(self.run_lvs_check)

        btn_ext = QPushButton("☍ Extract SPICE Netlist")
        btn_ext.clicked.connect(self.run_extract)

        for b in (btn_sim, btn_synth, btn_gen_lay, btn_drc, btn_lvs, btn_ext):
            left_l.addWidget(b)

        left_dock.setWidget(left_w)
        left_dock.setMinimumWidth(250)
        self.addDockWidget(Qt.LeftDockWidgetArea, left_dock)

        # Bottom Dock: Transcript & Tcl Command Bar
        bot_dock = QDockWidget("Transcript & Console", self)
        bot_w = QWidget()
        bot_l = QVBoxLayout(bot_w)
        bot_l.setContentsMargins(6, 6, 6, 6)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 9))
        bot_l.addWidget(self.console)

        cmd_row = QHBoxLayout()
        cmd_row.addWidget(QLabel("Tcl>"))
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Type command: sim, synth, genlayout, drc, lvs, extract, clear, help")
        self.cmd_input.returnPressed.connect(self._run_console_cmd)
        cmd_row.addWidget(self.cmd_input)
        bot_l.addLayout(cmd_row)

        bot_dock.setWidget(bot_w)
        bot_dock.setMinimumHeight(160)
        self.addDockWidget(Qt.BottomDockWidgetArea, bot_dock)

    def _build_menus_and_toolbar(self) -> None:
        menu = self.menuBar()
        file_m = menu.addMenu("&File")
        act_new = QAction("New Verilog Scratchpad (.v)", self)
        act_new.setShortcut("Ctrl+N")
        act_new.triggered.connect(self._new_scratchpad)
        act_adder = QAction("Load Demo: 1-bit Full Adder + CMOS Inverter", self)
        act_adder.triggered.connect(lambda: self._load_project(VLSIProject.sample_full_adder()))
        act_cnt = QAction("Load Demo: 4-bit Counter + CMOS NAND2", self)
        act_cnt.triggered.connect(lambda: self._load_project(VLSIProject.sample_counter()))
        act_cpu = QAction("Load Demo: 4-bit Accumulator CPU", self)
        act_cpu.triggered.connect(lambda: self._load_project(VLSIProject.sample_cpu4()))
        act_imp_rtl = QAction("Import RTL File (.v)...", self)
        act_imp_rtl.triggered.connect(lambda: self._import_verilog("rtl"))
        act_imp_tb = QAction("Import Testbench File (.v)...", self)
        act_imp_tb.triggered.connect(lambda: self._import_verilog("tb"))
        act_open = QAction("Open Verilog / Project...", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self._open_files_or_project)
        act_save = QAction("Save Active Verilog (.v)...", self)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(self._save_active_verilog)
        act_save_proj = QAction("Save Project Bundle (.vlsiproj)...", self)
        act_save_proj.triggered.connect(self._save_project)
        act_exit = QAction("Exit", self)
        act_exit.triggered.connect(self.close)

        for a in (act_new, act_adder, act_cnt, act_cpu, act_imp_rtl, act_imp_tb, act_open, act_save, act_save_proj, act_exit):
            file_m.addAction(a)

        flow_m = menu.addMenu("&Flow")
        flow_m.addAction("Run Simulation", self.run_simulation)
        flow_m.addAction("Synthesize & View Schematic", self.run_synthesis)
        flow_m.addAction("Generate Layout from RTL (Auto PnR)", self.run_layout_gen)
        flow_m.addAction("Run Magic DRC", self.run_drc)
        flow_m.addAction("Run LVS Check (Layout vs Schematic)", self.run_lvs_check)
        flow_m.addAction("Extract SPICE Netlist", self.run_extract)

        help_m = menu.addMenu("&Help")
        help_m.addAction("About SiliconForge", self._show_about)

        tb = self.addToolBar("Main Toolbar")
        tb.setMovable(False)
        tb.addAction("📄 New .v", self._new_scratchpad)
        tb.addAction("▶ Simulate", self.run_simulation)
        tb.addAction("⚙ Synthesize", self.run_synthesis)
        tb.addAction("🧱 Generate Layout", self.run_layout_gen)
        tb.addAction("✓ Magic DRC", self.run_drc)
        tb.addAction("⇄ LVS Check", self.run_lvs_check)
        tb.addAction("☍ Extract SPICE", self.run_extract)
        tb.addSeparator()
        tb.addAction("Demo: Full Adder", lambda: self._load_project(VLSIProject.sample_full_adder()))
        tb.addAction("Demo: 4-bit Counter", lambda: self._load_project(VLSIProject.sample_counter()))
        tb.addAction("Demo: 4-bit CPU", lambda: self._load_project(VLSIProject.sample_cpu4()))

        self.statusBar().showMessage("Ready — Self-contained RTL Simulation, Synthesis, and Magic Layout")

    def log(self, msg: str) -> None:
        self.console.appendPlainText(msg)

    def _load_project(self, proj: VLSIProject) -> None:
        self.project = proj
        self.proj_tree.clear()

        root_item = QTreeWidgetItem([proj.name])
        rtl_node = QTreeWidgetItem(["RTL Design Sources"])
        for fname in proj.rtl_files:
            item = QTreeWidgetItem([fname])
            item.setData(0, Qt.UserRole, ("rtl", fname))
            rtl_node.addChild(item)

        tb_node = QTreeWidgetItem(["Testbench Sources"])
        for fname in proj.tb_files:
            item = QTreeWidgetItem([fname])
            item.setData(0, Qt.UserRole, ("tb", fname))
            tb_node.addChild(item)

        lay_node = QTreeWidgetItem(["Physical Layout (Magic)"])
        cell_item = QTreeWidgetItem([f"{proj.layout.name}.mag"])
        cell_item.setData(0, Qt.UserRole, ("layout", proj.layout.name))
        lay_node.addChild(cell_item)

        root_item.addChild(rtl_node)
        root_item.addChild(tb_node)
        root_item.addChild(lay_node)
        self.proj_tree.addTopLevelItem(root_item)
        self.proj_tree.expandAll()

        self.layout_editor.set_cell(proj.layout)
        if proj.rtl_files:
            first_rtl = next(iter(proj.rtl_files))
            self._open_editor_file("rtl", first_rtl)

        self.log(f"[Project] Loaded '{proj.name}'.")

    def _open_editor_file(self, group: str, fname: str) -> None:
        self.current_file_group = group
        self.current_file_name = fname
        src = self.project.rtl_files.get(fname, "") if group == "rtl" else self.project.tb_files.get(fname, "")
        self.code_editor.blockSignals(True)
        self.code_editor.setPlainText(src)
        self.code_editor.set_error_line(None)
        self.code_editor.blockSignals(False)
        self.editor_header.setText(f"Editing ({group.upper()}): {fname}")
        self.tabs.setCurrentIndex(0)

    def _on_code_changed(self) -> None:
        self.code_editor.set_error_line(None)
        if not self.current_file_name:
            return
        text = self.code_editor.toPlainText()
        if self.current_file_group == "rtl":
            self.project.rtl_files[self.current_file_name] = text
        else:
            self.project.tb_files[self.current_file_name] = text

    def _on_tree_clicked(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, name = data
        if kind in ("rtl", "tb"):
            self._open_editor_file(kind, name)
        elif kind == "layout":
            self.tabs.setCurrentIndex(3)

    def _new_scratchpad(self) -> None:
        starter = (
            "// Write or paste any Verilog module (and optional testbench) here\n"
            "module my_design (\n"
            "    input  a,\n"
            "    input  b,\n"
            "    output y\n"
            ");\n"
            "    assign y = a & b;\n"
            "endmodule\n"
        )
        proj = VLSIProject(name="Verilog_Scratchpad", rtl_files={"design.v": starter}, tb_files={})
        self._load_project(proj)

    def _handle_syntax_error(self, exc: VerilogSyntaxError, file_label: str = "") -> None:
        msg = f"{file_label}: {exc}" if file_label else str(exc)
        self.log(f"[Verilog Error] {msg}")
        if not file_label or file_label == self.current_file_name:
            if exc.line > 0:
                self.code_editor.set_error_line(exc.line)
                blk = self.code_editor.document().findBlockByNumber(exc.line - 1)
                if blk.isValid():
                    cur = self.code_editor.textCursor()
                    cur.setPosition(blk.position())
                    self.code_editor.setTextCursor(cur)
                    self.code_editor.centerCursor()
                self.tabs.setCurrentIndex(0)
        QMessageBox.warning(self, "Verilog Syntax Error", msg)

    def _collect_modules(self):
        # Preserve leading newlines in editor_text so reported error line numbers match editor line numbers 1:1
        editor_text = self.code_editor.toPlainText()
        try:
            editor_mods = parse_verilog(editor_text) if editor_text.strip() else []
        except VerilogSyntaxError as exc:
            exc._file_label = self.current_file_name  # type: ignore[attr-defined]
            raise
        self.code_editor.set_error_line(None)
        editor_names = {m.name for m in editor_mods}

        all_mods = list(editor_mods)
        other_sources: list[tuple[str, str]] = []
        for fname, txt in self.project.rtl_files.items():
            if not (self.current_file_group == "rtl" and fname == self.current_file_name):
                other_sources.append((fname, txt))
        for fname, txt in self.project.tb_files.items():
            if not (self.current_file_group == "tb" and fname == self.current_file_name):
                other_sources.append((fname, txt))

        for fname, src in other_sources:
            if not src.strip():
                continue
            try:
                parsed = parse_verilog(src)
            except VerilogSyntaxError as exc:
                exc._file_label = fname  # type: ignore[attr-defined]
                raise
            for m in parsed:
                if m.name not in editor_names:
                    inst_names = {i.module_name for i in m.instances}
                    editor_inst_names = {i.module_name for em in editor_mods for i in em.instances}
                    if not editor_mods or (inst_names & editor_names) or (m.name in editor_inst_names):
                        all_mods.append(m)
        return all_mods

    def run_simulation(self, checked: bool = False, confirm: bool = True) -> None:
        try:
            modules = self._collect_modules()
        except VerilogSyntaxError as exc:
            self._handle_syntax_error(exc, getattr(exc, "_file_label", ""))
            return

        if not modules:
            QMessageBox.information(self, "Simulate", "Write or open a Verilog module first.")
            return

        sim = VerilogSimulator(modules)
        default_top = sim.choose_top_module()
        names = [m.name for m in modules]
        top_name = default_top

        if confirm:
            default_idx = names.index(default_top) if default_top in names else 0
            chosen, ok = QInputDialog.getItem(
                self,
                "Permission to Simulate",
                f"Detected {len(names)} module(s). Select top module to simulate:",
                names,
                default_idx,
                False,
            )
            if not ok:
                self.log("[ModelSim] Simulation cancelled by user.")
                return
            top_name = chosen

        res = sim.run(top_module=top_name)
        self.log(f"[ModelSim] Simulated top module '{res.top_module}' (0..{res.end_time} ns).")
        for line in res.console_output:
            self.log(f"  {line}")
        self.waveform_viewer.set_trace(res.trace)
        self.tabs.setCurrentIndex(1)
        self.statusBar().showMessage(f"Simulation complete: {res.top_module} ({res.end_time} ns)")

    def run_synthesis(self, checked: bool = False, confirm: bool = True) -> None:
        try:
            modules = self._collect_modules()
        except VerilogSyntaxError as exc:
            self._handle_syntax_error(exc, getattr(exc, "_file_label", ""))
            return

        if not modules:
            self.log("[Vivado Synth] No RTL modules found to synthesize.")
            QMessageBox.information(self, "Synthesize", "Write or open a Verilog module first.")
            return

        # Prefer modules with ports (DUT), fall back to all modules
        dut_candidates = [m for m in modules if m.port_order] or modules
        names = [m.name for m in dut_candidates]
        dut = dut_candidates[0]

        if confirm:
            chosen, ok = QInputDialog.getItem(
                self,
                "Permission to Synthesize",
                f"Detected {len(names)} synthesizable module(s). Select module to synthesize:",
                names,
                0,
                False,
            )
            if not ok:
                self.log("[Vivado Synth] Synthesis cancelled by user.")
                return
            dut = next(m for m in dut_candidates if m.name == chosen)

        netlist = synthesize_module(dut)
        self.schematic_viewer.set_netlist(netlist)
        self.tabs.setCurrentIndex(2)
        rep = netlist.report
        self.log(
            f"[Vivado Synth] Synthesized '{dut.name}': "
            f"{rep.luts_and_gates} LUTs/Gates, {rep.flip_flops} FFs, "
            f"{rep.inputs + rep.outputs} IOBs, depth={rep.logic_depth}."
        )
        self.statusBar().showMessage(f"Synthesis complete: {dut.name}")

    def run_layout_gen(self, checked: bool = False, confirm: bool = True) -> None:
        try:
            modules = self._collect_modules()
        except VerilogSyntaxError as exc:
            self._handle_syntax_error(exc, getattr(exc, "_file_label", ""))
            return

        if not modules:
            QMessageBox.information(self, "Generate Layout", "Write or open a Verilog module first.")
            return

        dut_candidates = [m for m in modules if m.port_order] or modules
        names = [m.name for m in dut_candidates]
        dut = dut_candidates[0]

        if confirm:
            chosen, ok = QInputDialog.getItem(
                self,
                "Permission to Generate Layout",
                f"Synthesize & auto-generate Magic layout for module:",
                names,
                0,
                False,
            )
            if not ok:
                self.log("[PnR Layout] Layout generation cancelled by user.")
                return
            dut = next(m for m in dut_candidates if m.name == chosen)

        netlist = synthesize_module(dut)
        self.schematic_viewer.set_netlist(netlist)
        cell = generate_layout_from_netlist(netlist)
        self.project.layout = cell
        self.layout_editor.set_cell(cell)
        violations = run_drc(cell)
        self.layout_editor.canvas.violations = violations
        self.layout_editor.canvas.rebuild_scene()

        # Refresh tree layout node label without disturbing current editor text
        for i in range(self.proj_tree.topLevelItemCount()):
            top_item = self.proj_tree.topLevelItem(i)
            for j in range(top_item.childCount()):
                cat = top_item.child(j)
                if cat.text(0).startswith("Physical Layout") and cat.childCount() > 0:
                    cat.child(0).setText(0, f"{cell.name}.mag")

        self.tabs.setCurrentIndex(3)
        self.log(
            f"[PnR Layout] Generated layout '{cell.name}.mag' ({len(cell.rects)} shapes, DRC violations: {len(violations)})."
        )
        self.statusBar().showMessage(
            f"Layout generated: {cell.name}.mag ({len(cell.rects)} shapes, {len(violations)} DRC errors)"
        )

    def run_drc(self) -> None:
        self.tabs.setCurrentIndex(3)
        violations = self.layout_editor.run_drc_check()
        self.statusBar().showMessage(
            "DRC Clean (0 violations)" if not violations else f"DRC Failed: {len(violations)} violation(s)"
        )

    def run_lvs_check(self, checked: bool = False, show_dialog: bool = True):
        netlist = None
        try:
            modules = self._collect_modules()
            dut_candidates = [m for m in modules if m.port_order] or modules
            if dut_candidates:
                cell_name = self.layout_editor.canvas.cell.name
                dut = next((m for m in dut_candidates if m.name == cell_name), dut_candidates[0])
                netlist = synthesize_module(dut)
        except VerilogSyntaxError as exc:
            self._handle_syntax_error(exc, getattr(exc, "_file_label", ""))
            return None

        cell = self.layout_editor.canvas.cell
        report = run_lvs(netlist, cell)
        self.log(f"[LVS] {report.summary}")
        for item in report.checks:
            tag = "PASS" if item.passed else "FAIL"
            self.log(f"  [{tag}] {item.name}: Schematic={item.schematic_val} | Layout={item.layout_val}")
        for m in report.mismatches:
            self.log(f"  [Mismatch] {m}")

        self.statusBar().showMessage(report.summary)
        if show_dialog:
            self._show_lvs_dialog(report)
        return report

    def _show_lvs_dialog(self, report) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(f"LVS Verification Report — {report.cell_name}")
        dlg.resize(620, 380)
        lay = QVBoxLayout(dlg)

        banner_col = "#10B981" if report.matched else "#EF4444"
        banner = QLabel(report.summary)
        banner.setStyleSheet(
            f"background-color: #1A1E26; color: {banner_col}; font-weight: 700; "
            f"font-size: 11pt; padding: 10px; border: 1px solid {banner_col}; border-radius: 4px;"
        )
        lay.addWidget(banner)

        table = QTableWidget(len(report.checks), 4)
        table.setHorizontalHeaderLabels(["Check", "Schematic", "Layout", "Result"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        for r_idx, chk in enumerate(report.checks):
            table.setItem(r_idx, 0, QTableWidgetItem(chk.name))
            table.setItem(r_idx, 1, QTableWidgetItem(chk.schematic_val))
            table.setItem(r_idx, 2, QTableWidgetItem(chk.layout_val))
            res_item = QTableWidgetItem("PASS" if chk.passed else f"FAIL ({chk.note})")
            res_item.setForeground(QColor("#10B981" if chk.passed else "#EF4444"))
            table.setItem(r_idx, 3, res_item)
        table.resizeColumnsToContents()
        lay.addWidget(table)

        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
        dlg.exec()

    def run_extract(self) -> None:
        self.tabs.setCurrentIndex(3)
        self.layout_editor.run_extract()

    def _run_console_cmd(self) -> None:
        cmd = self.cmd_input.text().strip().lower()
        self.cmd_input.clear()
        if not cmd:
            return
        self.log(f"Tcl> {cmd}")
        if cmd in ("sim", "run_sim", "simulate"):
            self.run_simulation()
        elif cmd in ("synth", "synthesize"):
            self.run_synthesis()
        elif cmd in ("genlayout", "layout", "pnr"):
            self.run_layout_gen()
        elif cmd == "drc":
            self.run_drc()
        elif cmd == "lvs":
            self.run_lvs_check()
        elif cmd in ("extract", "ext"):
            self.run_extract()
        elif cmd == "clear":
            self.console.clear()
        elif cmd == "help":
            self.log("Available commands: sim, synth, genlayout, drc, lvs, extract, clear, help")
        else:
            self.log(f"Unknown command '{cmd}'. Type 'help' for commands.")

    def _import_verilog(self, group: str) -> None:
        from pathlib import Path
        path, _ = QFileDialog.getOpenFileName(self, f"Import {group.upper()} Verilog", "", "Verilog Files (*.v *.sv)")
        if not path:
            return
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        if group == "rtl":
            self.project.rtl_files[p.name] = text
        else:
            self.project.tb_files[p.name] = text
        self._load_project(self.project)
        self._open_editor_file(group, p.name)
        self.log(f"[Project] Imported {group.upper()} file '{p.name}'.")

    def _open_files_or_project(self) -> None:
        from pathlib import Path
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open Verilog Files or Project",
            "",
            "Verilog Files (*.v *.sv);;VLSI Project (*.vlsiproj);;All Files (*.*)",
        )
        if not paths:
            return
        if len(paths) == 1 and paths[0].lower().endswith(".vlsiproj"):
            self._load_project(VLSIProject.load_from_file(paths[0]))
            return

        last_group, last_name = "rtl", ""
        for raw_path in paths:
            p = Path(raw_path)
            text = p.read_text(encoding="utf-8")
            is_tb = p.name.lower().startswith("tb_") or "initial" in text
            group = "tb" if is_tb else "rtl"
            if group == "tb":
                self.project.tb_files[p.name] = text
            else:
                self.project.rtl_files[p.name] = text
            last_group, last_name = group, p.name
            self.log(f"[Open] Loaded {group.upper()} file '{p.name}'.")

        self._load_project(self.project)
        if last_name:
            self._open_editor_file(last_group, last_name)

    def _save_active_verilog(self) -> None:
        from pathlib import Path
        default_name = self.current_file_name or "design.v"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Verilog File",
            default_name,
            "Verilog Files (*.v *.sv);;All Files (*.*)",
        )
        if path:
            Path(path).write_text(self.code_editor.toPlainText(), encoding="utf-8")
            self.log(f"[Save] Saved '{path}'.")

    def _save_project(self) -> None:
        self.project.layout = self.layout_editor.canvas.cell
        path, _ = QFileDialog.getSaveFileName(self, "Save VLSI Project", f"{self.project.name}.vlsiproj", "VLSI Project (*.vlsiproj)")
        if path:
            self.project.save_to_file(path)
            self.log(f"[Project] Saved to '{path}'.")

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "About SiliconForge VLSI Studio",
            "SiliconForge VLSI Studio v0.1.0\n\n"
            "Self-contained Educational VLSI Suite for Windows combining:\n"
            "• ModelSim-style Verilog Simulation & Waveforms (+ VCD export)\n"
            "• Vivado-style RTL Synthesis, Schematic & Utilization\n"
            "• Magic-style 2D SCMOS Layout, DRC & SPICE Extraction (.mag I/O)",
        )

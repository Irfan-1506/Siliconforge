"""Synthesizes a Verilog ModuleDef into a gate/RTL netlist with topological layout."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from vlsi_studio.verilog.ast_nodes import (
    AssignStmt,
    BinaryOp,
    BlockStmt,
    CaseStmt,
    ConcatExpr,
    Expr,
    ForStmt,
    IdentExpr,
    IfStmt,
    IndexExpr,
    ModuleDef,
    NumberLiteral,
    PartSelectExpr,
    RepeatStmt,
    ReplicateExpr,
    SliceExpr,
    Stmt,
    SysFuncExpr,
    TernaryOp,
    UnaryOp,
    WhileStmt,
)


@dataclass
class NetNode:
    id: str
    label: str
    kind: str  # INPUT, OUTPUT, AND, OR, NAND, NOR, XOR, NOT, BUF, MUX, ADD, SUB, CMP, DFF, CONST
    width: int = 1
    col: int = 0
    row: int = 0


@dataclass
class NetEdge:
    src_id: str
    dst_id: str
    label: str = ""


@dataclass
class UtilizationReport:
    module_name: str
    inputs: int = 0
    outputs: int = 0
    luts_and_gates: int = 0
    flip_flops: int = 0
    adders: int = 0
    muxes: int = 0
    logic_depth: int = 0
    cell_breakdown: dict[str, int] = field(default_factory=dict)


@dataclass
class Netlist:
    module_name: str
    nodes: dict[str, NetNode] = field(default_factory=dict)
    edges: list[NetEdge] = field(default_factory=list)
    report: UtilizationReport = field(default_factory=lambda: UtilizationReport(""))


class _NetlistBuilder:
    def __init__(self, mod: ModuleDef):
        self.mod = mod
        self.netlist = Netlist(module_name=mod.name, report=UtilizationReport(module_name=mod.name))
        self.signal_driver: dict[str, str] = {}
        self.reg_dff: dict[str, str] = {}
        self._counter = 0

    def _new_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    def _add_node(self, node_id: str, label: str, kind: str, width: int = 1) -> str:
        self.netlist.nodes[node_id] = NetNode(id=node_id, label=label, kind=kind, width=width)
        return node_id

    def _add_edge(self, src_id: str, dst_id: str, label: str = "") -> None:
        if src_id and dst_id:
            self.netlist.edges.append(NetEdge(src_id=src_id, dst_id=dst_id, label=label))

    def build(self) -> Netlist:
        # 1. Create Input & Output port nodes
        for pname in self.mod.port_order:
            sdecl = self.mod.signals.get(pname)
            if sdecl is None:
                continue
            if sdecl.kind == "input":
                nid = f"IN_{pname}"
                self._add_node(nid, f"{pname} [{sdecl.width}b]" if sdecl.width > 1 else pname, "INPUT", sdecl.width)
                self.signal_driver[pname] = nid
                self.netlist.report.inputs += sdecl.width

        # 2. Gate primitives
        for g in self.mod.gates:
            gid = self._new_id(g.gate_type.upper())
            self._add_node(gid, g.gate_type.upper(), g.gate_type.upper(), 1)
            for inp in g.inputs:
                src = self._synth_expr(inp)
                self._add_edge(src, gid)
            if isinstance(g.output, IdentExpr):
                self.signal_driver[g.output.name] = gid

        # 3. Continuous assignments
        for ca in self.mod.assigns:
            drv = self._synth_expr(ca.expr)
            if ca.lhs_concat:
                for t in ca.lhs_concat:
                    self.signal_driver[t] = drv
            else:
                self.signal_driver[ca.target] = drv

        # 4. Always blocks
        for ab in self.mod.always_blocks:
            is_seq = any(s.edge in ("posedge", "negedge") for s in ab.sensitivity)
            clk_sig = next((s.signal for s in ab.sensitivity if s.edge in ("posedge", "negedge") and s.signal), None)
            self._synth_stmt(ab.body, is_seq=is_seq, clk_sig=clk_sig, cond_chain=[])

        # 5. Connect Output port nodes
        for pname in self.mod.port_order:
            sdecl = self.mod.signals.get(pname)
            if sdecl and sdecl.kind in ("output", "reg", "inout"):
                out_id = f"OUT_{pname}"
                self._add_node(out_id, f"{pname} [{sdecl.width}b]" if sdecl.width > 1 else pname, "OUTPUT", sdecl.width)
                self.netlist.report.outputs += sdecl.width
                drv = self.signal_driver.get(pname)
                if drv:
                    self._add_edge(drv, out_id, pname)

        self._compute_layout_and_report()
        return self.netlist

    def _synth_expr(self, expr: Expr) -> str:
        if isinstance(expr, NumberLiteral):
            nid = self._new_id("CONST")
            self._add_node(nid, f"{expr.width}'d{expr.value}", "CONST", expr.width)
            return nid
        if isinstance(expr, IdentExpr):
            if expr.name in self.signal_driver:
                return self.signal_driver[expr.name]
            nid = self._new_id("SIG")
            self._add_node(nid, expr.name, "BUF", 1)
            self.signal_driver[expr.name] = nid
            return nid
        if isinstance(expr, IndexExpr):
            src = self.signal_driver.get(expr.name)
            nid = self._new_id("SLICE")
            self._add_node(nid, f"{expr.name}[..]", "BUF", 1)
            if src:
                self._add_edge(src, nid)
            return nid
        if isinstance(expr, SliceExpr):
            src = self.signal_driver.get(expr.name)
            nid = self._new_id("SLICE")
            self._add_node(nid, f"{expr.name}[{expr.msb}:{expr.lsb}]", "BUF", abs(expr.msb - expr.lsb) + 1)
            if src:
                self._add_edge(src, nid)
            return nid
        if isinstance(expr, PartSelectExpr):
            src = self.signal_driver.get(expr.name)
            nid = self._new_id("SLICE")
            self._add_node(nid, f"{expr.name}[..]", "BUF", expr.width)
            if src:
                self._add_edge(src, nid)
            return nid
        if isinstance(expr, ConcatExpr):
            nid = self._new_id("CONCAT")
            self._add_node(nid, "{...}", "BUF", 1)
            for p in expr.parts:
                self._add_edge(self._synth_expr(p), nid)
            return nid
        if isinstance(expr, ReplicateExpr):
            nid = self._new_id("REP")
            self._add_node(nid, f"{{{expr.count}{{...}}}}", "BUF", 1)
            self._add_edge(self._synth_expr(expr.expr), nid)
            return nid
        if isinstance(expr, SysFuncExpr):
            nid = self._new_id("CONST")
            self._add_node(nid, expr.name, "CONST", 32)
            return nid
        if isinstance(expr, UnaryOp):
            kind = "NOT" if expr.op in ("~", "!") else "BUF"
            nid = self._new_id(kind)
            self._add_node(nid, f"UNARY {expr.op}", kind, 1)
            self._add_edge(self._synth_expr(expr.operand), nid)
            return nid
        if isinstance(expr, BinaryOp):
            op_map = {
                "&": "AND", "~&": "NAND", "|": "OR", "~|": "NOR",
                "^": "XOR", "^~": "XNOR", "+": "ADD", "-": "SUB",
                "==": "CMP", "!=": "CMP", "<": "CMP", "<=": "CMP", ">": "CMP", ">=": "CMP",
                "&&": "AND", "||": "OR",
            }
            kind = op_map.get(expr.op, "LUT")
            nid = self._new_id(kind)
            self._add_node(nid, expr.op, kind, 1)
            self._add_edge(self._synth_expr(expr.left), nid)
            self._add_edge(self._synth_expr(expr.right), nid)
            return nid
        if isinstance(expr, TernaryOp):
            nid = self._new_id("MUX")
            self._add_node(nid, "MUX 2:1", "MUX", 1)
            self._add_edge(self._synth_expr(expr.cond), nid, "sel")
            self._add_edge(self._synth_expr(expr.true_expr), nid, "1")
            self._add_edge(self._synth_expr(expr.false_expr), nid, "0")
            return nid
        nid = self._new_id("CELL")
        self._add_node(nid, "LOGIC", "BUF", 1)
        return nid

    def _synth_stmt(
        self,
        stmt: Stmt,
        is_seq: bool,
        clk_sig: Optional[str],
        cond_chain: list[Expr],
    ) -> None:
        if isinstance(stmt, BlockStmt):
            for s in stmt.stmts:
                self._synth_stmt(s, is_seq, clk_sig, cond_chain)
        elif isinstance(stmt, IfStmt):
            self._synth_stmt(stmt.then_stmt, is_seq, clk_sig, cond_chain + [stmt.cond])
            if stmt.else_stmt is not None:
                self._synth_stmt(stmt.else_stmt, is_seq, clk_sig, cond_chain + [stmt.cond])
        elif isinstance(stmt, CaseStmt):
            for _, arm_stmt in stmt.arms:
                self._synth_stmt(arm_stmt, is_seq, clk_sig, cond_chain + [stmt.expr])
            if stmt.default_stmt is not None:
                self._synth_stmt(stmt.default_stmt, is_seq, clk_sig, cond_chain + [stmt.expr])
        elif isinstance(stmt, (RepeatStmt, WhileStmt)):
            self._synth_stmt(stmt.body, is_seq, clk_sig, cond_chain)
        elif isinstance(stmt, ForStmt):
            self._synth_stmt(stmt.body, is_seq, clk_sig, cond_chain)
        elif isinstance(stmt, AssignStmt):
            d_node = self._synth_expr(stmt.expr)
            if cond_chain:
                mux_id = self._new_id("MUX")
                self._add_node(mux_id, "MUX", "MUX", 1)
                self._add_edge(self._synth_expr(cond_chain[-1]), mux_id, "sel")
                self._add_edge(d_node, mux_id, "d")
                d_node = mux_id
            if is_seq:
                dff_id = self.reg_dff.get(stmt.target)
                if dff_id is None:
                    dff_id = self._new_id("DFF")
                    w = self.mod.signals[stmt.target].width if stmt.target in self.mod.signals else 1
                    self._add_node(dff_id, f"DFF ({stmt.target})", "DFF", w)
                    if clk_sig and clk_sig in self.signal_driver:
                        self._add_edge(self.signal_driver[clk_sig], dff_id, "CLK")
                    self.reg_dff[stmt.target] = dff_id
                    self.signal_driver[stmt.target] = dff_id
                self._add_edge(d_node, dff_id, "D")
            else:
                self.signal_driver[stmt.target] = d_node

    def _compute_layout_and_report(self) -> None:
        nodes = self.netlist.nodes
        edges = self.netlist.edges
        preds: dict[str, list[str]] = {nid: [] for nid in nodes}
        for e in edges:
            if e.dst_id in preds and e.src_id != e.dst_id:
                preds[e.dst_id].append(e.src_id)

        # Longest-path column assignment (with cycle guard)
        col_cache: dict[str, int] = {}
        visiting: set[str] = set()

        def get_col(nid: str) -> int:
            if nid in col_cache:
                return col_cache[nid]
            if nid in visiting:
                return 1
            visiting.add(nid)
            node = nodes[nid]
            if node.kind in ("INPUT", "CONST"):
                c = 0
            elif not preds[nid]:
                c = 1
            else:
                c = 1 + max(get_col(p) for p in preds[nid])
            visiting.remove(nid)
            col_cache[nid] = c
            return c

        for nid in nodes:
            nodes[nid].col = get_col(nid)

        max_col = max((n.col for n in nodes.values()), default=1)
        for n in nodes.values():
            if n.kind == "OUTPUT":
                n.col = max(n.col, max_col)

        # Assign rows within each column
        by_col: dict[int, list[NetNode]] = {}
        for n in nodes.values():
            by_col.setdefault(n.col, []).append(n)
        for c, col_nodes in by_col.items():
            for r_idx, n in enumerate(col_nodes):
                n.row = r_idx

        # Build Utilization Report
        rep = self.netlist.report
        rep.logic_depth = max(0, max_col - 1)
        for n in nodes.values():
            if n.kind in ("INPUT", "OUTPUT", "CONST"):
                continue
            rep.cell_breakdown[n.kind] = rep.cell_breakdown.get(n.kind, 0) + 1
            if n.kind == "DFF":
                rep.flip_flops += n.width
            elif n.kind in ("ADD", "SUB"):
                rep.adders += 1
                rep.luts_and_gates += 4
            elif n.kind == "MUX":
                rep.muxes += 1
                rep.luts_and_gates += 1
            else:
                rep.luts_and_gates += 1


def synthesize_module(mod: ModuleDef) -> Netlist:
    """Synthesize a Verilog ModuleDef into a Netlist with utilization metrics."""
    return _NetlistBuilder(mod).build()

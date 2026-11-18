"""Discrete-event Verilog simulator with hierarchical instantiation and VCD export."""

from __future__ import annotations

import heapq
import math
import random
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from .ast_nodes import (
    AlwaysBlock,
    AssignStmt,
    BinaryOp,
    BlockStmt,
    CaseStmt,
    ConcatExpr,
    DelayStmt,
    DisplayStmt,
    Expr,
    FinishStmt,
    ForeverStmt,
    ForStmt,
    GateInst,
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
class WaveSignal:
    name: str
    width: int
    transitions: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class WaveTrace:
    signals: dict[str, WaveSignal] = field(default_factory=dict)
    end_time: int = 0

    def record(self, full_name: str, width: int, time: int, value: int) -> None:
        sig = self.signals.get(full_name)
        if sig is None:
            sig = WaveSignal(name=full_name, width=width, transitions=[(time, value)])
            self.signals[full_name] = sig
        else:
            if sig.transitions and sig.transitions[-1][0] == time:
                sig.transitions[-1] = (time, value)
            elif not sig.transitions or sig.transitions[-1][1] != value:
                sig.transitions.append((time, value))
        if time > self.end_time:
            self.end_time = time

    def to_vcd(self) -> str:
        """Export the recorded waveform trace to IEEE 1364 VCD format."""
        lines = [
            "$date\n   SiliconForge VLSI Studio\n$end",
            "$version\n   0.1.0\n$end",
            "$timescale 1ns $end",
            "$scope module top $end",
        ]
        id_map: dict[str, str] = {}
        for idx, (name, sig) in enumerate(self.signals.items()):
            code = f"s{idx}"
            id_map[name] = code
            safe_name = name.replace(".", "_")
            lines.append(f"$var wire {sig.width} {code} {safe_name} $end")
        lines.append("$upscope $end")
        lines.append("$enddefinitions $end")

        events_by_time: dict[int, list[tuple[str, int, int]]] = {}
        for name, sig in self.signals.items():
            for t, val in sig.transitions:
                events_by_time.setdefault(t, []).append((id_map[name], val, sig.width))

        for t in sorted(events_by_time.keys()):
            lines.append(f"#{t}")
            for code, val, width in events_by_time[t]:
                if width == 1:
                    lines.append(f"{val & 1}{code}")
                else:
                    bits = format(val & ((1 << width) - 1), f"0{width}b")
                    lines.append(f"b{bits} {code}")
        return "\n".join(lines) + "\n"


@dataclass
class SimulationResult:
    trace: WaveTrace
    console_output: list[str]
    top_module: str
    end_time: int
    errors: list[str] = field(default_factory=list)


class _InstanceRuntime:
    def __init__(self, path: str, module: ModuleDef):
        self.path = path
        self.module = module
        self.values: dict[str, int] = {}
        self.widths: dict[str, int] = {}
        self.memories: dict[str, dict[int, int]] = {}
        for sname, sdecl in module.signals.items():
            self.values[sname] = 0
            self.widths[sname] = sdecl.width
            if sdecl.array_size > 0:
                self.memories[sname] = {}
        self.children: list[tuple[_InstanceRuntime, dict[str, Expr]]] = []


class VerilogSimulator:
    """Self-contained event-driven simulator for educational Verilog."""

    def __init__(self, modules: list[ModuleDef]):
        self.module_map: dict[str, ModuleDef] = {m.name: m for m in modules}
        self.trace = WaveTrace()
        self.console: list[str] = []
        self.errors: list[str] = []
        self._event_queue: list[tuple[int, int, Callable[[], None]]] = []
        self._seq_id = 0
        self._now = 0
        self._finished = False
        self._instances: list[_InstanceRuntime] = []
        self._monitors: list[tuple[_InstanceRuntime, DisplayStmt]] = []

    def choose_top_module(self, preferred: Optional[str] = None) -> str:
        if preferred and preferred in self.module_map:
            return preferred
        for m in self.module_map.values():
            if m.initial_blocks or not m.port_order:
                return m.name
        return next(iter(self.module_map.keys()))

    def run(self, top_module: Optional[str] = None, max_time: int = 1000) -> SimulationResult:
        if not self.module_map:
            return SimulationResult(self.trace, [], "", 0, ["No Verilog modules found."])

        top_name = self.choose_top_module(top_module)
        self._elaborate(top_name, top_name)

        # Evaluate inline initial values (`reg x = 1;`)
        for inst in self._instances:
            for sname, sdecl in inst.module.signals.items():
                if sdecl.init_expr is not None:
                    inst.values[sname] = self._eval_expr(inst, sdecl.init_expr) & ((1 << sdecl.width) - 1)

        self._record_all_signals(0)

        # Schedule initial blocks & timed always blocks (`always #5 clk = ~clk;`)
        has_testbench_stimulus = False
        for inst in self._instances:
            for init_blk in inst.module.initial_blocks:
                has_testbench_stimulus = True
                self._schedule_stmt_stream(inst, init_blk.body, 0)
            for ab in inst.module.always_blocks:
                if not ab.sensitivity:
                    has_testbench_stimulus = True
                    self._schedule_stmt_stream(inst, ForeverStmt(ab.body), 0)

        # If the user simulated a standalone design module without any testbench stimulus,
        # auto-generate a gentle clock/input stimulus so waveforms are visible!
        if not has_testbench_stimulus and self._instances:
            root = self._instances[0]
            inputs = [s for s in root.module.signals.values() if s.kind == "input"]
            if inputs:
                self.console.append(f"[Simulator] Auto-generating stimulus for input ports of '{top_name}'.")
                self._schedule_auto_stimulus(root, inputs)

        self._settle_combinational(0)

        while self._event_queue and not self._finished:
            t, _, cb = heapq.heappop(self._event_queue)
            if t > max_time:
                self.console.append(f"[Simulator] Reached max simulation time ({max_time}ns).")
                break
            self._now = t
            prev_snapshot = self._snapshot_values()
            cb()

            while self._event_queue and self._event_queue[0][0] == t and not self._finished:
                _, _, same_t_cb = heapq.heappop(self._event_queue)
                same_t_cb()

            self._settle_combinational(t, prev_snapshot)
            self._record_all_signals(t)
            self._check_monitors(t, prev_snapshot)

        self.trace.end_time = max(self.trace.end_time, self._now)
        return SimulationResult(
            trace=self.trace,
            console_output=self.console,
            top_module=top_name,
            end_time=self.trace.end_time,
            errors=self.errors,
        )

    def _schedule_auto_stimulus(self, root: _InstanceRuntime, inputs: list) -> None:
        clk_inputs = [s for s in inputs if "clk" in s.name.lower() or "clock" in s.name.lower()]
        rst_inputs = [s for s in inputs if "rst" in s.name.lower() or "reset" in s.name.lower()]
        data_inputs = [s for s in inputs if s not in clk_inputs and s not in rst_inputs]

        for r in rst_inputs:
            root.values[r.name] = 1
        for step in range(1, 17):
            t = step * 10
            def make_cb(st=step):
                for c in clk_inputs:
                    root.values[c.name] = st & 1
                if st == 2:
                    for r in rst_inputs:
                        root.values[r.name] = 0
                for idx, d in enumerate(data_inputs):
                    mask = (1 << d.width) - 1
                    root.values[d.name] = ((st // (idx + 1)) & mask)
            self._push_event(t, make_cb)

    def _elaborate(self, mod_name: str, path: str) -> _InstanceRuntime:
        mod = self.module_map.get(mod_name)
        if mod is None:
            # Create a dummy blackbox module rather than crashing if an unknown sub-module is instantiated
            mod = ModuleDef(name=mod_name)
        inst = _InstanceRuntime(path, mod)
        self._instances.append(inst)

        for child_inst in mod.instances:
            child_rt = self._elaborate(child_inst.module_name, f"{path}.{child_inst.inst_name}")
            port_bindings: dict[str, Expr] = {}
            if child_inst.port_conns:
                port_bindings = dict(child_inst.port_conns)
            else:
                for idx, expr in enumerate(child_inst.positional_conns):
                    if idx < len(child_rt.module.port_order):
                        port_bindings[child_rt.module.port_order[idx]] = expr
            inst.children.append((child_rt, port_bindings))
        return inst

    def _push_event(self, time: int, cb: Callable[[], None]) -> None:
        self._seq_id += 1
        heapq.heappush(self._event_queue, (time, self._seq_id, cb))

    def _schedule_stmt_stream(self, inst: _InstanceRuntime, stmt: Stmt, start_time: int) -> None:
        self._push_event(start_time, lambda: self._run_timed_stmt(inst, stmt, lambda: None))

    def _run_timed_stmt(self, inst: _InstanceRuntime, stmt: Optional[Stmt], on_done: Callable[[], None]) -> None:
        if self._finished or stmt is None:
            on_done()
            return

        if not self._contains_delay(stmt) and not isinstance(stmt, ForeverStmt):
            self._exec_stmt(inst, stmt, {})
            on_done()
            return

        if isinstance(stmt, DelayStmt):
            if stmt.delay > 0:
                self._push_event(self._now + stmt.delay, lambda: self._run_timed_stmt(inst, stmt.stmt, on_done))
            else:
                self._run_timed_stmt(inst, stmt.stmt, on_done)
            return

        if isinstance(stmt, BlockStmt):
            def run_idx(idx: int) -> None:
                if self._finished or idx >= len(stmt.stmts):
                    on_done()
                    return
                self._run_timed_stmt(inst, stmt.stmts[idx], lambda: run_idx(idx + 1))
            run_idx(0)
            return

        if isinstance(stmt, IfStmt):
            branch = stmt.then_stmt if self._eval_expr(inst, stmt.cond) else stmt.else_stmt
            self._run_timed_stmt(inst, branch, on_done)
            return

        if isinstance(stmt, RepeatStmt):
            remaining = max(0, min(1024, self._eval_expr(inst, stmt.count)))
            def next_rep(rem: int) -> None:
                if self._finished or rem <= 0:
                    on_done()
                    return
                self._run_timed_stmt(inst, stmt.body, lambda: next_rep(rem - 1))
            next_rep(remaining)
            return

        if isinstance(stmt, ForStmt):
            self._exec_stmt(inst, stmt.init_stmt, {})
            def next_for(iters: int) -> None:
                if self._finished or iters >= 1024 or not self._eval_expr(inst, stmt.cond):
                    on_done()
                    return
                def after_body() -> None:
                    self._exec_stmt(inst, stmt.step_stmt, {})
                    next_for(iters + 1)
                self._run_timed_stmt(inst, stmt.body, after_body)
            next_for(0)
            return

        if isinstance(stmt, WhileStmt):
            def next_while(iters: int) -> None:
                if self._finished or iters >= 1024 or not self._eval_expr(inst, stmt.cond):
                    on_done()
                    return
                self._run_timed_stmt(inst, stmt.body, lambda: next_while(iters + 1))
            next_while(0)
            return

        if isinstance(stmt, ForeverStmt):
            def next_forever(iters: int) -> None:
                if self._finished or iters >= 500:
                    on_done()
                    return
                t_before = self._now
                def after_body() -> None:
                    if self._now == t_before:
                        self._push_event(self._now + 5, lambda: next_forever(iters + 1))
                    else:
                        next_forever(iters + 1)
                self._run_timed_stmt(inst, stmt.body, after_body)
            next_forever(0)
            return

        self._exec_stmt(inst, stmt, {})
        on_done()

    def _contains_delay(self, stmt: Optional[Stmt]) -> bool:
        if stmt is None:
            return False
        if isinstance(stmt, DelayStmt):
            return True
        if isinstance(stmt, BlockStmt):
            return any(self._contains_delay(s) for s in stmt.stmts)
        if isinstance(stmt, IfStmt):
            return self._contains_delay(stmt.then_stmt) or self._contains_delay(stmt.else_stmt)
        if isinstance(stmt, (RepeatStmt, ForeverStmt, WhileStmt)):
            return self._contains_delay(stmt.body)
        if isinstance(stmt, ForStmt):
            return self._contains_delay(stmt.body)
        return False

    def _snapshot_values(self) -> dict[tuple[str, str], int]:
        snap: dict[tuple[str, str], int] = {}
        for inst in self._instances:
            for k, v in inst.values.items():
                snap[(inst.path, k)] = v
        return snap

    def _settle_combinational(
        self,
        time: int,
        prev_snapshot: Optional[dict[tuple[str, str], int]] = None,
        evaluate_edges: bool = True,
    ) -> None:
        if prev_snapshot is None:
            prev_snapshot = self._snapshot_values()

        for _ in range(32):
            changed = False
            for inst in self._instances:
                # 1. Parent -> child inputs
                for child_rt, bindings in inst.children:
                    for p_name, expr in bindings.items():
                        sdecl = child_rt.module.signals.get(p_name)
                        if sdecl and sdecl.kind in ("input", "inout"):
                            val = self._eval_expr(inst, expr) & ((1 << sdecl.width) - 1)
                            if child_rt.values.get(p_name) != val:
                                child_rt.values[p_name] = val
                                changed = True

                # 2. Continuous assigns
                for ca in inst.module.assigns:
                    val = self._eval_expr(inst, ca.expr)
                    if ca.lhs_concat:
                        if self._write_concat(inst, ca.lhs_concat, val):
                            changed = True
                    elif self._write_signal(inst, ca.target, ca.index, ca.msb, ca.lsb, val):
                        changed = True

                # 3. Gate primitives
                for gate in inst.module.gates:
                    gval = self._eval_gate(inst, gate)
                    if isinstance(gate.output, IdentExpr):
                        w = inst.widths.get(gate.output.name, 1)
                        masked = gval & ((1 << w) - 1)
                        if inst.values.get(gate.output.name) != masked:
                            inst.values[gate.output.name] = masked
                            changed = True

                # 4. Combinational always blocks (@(*) or level-sensitive)
                for ab in inst.module.always_blocks:
                    if ab.sensitivity and not any(s.edge in ("posedge", "negedge") for s in ab.sensitivity):
                        nb_updates: dict[str, int] = {}
                        before = dict(inst.values)
                        self._exec_stmt(inst, ab.body, nb_updates)
                        for k, v in nb_updates.items():
                            inst.values[k] = v
                        if inst.values != before:
                            changed = True

                # 5. Child -> parent outputs
                for child_rt, bindings in inst.children:
                    for p_name, expr in bindings.items():
                        sdecl = child_rt.module.signals.get(p_name)
                        if sdecl and sdecl.kind in ("output", "reg", "inout") and isinstance(expr, IdentExpr):
                            cval = child_rt.values.get(p_name, 0)
                            pw = inst.widths.get(expr.name, sdecl.width)
                            masked = cval & ((1 << pw) - 1)
                            if inst.values.get(expr.name) != masked:
                                inst.values[expr.name] = masked
                                changed = True

            if not changed:
                break

        if not evaluate_edges:
            return

        pending_nb: list[tuple[_InstanceRuntime, dict[str, int]]] = []
        for inst in self._instances:
            for ab in inst.module.always_blocks:
                if self._edge_triggered(inst, ab, prev_snapshot):
                    nb: dict[str, int] = {}
                    self._exec_stmt(inst, ab.body, nb)
                    if nb:
                        pending_nb.append((inst, nb))

        if pending_nb:
            for inst, nb in pending_nb:
                for k, v in nb.items():
                    w = inst.widths.get(k, 1)
                    inst.values[k] = v & ((1 << w) - 1)
            self._settle_combinational(time, self._snapshot_values(), evaluate_edges=False)

    def _edge_triggered(
        self,
        inst: _InstanceRuntime,
        ab: AlwaysBlock,
        prev_snapshot: dict[tuple[str, str], int],
    ) -> bool:
        has_edge = any(s.edge in ("posedge", "negedge") for s in ab.sensitivity)
        if not has_edge:
            return False
        for s in ab.sensitivity:
            if not s.signal:
                continue
            prev = prev_snapshot.get((inst.path, s.signal), 0) & 1
            curr = inst.values.get(s.signal, 0) & 1
            if s.edge == "posedge" and prev == 0 and curr == 1:
                return True
            if s.edge == "negedge" and prev == 1 and curr == 0:
                return True
        return False

    def _eval_gate(self, inst: _InstanceRuntime, gate: GateInst) -> int:
        ins = [self._eval_expr(inst, e) & 1 for e in gate.inputs]
        if not ins:
            return 0
        gt = gate.gate_type
        if gt == "buf":
            return ins[0]
        if gt == "not":
            return ins[0] ^ 1
        if gt == "and":
            return 1 if all(ins) else 0
        if gt == "nand":
            return 0 if all(ins) else 1
        if gt == "or":
            return 1 if any(ins) else 0
        if gt == "nor":
            return 0 if any(ins) else 1
        if gt == "xor":
            res = 0
            for v in ins:
                res ^= v
            return res
        if gt == "xnor":
            res = 0
            for v in ins:
                res ^= v
            return res ^ 1
        return 0

    def _exec_stmt(self, inst: _InstanceRuntime, stmt: Stmt, nb_updates: dict[str, int]) -> None:
        if isinstance(stmt, BlockStmt):
            for s in stmt.stmts:
                if self._finished:
                    break
                self._exec_stmt(inst, s, nb_updates)
        elif isinstance(stmt, IfStmt):
            if self._eval_expr(inst, stmt.cond):
                self._exec_stmt(inst, stmt.then_stmt, nb_updates)
            elif stmt.else_stmt is not None:
                self._exec_stmt(inst, stmt.else_stmt, nb_updates)
        elif isinstance(stmt, CaseStmt):
            sel_val = self._eval_expr(inst, stmt.expr)
            matched = False
            for labels, arm_stmt in stmt.arms:
                if any(self._eval_expr(inst, lbl) == sel_val for lbl in labels):
                    self._exec_stmt(inst, arm_stmt, nb_updates)
                    matched = True
                    break
            if not matched and stmt.default_stmt is not None:
                self._exec_stmt(inst, stmt.default_stmt, nb_updates)
        elif isinstance(stmt, ForStmt):
            self._exec_stmt(inst, stmt.init_stmt, nb_updates)
            iters = 0
            while self._eval_expr(inst, stmt.cond) and iters < 1024 and not self._finished:
                self._exec_stmt(inst, stmt.body, nb_updates)
                self._exec_stmt(inst, stmt.step_stmt, nb_updates)
                iters += 1
        elif isinstance(stmt, WhileStmt):
            iters = 0
            while self._eval_expr(inst, stmt.cond) and iters < 1024 and not self._finished:
                self._exec_stmt(inst, stmt.body, nb_updates)
                iters += 1
        elif isinstance(stmt, RepeatStmt):
            cnt = self._eval_expr(inst, stmt.count)
            for _ in range(max(0, min(1024, cnt))):
                if self._finished:
                    break
                self._exec_stmt(inst, stmt.body, nb_updates)
        elif isinstance(stmt, AssignStmt):
            val = self._eval_expr(inst, stmt.expr)
            if stmt.lhs_concat:
                self._write_concat(inst, stmt.lhs_concat, val, nb_updates if stmt.nonblocking else None)
            elif stmt.nonblocking:
                if stmt.target in inst.memories and stmt.index is not None:
                    addr = self._eval_expr(inst, stmt.index)
                    w = inst.widths.get(stmt.target, 32)
                    inst.memories[stmt.target][addr] = val & ((1 << w) - 1)
                else:
                    w = inst.widths.get(stmt.target, 32)
                    nb_updates[stmt.target] = val & ((1 << w) - 1)
            else:
                self._write_signal(inst, stmt.target, stmt.index, stmt.msb, stmt.lsb, val)
        elif isinstance(stmt, DisplayStmt):
            self._settle_combinational(self._now, evaluate_edges=False)
            if stmt.is_monitor:
                self._monitors.append((inst, stmt))
            self.console.append(self._format_display(inst, stmt))
        elif isinstance(stmt, FinishStmt):
            self._finished = True
            self.console.append(f"[{self._now}ns] $finish called.")

    def _write_concat(
        self,
        inst: _InstanceRuntime,
        targets: list[str],
        val: int,
        nb_updates: Optional[dict[str, int]] = None,
    ) -> bool:
        changed = False
        shift = 0
        for name in reversed(targets):
            w = inst.widths.get(name, 1)
            part = (val >> shift) & ((1 << w) - 1)
            shift += w
            if nb_updates is not None:
                nb_updates[name] = part
            else:
                if inst.values.get(name, 0) != part:
                    inst.values[name] = part
                    changed = True
        return changed

    def _write_signal(
        self,
        inst: _InstanceRuntime,
        target: str,
        index: Optional[Expr],
        msb: Optional[int],
        lsb: Optional[int],
        val: int,
    ) -> bool:
        if target in inst.memories and index is not None:
            addr = self._eval_expr(inst, index)
            w = inst.widths.get(target, 32)
            masked = val & ((1 << w) - 1)
            old_m = inst.memories[target].get(addr, 0)
            inst.memories[target][addr] = masked
            return masked != old_m

        w = inst.widths.get(target, 32)
        old = inst.values.get(target, 0)
        if index is not None:
            bit_idx = self._eval_expr(inst, index)
            bit_val = val & 1
            new_val = (old | (1 << bit_idx)) if bit_val else (old & ~(1 << bit_idx))
        elif msb is not None and lsb is not None:
            lo, hi = min(msb, lsb), max(msb, lsb)
            slice_w = hi - lo + 1
            mask = ((1 << slice_w) - 1) << lo
            new_val = (old & ~mask) | ((val << lo) & mask)
        else:
            new_val = val & ((1 << w) - 1)
        inst.values[target] = new_val
        return new_val != old

    def _eval_expr(self, inst: _InstanceRuntime, expr: Expr) -> int:
        if isinstance(expr, NumberLiteral):
            return expr.value
        if isinstance(expr, IdentExpr):
            return inst.values.get(expr.name, 0)
        if isinstance(expr, IndexExpr):
            idx = self._eval_expr(inst, expr.index)
            if expr.name in inst.memories:
                return inst.memories[expr.name].get(idx, 0)
            return (inst.values.get(expr.name, 0) >> idx) & 1
        if isinstance(expr, SliceExpr):
            lo, hi = min(expr.msb, expr.lsb), max(expr.msb, expr.lsb)
            mask = (1 << (hi - lo + 1)) - 1
            return (inst.values.get(expr.name, 0) >> lo) & mask
        if isinstance(expr, PartSelectExpr):
            base = self._eval_expr(inst, expr.base)
            lo = base if expr.ascending else max(0, base - expr.width + 1)
            mask = (1 << expr.width) - 1
            return (inst.values.get(expr.name, 0) >> lo) & mask
        if isinstance(expr, ConcatExpr):
            acc = 0
            for part in expr.parts:
                pw = self._infer_width(inst, part)
                pv = self._eval_expr(inst, part) & ((1 << pw) - 1)
                acc = (acc << pw) | pv
            return acc
        if isinstance(expr, ReplicateExpr):
            pw = self._infer_width(inst, expr.expr)
            pv = self._eval_expr(inst, expr.expr) & ((1 << pw) - 1)
            acc = 0
            for _ in range(expr.count):
                acc = (acc << pw) | pv
            return acc
        if isinstance(expr, SysFuncExpr):
            fn = expr.name.lower()
            if fn in ("$time", "$stime", "$realtime"):
                return self._now
            if fn in ("$random", "$urandom"):
                return random.randint(0, 0xFFFF)
            if fn in ("$unsigned", "$signed") and expr.args:
                return self._eval_expr(inst, expr.args[0])
            if fn == "$clog2" and expr.args:
                v = self._eval_expr(inst, expr.args[0])
                return max(1, math.ceil(math.log2(max(2, v))))
            return 0
        if isinstance(expr, UnaryOp):
            v = self._eval_expr(inst, expr.operand)
            w = self._infer_width(inst, expr.operand)
            mask = (1 << w) - 1
            if expr.op == "~":
                return (~v) & mask
            if expr.op == "!":
                return 0 if v else 1
            if expr.op == "-":
                return (-v) & mask
            if expr.op == "&":
                return 1 if (v & mask) == mask else 0
            if expr.op == "~&":
                return 0 if (v & mask) == mask else 1
            if expr.op == "|":
                return 1 if (v & mask) != 0 else 0
            if expr.op == "~|":
                return 0 if (v & mask) != 0 else 1
            if expr.op == "^":
                return bin(v & mask).count("1") & 1
            if expr.op in ("~^", "^~"):
                return (bin(v & mask).count("1") & 1) ^ 1
        if isinstance(expr, BinaryOp):
            l = self._eval_expr(inst, expr.left)
            r = self._eval_expr(inst, expr.right)
            op = expr.op
            if op == "+": return l + r
            if op == "-": return l - r
            if op == "*": return l * r
            if op == "**": return l ** max(0, min(32, r))
            if op == "/": return l // r if r else 0
            if op == "%": return l % r if r else 0
            if op == "&": return l & r
            if op == "~&": return ~(l & r)
            if op == "|": return l | r
            if op == "~|": return ~(l | r)
            if op == "^": return l ^ r
            if op == "^~": return ~(l ^ r)
            if op == "<<": return l << max(0, min(64, r))
            if op == ">>": return l >> max(0, min(64, r))
            if op == "==": return int(l == r)
            if op == "!=": return int(l != r)
            if op == "<": return int(l < r)
            if op == "<=": return int(l <= r)
            if op == ">": return int(l > r)
            if op == ">=": return int(l >= r)
            if op == "&&": return int(bool(l) and bool(r))
            if op == "||": return int(bool(l) or bool(r))
        if isinstance(expr, TernaryOp):
            return self._eval_expr(inst, expr.true_expr if self._eval_expr(inst, expr.cond) else expr.false_expr)
        return 0

    def _infer_width(self, inst: _InstanceRuntime, expr: Expr) -> int:
        if isinstance(expr, NumberLiteral):
            return expr.width
        if isinstance(expr, IdentExpr):
            return inst.widths.get(expr.name, 1)
        if isinstance(expr, IndexExpr):
            if expr.name in inst.memories:
                return inst.widths.get(expr.name, 8)
            return 1
        if isinstance(expr, SliceExpr):
            return abs(expr.msb - expr.lsb) + 1
        if isinstance(expr, PartSelectExpr):
            return expr.width
        if isinstance(expr, ConcatExpr):
            return sum(self._infer_width(inst, p) for p in expr.parts)
        if isinstance(expr, ReplicateExpr):
            return expr.count * self._infer_width(inst, expr.expr)
        return 1

    def _format_display(self, inst: _InstanceRuntime, stmt: DisplayStmt) -> str:
        vals = [self._eval_expr(inst, a) for a in stmt.args]
        arg_idx = 0

        def repl(m: re.Match[str]) -> str:
            nonlocal arg_idx
            spec = m.group(1).lower()
            if spec == "t":
                if arg_idx < len(stmt.args) and isinstance(stmt.args[arg_idx], SysFuncExpr):
                    arg_idx += 1
                return str(self._now)
            if arg_idx >= len(vals):
                return m.group(0)
            v = vals[arg_idx]
            w = self._infer_width(inst, stmt.args[arg_idx])
            arg_idx += 1
            if spec == "b":
                return format(v & ((1 << w) - 1), f"0{w}b")
            if spec in ("h", "x"):
                return format(v & ((1 << w) - 1), "x")
            return str(v)

        text = re.sub(r"%0*([bdhxtBDHXT])", repl, stmt.fmt)
        return f"[{self._now}ns] {text}"

    def _check_monitors(self, time: int, prev_snapshot: dict[tuple[str, str], int]) -> None:
        for inst, stmt in self._monitors:
            self.console.append(self._format_display(inst, stmt))

    def _record_all_signals(self, time: int) -> None:
        for inst in self._instances:
            for sname, sdecl in inst.module.signals.items():
                if sdecl.array_size == 0:
                    self.trace.record(f"{inst.path}.{sname}", sdecl.width, time, inst.values.get(sname, 0))

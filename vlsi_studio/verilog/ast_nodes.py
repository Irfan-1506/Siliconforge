"""AST node definitions for Verilog-2001 / SystemVerilog subset."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SignalDecl:
    name: str
    kind: str  # "input", "output", "inout", "wire", "reg"
    msb: int = 0
    lsb: int = 0
    init_expr: Optional[Expr] = None
    array_size: int = 0  # >0 for 2D memory reg [W-1:0] mem [0:N-1]

    @property
    def width(self) -> int:
        return abs(self.msb - self.lsb) + 1


# --- Expressions ---


@dataclass
class Expr:
    pass


@dataclass
class NumberLiteral(Expr):
    value: int
    width: int = 32


@dataclass
class IdentExpr(Expr):
    name: str


@dataclass
class IndexExpr(Expr):
    name: str
    index: Expr


@dataclass
class SliceExpr(Expr):
    name: str
    msb: int
    lsb: int


@dataclass
class PartSelectExpr(Expr):
    name: str
    base: Expr
    width: int
    ascending: bool = True  # +: is True, -: is False


@dataclass
class ConcatExpr(Expr):
    parts: list[Expr]


@dataclass
class ReplicateExpr(Expr):
    count: int
    expr: Expr


@dataclass
class SysFuncExpr(Expr):
    name: str
    args: list[Expr] = field(default_factory=list)


@dataclass
class UnaryOp(Expr):
    op: str  # "~", "!", "&", "~&", "|", "~|", "^", "~^", "-", "+"
    operand: Expr


@dataclass
class BinaryOp(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass
class TernaryOp(Expr):
    cond: Expr
    true_expr: Expr
    false_expr: Expr


# --- Statements ---


@dataclass
class Stmt:
    pass


@dataclass
class BlockStmt(Stmt):
    stmts: list[Stmt] = field(default_factory=list)


@dataclass
class AssignStmt(Stmt):
    target: str
    index: Optional[Expr]
    msb: Optional[int]
    lsb: Optional[int]
    expr: Expr
    nonblocking: bool = False
    lhs_concat: list[str] = field(default_factory=list)


@dataclass
class DelayStmt(Stmt):
    delay: int
    stmt: Optional[Stmt] = None


@dataclass
class IfStmt(Stmt):
    cond: Expr
    then_stmt: Stmt
    else_stmt: Optional[Stmt] = None


@dataclass
class CaseStmt(Stmt):
    expr: Expr
    arms: list[tuple[list[Expr], Stmt]] = field(default_factory=list)
    default_stmt: Optional[Stmt] = None


@dataclass
class RepeatStmt(Stmt):
    count: Expr
    body: Stmt


@dataclass
class ForeverStmt(Stmt):
    body: Stmt


@dataclass
class ForStmt(Stmt):
    init_stmt: Stmt
    cond: Expr
    step_stmt: Stmt
    body: Stmt


@dataclass
class WhileStmt(Stmt):
    cond: Expr
    body: Stmt


@dataclass
class DisplayStmt(Stmt):
    fmt: str
    args: list[Expr] = field(default_factory=list)
    is_monitor: bool = False


@dataclass
class FinishStmt(Stmt):
    pass


# --- Module Items ---


@dataclass
class ContinuousAssign:
    target: str
    index: Optional[Expr]
    msb: Optional[int]
    lsb: Optional[int]
    expr: Expr
    lhs_concat: list[str] = field(default_factory=list)


@dataclass
class SensitivityItem:
    edge: Optional[str]  # "posedge", "negedge", or None
    signal: Optional[str]  # None means "*"


@dataclass
class AlwaysBlock:
    sensitivity: list[SensitivityItem]  # empty list means timed always (e.g. always #5 clk = ~clk;)
    body: Stmt


@dataclass
class InitialBlock:
    body: Stmt


@dataclass
class GateInst:
    gate_type: str  # "and", "or", "nand", "nor", "xor", "xnor", "not", "buf"
    inst_name: str
    output: Expr
    inputs: list[Expr]


@dataclass
class ModuleInst:
    module_name: str
    inst_name: str
    port_conns: dict[str, Expr]
    positional_conns: list[Expr] = field(default_factory=list)


@dataclass
class ModuleDef:
    name: str
    port_order: list[str] = field(default_factory=list)
    signals: dict[str, SignalDecl] = field(default_factory=dict)
    assigns: list[ContinuousAssign] = field(default_factory=list)
    always_blocks: list[AlwaysBlock] = field(default_factory=list)
    initial_blocks: list[InitialBlock] = field(default_factory=list)
    gates: list[GateInst] = field(default_factory=list)
    instances: list[ModuleInst] = field(default_factory=list)

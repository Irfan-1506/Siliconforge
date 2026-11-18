"""Lexer and recursive-descent parser for Verilog-2001 / SystemVerilog subset."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .ast_nodes import (
    AlwaysBlock,
    AssignStmt,
    BinaryOp,
    BlockStmt,
    CaseStmt,
    ConcatExpr,
    ContinuousAssign,
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
    InitialBlock,
    ModuleDef,
    ModuleInst,
    NumberLiteral,
    PartSelectExpr,
    RepeatStmt,
    ReplicateExpr,
    SensitivityItem,
    SignalDecl,
    SliceExpr,
    Stmt,
    SysFuncExpr,
    TernaryOp,
    UnaryOp,
    WhileStmt,
)

GATE_TYPES = {"and", "or", "nand", "nor", "xor", "xnor", "not", "buf"}

KEYWORDS = {
    "module", "endmodule", "input", "output", "inout",
    "wire", "tri", "supply0", "supply1", "reg", "logic", "integer", "int",
    "signed", "unsigned",
    "assign", "always", "always_comb", "always_ff", "always_latch", "initial",
    "begin", "end", "if", "else",
    "case", "casez", "casex", "endcase", "default",
    "posedge", "negedge", "or",
    "repeat", "forever", "for", "while",
    "parameter", "localparam",
} | GATE_TYPES


class VerilogSyntaxError(Exception):
    """Raised when Verilog source contains a syntax error."""

    def __init__(self, message: str, line: int = 0):
        self.line = line
        super().__init__(f"Line {line}: {message}" if line else message)


@dataclass
class Token:
    kind: str
    value: str
    line: int


_TOKEN_SPEC = [
    ("COMMENT_LINE", r"//[^\n]*"),
    ("COMMENT_BLOCK", r"/\*[\s\S]*?\*/"),
    ("ATTR_BLOCK", r"\(\*[\s\S]*?\*\)"),
    ("STRING", r'"(?:\\.|[^"\\])*"'),
    ("SIZED_NUM", r"\d*'[sS]?[bBoOdDhH][ \t]*[0-9a-fA-F_xXzZ?]+"),
    ("UNBASED_NUM", r"'[01xXzZ]"),
    ("FLOAT_NUM", r"\d+\.\d+"),
    ("NUMBER", r"\d[0-9_]*"),
    ("SYS_IDENT", r"\$[A-Za-z_][A-Za-z0-9_$]*"),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_$]*"),
    (
        "OP",
        r"\+\+|--|===|!==|==|!=|<=|>=|&&|\|\||<<<|>>>|<<|>>|\+:|-:|\*\*|~\^|\^~|~&|~\||"
        r"[+\-*/%&|^~!<>?:=.,;()\[\]{}@#]",
    ),
    ("NEWLINE", r"\n"),
    ("SKIP", r"[ \t\r]+"),
    ("MISMATCH", r"."),
]
_MASTER_RE = re.compile("|".join(f"(?P<{name}>{pat})" for name, pat in _TOKEN_SPEC))


def _preprocess_lines(source: str) -> str:
    """Expand `define macros and strip compiler directives while preserving exact line count."""
    macros: dict[str, str] = {}
    out_lines: list[str] = []
    for raw_line in source.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("`define"):
            m = re.match(r"^`define\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.*)$", stripped)
            if m:
                macros[m.group(1)] = m.group(2).split("//")[0].strip()
            out_lines.append("")
            continue
        if stripped.startswith((
            "`timescale", "`default_nettype", "`include", "`ifdef",
            "`ifndef", "`else", "`elsif", "`endif", "`resetall", "`celldefine", "`endcelldefine"
        )):
            out_lines.append("")
            continue
        line = raw_line
        if "`" in line:
            for k, v in macros.items():
                line = re.sub(rf"`\b{re.escape(k)}\b", v, line)
            # Remove any unknown `directive token gracefully
            line = re.sub(r"`[A-Za-z_][A-Za-z0-9_]*", "0", line)
        out_lines.append(line)
    return "\n".join(out_lines)


def tokenize(source: str) -> list[Token]:
    cleaned = _preprocess_lines(source)
    tokens: list[Token] = []
    line = 1
    for m in _MASTER_RE.finditer(cleaned):
        kind = m.lastgroup
        val = m.group()
        if kind == "NEWLINE":
            line += 1
        elif kind in ("SKIP", "COMMENT_LINE"):
            continue
        elif kind in ("COMMENT_BLOCK", "ATTR_BLOCK"):
            line += val.count("\n")
        elif kind == "MISMATCH":
            raise VerilogSyntaxError(f"Unexpected character {val!r}", line)
        else:
            if kind == "STRING":
                line += val.count("\n")
            if kind == "IDENT" and val in KEYWORDS:
                kind = "KW"
            tokens.append(Token(kind, val, line))
    tokens.append(Token("EOF", "", line))
    return tokens


def _parse_sized_number(text: str, line: int) -> NumberLiteral:
    if text.startswith("'") and len(text) == 2:
        ch = text[1].lower()
        val = (1 << 32) - 1 if ch == "1" else 0
        return NumberLiteral(value=val, width=32)

    parts = text.split("'", 1)
    width = int(parts[0]) if parts[0] else 32
    rest = parts[1].strip()
    if rest and rest[0].lower() == "s":
        rest = rest[1:].strip()
    base_char = rest[0].lower()
    digits = (
        rest[1:]
        .strip()
        .replace("_", "")
        .replace("x", "0")
        .replace("X", "0")
        .replace("z", "0")
        .replace("Z", "0")
        .replace("?", "0")
    )
    base_map = {"b": 2, "o": 8, "d": 10, "h": 16}
    if base_char not in base_map:
        raise VerilogSyntaxError(f"Invalid number base in {text!r}", line)
    val = int(digits or "0", base_map[base_char])
    mask = (1 << width) - 1
    return NumberLiteral(value=val & mask, width=width)


class _Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0
        self.params: dict[str, int] = {}

    def peek(self, offset: int = 0) -> Token:
        idx = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[idx]

    def match(self, *values: str) -> bool:
        if self.peek().value in values:
            self.pos += 1
            return True
        return False

    def expect(self, value: str) -> Token:
        tok = self.peek()
        if tok.value != value:
            raise VerilogSyntaxError(f"Expected {value!r}, got {tok.value!r}", tok.line)
        self.pos += 1
        return tok

    def expect_ident(self) -> str:
        tok = self.peek()
        if tok.kind == "IDENT":
            self.pos += 1
            return tok.value
        raise VerilogSyntaxError(f"Expected identifier, got {tok.value!r}", tok.line)

    def parse_all(self) -> list[ModuleDef]:
        modules: list[ModuleDef] = []
        while self.peek().kind != "EOF":
            if self.match(";"):
                continue
            modules.append(self.parse_module())
        return modules

    def _parse_range(self) -> tuple[int, int]:
        self.expect("[")
        msb = self._eval_const_expr()
        self.expect(":")
        lsb = self._eval_const_expr()
        self.expect("]")
        return msb, lsb

    def _eval_const_expr(self) -> int:
        expr = self.parse_expr()
        return self._const_eval(expr)

    def _const_eval(self, expr: Expr) -> int:
        if isinstance(expr, NumberLiteral):
            return expr.value
        if isinstance(expr, IdentExpr) and expr.name in self.params:
            return self.params[expr.name]
        if isinstance(expr, SysFuncExpr) and expr.name == "$clog2" and expr.args:
            v = self._const_eval(expr.args[0])
            return max(1, math.ceil(math.log2(max(2, v))))
        if isinstance(expr, UnaryOp):
            v = self._const_eval(expr.operand)
            if expr.op == "-":
                return -v
            if expr.op == "+":
                return v
            return ~v
        if isinstance(expr, BinaryOp):
            l, r = self._const_eval(expr.left), self._const_eval(expr.right)
            ops = {
                "+": l + r,
                "-": l - r,
                "*": l * r,
                "/": l // r if r else 0,
                "%": l % r if r else 0,
                "**": l ** r,
                "<<": l << r,
                ">>": l >> r,
            }
            if expr.op in ops:
                return ops[expr.op]
        if isinstance(expr, TernaryOp):
            return self._const_eval(expr.true_expr if self._const_eval(expr.cond) else expr.false_expr)
        raise VerilogSyntaxError("Expected constant integer expression", self.peek().line)

    def _skip_type_qualifiers(self) -> bool:
        """Consume optional wire/reg/logic/signed/unsigned qualifiers; return True if reg/logic."""
        is_reg = False
        while self.peek().value in ("wire", "tri", "reg", "logic", "signed", "unsigned", "integer", "int"):
            if self.peek().value in ("reg", "logic", "integer", "int"):
                is_reg = True
            self.pos += 1
        return is_reg

    def parse_module(self) -> ModuleDef:
        self.expect("module")
        name = self.expect_ident()
        mod = ModuleDef(name=name)
        self.params = {}

        # Optional parameter list #(...)
        if self.match("#"):
            self.expect("(")
            while not self.match(")"):
                if self.peek().kind == "EOF":
                    raise VerilogSyntaxError("Unclosed parameter list '#('", self.peek().line)
                self.match("parameter", "localparam")
                self._skip_type_qualifiers()
                if self.peek().value == "[":
                    self._parse_range()
                pname = self.expect_ident()
                if self.match("="):
                    self.params[pname] = self._eval_const_expr()
                self.match(",")

        # Port list (...)
        if self.match("("):
            if not self.match(")"):
                self._parse_port_list(mod)
                self.expect(")")
        self.expect(";")

        # Module body
        while not self.match("endmodule"):
            tok = self.peek()
            if tok.kind == "EOF":
                raise VerilogSyntaxError(f"Unexpected EOF in module {name!r}, missing 'endmodule'", tok.line)
            if self.match(";"):
                continue
            if tok.value in (
                "input", "output", "inout", "wire", "tri", "supply0", "supply1",
                "reg", "logic", "integer", "int"
            ):
                self._parse_decl_stmt(mod)
            elif tok.value in ("parameter", "localparam"):
                self._parse_param_decl()
            elif tok.value == "assign":
                self._parse_continuous_assign(mod)
            elif tok.value in ("always", "always_comb", "always_ff", "always_latch"):
                mod.always_blocks.append(self._parse_always())
            elif tok.value == "initial":
                self.pos += 1
                mod.initial_blocks.append(InitialBlock(body=self._parse_stmt()))
            elif tok.value in GATE_TYPES:
                mod.gates.append(self._parse_gate_inst())
            elif tok.kind == "IDENT":
                mod.instances.append(self._parse_module_inst())
            else:
                raise VerilogSyntaxError(f"Unexpected token {tok.value!r} in module {name}", tok.line)

        # Optional `: module_name` after endmodule
        if self.match(":"):
            self.expect_ident()
        return mod

    def _parse_param_decl(self) -> None:
        self.pos += 1  # parameter / localparam
        self._skip_type_qualifiers()
        if self.peek().value == "[":
            self._parse_range()
        while True:
            pname = self.expect_ident()
            self.expect("=")
            self.params[pname] = self._eval_const_expr()
            if not self.match(","):
                break
        self.expect(";")

    def _parse_port_list(self, mod: ModuleDef) -> None:
        current_dir: str | None = None
        current_is_reg = False
        current_msb, current_lsb = 0, 0
        while self.peek().value != ")" and self.peek().kind != "EOF":
            tok = self.peek()
            if tok.value in ("input", "output", "inout"):
                current_dir = tok.value
                self.pos += 1
                current_is_reg = self._skip_type_qualifiers()
                if self.peek().value == "[":
                    current_msb, current_lsb = self._parse_range()
                else:
                    current_msb, current_lsb = 0, 0
                self._skip_type_qualifiers()

            pname = self.expect_ident()
            if pname not in mod.port_order:
                mod.port_order.append(pname)
            if current_dir:
                kind = "reg" if (current_dir == "output" and current_is_reg) else current_dir
                sdecl = SignalDecl(pname, kind, current_msb, current_lsb)
            else:
                sdecl = mod.signals.get(pname, SignalDecl(pname, "wire", 0, 0))

            if self.match("="):
                sdecl.init_expr = self.parse_expr()
            mod.signals[pname] = sdecl

            if not self.match(","):
                break

    def _parse_decl_stmt(self, mod: ModuleDef) -> None:
        decl_kw = self.tokens[self.pos].value
        self.pos += 1
        extra_reg = self._skip_type_qualifiers()
        is_integer = decl_kw in ("integer", "int")
        is_reg = decl_kw in ("reg", "logic", "integer", "int") or extra_reg

        if is_integer:
            msb, lsb = 31, 0
        elif self.peek().value == "[":
            msb, lsb = self._parse_range()
        else:
            msb, lsb = 0, 0

        self._skip_type_qualifiers()
        if not is_integer and self.peek().value == "[":
            msb, lsb = self._parse_range()

        while True:
            name = self.expect_ident()
            arr_size = 0
            if self.peek().value == "[":
                a_start, a_end = self._parse_range()
                arr_size = abs(a_end - a_start) + 1

            init_expr: Expr | None = None
            if self.match("="):
                init_expr = self.parse_expr()

            existing = mod.signals.get(name)
            if existing is not None:
                if is_reg:
                    existing.kind = "reg"
                elif decl_kw in ("input", "output", "inout"):
                    existing.kind = decl_kw
                if msb != 0 or lsb != 0:
                    existing.msb, existing.lsb = msb, lsb
                if arr_size:
                    existing.array_size = arr_size
                if init_expr is not None:
                    if existing.kind == "wire":
                        mod.assigns.append(ContinuousAssign(name, None, None, None, init_expr))
                    else:
                        existing.init_expr = init_expr
            else:
                kind = "reg" if is_reg else ("wire" if decl_kw in ("tri", "supply0", "supply1") else decl_kw)
                sdecl = SignalDecl(name, kind, msb, lsb, init_expr=init_expr if kind != "wire" else None, array_size=arr_size)
                mod.signals[name] = sdecl
                if kind == "wire" and init_expr is not None:
                    mod.assigns.append(ContinuousAssign(name, None, None, None, init_expr))
                elif decl_kw == "supply0":
                    mod.assigns.append(ContinuousAssign(name, None, None, None, NumberLiteral(0, 1)))
                elif decl_kw == "supply1":
                    mod.assigns.append(ContinuousAssign(name, None, None, None, NumberLiteral(1, 1)))

            if not self.match(","):
                break
        self.expect(";")

    def _parse_lvalue(self) -> tuple[str, Expr | None, int | None, int | None, list[str]]:
        if self.match("{"):
            names: list[str] = [self.expect_ident()]
            while self.match(","):
                names.append(self.expect_ident())
            self.expect("}")
            return names[0], None, None, None, names

        name = self.expect_ident()
        if self.match("["):
            first = self.parse_expr()
            if self.match(":"):
                lsb = self._const_eval(self.parse_expr())
                self.expect("]")
                return name, None, self._const_eval(first), lsb, []
            if self.match("+:"):
                w = self._const_eval(self.parse_expr())
                self.expect("]")
                return name, first, None, None, []
            if self.match("-:"):
                w = self._const_eval(self.parse_expr())
                self.expect("]")
                return name, first, None, None, []
            self.expect("]")
            return name, first, None, None, []
        return name, None, None, None, []

    def _parse_continuous_assign(self, mod: ModuleDef) -> None:
        self.expect("assign")
        # Optional drive strength or #delay on assign
        if self.peek().value == "#":
            self._consume_delay_val()
        while True:
            target, idx, msb, lsb, lhs_concat = self._parse_lvalue()
            self.expect("=")
            expr = self.parse_expr()
            mod.assigns.append(ContinuousAssign(target, idx, msb, lsb, expr, lhs_concat=lhs_concat))
            if not self.match(","):
                break
        self.expect(";")

    def _consume_delay_val(self) -> int:
        self.expect("#")
        if self.match("("):
            d = self._eval_const_expr()
            self.expect(")")
            return d
        tok = self.peek()
        if tok.kind == "NUMBER":
            self.pos += 1
            return int(tok.value.replace("_", ""))
        if tok.kind == "FLOAT_NUM":
            self.pos += 1
            return max(1, round(float(tok.value)))
        if tok.kind == "IDENT" and tok.value in self.params:
            self.pos += 1
            return self.params[tok.value]
        raise VerilogSyntaxError(f"Expected delay value after '#', got {tok.value!r}", tok.line)

    def _parse_always(self) -> AlwaysBlock:
        kw = self.tokens[self.pos].value
        self.pos += 1
        sens: list[SensitivityItem] = []
        if kw in ("always_comb", "always_latch"):
            sens.append(SensitivityItem(None, None))
        elif self.match("@"):
            if self.match("*"):
                sens.append(SensitivityItem(None, None))
            else:
                self.expect("(")
                if self.match("*"):
                    sens.append(SensitivityItem(None, None))
                else:
                    while True:
                        edge = None
                        if self.peek().value in ("posedge", "negedge"):
                            edge = self.tokens[self.pos].value
                            self.pos += 1
                        sig = self.expect_ident()
                        # Ignore optional bit-select in sensitivity list e.g. @(posedge clk[0])
                        if self.match("["):
                            self.parse_expr()
                            if self.match(":"):
                                self.parse_expr()
                            self.expect("]")
                        sens.append(SensitivityItem(edge, sig))
                        if self.match("or", ","):
                            continue
                        break
                self.expect(")")
        body = self._parse_stmt()
        return AlwaysBlock(sensitivity=sens, body=body)

    def _parse_assign_no_semi(self) -> AssignStmt:
        target, idx, msb, lsb, lhs_concat = self._parse_lvalue()
        if self.match("++"):
            return AssignStmt(target, idx, msb, lsb, BinaryOp("+", IdentExpr(target), NumberLiteral(1, 32)), lhs_concat=lhs_concat)
        if self.match("--"):
            return AssignStmt(target, idx, msb, lsb, BinaryOp("-", IdentExpr(target), NumberLiteral(1, 32)), lhs_concat=lhs_concat)
        nonblocking = self.match("<=")
        if not nonblocking:
            self.expect("=")
        if self.peek().value == "#":
            self._consume_delay_val()
        expr = self.parse_expr()
        return AssignStmt(target, idx, msb, lsb, expr, nonblocking=nonblocking, lhs_concat=lhs_concat)

    def _parse_stmt(self) -> Stmt:
        tok = self.peek()
        if tok.value == "begin":
            self.pos += 1
            # Optional named block `begin : block_name`
            if self.match(":"):
                self.expect_ident()
            stmts: list[Stmt] = []
            while not self.match("end"):
                if self.peek().kind == "EOF":
                    raise VerilogSyntaxError("Missing 'end'", self.peek().line)
                # Allow local integer/reg declarations inside named begin..end blocks
                if self.peek().value in ("integer", "int", "reg", "logic"):
                    self.pos += 1
                    if self.peek().value == "[":
                        self._parse_range()
                    while True:
                        vname = self.expect_ident()
                        if self.match("="):
                            stmts.append(AssignStmt(vname, None, None, None, self.parse_expr()))
                        if not self.match(","):
                            break
                    self.expect(";")
                    continue
                stmts.append(self._parse_stmt())
            if self.match(":"):
                self.expect_ident()
            return BlockStmt(stmts)

        if tok.value == "if":
            self.pos += 1
            self.expect("(")
            cond = self.parse_expr()
            self.expect(")")
            then_s = self._parse_stmt()
            else_s = self._parse_stmt() if self.match("else") else None
            return IfStmt(cond, then_s, else_s)

        if tok.value in ("case", "casez", "casex"):
            self.pos += 1
            self.expect("(")
            case_expr = self.parse_expr()
            self.expect(")")
            arms: list[tuple[list[Expr], Stmt]] = []
            default_s: Stmt | None = None
            while not self.match("endcase"):
                if self.peek().kind == "EOF":
                    raise VerilogSyntaxError("Missing 'endcase'", self.peek().line)
                if self.match("default"):
                    self.match(":")
                    default_s = self._parse_stmt()
                else:
                    labels = [self.parse_expr()]
                    while self.match(","):
                        labels.append(self.parse_expr())
                    self.expect(":")
                    arms.append((labels, self._parse_stmt()))
            return CaseStmt(case_expr, arms, default_s)

        if tok.value == "repeat":
            self.pos += 1
            self.expect("(")
            cnt = self.parse_expr()
            self.expect(")")
            body = self._parse_stmt()
            return RepeatStmt(cnt, body)

        if tok.value == "forever":
            self.pos += 1
            return ForeverStmt(self._parse_stmt())

        if tok.value == "while":
            self.pos += 1
            self.expect("(")
            cond = self.parse_expr()
            self.expect(")")
            return WhileStmt(cond, self._parse_stmt())

        if tok.value == "for":
            self.pos += 1
            self.expect("(")
            self.match("integer", "int")
            init_s = self._parse_assign_no_semi()
            self.expect(";")
            cond = self.parse_expr()
            self.expect(";")
            step_s = self._parse_assign_no_semi()
            self.expect(")")
            body = self._parse_stmt()
            return ForStmt(init_s, cond, step_s, body)

        if tok.value == "#":
            delay = self._consume_delay_val()
            if self.match(";"):
                return DelayStmt(delay, None)
            return DelayStmt(delay, self._parse_stmt())

        if tok.kind == "SYS_IDENT":
            sys_name = tok.value
            self.pos += 1
            if sys_name in ("$display", "$write", "$strobe", "$monitor"):
                fmt = ""
                args: list[Expr] = []
                if self.match("("):
                    if not self.match(")"):
                        if self.peek().kind == "STRING":
                            fmt = self.tokens[self.pos].value[1:-1]
                            self.pos += 1
                            while self.match(","):
                                args.append(self.parse_expr())
                        else:
                            first_e = self.parse_expr()
                            args.append(first_e)
                            while self.match(","):
                                args.append(self.parse_expr())
                            fmt = " ".join("%d" for _ in args)
                        self.expect(")")
                self.expect(";")
                return DisplayStmt(fmt, args, is_monitor=(sys_name == "$monitor"))
            if sys_name in ("$finish", "$stop"):
                if self.match("("):
                    while not self.match(")") and self.peek().kind != "EOF":
                        self.pos += 1
                self.expect(";")
                return FinishStmt()
            # Ignore other system tasks ($dumpfile, $dumpvars, $readmemh, etc.)
            if self.match("("):
                depth = 1
                while depth > 0 and self.peek().kind != "EOF":
                    if self.match("("):
                        depth += 1
                    elif self.match(")"):
                        depth -= 1
                    else:
                        self.pos += 1
            self.expect(";")
            return BlockStmt([])

        if tok.value == "{":
            stmt = self._parse_assign_no_semi()
            self.expect(";")
            return stmt

        if tok.kind == "IDENT":
            # Optional statement label `label_name: stmt`
            if self.peek(1).value == ":":
                self.pos += 2
                return self._parse_stmt()
            stmt = self._parse_assign_no_semi()
            self.expect(";")
            return stmt

        if tok.value == ";":
            self.pos += 1
            return BlockStmt([])

        raise VerilogSyntaxError(f"Unexpected statement token {tok.value!r}", tok.line)

    def _parse_gate_inst(self) -> GateInst:
        gtype = self.tokens[self.pos].value
        self.pos += 1
        if self.peek().value == "#":
            self._consume_delay_val()
        inst_name = ""
        if self.peek().kind == "IDENT":
            inst_name = self.expect_ident()
        self.expect("(")
        out_expr = self.parse_expr()
        inputs: list[Expr] = []
        while self.match(","):
            inputs.append(self.parse_expr())
        self.expect(")")
        self.expect(";")
        return GateInst(gtype, inst_name or gtype, out_expr, inputs)

    def _parse_module_inst(self) -> ModuleInst:
        mod_name = self.expect_ident()
        if self.match("#"):
            self.expect("(")
            depth = 1
            while depth > 0 and self.peek().kind != "EOF":
                if self.match("("):
                    depth += 1
                elif self.match(")"):
                    depth -= 1
                else:
                    self.pos += 1
        inst_name = self.expect_ident()
        self.expect("(")
        named: dict[str, Expr] = {}
        pos_conns: list[Expr] = []
        if not self.match(")"):
            while True:
                if self.match("."):
                    port_name = self.expect_ident()
                    self.expect("(")
                    if not self.match(")"):
                        conn_expr = self.parse_expr()
                        self.expect(")")
                        named[port_name] = conn_expr
                else:
                    pos_conns.append(self.parse_expr())
                if not self.match(","):
                    break
            self.expect(")")
        self.expect(";")
        return ModuleInst(mod_name, inst_name, named, pos_conns)

    # --- Expression Parsing ---

    def parse_expr(self) -> Expr:
        return self._parse_ternary()

    def _parse_ternary(self) -> Expr:
        cond = self._parse_logical_or()
        if self.match("?"):
            t = self.parse_expr()
            self.expect(":")
            f = self._parse_ternary()
            return TernaryOp(cond, t, f)
        return cond

    def _parse_logical_or(self) -> Expr:
        left = self._parse_logical_and()
        while self.match("||"):
            left = BinaryOp("||", left, self._parse_logical_and())
        return left

    def _parse_logical_and(self) -> Expr:
        left = self._parse_bit_or()
        while self.match("&&"):
            left = BinaryOp("&&", left, self._parse_bit_or())
        return left

    def _parse_bit_or(self) -> Expr:
        left = self._parse_bit_xor()
        while self.peek().value in ("|", "~|"):
            op = self.tokens[self.pos].value
            self.pos += 1
            left = BinaryOp(op, left, self._parse_bit_xor())
        return left

    def _parse_bit_xor(self) -> Expr:
        left = self._parse_bit_and()
        while self.peek().value in ("^", "~^", "^~"):
            op = self.tokens[self.pos].value
            self.pos += 1
            left = BinaryOp("^~" if op in ("~^", "^~") else "^", left, self._parse_bit_and())
        return left

    def _parse_bit_and(self) -> Expr:
        left = self._parse_eq()
        while self.peek().value in ("&", "~&"):
            op = self.tokens[self.pos].value
            self.pos += 1
            left = BinaryOp(op, left, self._parse_eq())
        return left

    def _parse_eq(self) -> Expr:
        left = self._parse_rel()
        while self.peek().value in ("==", "!=", "===", "!=="):
            op = self.tokens[self.pos].value
            self.pos += 1
            norm_op = "==" if op == "===" else ("!=" if op == "!==" else op)
            left = BinaryOp(norm_op, left, self._parse_rel())
        return left

    def _parse_rel(self) -> Expr:
        left = self._parse_shift()
        while self.peek().value in ("<", "<=", ">", ">="):
            op = self.tokens[self.pos].value
            self.pos += 1
            left = BinaryOp(op, left, self._parse_shift())
        return left

    def _parse_shift(self) -> Expr:
        left = self._parse_add()
        while self.peek().value in ("<<", ">>", "<<<", ">>>"):
            op = self.tokens[self.pos].value
            self.pos += 1
            norm_op = "<<" if op == "<<<" else (">>" if op == ">>>" else op)
            left = BinaryOp(norm_op, left, self._parse_add())
        return left

    def _parse_add(self) -> Expr:
        left = self._parse_mul()
        while self.peek().value in ("+", "-"):
            op = self.tokens[self.pos].value
            self.pos += 1
            left = BinaryOp(op, left, self._parse_mul())
        return left

    def _parse_mul(self) -> Expr:
        left = self._parse_power()
        while self.peek().value in ("*", "/", "%"):
            op = self.tokens[self.pos].value
            self.pos += 1
            left = BinaryOp(op, left, self._parse_power())
        return left

    def _parse_power(self) -> Expr:
        left = self._parse_unary()
        while self.match("**"):
            left = BinaryOp("**", left, self._parse_unary())
        return left

    def _parse_unary(self) -> Expr:
        if self.peek().value in ("~", "!", "-", "+", "&", "~&", "|", "~|", "^", "~^", "^~"):
            op = self.tokens[self.pos].value
            self.pos += 1
            if op == "+":
                return self._parse_unary()
            return UnaryOp(op, self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        tok = self.peek()
        if tok.kind in ("SIZED_NUM", "UNBASED_NUM"):
            self.pos += 1
            return _parse_sized_number(tok.value, tok.line)
        if tok.kind == "NUMBER":
            self.pos += 1
            return NumberLiteral(int(tok.value.replace("_", "")), 32)
        if tok.kind == "FLOAT_NUM":
            self.pos += 1
            return NumberLiteral(round(float(tok.value)), 32)
        if tok.kind == "SYS_IDENT":
            self.pos += 1
            args: list[Expr] = []
            if self.match("("):
                if not self.match(")"):
                    args.append(self.parse_expr())
                    while self.match(","):
                        args.append(self.parse_expr())
                    self.expect(")")
            return SysFuncExpr(tok.value, args)
        if self.match("("):
            expr = self.parse_expr()
            self.expect(")")
            return expr
        if self.match("{"):
            first = self.parse_expr()
            # Check for replication `{count{expr}}`
            if self.match("{"):
                inner_parts = [self.parse_expr()]
                while self.match(","):
                    inner_parts.append(self.parse_expr())
                self.expect("}")
                self.expect("}")
                inner = inner_parts[0] if len(inner_parts) == 1 else ConcatExpr(inner_parts)
                return ReplicateExpr(max(1, self._const_eval(first)), inner)
            parts: list[Expr] = [first]
            while self.match(","):
                parts.append(self.parse_expr())
            self.expect("}")
            return ConcatExpr(parts)
        if tok.kind == "IDENT":
            self.pos += 1
            if tok.value in self.params:
                return NumberLiteral(self.params[tok.value], 32)
            if self.match("["):
                first = self.parse_expr()
                if self.match(":"):
                    lsb = self._const_eval(self.parse_expr())
                    self.expect("]")
                    return SliceExpr(tok.value, self._const_eval(first), lsb)
                if self.match("+:"):
                    w = self._const_eval(self.parse_expr())
                    self.expect("]")
                    return PartSelectExpr(tok.value, first, w, ascending=True)
                if self.match("-:"):
                    w = self._const_eval(self.parse_expr())
                    self.expect("]")
                    return PartSelectExpr(tok.value, first, w, ascending=False)
                self.expect("]")
                return IndexExpr(tok.value, first)
            return IdentExpr(tok.value)
        raise VerilogSyntaxError(f"Expected expression, got {tok.value!r}", tok.line)


def parse_verilog(source: str) -> list[ModuleDef]:
    """Parse Verilog source code into a list of ModuleDef AST nodes."""
    tokens = tokenize(source)
    return _Parser(tokens).parse_all()

"""Verilog RTL code editor with syntax highlighting and accurate line numbers."""

from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextFormat
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget


class VerilogHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for Verilog-2001 / SystemVerilog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rules: list[tuple[re.Pattern[str], QTextCharFormat]] = []

        def fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Bold)
            if italic:
                f.setFontItalic(True)
            return f

        kw_fmt = fmt("#60A5FA", bold=True)
        keywords = (
            "module|endmodule|input|output|inout|wire|reg|logic|integer|signed|unsigned|"
            "assign|always|always_comb|always_ff|initial|forever|for|while|"
            "begin|end|if|else|case|casez|casex|endcase|default|"
            "posedge|negedge|or|repeat|parameter|localparam|"
            "and|or|nand|nor|xor|xnor|not|buf"
        )
        self.rules.append((re.compile(rf"\b({keywords})\b"), kw_fmt))
        self.rules.append((re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*"), fmt("#C084FC", bold=True)))
        self.rules.append((re.compile(r"`[A-Za-z_][A-Za-z0-9_]*"), fmt("#38BDF8")))
        self.rules.append((re.compile(r"\b\d*'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+\b"), fmt("#F59E0B")))
        self.rules.append((re.compile(r"\b\d+\b"), fmt("#F59E0B")))
        self.rules.append((re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"'), fmt("#34D399")))
        self.rules.append((re.compile(r"//[^\n]*"), fmt("#6B7280", italic=True)))

        self.comment_fmt = fmt("#6B7280", italic=True)
        self.comment_start = re.compile(r"/\*")
        self.comment_end = re.compile(r"\*/")

    def highlightBlock(self, text: str) -> None:
        for pattern, char_fmt in self.rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), char_fmt)

        self.setCurrentBlockState(0)
        start = 0
        if self.previousBlockState() != 1:
            m = self.comment_start.search(text)
            start = m.start() if m else -1
        while start >= 0:
            end_m = self.comment_end.search(text, start)
            if end_m is None:
                self.setCurrentBlockState(1)
                self.setFormat(start, len(text) - start, self.comment_fmt)
                break
            length = end_m.end() - start
            self.setFormat(start, length, self.comment_fmt)
            next_m = self.comment_start.search(text, start + length)
            start = next_m.start() if next_m else -1


class _LineNumberArea(QWidget):
    def __init__(self, editor: CodeEditor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.line_number_area_paint_event(event)


class CodeEditor(QPlainTextEdit):
    """Monospace Verilog code editor with pixel-aligned line numbers and error highlighting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("codeEditor")
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.Monospace)
        font.setFixedPitch(True)
        self.setFont(font)
        self.document().setDocumentMargin(4)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)

        self._error_line: int | None = None
        self.line_number_area = _LineNumberArea(self)
        self.line_number_area.setFont(font)
        self.highlighter = VerilogHighlighter(self.document())

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self._update_extra_selections)

        self.update_line_number_area_width(0)
        self._update_extra_selections()

    def set_error_line(self, line: int | None) -> None:
        self._error_line = line
        self._update_extra_selections()
        self.line_number_area.update()

    def line_number_area_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def _update_extra_selections(self) -> None:
        extra = []
        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(QColor("#1F2633"))
            sel.format.setProperty(QTextFormat.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            extra.append(sel)

        if self._error_line is not None and self._error_line >= 1:
            blk = self.document().findBlockByNumber(self._error_line - 1)
            if blk.isValid():
                err_sel = QTextEdit.ExtraSelection()
                err_sel.format.setBackground(QColor("#451A1A"))
                err_sel.format.setProperty(QTextFormat.FullWidthSelection, True)
                cur = self.textCursor()
                cur.setPosition(blk.position())
                err_sel.cursor = cur
                extra.append(err_sel)
        self.setExtraSelections(extra)

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self.line_number_area)
        painter.setFont(self.font())
        painter.fillRect(event.rect(), QColor("#161A22"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        offset = self.contentOffset()
        top = round(self.blockBoundingGeometry(block).translated(offset).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        cur_line = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line_num = block_number + 1
                if self._error_line == line_num:
                    painter.setPen(QColor("#EF4444"))
                elif block_number == cur_line:
                    painter.setPen(QColor("#E6EDF3"))
                else:
                    painter.setPen(QColor("#6B7280"))
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 8,
                    round(self.blockBoundingRect(block).height()),
                    Qt.AlignRight | Qt.AlignVCenter,
                    str(line_num),
                )
            block = block.next()
            block_number += 1
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())

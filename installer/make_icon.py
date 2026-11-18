"""Generate a crisp Windows .ico file for SiliconForge VLSI Studio using PySide6."""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPen


def generate_ico(out_path: Path) -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sizes = [256, 64, 48, 32, 16]
    png_blobs: list[tuple[int, bytes]] = []

    for sz in sizes:
        img = QImage(sz, sz, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)

        s = sz / 256.0
        # Rounded dark IC package
        p.setBrush(QBrush(QColor("#111827")))
        p.setPen(QPen(QColor("#38BDF8"), max(1.5, 6 * s)))
        p.drawRoundedRect(QRectF(36 * s, 36 * s, 184 * s, 184 * s), 24 * s, 24 * s)

        # Chip pins (top, bottom, left, right)
        p.setBrush(QBrush(QColor("#F59E0B")))
        p.setPen(Qt.NoPen)
        for i in range(4):
            pos = (64 + i * 38) * s
            pw = 16 * s
            ph = 24 * s
            p.drawRoundedRect(QRectF(pos, 10 * s, pw, ph), 3 * s, 3 * s)
            p.drawRoundedRect(QRectF(pos, 222 * s, pw, ph), 3 * s, 3 * s)
            p.drawRoundedRect(QRectF(10 * s, pos, ph, pw), 3 * s, 3 * s)
            p.drawRoundedRect(QRectF(222 * s, pos, ph, pw), 3 * s, 3 * s)

        # Inner silicon die
        p.setBrush(QBrush(QColor("#1E293B")))
        p.setPen(QPen(QColor("#10B981"), max(1.0, 4 * s)))
        p.drawRoundedRect(QRectF(68 * s, 68 * s, 120 * s, 120 * s), 12 * s, 12 * s)

        # Die routing traces & waveform motif
        p.setPen(QPen(QColor("#38BDF8"), max(1.5, 7 * s), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(int(88 * s), int(146 * s), int(112 * s), int(146 * s))
        p.drawLine(int(112 * s), int(146 * s), int(112 * s), int(104 * s))
        p.drawLine(int(112 * s), int(104 * s), int(144 * s), int(104 * s))
        p.drawLine(int(144 * s), int(104 * s), int(144 * s), int(146 * s))
        p.drawLine(int(144 * s), int(146 * s), int(168 * s), int(146 * s))

        p.end()

        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        png_blobs.append((sz, bytes(buf.data())))

    # Write ICO container with embedded PNGs (supported natively since Windows Vista)
    header = struct.pack("<HHH", 0, 1, len(png_blobs))
    offset = 6 + 16 * len(png_blobs)
    entries = []
    data_chunks = []
    for sz, blob in png_blobs:
        dim = 0 if sz >= 256 else sz
        entries.append(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset))
        data_chunks.append(blob)
        offset += len(blob)

    out_path.write_bytes(header + b"".join(entries) + b"".join(data_chunks))


if __name__ == "__main__":
    generate_ico(Path("assets/siliconforge.ico"))

"""Read and write authentic Magic VLSI (.mag) layout files."""

from __future__ import annotations

import time

from .layers import LAYER_MAP, LayoutCell, LayoutLabel, LayoutRect

_MAGIC_ALIAS = {
    "ndiffusion": "ndiff",
    "pdiffusion": "pdiff",
    "polysilicon": "poly",
    "m1": "metal1",
    "m2": "metal2",
    "polycontact": "contact",
    "ndcontact": "contact",
    "pdcontact": "contact",
    "m2contact": "via",
}


def save_mag(cell: LayoutCell) -> str:
    """Serialize a LayoutCell into Magic .mag file format."""
    lines = [
        "magic",
        "tech scmos",
        f"timestamp {int(time.time())}",
    ]
    by_layer: dict[str, list[LayoutRect]] = {}
    for r in cell.rects:
        by_layer.setdefault(r.layer, []).append(r)

    for layer, rects in by_layer.items():
        lines.append(f"<< {layer} >>")
        for r in rects:
            lines.append(f"rect {r.x1} {r.y1} {r.x2} {r.y2}")

    if cell.labels:
        lines.append("<< labels >>")
        for lbl in cell.labels:
            lines.append(f"rlabel {lbl.layer} {lbl.x} {lbl.y} {lbl.x} {lbl.y} 0 {lbl.text}")

    lines.append("<< end >>")
    return "\n".join(lines) + "\n"


def load_mag(text: str, cell_name: str = "imported") -> LayoutCell:
    """Parse Magic .mag text into a LayoutCell."""
    cell = LayoutCell(name=cell_name)
    current_layer: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("<<") and line.endswith(">>"):
            sec = line[2:-2].strip().lower()
            if sec == "end":
                break
            current_layer = _MAGIC_ALIAS.get(sec, sec)
            continue
        parts = line.split()
        if parts[0] == "rect" and len(parts) >= 5 and current_layer in LAYER_MAP:
            x1, y1, x2, y2 = map(int, parts[1:5])
            cell.rects.append(LayoutRect(current_layer, x1, y1, x2, y2))
        elif parts[0] == "rlabel" and len(parts) >= 8:
            layer = _MAGIC_ALIAS.get(parts[1].lower(), parts[1].lower())
            x, y = int(parts[2]), int(parts[3])
            lbl_text = " ".join(parts[7:])
            cell.labels.append(LayoutLabel(lbl_text, layer, x, y))
    return cell

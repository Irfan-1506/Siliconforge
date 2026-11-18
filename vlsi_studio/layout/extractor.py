"""Magic-style SPICE & transistor netlist extractor from 2D layout geometry."""

from __future__ import annotations

from dataclasses import dataclass, field

from .layers import LayoutCell, LayoutRect


@dataclass
class ExtractedMosfet:
    name: str
    mos_type: str  # "nmos" or "pmos"
    gate_net: str
    terminal_a: str
    terminal_b: str
    width: int
    length: int


@dataclass
class ExtractionResult:
    cell_name: str
    nets: list[str] = field(default_factory=list)
    mosfets: list[ExtractedMosfet] = field(default_factory=list)
    shorted_labels: list[tuple[str, str]] = field(default_factory=list)
    spice_text: str = ""


def _intersect(a: LayoutRect, b: LayoutRect) -> LayoutRect | None:
    x1, y1 = max(a.x1, b.x1), max(a.y1, b.y1)
    x2, y2 = min(a.x2, b.x2), min(a.y2, b.y2)
    if x1 < x2 and y1 < y2:
        return LayoutRect("poly", x1, y1, x2, y2)
    return None


def _split_diff_by_poly(diff_rect: LayoutRect, polys: list[LayoutRect]) -> list[LayoutRect]:
    """Split a diffusion rectangle at intersecting poly gates so source/drain islands are distinct."""
    cuts = sorted(
        {
            x
            for p in polys
            if p.strictly_overlaps(diff_rect)
            for x in (max(diff_rect.x1, p.x1), min(diff_rect.x2, p.x2))
        }
    )
    if len(cuts) < 2:
        return [diff_rect]

    # Build non-channel segments (exclude regions covered by poly gates)
    boundaries = sorted({diff_rect.x1, diff_rect.x2, *cuts})
    segments: list[LayoutRect] = []
    for i in range(len(boundaries) - 1):
        sx1, sx2 = boundaries[i], boundaries[i + 1]
        if sx2 <= sx1:
            continue
        mid_x = (sx1 + sx2) / 2.0
        in_gate = any(
            p.x1 <= mid_x <= p.x2 and p.y1 < diff_rect.y2 and p.y2 > diff_rect.y1
            for p in polys
        )
        if not in_gate:
            segments.append(LayoutRect(diff_rect.layer, sx1, diff_rect.y1, sx2, diff_rect.y2))
    return segments or [diff_rect]


def extract_netlist(cell: LayoutCell) -> ExtractionResult:
    """Extract electrical nets and NMOS/PMOS transistors into a SPICE netlist."""
    raw_rects = [r for r in cell.rects if r.width > 0 and r.height > 0]
    poly_rects = [r for r in raw_rects if r.layer == "poly"]

    # Split diffusions by poly channels so source and drain are not shorted
    rects: list[LayoutRect] = []
    orig_diffs: list[LayoutRect] = []
    for r in raw_rects:
        if r.layer in ("ndiff", "pdiff"):
            orig_diffs.append(r)
            rects.extend(_split_diff_by_poly(r, poly_rects))
        else:
            rects.append(r)

    n = len(rects)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Connect conductive shapes (diffusions only connect within their split source/drain island)
    conductive = {"ndiff", "pdiff", "poly", "metal1", "metal2", "contact", "via"}
    for i in range(n):
        ri = rects[i]
        if ri.layer not in conductive:
            continue
        for j in range(i + 1, n):
            rj = rects[j]
            if rj.layer not in conductive:
                continue
            if not ri.overlaps_or_touches(rj):
                continue
            if ri.layer == rj.layer:
                union(i, j)
            elif "contact" in (ri.layer, rj.layer):
                other = rj.layer if ri.layer == "contact" else ri.layer
                if other in ("metal1", "poly", "ndiff", "pdiff"):
                    union(i, j)
            elif "via" in (ri.layer, rj.layer):
                other = rj.layer if ri.layer == "via" else ri.layer
                if other in ("metal1", "metal2"):
                    union(i, j)

    # Name each connected component (preferring user labels) and detect shorted distinct labels
    comp_name: dict[int, str] = {}
    shorted_labels: list[tuple[str, str]] = []
    for lbl in cell.labels:
        for idx, r in enumerate(rects):
            if r.layer == lbl.layer and r.x1 <= lbl.x <= r.x2 and r.y1 <= lbl.y <= r.y2:
                root = find(idx)
                prev = comp_name.get(root)
                if prev is not None and prev != lbl.text:
                    shorted_labels.append((prev, lbl.text))
                else:
                    comp_name[root] = lbl.text
                break

    net_counter = 1
    for i, r in enumerate(rects):
        if r.layer not in conductive:
            continue
        root = find(i)
        if root not in comp_name:
            comp_name[root] = f"N{net_counter}"
            net_counter += 1

    # Helper to find source/drain nets adjacent to a MOSFET channel intersection
    diff_island_indices = [i for i, r in enumerate(rects) if r.layer in ("ndiff", "pdiff")]

    def _adjacent_nets(diff_layer: str, inter: LayoutRect, default_b: str) -> tuple[str, str]:
        left_net = default_b
        right_net = default_b
        for di in diff_island_indices:
            dr = rects[di]
            if dr.layer != diff_layer or dr.y2 <= inter.y1 or dr.y1 >= inter.y2:
                continue
            if dr.x2 <= inter.x1 and inter.x1 - dr.x2 <= 1:
                left_net = comp_name[find(di)]
            elif dr.x1 >= inter.x2 and dr.x1 - inter.x2 <= 1:
                right_net = comp_name[find(di)]
        return right_net, left_net

    poly_indices = [i for i, r in enumerate(rects) if r.layer == "poly"]
    mosfets: list[ExtractedMosfet] = []
    m_idx = 1
    for pi in poly_indices:
        pr = rects[pi]
        gate_net = comp_name[find(pi)]
        for dr in orig_diffs:
            inter = _intersect(pr, dr)
            if not inter:
                continue
            mos_type = "nmos" if dr.layer == "ndiff" else "pmos"
            default_bulk = "GND" if mos_type == "nmos" else "VDD"
            term_a, term_b = _adjacent_nets(dr.layer, inter, default_bulk)
            mosfets.append(
                ExtractedMosfet(
                    name=f"M{m_idx}",
                    mos_type=mos_type,
                    gate_net=gate_net,
                    terminal_a=term_a,
                    terminal_b=term_b,
                    width=inter.height,
                    length=inter.width,
                )
            )
            m_idx += 1

    nets = sorted(set(comp_name.values()))
    spice_lines = [
        "* Extracted by SiliconForge VLSI Studio",
        f".subckt {cell.name} " + " ".join(nets[:6]),
    ]
    for m in mosfets:
        bulk = "GND" if m.mos_type == "nmos" else "VDD"
        spice_lines.append(
            f"{m.name} {m.terminal_a} {m.gate_net} {m.terminal_b} {bulk} {m.mos_type} W={m.width}u L={m.length}u"
        )
    spice_lines.append(f".ends {cell.name}")

    return ExtractionResult(
        cell_name=cell.name,
        nets=nets,
        mosfets=mosfets,
        shorted_labels=shorted_labels,
        spice_text="\n".join(spice_lines),
    )

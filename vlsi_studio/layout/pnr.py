"""Automatic RTL-to-Layout Place & Route generator (SCMOS standard cells + Metal2 routing)."""

from __future__ import annotations

from vlsi_studio.synth.synthesizer import Netlist, NetNode

from .layers import LayoutCell, LayoutLabel, LayoutRect

_CELL_GATES = {
    "NOT": 1,
    "BUF": 1,
    "AND": 2,
    "NAND": 2,
    "OR": 2,
    "NOR": 2,
    "CMP": 2,
    "XOR": 3,
    "XNOR": 3,
    "MUX": 3,
    "ADD": 3,
    "SUB": 3,
    "DFF": 3,
    "LUT": 3,
}


def cell_finger_count(node: NetNode, fanin_count: int) -> int:
    return max(_CELL_GATES.get(node.kind, 2), fanin_count)


def generate_layout_from_netlist(netlist: Netlist) -> LayoutCell:
    """Place multi-pin SCMOS standard cells for every synthesized gate/DFF and route nets in Metal2."""
    logic_nodes: list[NetNode] = [
        n for n in netlist.nodes.values() if n.kind not in ("INPUT", "OUTPUT", "CONST")
    ]
    logic_nodes.sort(key=lambda n: (n.col, n.row, n.id))

    if not logic_nodes:
        logic_nodes = [NetNode(id="BUF_AUTO", label="BUF", kind="BUF", width=1)]

    node_outputs: dict[str, list[str]] = {}
    node_inputs: dict[str, list[str]] = {}
    for e in netlist.edges:
        if e.src_id in netlist.nodes and e.dst_id in netlist.nodes:
            node_outputs.setdefault(e.src_id, []).append(e.dst_id)
            node_inputs.setdefault(e.dst_id, []).append(e.src_id)

    routed_nets: list[str] = [nid for nid, targets in node_outputs.items() if targets]
    num_tracks = max(2, len(routed_nets))

    # Channel geometry between NMOS (bottom) and PMOS (top)
    chan_y0 = 21
    track_pitch = 7  # 4λ Metal2 height + 3λ spacing
    chan_h = num_tracks * track_pitch + 4
    pdiff_y1 = chan_y0 + chan_h + 2
    pdiff_y2 = pdiff_y1 + 7
    vdd_y1 = pdiff_y2 + 4
    vdd_y2 = vdd_y1 + 4
    nwell_y1 = pdiff_y1 - 4
    nwell_y2 = vdd_y2

    # Compute x placement with dedicated vertical pin straps per input
    cell_geom: dict[str, tuple[int, int, list[int], int]] = {}  # nid -> (x0, cell_w, pin_xs, out_x)
    cur_x = 4
    for node in logic_nodes:
        fanin_srcs = node_inputs.get(node.id, [])
        n_pins = cell_finger_count(node, len(fanin_srcs))
        pin_xs = [cur_x + 12 + k * 14 for k in range(n_pins)]
        out_x = cur_x + 12 + n_pins * 14
        cell_w = 12 + n_pins * 14 + 8
        cell_geom[node.id] = (cur_x, cell_w, pin_xs, out_x)
        cur_x += cell_w + 4

    total_w = max(60, cur_x + 4)

    rects: list[LayoutRect] = [
        LayoutRect("nwell", 0, nwell_y1, total_w, nwell_y2),
        LayoutRect("metal1", 0, vdd_y1, total_w, vdd_y2),
        LayoutRect("metal1", 0, 1, total_w, 5),
    ]
    labels: list[LayoutLabel] = [
        LayoutLabel("VDD", "metal1", 2, (vdd_y1 + vdd_y2) // 2),
        LayoutLabel("GND", "metal1", 2, 3),
    ]

    for node in logic_nodes:
        x0, cell_w, pin_xs, out_x = cell_geom[node.id]

        # PMOS & NMOS active diffusions
        rects.append(LayoutRect("pdiff", x0 + 4, pdiff_y1, x0 + cell_w - 4, pdiff_y2))
        rects.append(LayoutRect("ndiff", x0 + 4, 8, x0 + cell_w - 4, 14))

        # Dedicated input pin strap + contact + poly finger per pin
        for px in pin_xs:
            gx = px + 6
            rects.append(LayoutRect("poly", gx, 6, gx + 2, pdiff_y2 + 2))
            rects.append(LayoutRect("poly", px, 15, gx + 2, 19))
            rects.append(LayoutRect("contact", px + 1, 16, px + 3, 18))
            rects.append(LayoutRect("metal1", px, 15, px + 4, chan_y0 + chan_h))

        # VDD & GND power straps + contacts (at x0 + 4 .. x0 + 8)
        rects.append(LayoutRect("metal1", x0 + 4, pdiff_y1 + 2, x0 + 8, vdd_y1))
        rects.append(LayoutRect("contact", x0 + 5, pdiff_y1 + 3, x0 + 7, pdiff_y1 + 5))
        rects.append(LayoutRect("metal1", x0 + 4, 5, x0 + 8, 13))
        rects.append(LayoutRect("contact", x0 + 5, 10, x0 + 7, 12))

        # Output Metal1 drain strap + PMOS/NMOS contacts
        rects.append(LayoutRect("metal1", out_x, 9, out_x + 4, pdiff_y2 - 1))
        rects.append(LayoutRect("contact", out_x + 1, pdiff_y1 + 2, out_x + 3, pdiff_y1 + 4))
        rects.append(LayoutRect("contact", out_x + 1, 10, out_x + 3, 12))

    # Map each edge (src_id, dst_id, occurrence) -> specific input pin_x on dst_id
    dst_pin_cursor: dict[str, int] = {}
    edge_pin_x: list[tuple[str, str, int]] = []
    for e in netlist.edges:
        if e.dst_id in cell_geom:
            idx_k = dst_pin_cursor.get(e.dst_id, 0)
            dst_pin_cursor[e.dst_id] = idx_k + 1
            pin_xs = cell_geom[e.dst_id][2]
            edge_pin_x.append((e.src_id, e.dst_id, pin_xs[min(idx_k, len(pin_xs) - 1)]))

    # Route each net across its own Metal2 track
    for idx, src_id in enumerate(routed_nets[:num_tracks]):
        track_y = chan_y0 + idx * track_pitch
        x_points: list[int] = []
        via_xs: list[int] = []

        if src_id in cell_geom:
            out_x = cell_geom[src_id][3]
            x_points.append(out_x)
            via_xs.append(out_x + 1)

        for e_src, e_dst, px in edge_pin_x:
            if e_src == src_id:
                x_points.append(px)
                via_xs.append(px + 1)

        src_node = netlist.nodes.get(src_id)
        if src_node and src_node.kind == "INPUT":
            x_points.append(4)
            labels.append(LayoutLabel(src_node.label.split()[0], "metal2", 5, track_y + 2))

        for dst_id in node_outputs.get(src_id, []):
            dst_node = netlist.nodes.get(dst_id)
            if dst_node and dst_node.kind == "OUTPUT":
                x_points.append(total_w - 8)
                labels.append(LayoutLabel(dst_node.label.split()[0], "metal2", total_w - 14, track_y + 2))

        if not x_points:
            continue
        x_min = min(x_points)
        x_max = max(x_points) + 4
        if x_max - x_min < 4:
            x_max = x_min + 4

        rects.append(LayoutRect("metal2", x_min, track_y, x_max, track_y + 4))

        for vx in sorted(set(via_xs)):
            rects.append(LayoutRect("via", vx, track_y + 1, vx + 2, track_y + 3))

    return LayoutCell(name=netlist.module_name or "auto_layout", rects=rects, labels=labels)

"""Layout vs. Schematic (LVS) verification comparing synthesized Netlist and extracted Layout."""

from __future__ import annotations

from dataclasses import dataclass, field

from vlsi_studio.synth.synthesizer import Netlist, NetNode

from .extractor import ExtractionResult, extract_netlist
from .layers import LayoutCell
from .pnr import cell_finger_count


@dataclass
class LVSCheckItem:
    name: str
    schematic_val: str
    layout_val: str
    passed: bool
    note: str = ""


@dataclass
class LVSReport:
    module_name: str
    cell_name: str
    matched: bool
    checks: list[LVSCheckItem] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    extraction: ExtractionResult = field(default_factory=lambda: ExtractionResult(""))

    @property
    def summary(self) -> str:
        status = "MATCHED (PASS)" if self.matched else "MISMATCH (FAIL)"
        return f"LVS {status}: {self.module_name} vs {self.cell_name} ({len(self.mismatches)} mismatch(es))"


def _base_port_name(label: str) -> str:
    return label.split("[", 1)[0].strip()


def run_lvs(netlist: Netlist | None, cell: LayoutCell) -> LVSReport:
    """Run Layout vs. Schematic checks between a synthesized Netlist and a LayoutCell."""
    ext = extract_netlist(cell)
    checks: list[LVSCheckItem] = []
    mismatches: list[str] = []

    lay_nmos = sum(1 for m in ext.mosfets if m.mos_type == "nmos")
    lay_pmos = sum(1 for m in ext.mosfets if m.mos_type == "pmos")
    lay_total = len(ext.mosfets)
    lay_labels = {lbl.text for lbl in cell.labels}
    lay_base_labels = {_base_port_name(lbl.text) for lbl in cell.labels}

    # 1. Shorted Labels / Power Shorts check
    if ext.shorted_labels:
        pairs = ", ".join(f"{a}<->{b}" for a, b in ext.shorted_labels)
        checks.append(LVSCheckItem("Net Shorts", "0 shorts", f"{len(ext.shorted_labels)} short(s)", False, pairs))
        mismatches.append(f"Electrical short detected between labels: {pairs}")
    else:
        checks.append(LVSCheckItem("Net Shorts", "0 shorts", "0 shorts", True, "All labeled nets isolated"))

    # 2. Power Rails check (VDD / GND)
    has_vdd = "VDD" in lay_labels
    has_gnd = "GND" in lay_labels
    pwr_ok = has_vdd and has_gnd
    checks.append(
        LVSCheckItem(
            "Power Rails",
            "VDD, GND",
            ", ".join(p for p, ok in (("VDD", has_vdd), ("GND", has_gnd)) if ok) or "(none)",
            pwr_ok,
            "" if pwr_ok else "Missing VDD or GND label on power rail",
        )
    )
    if not pwr_ok:
        mismatches.append("Missing VDD and/or GND power rail labels in layout.")

    # If no synthesized schematic is provided, run complementary-CMOS structural LVS
    if netlist is None:
        comp_ok = lay_nmos > 0 and lay_nmos == lay_pmos
        checks.append(LVSCheckItem("NMOS Devices", ">= 1", str(lay_nmos), lay_nmos > 0))
        checks.append(LVSCheckItem("PMOS Devices", f"{lay_nmos} (complementary)", str(lay_pmos), comp_ok))
        if not comp_ok:
            mismatches.append(f"Complementary CMOS mismatch: NMOS={lay_nmos}, PMOS={lay_pmos}")
        return LVSReport(
            module_name="(standalone)",
            cell_name=cell.name,
            matched=(len(mismatches) == 0),
            checks=checks,
            mismatches=mismatches,
            extraction=ext,
        )

    # 3. Schematic Expected Transistor & Cell Counts
    logic_nodes: list[NetNode] = [
        n for n in netlist.nodes.values() if n.kind not in ("INPUT", "OUTPUT", "CONST")
    ]
    if not logic_nodes:
        logic_nodes = [NetNode(id="BUF_AUTO", label="BUF", kind="BUF", width=1)]

    node_fanin: dict[str, int] = {}
    for e in netlist.edges:
        if e.src_id in netlist.nodes and e.dst_id in netlist.nodes:
            node_fanin[e.dst_id] = node_fanin.get(e.dst_id, 0) + 1

    exp_fingers = sum(cell_finger_count(n, node_fanin.get(n.id, 0)) for n in logic_nodes)
    exp_nmos = exp_fingers
    exp_pmos = exp_fingers

    nmos_ok = lay_nmos == exp_nmos
    pmos_ok = lay_pmos == exp_pmos
    checks.append(LVSCheckItem("NMOS Transistors", str(exp_nmos), str(lay_nmos), nmos_ok))
    checks.append(LVSCheckItem("PMOS Transistors", str(exp_pmos), str(lay_pmos), pmos_ok))
    checks.append(LVSCheckItem("Total MOSFETs", str(exp_nmos + exp_pmos), str(lay_total), nmos_ok and pmos_ok))
    if not nmos_ok:
        mismatches.append(f"NMOS count mismatch: schematic expects {exp_nmos}, layout extracted {lay_nmos}.")
    if not pmos_ok:
        mismatches.append(f"PMOS count mismatch: schematic expects {exp_pmos}, layout extracted {lay_pmos}.")

    # 4. Port / Pin Matching (Schematic INPUT/OUTPUT pins vs Layout Labels)
    sch_ports = [
        n.label.split()[0]
        for n in netlist.nodes.values()
        if n.kind in ("INPUT", "OUTPUT")
    ]
    missing_ports = [p for p in sch_ports if p not in lay_labels and _base_port_name(p) not in lay_base_labels]
    ports_ok = len(missing_ports) == 0
    checks.append(
        LVSCheckItem(
            "I/O Pin Match",
            f"{len(sch_ports)} ports",
            f"{len(sch_ports) - len(missing_ports)}/{len(sch_ports)} matched",
            ports_ok,
            "" if ports_ok else f"Missing pins: {', '.join(missing_ports)}",
        )
    )
    if not ports_ok:
        mismatches.append(f"Unmatched I/O ports in layout: {', '.join(missing_ports)}")

    # 5. Net Connectivity Check
    sch_nets = len({e.src_id for e in netlist.edges})
    nets_ok = len(ext.nets) >= max(2, min(sch_nets, 2))
    checks.append(
        LVSCheckItem(
            "Electrical Nets",
            f"{sch_nets} routed",
            f"{len(ext.nets)} extracted",
            nets_ok,
        )
    )
    if not nets_ok:
        mismatches.append("Layout appears disconnected (too few electrical nets extracted).")

    return LVSReport(
        module_name=netlist.module_name,
        cell_name=cell.name,
        matched=(len(mismatches) == 0),
        checks=checks,
        mismatches=mismatches,
        extraction=ext,
    )

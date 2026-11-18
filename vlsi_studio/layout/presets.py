"""Built-in DRC-clean SCMOS sample layouts (CMOS Inverter & CMOS NAND2)."""

from .layers import LayoutCell, LayoutLabel, LayoutRect


def create_cmos_inverter() -> LayoutCell:
    """Create a DRC-clean CMOS Inverter layout in SCMOS lambda coordinates."""
    rects = [
        # N-Well for PMOS (top)
        LayoutRect("nwell", 0, 14, 24, 34),
        # VDD Metal1 rail
        LayoutRect("metal1", 0, 29, 24, 33),
        # GND Metal1 rail
        LayoutRect("metal1", 0, 1, 24, 5),
        # PMOS diffusion (top) & NMOS diffusion (bottom)
        LayoutRect("pdiff", 4, 19, 20, 26),
        LayoutRect("ndiff", 4, 8, 20, 13),
        # Shared Polysilicon gate (vertical)
        LayoutRect("poly", 11, 6, 13, 28),
        # Input Poly pad + contact + Metal1 input stub (shifted left for >=4λ M1 spacing)
        LayoutRect("poly", -3, 14, 11, 18),
        LayoutRect("contact", -2, 15, 0, 17),
        LayoutRect("metal1", -3, 14, 1, 18),
        # VDD contact to PMOS source (left)
        LayoutRect("metal1", 5, 21, 9, 29),
        LayoutRect("contact", 6, 22, 8, 24),
        # GND contact to NMOS source (left)
        LayoutRect("metal1", 5, 5, 9, 13),
        LayoutRect("contact", 6, 10, 8, 12),
        # Output Metal1 strap connecting PMOS & NMOS drains (right)
        LayoutRect("metal1", 15, 9, 19, 25),
        LayoutRect("contact", 16, 21, 18, 23),
        LayoutRect("contact", 16, 10, 18, 12),
    ]
    labels = [
        LayoutLabel("VDD", "metal1", 2, 31),
        LayoutLabel("GND", "metal1", 2, 3),
        LayoutLabel("IN", "metal1", -1, 17),
        LayoutLabel("OUT", "metal1", 17, 17),
    ]
    return LayoutCell(name="cmos_inverter", rects=rects, labels=labels)


def create_cmos_nand2() -> LayoutCell:
    """Create a DRC-clean 2-input CMOS NAND gate layout."""
    rects = [
        # N-Well
        LayoutRect("nwell", 0, 16, 32, 36),
        # Power rails
        LayoutRect("metal1", 0, 31, 32, 35),
        LayoutRect("metal1", 0, 1, 32, 5),
        # Diffusions
        LayoutRect("pdiff", 4, 20, 28, 28),
        LayoutRect("ndiff", 4, 8, 28, 14),
        # Two Polysilicon gates (A and B)
        LayoutRect("poly", 10, 6, 12, 30),
        LayoutRect("poly", 18, 6, 20, 30),
        # PMOS parallel VDD contacts (left & right)
        LayoutRect("metal1", 5, 23, 9, 31),
        LayoutRect("contact", 6, 24, 8, 26),
        LayoutRect("metal1", 23, 23, 27, 31),
        LayoutRect("contact", 24, 24, 26, 26),
        # NMOS series GND contact (left)
        LayoutRect("metal1", 5, 5, 9, 13),
        LayoutRect("contact", 6, 10, 8, 12),
        # Output Y strap (PMOS center drain -> NMOS right drain)
        LayoutRect("metal1", 13, 15, 17, 27),
        LayoutRect("contact", 14, 23, 16, 25),
        LayoutRect("metal1", 13, 15, 27, 19),
        LayoutRect("metal1", 23, 9, 27, 19),
        LayoutRect("contact", 24, 10, 26, 12),
    ]
    labels = [
        LayoutLabel("VDD", "metal1", 2, 33),
        LayoutLabel("GND", "metal1", 2, 3),
        LayoutLabel("A", "poly", 11, 18),
        LayoutLabel("B", "poly", 19, 18),
        LayoutLabel("Y", "metal1", 25, 17),
    ]
    return LayoutCell(name="cmos_nand2", rects=rects, labels=labels)

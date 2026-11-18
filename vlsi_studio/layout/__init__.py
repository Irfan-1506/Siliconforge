"""Magic-style 2D VLSI layout data model, DRC, SPICE extraction, and .mag I/O."""

from .drc import DRCViolation, run_drc
from .extractor import ExtractionResult, extract_netlist
from .layers import LAYER_MAP, LAYERS, LayerDef, LayoutCell, LayoutLabel, LayoutRect
from .lvs import LVSCheckItem, LVSReport, run_lvs
from .mag_io import load_mag, save_mag
from .pnr import generate_layout_from_netlist
from .presets import create_cmos_inverter, create_cmos_nand2

__all__ = [
    "DRCViolation",
    "run_drc",
    "ExtractionResult",
    "extract_netlist",
    "LAYER_MAP",
    "LAYERS",
    "LayerDef",
    "LayoutCell",
    "LayoutLabel",
    "LayoutRect",
    "LVSCheckItem",
    "LVSReport",
    "run_lvs",
    "load_mag",
    "save_mag",
    "generate_layout_from_netlist",
    "create_cmos_inverter",
    "create_cmos_nand2",
]

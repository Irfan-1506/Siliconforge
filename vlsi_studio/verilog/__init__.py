"""Self-contained Verilog parser and discrete-event simulator."""

from .parser import VerilogSyntaxError, parse_verilog
from .simulator import SimulationResult, VerilogSimulator, WaveTrace

__all__ = [
    "VerilogSyntaxError",
    "parse_verilog",
    "SimulationResult",
    "VerilogSimulator",
    "WaveTrace",
]

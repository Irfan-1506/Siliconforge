"""Project model and built-in educational VLSI design templates."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from vlsi_studio.layout.layers import LayoutCell
from vlsi_studio.layout.mag_io import load_mag, save_mag
from vlsi_studio.layout.presets import create_cmos_inverter, create_cmos_nand2

SAMPLE_FULL_ADDER_RTL = """\
// 1-bit Full Adder (RTL)
module full_adder (
    input  a,
    input  b,
    input  cin,
    output sum,
    output cout
);
    assign sum  = a ^ b ^ cin;
    assign cout = (a & b) | (cin & (a ^ b));
endmodule
"""

SAMPLE_FULL_ADDER_TB = """\
// Testbench for 1-bit Full Adder
module tb_full_adder;
    reg a, b, cin;
    wire sum, cout;

    full_adder dut (
        .a(a),
        .b(b),
        .cin(cin),
        .sum(sum),
        .cout(cout)
    );

    initial begin
        a = 0; b = 0; cin = 0;
        #10; a = 0; b = 0; cin = 1;
        $display("a=%b b=%b cin=%b -> sum=%b cout=%b", a, b, cin, sum, cout);
        #10; a = 0; b = 1; cin = 0;
        $display("a=%b b=%b cin=%b -> sum=%b cout=%b", a, b, cin, sum, cout);
        #10; a = 0; b = 1; cin = 1;
        $display("a=%b b=%b cin=%b -> sum=%b cout=%b", a, b, cin, sum, cout);
        #10; a = 1; b = 0; cin = 0;
        $display("a=%b b=%b cin=%b -> sum=%b cout=%b", a, b, cin, sum, cout);
        #10; a = 1; b = 1; cin = 1;
        $display("a=%b b=%b cin=%b -> sum=%b cout=%b", a, b, cin, sum, cout);
        #10;
        $finish;
    end
endmodule
"""

SAMPLE_COUNTER_RTL = """\
// 4-bit Synchronous Up-Counter with Active-High Reset
module counter4 (
    input        clk,
    input        rst,
    input        en,
    output reg [3:0] count
);
    always @(posedge clk) begin
        if (rst) begin
            count <= 4'd0;
        end else if (en) begin
            count <= count + 4'd1;
        end
    end
endmodule
"""

SAMPLE_COUNTER_TB = """\
// Testbench for 4-bit Counter
module tb_counter4;
    reg clk, rst, en;
    wire [3:0] count;

    counter4 dut (
        .clk(clk),
        .rst(rst),
        .en(en),
        .count(count)
    );

    initial begin
        clk = 0; rst = 1; en = 0;
        #5; clk = 1; #5; clk = 0;
        rst = 0; en = 1;
        repeat (10) begin
            #5; clk = 1;
            $display("t=%t count=%d (0x%h)", clk, count, count);
            #5; clk = 0;
        end
        $finish;
    end
endmodule
"""


@dataclass
class VLSIProject:
    name: str
    rtl_files: dict[str, str] = field(default_factory=dict)
    tb_files: dict[str, str] = field(default_factory=dict)
    layout: LayoutCell = field(default_factory=create_cmos_inverter)

    @classmethod
    def sample_full_adder(cls) -> VLSIProject:
        return cls(
            name="FullAdder_Demo",
            rtl_files={"full_adder.v": SAMPLE_FULL_ADDER_RTL},
            tb_files={"tb_full_adder.v": SAMPLE_FULL_ADDER_TB},
            layout=create_cmos_inverter(),
        )

    @classmethod
    def sample_counter(cls) -> VLSIProject:
        return cls(
            name="Counter4_Demo",
            rtl_files={"counter4.v": SAMPLE_COUNTER_RTL},
            tb_files={"tb_counter4.v": SAMPLE_COUNTER_TB},
            layout=create_cmos_nand2(),
        )

    @classmethod
    def sample_cpu4(cls) -> VLSIProject:
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        base = root / "examples" / "cpu4"
        rtl = (base / "cpu4.v").read_text(encoding="utf-8")
        tb = (base / "tb_cpu4.v").read_text(encoding="utf-8")
        mag_path = base / "cpu4.mag"
        layout = load_mag(mag_path.read_text(encoding="utf-8"), "cpu4") if mag_path.exists() else create_cmos_nand2()
        return cls(
            name="CPU4_Demo",
            rtl_files={"cpu4.v": rtl},
            tb_files={"tb_cpu4.v": tb},
            layout=layout,
        )

    def save_to_file(self, path: str | Path) -> None:
        data = {
            "name": self.name,
            "rtl_files": self.rtl_files,
            "tb_files": self.tb_files,
            "layout_name": self.layout.name,
            "layout_mag": save_mag(self.layout),
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load_from_file(cls, path: str | Path) -> VLSIProject:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        layout = load_mag(data.get("layout_mag", ""), data.get("layout_name", "cell"))
        return cls(
            name=data.get("name", "VLSI_Project"),
            rtl_files=data.get("rtl_files", {}),
            tb_files=data.get("tb_files", {}),
            layout=layout,
        )

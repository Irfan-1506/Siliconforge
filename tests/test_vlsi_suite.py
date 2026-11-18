"""End-to-end tests for Verilog simulation, RTL synthesis, and Magic layout/DRC/extraction."""

from vlsi_studio.layout import (
    LayoutCell,
    LayoutLabel,
    LayoutRect,
    create_cmos_inverter,
    create_cmos_nand2,
    extract_netlist,
    generate_layout_from_netlist,
    load_mag,
    run_drc,
    run_lvs,
    save_mag,
)
from vlsi_studio.models import VLSIProject
from vlsi_studio.synth import synthesize_module
from vlsi_studio.verilog import VerilogSimulator, VerilogSyntaxError, parse_verilog


def test_full_adder_simulation_and_vcd():
    proj = VLSIProject.sample_full_adder()
    src = "\n".join(list(proj.rtl_files.values()) + list(proj.tb_files.values()))
    modules = parse_verilog(src)
    res = VerilogSimulator(modules).run()

    assert res.top_module == "tb_full_adder"
    assert res.end_time >= 50
    joined = "\n".join(res.console_output)
    assert "a=0 b=0 cin=1 -> sum=1 cout=0" in joined
    assert "a=1 b=1 cin=1 -> sum=1 cout=1" in joined

    vcd = res.trace.to_vcd()
    assert "$timescale 1ns $end" in vcd
    assert "$var wire" in vcd


def test_counter4_simulation():
    proj = VLSIProject.sample_counter()
    src = "\n".join(list(proj.rtl_files.values()) + list(proj.tb_files.values()))
    modules = parse_verilog(src)
    res = VerilogSimulator(modules).run()

    assert res.top_module == "tb_counter4"
    count_sig = res.trace.signals["tb_counter4.dut.count"]
    final_val = count_sig.transitions[-1][1]
    assert final_val == 10


def test_synthesis_full_adder_and_counter():
    fa_mods = parse_verilog(VLSIProject.sample_full_adder().rtl_files["full_adder.v"])
    fa_net = synthesize_module(fa_mods[0])
    assert fa_net.report.inputs == 3
    assert fa_net.report.outputs == 2
    assert fa_net.report.luts_and_gates >= 4

    cnt_mods = parse_verilog(VLSIProject.sample_counter().rtl_files["counter4.v"])
    cnt_net = synthesize_module(cnt_mods[0])
    assert cnt_net.report.flip_flops == 4
    assert cnt_net.report.adders >= 1


def test_magic_presets_drc_clean_and_extract():
    inv = create_cmos_inverter()
    assert run_drc(inv) == []
    inv_ext = extract_netlist(inv)
    types = sorted(m.mos_type for m in inv_ext.mosfets)
    assert types == ["nmos", "pmos"]
    assert ".subckt cmos_inverter" in inv_ext.spice_text

    nand2 = create_cmos_nand2()
    assert run_drc(nand2) == []
    nand_ext = extract_netlist(nand2)
    assert sorted(m.mos_type for m in nand_ext.mosfets) == ["nmos", "nmos", "pmos", "pmos"]


def test_drc_detects_width_and_enclosure_errors():
    bad = LayoutCell(
        name="bad_cell",
        rects=[
            LayoutRect("poly", 0, 0, 1, 5),     # width 1 < 2λ
            LayoutRect("contact", 10, 10, 12, 12),  # unenclosed contact
        ],
    )
    violations = run_drc(bad)
    rules = {v.rule for v in violations}
    assert "MIN_WIDTH" in rules
    assert "CONTACT_M1_ENC" in rules
    assert "CONTACT_ACTIVE_ENC" in rules


def test_mag_roundtrip():
    inv = create_cmos_inverter()
    mag_text = save_mag(inv)
    reloaded = load_mag(mag_text, "cmos_inverter")
    assert len(reloaded.rects) == len(inv.rects)
    assert len(reloaded.labels) == len(inv.labels)


def test_case_statement_simulation_and_synthesis():
    src = """
    module mux4(input [1:0] sel, input [3:0] d, output reg y);
        always @(*) begin
            case (sel)
                2'd0: y = d[0];
                2'd1: y = d[1];
                2'd2: y = d[2];
                default: y = d[3];
            endcase
        end
    endmodule
    module tb_mux4;
        reg [1:0] sel; reg [3:0] d; wire y;
        mux4 dut(.sel(sel), .d(d), .y(y));
        initial begin
            d = 4'b1010; sel = 2'd0; #10;
            sel = 2'd1; #10;
            sel = 2'd3; #10;
            $finish;
        end
    endmodule
    """
    mods = parse_verilog(src)
    res = VerilogSimulator(mods).run()
    assert res.top_module == "tb_mux4"
    y_sig = res.trace.signals["tb_mux4.dut.y"]
    assert y_sig.transitions[-1][1] == 1  # d[3] == 1

    net = synthesize_module(mods[0])
    assert net.report.inputs == 6
    assert net.report.outputs == 1


def test_modern_verilog_constructs_and_auto_stimulus():
    src = """`timescale 1ns/1ps
`define WIDTH 4
(* keep = "true" *)
module alu_sv #(parameter W = `WIDTH) (
    input  logic signed [W-1:0] a, b,
    input  logic                op,
    output logic        [W-1:0] y,
    output logic                cout
);
    always_comb begin : comb_blk
        if (op)
            {cout, y} = {1'b0, a} + {1'b0, b};
        else
            {cout, y} = {1'b0, {4{a[0]}} ^ b};
    end : comb_blk
endmodule

module tb_alu_sv;
    reg [3:0] a, b;
    reg op;
    wire [3:0] y;
    wire cout;
    integer i;
    reg clk = 0;

    alu_sv dut(.a(a), .b(b), .op(op), .y(y), .cout(cout));

    always #5 clk = ~clk;

    initial begin
        $dumpfile("alu.vcd");
        $dumpvars(0, tb_alu_sv);
        op = 1; a = 4'd3; b = 4'd5;
        for (i = 0; i < 2; i++) begin
            #10;
            a = a + 4'd1;
        end
        $display("t=%t y=%d cout=%b", $time, y, cout);
        $finish;
    end
endmodule
"""
    mods = parse_verilog(src)
    assert len(mods) == 2

    res = VerilogSimulator(mods).run()
    assert res.top_module == "tb_alu_sv"
    assert any("y=10 cout=0" in line for line in res.console_output)

    # Also verify standalone design simulation (no testbench) auto-generates stimulus
    standalone_res = VerilogSimulator([mods[0]]).run(top_module="alu_sv")
    assert standalone_res.end_time > 0
    assert synthesize_module(mods[0]).report.outputs == 5


def test_syntax_error_line_numbers_preserved():
    src = "\n\n`timescale 1ns/1ps\n// comment\nmodule bad(\n    input a,\n    output y\n);\n    assign y = a @ b;\nendmodule\n"
    try:
        parse_verilog(src)
        assert False, "Expected VerilogSyntaxError"
    except VerilogSyntaxError as exc:
        assert exc.line == 9


def test_auto_pnr_layout_generation_drc_clean():
    for proj in (VLSIProject.sample_full_adder(), VLSIProject.sample_counter(), VLSIProject.sample_cpu4()):
        rtl = "\n".join(proj.rtl_files.values())
        mod = parse_verilog(rtl)[0]
        net = synthesize_module(mod)
        cell = generate_layout_from_netlist(net)
        assert run_drc(cell) == []
        ext = extract_netlist(cell)
        assert len(ext.mosfets) >= 2
        lvs = run_lvs(net, cell)
        assert lvs.matched, lvs.mismatches


def test_lvs_detects_short_and_mismatch():
    mod = parse_verilog(VLSIProject.sample_full_adder().rtl_files["full_adder.v"])[0]
    net = synthesize_module(mod)
    cell = generate_layout_from_netlist(net)

    # Inject a VDD-to-GND metal1 short
    cell.rects.append(LayoutRect("metal1", 0, 1, 4, cell.rects[1].y2))
    lvs_short = run_lvs(net, cell)
    assert not lvs_short.matched
    assert any("short" in m.lower() for m in lvs_short.mismatches)

    # Standalone preset passes complementary CMOS LVS
    assert run_lvs(None, create_cmos_inverter()).matched
    assert run_lvs(None, create_cmos_nand2()).matched

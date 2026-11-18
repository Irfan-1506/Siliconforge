// Testbench with combinational Instruction ROM for 4-bit CPU
module tb_cpu4;
    reg        clk;
    reg        rst;
    reg  [7:0] instr;
    wire [3:0] pc;
    wire [3:0] acc;
    wire       zero;
    wire       halted;

    cpu4 dut (
        .clk(clk),
        .rst(rst),
        .instr(instr),
        .pc(pc),
        .acc(acc),
        .zero(zero),
        .halted(halted)
    );

    // Program ROM
    always @(*) begin
        if (pc == 4'd0)      instr = 8'h15; // LDI 5  -> acc = 5
        else if (pc == 4'd1) instr = 8'h23; // ADD 3  -> acc = 8
        else if (pc == 4'd2) instr = 8'h32; // SUB 2  -> acc = 6
        else if (pc == 4'd3) instr = 8'h4C; // AND 12 -> acc = 4
        else if (pc == 4'd4) instr = 8'h51; // OR  1  -> acc = 5
        else if (pc == 4'd5) instr = 8'hF0; // HLT
        else                 instr = 8'h00; // NOP
    end

    initial begin
        clk = 0; rst = 1;
        #5; clk = 1; #5; clk = 0;
        rst = 0;

        repeat (8) begin
            #5; clk = 1;
            #5; clk = 0;
            $display("pc=%d acc=%d (0x%h) zero=%b halted=%b", pc, acc, acc, zero, halted);
        end
        $finish;
    end
endmodule

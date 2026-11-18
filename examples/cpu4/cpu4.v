// 4-bit Accumulator CPU (compatible with SiliconForge VLSI Studio, ModelSim & Vivado)
module cpu4 (
    input            clk,
    input            rst,
    input      [7:0] instr,
    output reg [3:0] pc,
    output reg [3:0] acc,
    output           zero,
    output reg       halted
);
    wire [3:0] opcode;
    wire [3:0] imm;

    assign opcode = instr[7:4];
    assign imm    = instr[3:0];
    assign zero   = (acc == 4'd0);

    always @(posedge clk) begin
        if (rst) begin
            pc     <= 4'd0;
            acc    <= 4'd0;
            halted <= 1'b0;
        end else if (!halted) begin
            if (opcode == 4'h0) begin
                // NOP
                pc <= pc + 4'd1;
            end else if (opcode == 4'h1) begin
                // LDI imm: acc = imm
                acc <= imm;
                pc  <= pc + 4'd1;
            end else if (opcode == 4'h2) begin
                // ADD imm: acc = acc + imm
                acc <= acc + imm;
                pc  <= pc + 4'd1;
            end else if (opcode == 4'h3) begin
                // SUB imm: acc = acc - imm
                acc <= acc - imm;
                pc  <= pc + 4'd1;
            end else if (opcode == 4'h4) begin
                // AND imm: acc = acc & imm
                acc <= acc & imm;
                pc  <= pc + 4'd1;
            end else if (opcode == 4'h5) begin
                // OR imm: acc = acc | imm
                acc <= acc | imm;
                pc  <= pc + 4'd1;
            end else if (opcode == 4'h6) begin
                // XOR imm: acc = acc ^ imm
                acc <= acc ^ imm;
                pc  <= pc + 4'd1;
            end else if (opcode == 4'h7) begin
                // JMP addr
                pc <= imm;
            end else if (opcode == 4'h8) begin
                // JZ addr
                if (acc == 4'd0)
                    pc <= imm;
                else
                    pc <= pc + 4'd1;
            end else if (opcode == 4'hF) begin
                // HLT
                halted <= 1'b1;
            end else begin
                pc <= pc + 4'd1;
            end
        end
    end
endmodule

module regfile (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        wb_we,
    input  logic [4:0]  wb_rd,
    input  logic [31:0] wb_wdata,
    input  logic [4:0]  rs1_addr,
    output logic [31:0] rs1_data,
    input  logic [4:0]  rs2_addr,
    output logic [31:0] rs2_data,
    input  logic [4:0]  dbg_addr,
    output logic [31:0] dbg_data,
    output logic [31:0] x10_value
);

    logic [31:0] regs [1:31];

    integer i;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (i = 1; i < 32; i = i + 1) begin
                regs[i] <= 32'b0;
            end
        end else if (wb_we && (wb_rd != 5'd0)) begin
            regs[wb_rd] <= wb_wdata;
        end
    end

    always_comb begin
        if (rs1_addr == 5'd0) begin
            rs1_data = 32'b0;
        end else if (wb_we && (wb_rd != 5'd0) && (wb_rd == rs1_addr)) begin
            rs1_data = wb_wdata;
        end else begin
            rs1_data = regs[rs1_addr];
        end
    end

    always_comb begin
        if (rs2_addr == 5'd0) begin
            rs2_data = 32'b0;
        end else if (wb_we && (wb_rd != 5'd0) && (wb_rd == rs2_addr)) begin
            rs2_data = wb_wdata;
        end else begin
            rs2_data = regs[rs2_addr];
        end
    end

    always_comb begin
        if (dbg_addr == 5'd0) begin
            dbg_data = 32'b0;
        end else if (wb_we && (wb_rd != 5'd0) && (wb_rd == dbg_addr)) begin
            dbg_data = wb_wdata;
        end else begin
            dbg_data = regs[dbg_addr];
        end
    end

    always_comb begin
        if (wb_we && (wb_rd == 5'd10)) begin
            x10_value = wb_wdata;
        end else begin
            x10_value = regs[10];
        end
    end

endmodule

module if_stage (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        halt,
    input  logic        stall,
    input  logic        redirect,
    input  logic [31:0] redirect_pc,
    output logic [31:0] imem_addr,
    input  logic [31:0] imem_rdata,
    output logic        if_valid,
    output logic [31:0] if_pc,
    output logic [31:0] if_pc_plus4,
    output logic [31:0] if_instr
);

    logic [31:0] pc;
    logic [31:0] pc_plus4;
    logic        if_valid_r;
    logic [31:0] if_pc_r;
    logic [31:0] if_pc_plus4_r;
    logic [31:0] if_instr_r;

    assign imem_addr = pc;

    assign pc_plus4 = pc + 32'd4;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            pc            <= 32'd0;
            if_valid_r    <= 1'b0;
            if_pc_r       <= 32'd0;
            if_pc_plus4_r <= 32'd0;
            if_instr_r    <= 32'd0;
        end else if (halt) begin
            pc            <= pc;
            if_valid_r    <= if_valid_r;
            if_pc_r       <= if_pc_r;
            if_pc_plus4_r <= if_pc_plus4_r;
            if_instr_r    <= if_instr_r;
        end else if (redirect) begin
            pc            <= redirect_pc;
            if_valid_r    <= 1'b0;
            if_pc_r       <= 32'd0;
            if_pc_plus4_r <= 32'd0;
            if_instr_r    <= 32'd0;
        end else if (stall) begin
            pc            <= pc;
            if_valid_r    <= if_valid_r;
            if_pc_r       <= if_pc_r;
            if_pc_plus4_r <= if_pc_plus4_r;
            if_instr_r    <= if_instr_r;
        end else begin
            pc            <= pc_plus4;
            if_valid_r    <= 1'b1;
            if_pc_r       <= pc;
            if_pc_plus4_r <= pc_plus4;
            if_instr_r    <= imem_rdata;
        end
    end

    assign if_valid    = if_valid_r;
    assign if_pc       = if_pc_r;
    assign if_pc_plus4 = if_pc_plus4_r;
    assign if_instr    = if_instr_r;

endmodule

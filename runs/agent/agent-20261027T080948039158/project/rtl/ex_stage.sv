module ex_stage (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        halt,
    input  logic        flush,
    input  logic        id_valid,
    input  logic [31:0] id_pc,
    input  logic [31:0] id_pc_plus4,
    input  logic [31:0] id_rs1_data,
    input  logic [31:0] id_rs2_data,
    input  logic [4:0]  id_rs1_addr,
    input  logic [4:0]  id_rs2_addr,
    input  logic [31:0] id_imm,
    input  logic [4:0]  id_rd,
    input  logic [3:0]  id_alu_op,
    input  logic        id_alu_a_sel,
    input  logic        id_alu_b_sel,
    input  logic        id_reg_write,
    input  logic        id_is_load,
    input  logic        id_is_store,
    input  logic        id_mem_to_reg,
    input  logic [2:0]  id_br_op,
    input  logic        id_is_branch,
    input  logic        id_is_jal,
    input  logic        id_is_jalr,
    input  logic        id_is_ecall,
    input  logic [2:0]  id_funct3,
    input  logic [1:0]  fwd_a,
    input  logic [1:0]  fwd_b,
    input  logic [31:0] ex_mem_alu_result,
    input  logic [31:0] mem_wb_wdata,
    output logic [4:0]  id_ex_rs1_addr,
    output logic [4:0]  id_ex_rs2_addr,
    output logic        ex_redirect,
    output logic [31:0] ex_redirect_pc,
    output logic        ex_valid,
    output logic [31:0] ex_pc_plus4,
    output logic [31:0] ex_alu_result,
    output logic [31:0] ex_store_data,
    output logic [4:0]  ex_rd,
    output logic        ex_reg_write,
    output logic        ex_is_load,
    output logic        ex_is_store,
    output logic        ex_mem_to_reg,
    output logic [2:0]  ex_funct3,
    output logic        ex_is_ecall
);

    localparam logic [3:0] ALU_ADD  = 4'd0;
    localparam logic [3:0] ALU_SUB  = 4'd1;
    localparam logic [3:0] ALU_SLL  = 4'd2;
    localparam logic [3:0] ALU_SLT  = 4'd3;
    localparam logic [3:0] ALU_SLTU = 4'd4;
    localparam logic [3:0] ALU_XOR  = 4'd5;
    localparam logic [3:0] ALU_SRL  = 4'd6;
    localparam logic [3:0] ALU_SRA  = 4'd7;
    localparam logic [3:0] ALU_OR   = 4'd8;
    localparam logic [3:0] ALU_AND  = 4'd9;
    localparam logic [3:0] ALU_PASSB= 4'd10;

    localparam logic [2:0] BR_BEQ  = 3'd0;
    localparam logic [2:0] BR_BNE  = 3'd1;
    localparam logic [2:0] BR_BLT  = 3'd2;
    localparam logic [2:0] BR_BGE  = 3'd3;
    localparam logic [2:0] BR_BLTU = 3'd4;
    localparam logic [2:0] BR_BGEU = 3'd5;

    logic        id_ex_valid;
    logic [31:0] id_ex_pc;
    logic [31:0] id_ex_pc_plus4;
    logic [31:0] id_ex_rs1_data;
    logic [31:0] id_ex_rs2_data;
    logic [31:0] id_ex_imm;
    logic [4:0]  id_ex_rd;
    logic [3:0]  id_ex_alu_op;
    logic        id_ex_alu_a_sel;
    logic        id_ex_alu_b_sel;
    logic        id_ex_reg_write;
    logic        id_ex_is_load;
    logic        id_ex_is_store;
    logic        id_ex_mem_to_reg;
    logic [2:0]  id_ex_br_op;
    logic        id_ex_is_branch;
    logic        id_ex_is_jal;
    logic        id_ex_is_jalr;
    logic        id_ex_is_ecall;
    logic [2:0]  id_ex_funct3;

    logic [31:0] rs1_fwd;
    logic [31:0] rs2_fwd;
    logic [31:0] alu_a;
    logic [31:0] alu_b;
    logic [31:0] alu_result;
    logic [31:0] branch_target;
    logic [31:0] jalr_target;
    logic        branch_taken;
    logic        redirect;
    logic [31:0] redirect_pc;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            id_ex_valid       <= 1'b0;
            id_ex_pc          <= 32'b0;
            id_ex_pc_plus4    <= 32'b0;
            id_ex_rs1_data    <= 32'b0;
            id_ex_rs2_data    <= 32'b0;
            id_ex_rs1_addr    <= 5'b0;
            id_ex_rs2_addr    <= 5'b0;
            id_ex_imm         <= 32'b0;
            id_ex_rd          <= 5'b0;
            id_ex_alu_op      <= 4'b0;
            id_ex_alu_a_sel   <= 1'b0;
            id_ex_alu_b_sel   <= 1'b0;
            id_ex_reg_write   <= 1'b0;
            id_ex_is_load     <= 1'b0;
            id_ex_is_store    <= 1'b0;
            id_ex_mem_to_reg  <= 1'b0;
            id_ex_br_op       <= 3'b0;
            id_ex_is_branch   <= 1'b0;
            id_ex_is_jal      <= 1'b0;
            id_ex_is_jalr     <= 1'b0;
            id_ex_is_ecall    <= 1'b0;
            id_ex_funct3      <= 3'b0;
        end else if (halt) begin
            id_ex_valid       <= id_ex_valid;
            id_ex_pc          <= id_ex_pc;
            id_ex_pc_plus4    <= id_ex_pc_plus4;
            id_ex_rs1_data    <= id_ex_rs1_data;
            id_ex_rs2_data    <= id_ex_rs2_data;
            id_ex_rs1_addr    <= id_ex_rs1_addr;
            id_ex_rs2_addr    <= id_ex_rs2_addr;
            id_ex_imm         <= id_ex_imm;
            id_ex_rd          <= id_ex_rd;
            id_ex_alu_op      <= id_ex_alu_op;
            id_ex_alu_a_sel   <= id_ex_alu_a_sel;
            id_ex_alu_b_sel   <= id_ex_alu_b_sel;
            id_ex_reg_write   <= id_ex_reg_write;
            id_ex_is_load     <= id_ex_is_load;
            id_ex_is_store    <= id_ex_is_store;
            id_ex_mem_to_reg  <= id_ex_mem_to_reg;
            id_ex_br_op       <= id_ex_br_op;
            id_ex_is_branch   <= id_ex_is_branch;
            id_ex_is_jal      <= id_ex_is_jal;
            id_ex_is_jalr     <= id_ex_is_jalr;
            id_ex_is_ecall    <= id_ex_is_ecall;
            id_ex_funct3      <= id_ex_funct3;
        end else if (flush) begin
            id_ex_valid       <= 1'b0;
            id_ex_pc          <= 32'b0;
            id_ex_pc_plus4    <= 32'b0;
            id_ex_rs1_data    <= 32'b0;
            id_ex_rs2_data    <= 32'b0;
            id_ex_rs1_addr    <= 5'b0;
            id_ex_rs2_addr    <= 5'b0;
            id_ex_imm         <= 32'b0;
            id_ex_rd          <= 5'b0;
            id_ex_alu_op      <= 4'b0;
            id_ex_alu_a_sel   <= 1'b0;
            id_ex_alu_b_sel   <= 1'b0;
            id_ex_reg_write   <= 1'b0;
            id_ex_is_load     <= 1'b0;
            id_ex_is_store    <= 1'b0;
            id_ex_mem_to_reg  <= 1'b0;
            id_ex_br_op       <= 3'b0;
            id_ex_is_branch   <= 1'b0;
            id_ex_is_jal      <= 1'b0;
            id_ex_is_jalr     <= 1'b0;
            id_ex_is_ecall    <= 1'b0;
            id_ex_funct3      <= 3'b0;
        end else begin
            id_ex_valid       <= id_valid;
            id_ex_pc          <= id_pc;
            id_ex_pc_plus4    <= id_pc_plus4;
            id_ex_rs1_data    <= id_rs1_data;
            id_ex_rs2_data    <= id_rs2_data;
            id_ex_rs1_addr    <= id_rs1_addr;
            id_ex_rs2_addr    <= id_rs2_addr;
            id_ex_imm         <= id_imm;
            id_ex_rd          <= id_rd;
            id_ex_alu_op      <= id_alu_op;
            id_ex_alu_a_sel   <= id_alu_a_sel;
            id_ex_alu_b_sel   <= id_alu_b_sel;
            id_ex_reg_write   <= id_reg_write;
            id_ex_is_load     <= id_is_load;
            id_ex_is_store    <= id_is_store;
            id_ex_mem_to_reg  <= id_mem_to_reg;
            id_ex_br_op       <= id_br_op;
            id_ex_is_branch   <= id_is_branch;
            id_ex_is_jal      <= id_is_jal;
            id_ex_is_jalr     <= id_is_jalr;
            id_ex_is_ecall    <= id_is_ecall;
            id_ex_funct3      <= id_funct3;
        end
    end

    always_comb begin
        rs1_fwd = id_ex_rs1_data;
        if (fwd_a == 2'b01)
            rs1_fwd = ex_mem_alu_result;
        else if (fwd_a == 2'b10)
            rs1_fwd = mem_wb_wdata;

        rs2_fwd = id_ex_rs2_data;
        if (fwd_b == 2'b01)
            rs2_fwd = ex_mem_alu_result;
        else if (fwd_b == 2'b10)
            rs2_fwd = mem_wb_wdata;
    end

    always_comb begin
        alu_a = id_ex_alu_a_sel ? id_ex_pc : rs1_fwd;
        alu_b = id_ex_alu_b_sel ? id_ex_imm : rs2_fwd;
    end

    always_comb begin
        alu_result = 32'b0;
        case (id_ex_alu_op)
            ALU_ADD:   alu_result = alu_a + alu_b;
            ALU_SUB:   alu_result = alu_a - alu_b;
            ALU_SLL:   alu_result = alu_a << alu_b[4:0];
            ALU_SLT:   alu_result = ($signed(alu_a) < $signed(alu_b)) ? 32'd1 : 32'd0;
            ALU_SLTU:  alu_result = (alu_a < alu_b) ? 32'd1 : 32'd0;
            ALU_XOR:   alu_result = alu_a ^ alu_b;
            ALU_SRL:   alu_result = alu_a >> alu_b[4:0];
            ALU_SRA:   alu_result = $signed(alu_a) >>> alu_b[4:0];
            ALU_OR:    alu_result = alu_a | alu_b;
            ALU_AND:   alu_result = alu_a & alu_b;
            ALU_PASSB: alu_result = alu_b;
            default:   alu_result = 32'b0;
        endcase
    end

    always_comb begin
        branch_taken = 1'b0;
        case (id_ex_br_op)
            BR_BEQ:  branch_taken = (rs1_fwd == rs2_fwd);
            BR_BNE:  branch_taken = (rs1_fwd != rs2_fwd);
            BR_BLT:  branch_taken = ($signed(rs1_fwd) < $signed(rs2_fwd));
            BR_BGE:  branch_taken = ($signed(rs1_fwd) >= $signed(rs2_fwd));
            BR_BLTU: branch_taken = (rs1_fwd < rs2_fwd);
            BR_BGEU: branch_taken = (rs1_fwd >= rs2_fwd);
            default: branch_taken = 1'b0;
        endcase
    end

    always_comb begin
        branch_target = id_ex_pc + id_ex_imm;
        jalr_target   = (rs1_fwd + id_ex_imm) & 32'hFFFF_FFFE;

        redirect    = 1'b0;
        redirect_pc = 32'b0;

        if (id_ex_valid) begin
            if (id_ex_is_jal) begin
                redirect    = 1'b1;
                redirect_pc = branch_target;
            end else if (id_ex_is_jalr) begin
                redirect    = 1'b1;
                redirect_pc = jalr_target;
            end else if (id_ex_is_branch && branch_taken) begin
                redirect    = 1'b1;
                redirect_pc = branch_target;
            end
        end
    end

    assign ex_redirect    = redirect;
    assign ex_redirect_pc = redirect_pc;

    assign ex_valid       = id_ex_valid;
    assign ex_pc_plus4    = id_ex_pc_plus4;
    assign ex_alu_result  = (id_ex_is_jal || id_ex_is_jalr) ? id_ex_pc_plus4 : alu_result;
    assign ex_store_data  = rs2_fwd;
    assign ex_rd          = id_ex_rd;
    assign ex_reg_write   = id_ex_reg_write;
    assign ex_is_load     = id_ex_is_load;
    assign ex_is_store    = id_ex_is_store;
    assign ex_mem_to_reg  = id_ex_mem_to_reg;
    assign ex_funct3      = id_ex_funct3;
    assign ex_is_ecall    = id_ex_is_ecall;

endmodule

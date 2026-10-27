// file: rtl/rv32i5.sv
module rv32i5 (
    input  logic        clk,
    input  logic        rst_n,
    output logic [31:0] imem_addr,
    input  logic [31:0] imem_rdata,
    output logic        dmem_valid,
    output logic        dmem_we,
    output logic [31:0] dmem_addr,
    output logic [31:0] dmem_wdata,
    output logic [3:0]  dmem_be,
    input  logic [31:0] dmem_rdata,
    input  logic [4:0]  dbg_reg_addr,
    output logic [31:0] dbg_reg_data,
    output logic        halted,
    output logic [31:0] exit_code
);

    // IF stage outputs
    logic        if_valid;
    logic [31:0] if_pc;
    logic [31:0] if_pc_plus4;
    logic [31:0] if_instr;

    // ID stage outputs
    logic [4:0]  rs1_addr;
    logic [4:0]  rs2_addr;
    logic [31:0] rs1_data;
    logic [31:0] rs2_data;
    logic        id_valid;
    logic [31:0] id_pc;
    logic [31:0] id_pc_plus4;
    logic [31:0] id_rs1_data;
    logic [31:0] id_rs2_data;
    logic [4:0]  id_rs1_addr;
    logic [4:0]  id_rs2_addr;
    logic [31:0] id_imm;
    logic [4:0]  id_rd;
    logic [3:0]  id_alu_op;
    logic        id_alu_a_sel;
    logic        id_alu_b_sel;
    logic        id_reg_write;
    logic        id_is_load;
    logic        id_is_store;
    logic        id_mem_to_reg;
    logic [2:0]  id_br_op;
    logic        id_is_branch;
    logic        id_is_jal;
    logic        id_is_jalr;
    logic        id_is_ecall;
    logic [2:0]  id_funct3;
    logic        id_uses_rs1;
    logic        id_uses_rs2;

    // EX stage outputs
    logic [4:0]  id_ex_rs1_addr;
    logic [4:0]  id_ex_rs2_addr;
    logic        ex_redirect;
    logic [31:0] ex_redirect_pc;
    logic        ex_valid;
    logic [31:0] ex_pc_plus4;
    logic [31:0] ex_alu_result;
    logic [31:0] ex_store_data;
    logic [4:0]  ex_rd;
    logic        ex_reg_write;
    logic        ex_is_load;
    logic        ex_is_store;
    logic        ex_mem_to_reg;
    logic [2:0]  ex_funct3;
    logic        ex_is_ecall;

    // MEM stage outputs
    logic        ex_mem_valid;
    logic [31:0] ex_mem_alu_result;
    logic        ex_mem_reg_write;
    logic [4:0]  ex_mem_rd;
    logic        ex_mem_is_load;
    logic        mem_valid;
    logic [31:0] mem_wdata;
    logic [4:0]  mem_rd;
    logic        mem_reg_write;
    logic        mem_is_ecall;

    // WB stage outputs
    logic        mem_wb_valid;
    logic        mem_wb_reg_write;
    logic [4:0]  mem_wb_rd;
    logic [31:0] mem_wb_wdata;
    logic        wb_we;
    logic [4:0]  wb_rd;
    logic [31:0] wb_wdata;

    // Hazard unit outputs
    logic        stall_pc;
    logic        flush_if_id;
    logic        flush_id_ex;
    logic        halt_pending;

    // Forwarding unit outputs
    logic [1:0]  fwd_a;
    logic [1:0]  fwd_b;

    // Register file x10
    logic [31:0] x10_value;

    // Internal dmem signals from mem_stage
    logic        dmem_valid_i;
    logic        dmem_we_i;

    // Top-level combinational masking of dmem outputs
    assign dmem_valid = dmem_valid_i & rst_n & ~halted;
    assign dmem_we    = dmem_we_i    & rst_n & ~halted;

    if_stage u_if (
        .clk          (clk),
        .rst_n        (rst_n),
        .halt         (halted),
        .stall        (stall_pc),
        .redirect     (ex_redirect),
        .redirect_pc  (ex_redirect_pc),
        .imem_addr    (imem_addr),
        .imem_rdata   (imem_rdata),
        .if_valid     (if_valid),
        .if_pc        (if_pc),
        .if_pc_plus4  (if_pc_plus4),
        .if_instr     (if_instr)
    );

    id_stage u_id (
        .clk          (clk),
        .rst_n        (rst_n),
        .halt         (halted),
        .flush        (flush_if_id),
        .stall        (stall_pc),
        .if_valid     (if_valid),
        .if_pc        (if_pc),
        .if_pc_plus4  (if_pc_plus4),
        .if_instr     (if_instr),
        .rs1_data     (rs1_data),
        .rs2_data     (rs2_data),
        .rs1_addr     (rs1_addr),
        .rs2_addr     (rs2_addr),
        .id_valid     (id_valid),
        .id_pc        (id_pc),
        .id_pc_plus4  (id_pc_plus4),
        .id_rs1_data  (id_rs1_data),
        .id_rs2_data  (id_rs2_data),
        .id_rs1_addr  (id_rs1_addr),
        .id_rs2_addr  (id_rs2_addr),
        .id_imm       (id_imm),
        .id_rd        (id_rd),
        .id_alu_op    (id_alu_op),
        .id_alu_a_sel (id_alu_a_sel),
        .id_alu_b_sel (id_alu_b_sel),
        .id_reg_write (id_reg_write),
        .id_is_load   (id_is_load),
        .id_is_store  (id_is_store),
        .id_mem_to_reg(id_mem_to_reg),
        .id_br_op     (id_br_op),
        .id_is_branch (id_is_branch),
        .id_is_jal    (id_is_jal),
        .id_is_jalr   (id_is_jalr),
        .id_is_ecall  (id_is_ecall),
        .id_funct3    (id_funct3),
        .id_uses_rs1  (id_uses_rs1),
        .id_uses_rs2  (id_uses_rs2)
    );

    ex_stage u_ex (
        .clk             (clk),
        .rst_n           (rst_n),
        .halt            (halted),
        .flush           (flush_id_ex),
        .id_valid        (id_valid),
        .id_pc           (id_pc),
        .id_pc_plus4     (id_pc_plus4),
        .id_rs1_data     (id_rs1_data),
        .id_rs2_data     (id_rs2_data),
        .id_rs1_addr     (id_rs1_addr),
        .id_rs2_addr     (id_rs2_addr),
        .id_imm          (id_imm),
        .id_rd           (id_rd),
        .id_alu_op       (id_alu_op),
        .id_alu_a_sel    (id_alu_a_sel),
        .id_alu_b_sel    (id_alu_b_sel),
        .id_reg_write    (id_reg_write),
        .id_is_load      (id_is_load),
        .id_is_store     (id_is_store),
        .id_mem_to_reg   (id_mem_to_reg),
        .id_br_op        (id_br_op),
        .id_is_branch    (id_is_branch),
        .id_is_jal       (id_is_jal),
        .id_is_jalr      (id_is_jalr),
        .id_is_ecall     (id_is_ecall),
        .id_funct3       (id_funct3),
        .fwd_a           (fwd_a),
        .fwd_b           (fwd_b),
        .ex_mem_alu_result(ex_mem_alu_result),
        .mem_wb_wdata    (mem_wb_wdata),
        .id_ex_rs1_addr  (id_ex_rs1_addr),
        .id_ex_rs2_addr  (id_ex_rs2_addr),
        .ex_redirect     (ex_redirect),
        .ex_redirect_pc  (ex_redirect_pc),
        .ex_valid        (ex_valid),
        .ex_pc_plus4     (ex_pc_plus4),
        .ex_alu_result   (ex_alu_result),
        .ex_store_data   (ex_store_data),
        .ex_rd           (ex_rd),
        .ex_reg_write    (ex_reg_write),
        .ex_is_load      (ex_is_load),
        .ex_is_store     (ex_is_store),
        .ex_mem_to_reg   (ex_mem_to_reg),
        .ex_funct3       (ex_funct3),
        .ex_is_ecall     (ex_is_ecall)
    );

    mem_stage u_mem (
        .clk             (clk),
        .rst_n           (rst_n),
        .halt            (halted),
        .ex_valid        (ex_valid),
        .ex_pc_plus4     (ex_pc_plus4),
        .ex_alu_result   (ex_alu_result),
        .ex_store_data   (ex_store_data),
        .ex_rd           (ex_rd),
        .ex_reg_write    (ex_reg_write),
        .ex_is_load      (ex_is_load),
        .ex_is_store     (ex_is_store),
        .ex_mem_to_reg   (ex_mem_to_reg),
        .ex_funct3       (ex_funct3),
        .ex_is_ecall     (ex_is_ecall),
        .dmem_rdata      (dmem_rdata),
        .dmem_valid      (dmem_valid_i),
        .dmem_we         (dmem_we_i),
        .dmem_addr       (dmem_addr),
        .dmem_wdata      (dmem_wdata),
        .dmem_be         (dmem_be),
        .ex_mem_valid    (ex_mem_valid),
        .ex_mem_alu_result(ex_mem_alu_result),
        .ex_mem_reg_write(ex_mem_reg_write),
        .ex_mem_rd       (ex_mem_rd),
        .ex_mem_is_load  (ex_mem_is_load),
        .mem_valid       (mem_valid),
        .mem_wdata       (mem_wdata),
        .mem_rd          (mem_rd),
        .mem_reg_write   (mem_reg_write),
        .mem_is_ecall    (mem_is_ecall)
    );

    wb_stage u_wb (
        .clk             (clk),
        .rst_n           (rst_n),
        .mem_valid       (mem_valid),
        .mem_wdata       (mem_wdata),
        .mem_rd          (mem_rd),
        .mem_reg_write   (mem_reg_write),
        .mem_is_ecall    (mem_is_ecall),
        .x10_value       (x10_value),
        .mem_wb_valid    (mem_wb_valid),
        .mem_wb_reg_write(mem_wb_reg_write),
        .mem_wb_rd       (mem_wb_rd),
        .mem_wb_wdata    (mem_wb_wdata),
        .wb_we           (wb_we),
        .wb_rd           (wb_rd),
        .wb_wdata        (wb_wdata),
        .halted          (halted),
        .exit_code       (exit_code)
    );

    hazard_unit u_hazard (
        .clk          (clk),
        .rst_n        (rst_n),
        .halt         (halted),
        .id_valid     (id_valid),
        .id_rs1_addr  (id_rs1_addr),
        .id_rs2_addr  (id_rs2_addr),
        .id_uses_rs1  (id_uses_rs1),
        .id_uses_rs2  (id_uses_rs2),
        .id_is_ecall  (id_is_ecall),
        .ex_valid     (ex_valid),
        .ex_is_load   (ex_is_load),
        .ex_rd        (ex_rd),
        .ex_redirect  (ex_redirect),
        .stall_pc     (stall_pc),
        .flush_if_id  (flush_if_id),
        .flush_id_ex  (flush_id_ex),
        .halt_pending (halt_pending)
    );

    forwarding_unit u_fwd (
        .ex_mem_valid    (ex_mem_valid),
        .ex_mem_reg_write(ex_mem_reg_write),
        .ex_mem_rd       (ex_mem_rd),
        .ex_mem_is_load  (ex_mem_is_load),
        .mem_wb_valid    (mem_wb_valid),
        .mem_wb_reg_write(mem_wb_reg_write),
        .mem_wb_rd       (mem_wb_rd),
        .id_ex_rs1_addr  (id_ex_rs1_addr),
        .id_ex_rs2_addr  (id_ex_rs2_addr),
        .fwd_a           (fwd_a),
        .fwd_b           (fwd_b)
    );

    regfile u_regfile (
        .clk       (clk),
        .rst_n     (rst_n),
        .wb_we     (wb_we),
        .wb_rd     (wb_rd),
        .wb_wdata  (wb_wdata),
        .rs1_addr  (rs1_addr),
        .rs1_data  (rs1_data),
        .rs2_addr  (rs2_addr),
        .rs2_data  (rs2_data),
        .dbg_addr  (dbg_reg_addr),
        .dbg_data  (dbg_reg_data),
        .x10_value (x10_value)
    );

endmodule


// file: rtl/if_stage.sv
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


// file: rtl/id_stage.sv
module id_stage (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        halt,
    input  logic        flush,
    input  logic        stall,
    input  logic        if_valid,
    input  logic [31:0] if_pc,
    input  logic [31:0] if_pc_plus4,
    input  logic [31:0] if_instr,
    input  logic [31:0] rs1_data,
    input  logic [31:0] rs2_data,
    output logic [4:0]  rs1_addr,
    output logic [4:0]  rs2_addr,
    output logic        id_valid,
    output logic [31:0] id_pc,
    output logic [31:0] id_pc_plus4,
    output logic [31:0] id_rs1_data,
    output logic [31:0] id_rs2_data,
    output logic [4:0]  id_rs1_addr,
    output logic [4:0]  id_rs2_addr,
    output logic [31:0] id_imm,
    output logic [4:0]  id_rd,
    output logic [3:0]  id_alu_op,
    output logic        id_alu_a_sel,
    output logic        id_alu_b_sel,
    output logic        id_reg_write,
    output logic        id_is_load,
    output logic        id_is_store,
    output logic        id_mem_to_reg,
    output logic [2:0]  id_br_op,
    output logic        id_is_branch,
    output logic        id_is_jal,
    output logic        id_is_jalr,
    output logic        id_is_ecall,
    output logic [2:0]  id_funct3,
    output logic        id_uses_rs1,
    output logic        id_uses_rs2
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
    localparam logic [3:0] ALU_PASS = 4'd10;

    localparam logic [6:0] OP_RTYPE  = 7'b0110011;
    localparam logic [6:0] OP_ITYPE  = 7'b0010011;
    localparam logic [6:0] OP_LOAD   = 7'b0000011;
    localparam logic [6:0] OP_STORE  = 7'b0100011;
    localparam logic [6:0] OP_BRANCH = 7'b1100011;
    localparam logic [6:0] OP_JAL    = 7'b1101111;
    localparam logic [6:0] OP_JALR   = 7'b1100111;
    localparam logic [6:0] OP_LUI    = 7'b0110111;
    localparam logic [6:0] OP_AUIPC  = 7'b0010111;
    localparam logic [6:0] OP_SYSTEM = 7'b1110011;

    logic        id_valid_r;
    logic [31:0] id_pc_r;
    logic [31:0] id_pc_plus4_r;
    logic [31:0] id_instr_r;

    logic [6:0]  opcode;
    logic [2:0]  funct3;
    logic [6:0]  funct7;
    logic [4:0]  rd_dec;
    logic [4:0]  rs1_dec;
    logic [4:0]  rs2_dec;

    logic [31:0] imm_i;
    logic [31:0] imm_s;
    logic [31:0] imm_b;
    logic [31:0] imm_u;
    logic [31:0] imm_j;
    logic [31:0] imm_sel;

    logic [3:0]  alu_op_c;
    logic        alu_a_sel_c;
    logic        alu_b_sel_c;
    logic        reg_write_c;
    logic        is_load_c;
    logic        is_store_c;
    logic        mem_to_reg_c;
    logic [2:0]  br_op_c;
    logic        is_branch_c;
    logic        is_jal_c;
    logic        is_jalr_c;
    logic        is_ecall_c;
    logic        uses_rs1_c;
    logic        uses_rs2_c;

    assign opcode = id_instr_r[6:0];
    assign funct3 = id_instr_r[14:12];
    assign funct7 = id_instr_r[31:25];
    assign rd_dec  = id_instr_r[11:7];
    assign rs1_dec = id_instr_r[19:15];
    assign rs2_dec = id_instr_r[24:20];

    assign imm_i = {{20{id_instr_r[31]}}, id_instr_r[31:20]};
    assign imm_s = {{20{id_instr_r[31]}}, id_instr_r[31:25], id_instr_r[11:7]};
    assign imm_b = {{19{id_instr_r[31]}}, id_instr_r[31], id_instr_r[7],
                    id_instr_r[30:25], id_instr_r[11:8], 1'b0};
    assign imm_u = {id_instr_r[31:12], 12'b0};
    assign imm_j = {{11{id_instr_r[31]}}, id_instr_r[31], id_instr_r[19:12],
                    id_instr_r[20], id_instr_r[30:21], 1'b0};

    always_comb begin
        imm_sel = 32'b0;
        case (opcode)
            OP_ITYPE, OP_LOAD, OP_JALR: imm_sel = imm_i;
            OP_STORE:                   imm_sel = imm_s;
            OP_BRANCH:                  imm_sel = imm_b;
            OP_LUI, OP_AUIPC:           imm_sel = imm_u;
            OP_JAL:                     imm_sel = imm_j;
            default:                    imm_sel = 32'b0;
        endcase
    end

    always_comb begin
        alu_op_c    = ALU_ADD;
        alu_a_sel_c = 1'b0;
        alu_b_sel_c = 1'b0;
        reg_write_c = 1'b0;
        is_load_c   = 1'b0;
        is_store_c  = 1'b0;
        mem_to_reg_c= 1'b0;
        br_op_c     = 3'b0;
        is_branch_c = 1'b0;
        is_jal_c    = 1'b0;
        is_jalr_c   = 1'b0;
        is_ecall_c  = 1'b0;
        uses_rs1_c  = 1'b0;
        uses_rs2_c  = 1'b0;

        case (opcode)
            OP_RTYPE: begin
                reg_write_c = 1'b1;
                uses_rs1_c  = 1'b1;
                uses_rs2_c  = 1'b1;
                alu_b_sel_c = 1'b0;
                case (funct3)
                    3'b000: alu_op_c = funct7[5] ? ALU_SUB : ALU_ADD;
                    3'b001: alu_op_c = ALU_SLL;
                    3'b010: alu_op_c = ALU_SLT;
                    3'b011: alu_op_c = ALU_SLTU;
                    3'b100: alu_op_c = ALU_XOR;
                    3'b101: alu_op_c = funct7[5] ? ALU_SRA : ALU_SRL;
                    3'b110: alu_op_c = ALU_OR;
                    3'b111: alu_op_c = ALU_AND;
                    default: alu_op_c = ALU_ADD;
                endcase
            end
            OP_ITYPE: begin
                reg_write_c = 1'b1;
                uses_rs1_c  = 1'b1;
                alu_b_sel_c = 1'b1;
                case (funct3)
                    3'b000: alu_op_c = ALU_ADD;
                    3'b001: alu_op_c = ALU_SLL;
                    3'b010: alu_op_c = ALU_SLT;
                    3'b011: alu_op_c = ALU_SLTU;
                    3'b100: alu_op_c = ALU_XOR;
                    3'b101: alu_op_c = funct7[5] ? ALU_SRA : ALU_SRL;
                    3'b110: alu_op_c = ALU_OR;
                    3'b111: alu_op_c = ALU_AND;
                    default: alu_op_c = ALU_ADD;
                endcase
            end
            OP_LOAD: begin
                reg_write_c = 1'b1;
                is_load_c   = 1'b1;
                mem_to_reg_c= 1'b1;
                uses_rs1_c  = 1'b1;
                alu_op_c    = ALU_ADD;
                alu_b_sel_c = 1'b1;
            end
            OP_STORE: begin
                is_store_c  = 1'b1;
                uses_rs1_c  = 1'b1;
                uses_rs2_c  = 1'b1;
                alu_op_c    = ALU_ADD;
                alu_b_sel_c = 1'b1;
            end
            OP_BRANCH: begin
                is_branch_c = 1'b1;
                uses_rs1_c  = 1'b1;
                uses_rs2_c  = 1'b1;
                alu_op_c    = ALU_SUB;
                alu_b_sel_c = 1'b0;
                case (funct3)
                    3'b000: br_op_c = 3'd0;
                    3'b001: br_op_c = 3'd1;
                    3'b100: br_op_c = 3'd2;
                    3'b101: br_op_c = 3'd3;
                    3'b110: br_op_c = 3'd4;
                    3'b111: br_op_c = 3'd5;
                    default: br_op_c = 3'd0;
                endcase
            end
            OP_JAL: begin
                is_jal_c    = 1'b1;
                reg_write_c = 1'b1;
                alu_op_c    = ALU_ADD;
                alu_a_sel_c = 1'b1;
                alu_b_sel_c = 1'b1;
            end
            OP_JALR: begin
                is_jalr_c   = 1'b1;
                reg_write_c = 1'b1;
                uses_rs1_c  = 1'b1;
                alu_op_c    = ALU_ADD;
                alu_b_sel_c = 1'b1;
            end
            OP_LUI: begin
                reg_write_c = 1'b1;
                alu_op_c    = ALU_PASS;
                alu_b_sel_c = 1'b1;
            end
            OP_AUIPC: begin
                reg_write_c = 1'b1;
                alu_op_c    = ALU_ADD;
                alu_a_sel_c = 1'b1;
                alu_b_sel_c = 1'b1;
            end
            OP_SYSTEM: begin
                if (id_instr_r == 32'h0000_0073) begin
                    is_ecall_c = 1'b1;
                end
            end
            default: begin
            end
        endcase
    end

    assign rs1_addr = rs1_dec;
    assign rs2_addr = rs2_dec;

    assign id_valid      = id_valid_r;
    assign id_pc         = id_pc_r;
    assign id_pc_plus4   = id_pc_plus4_r;
    assign id_rs1_data   = rs1_data;
    assign id_rs2_data   = rs2_data;
    assign id_rs1_addr   = rs1_dec;
    assign id_rs2_addr   = rs2_dec;
    assign id_imm        = imm_sel;
    assign id_rd         = rd_dec;
    assign id_alu_op     = alu_op_c;
    assign id_alu_a_sel  = alu_a_sel_c;
    assign id_alu_b_sel  = alu_b_sel_c;
    assign id_reg_write  = reg_write_c;
    assign id_is_load    = is_load_c;
    assign id_is_store   = is_store_c;
    assign id_mem_to_reg = mem_to_reg_c;
    assign id_br_op      = br_op_c;
    assign id_is_branch  = is_branch_c;
    assign id_is_jal     = is_jal_c;
    assign id_is_jalr    = is_jalr_c;
    assign id_is_ecall   = is_ecall_c;
    assign id_funct3     = funct3;
    assign id_uses_rs1   = uses_rs1_c;
    assign id_uses_rs2   = uses_rs2_c;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            id_valid_r    <= 1'b0;
            id_pc_r       <= 32'b0;
            id_pc_plus4_r <= 32'b0;
            id_instr_r    <= 32'b0;
        end else if (halt) begin
            id_valid_r    <= id_valid_r;
            id_pc_r       <= id_pc_r;
            id_pc_plus4_r <= id_pc_plus4_r;
            id_instr_r    <= id_instr_r;
        end else if (flush) begin
            id_valid_r    <= 1'b0;
            id_pc_r       <= 32'b0;
            id_pc_plus4_r <= 32'b0;
            id_instr_r    <= 32'b0;
        end else if (stall) begin
            id_valid_r    <= id_valid_r;
            id_pc_r       <= id_pc_r;
            id_pc_plus4_r <= id_pc_plus4_r;
            id_instr_r    <= id_instr_r;
        end else begin
            id_valid_r    <= if_valid;
            id_pc_r       <= if_pc;
            id_pc_plus4_r <= if_pc_plus4;
            id_instr_r    <= if_instr;
        end
    end

endmodule


// file: rtl/ex_stage.sv
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


// file: rtl/mem_stage.sv
module mem_stage (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        halt,
    input  logic        ex_valid,
    input  logic [31:0] ex_pc_plus4,
    input  logic [31:0] ex_alu_result,
    input  logic [31:0] ex_store_data,
    input  logic [4:0]  ex_rd,
    input  logic        ex_reg_write,
    input  logic        ex_is_load,
    input  logic        ex_is_store,
    input  logic        ex_mem_to_reg,
    input  logic [2:0]  ex_funct3,
    input  logic        ex_is_ecall,
    input  logic [31:0] dmem_rdata,
    output logic        dmem_valid,
    output logic        dmem_we,
    output logic [31:0] dmem_addr,
    output logic [31:0] dmem_wdata,
    output logic [3:0]  dmem_be,
    output logic        ex_mem_valid,
    output logic [31:0] ex_mem_alu_result,
    output logic        ex_mem_reg_write,
    output logic [4:0]  ex_mem_rd,
    output logic        ex_mem_is_load,
    output logic        mem_valid,
    output logic [31:0] mem_wdata,
    output logic [4:0]  mem_rd,
    output logic        mem_reg_write,
    output logic        mem_is_ecall
);

    logic        em_valid;
    logic [31:0] em_pc_plus4;
    logic [31:0] em_alu_result;
    logic [31:0] em_store_data;
    logic [4:0]  em_rd;
    logic        em_reg_write;
    logic        em_is_load;
    logic        em_is_store;
    logic        em_mem_to_reg;
    logic [2:0]  em_funct3;
    logic        em_is_ecall;

    logic [31:0] load_data;
    logic [31:0] wb_data;
    logic [7:0]  load_byte;
    logic [15:0] load_half;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            em_valid       <= 1'b0;
            em_pc_plus4    <= 32'b0;
            em_alu_result  <= 32'b0;
            em_store_data  <= 32'b0;
            em_rd          <= 5'b0;
            em_reg_write   <= 1'b0;
            em_is_load     <= 1'b0;
            em_is_store    <= 1'b0;
            em_mem_to_reg  <= 1'b0;
            em_funct3      <= 3'b0;
            em_is_ecall    <= 1'b0;
        end else if (halt) begin
            em_valid       <= em_valid;
            em_pc_plus4    <= em_pc_plus4;
            em_alu_result  <= em_alu_result;
            em_store_data  <= em_store_data;
            em_rd          <= em_rd;
            em_reg_write   <= em_reg_write;
            em_is_load     <= em_is_load;
            em_is_store    <= em_is_store;
            em_mem_to_reg  <= em_mem_to_reg;
            em_funct3      <= em_funct3;
            em_is_ecall    <= em_is_ecall;
        end else begin
            em_valid       <= ex_valid;
            em_pc_plus4    <= ex_pc_plus4;
            em_alu_result  <= ex_alu_result;
            em_store_data  <= ex_store_data;
            em_rd          <= ex_rd;
            em_reg_write   <= ex_reg_write;
            em_is_load     <= ex_is_load;
            em_is_store    <= ex_is_store;
            em_mem_to_reg  <= ex_mem_to_reg;
            em_funct3      <= ex_funct3;
            em_is_ecall    <= ex_is_ecall;
        end
    end

    assign ex_mem_valid      = em_valid;
    assign ex_mem_alu_result = em_alu_result;
    assign ex_mem_reg_write  = em_reg_write;
    assign ex_mem_rd         = em_rd;
    assign ex_mem_is_load    = em_is_load;

    always_comb begin
        dmem_valid = 1'b0;
        dmem_we    = 1'b0;
        dmem_addr  = em_alu_result;
        dmem_wdata = em_store_data;
        dmem_be    = 4'b0000;
        if (rst_n && !halt && em_valid) begin
            if (em_is_load) begin
                dmem_valid = 1'b1;
                dmem_we    = 1'b0;
                dmem_be    = 4'b0000;
            end else if (em_is_store) begin
                dmem_valid = 1'b1;
                dmem_we    = 1'b1;
                case (em_funct3)
                    3'b000: begin
                        dmem_wdata = {4{em_store_data[7:0]}};
                        dmem_be    = 4'b0001 << em_alu_result[1:0];
                    end
                    3'b001: begin
                        dmem_wdata = {2{em_store_data[15:0]}};
                        dmem_be    = em_alu_result[1] ? 4'b1100 : 4'b0011;
                    end
                    default: begin
                        dmem_wdata = em_store_data;
                        dmem_be    = 4'b1111;
                    end
                endcase
            end
        end
    end

    // Little-endian byte/half selection using the low address bits
    always_comb begin
        load_byte = dmem_rdata[7:0];
        case (em_alu_result[1:0])
            2'b00: load_byte = dmem_rdata[7:0];
            2'b01: load_byte = dmem_rdata[15:8];
            2'b10: load_byte = dmem_rdata[23:16];
            2'b11: load_byte = dmem_rdata[31:24];
        endcase
    end

    always_comb begin
        load_half = dmem_rdata[15:0];
        if (em_alu_result[1])
            load_half = dmem_rdata[31:16];
        else
            load_half = dmem_rdata[15:0];
    end

    always_comb begin
        case (em_funct3)
            3'b000:  load_data = {{24{load_byte[7]}}, load_byte};
            3'b001:  load_data = {{16{load_half[15]}}, load_half};
            3'b100:  load_data = {24'b0, load_byte};
            3'b101:  load_data = {16'b0, load_half};
            default: load_data = dmem_rdata;
        endcase
    end

    assign wb_data = em_mem_to_reg ? load_data : em_alu_result;

    assign mem_valid      = em_valid;
    assign mem_wdata      = wb_data;
    assign mem_rd         = em_rd;
    assign mem_reg_write  = em_reg_write;
    assign mem_is_ecall   = em_is_ecall;

endmodule


// file: rtl/wb_stage.sv
module wb_stage (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        mem_valid,
    input  logic [31:0] mem_wdata,
    input  logic [4:0]  mem_rd,
    input  logic        mem_reg_write,
    input  logic        mem_is_ecall,
    input  logic [31:0] x10_value,
    output logic        mem_wb_valid,
    output logic        mem_wb_reg_write,
    output logic [4:0]  mem_wb_rd,
    output logic [31:0] mem_wb_wdata,
    output logic        wb_we,
    output logic [4:0]  wb_rd,
    output logic [31:0] wb_wdata,
    output logic        halted,
    output logic [31:0] exit_code
);

    logic        mem_wb_is_ecall;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            mem_wb_valid     <= 1'b0;
            mem_wb_reg_write <= 1'b0;
            mem_wb_rd        <= 5'd0;
            mem_wb_wdata     <= 32'd0;
            mem_wb_is_ecall  <= 1'b0;
            halted           <= 1'b0;
            exit_code        <= 32'd0;
        end else if (!halted) begin
            mem_wb_valid     <= mem_valid;
            mem_wb_reg_write <= mem_reg_write;
            mem_wb_rd        <= mem_rd;
            mem_wb_wdata     <= mem_wdata;
            mem_wb_is_ecall  <= mem_is_ecall;
            if (mem_valid && mem_is_ecall) begin
                halted    <= 1'b1;
                exit_code <= x10_value;
            end
        end
    end

    assign wb_we    = mem_wb_valid && mem_wb_reg_write && (mem_wb_rd != 5'd0) && !halted;
    assign wb_rd    = mem_wb_rd;
    assign wb_wdata = mem_wb_wdata;

endmodule


// file: rtl/hazard_unit.sv
module hazard_unit (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       halt,
    input  logic       id_valid,
    input  logic [4:0] id_rs1_addr,
    input  logic [4:0] id_rs2_addr,
    input  logic       id_uses_rs1,
    input  logic       id_uses_rs2,
    input  logic       id_is_ecall,
    input  logic       ex_valid,
    input  logic       ex_is_load,
    input  logic [4:0] ex_rd,
    input  logic       ex_redirect,
    output logic       stall_pc,
    output logic       flush_if_id,
    output logic       flush_id_ex,
    output logic       halt_pending
);

    logic load_use_stall;
    logic ecall_halt;

    always_comb begin
        load_use_stall = 1'b0;
        if (ex_valid && ex_is_load && (ex_rd != 5'd0) && id_valid) begin
            if ((id_uses_rs1 && (id_rs1_addr == ex_rd)) ||
                (id_uses_rs2 && (id_rs2_addr == ex_rd))) begin
                load_use_stall = 1'b1;
            end
        end
    end

    always_comb begin
        ecall_halt = id_valid && id_is_ecall && !ex_redirect;
    end

    always_comb begin
        if (ex_redirect) begin
            stall_pc    = 1'b0;
            flush_if_id = 1'b1;
            flush_id_ex = 1'b1;
        end else if (halt_pending || ecall_halt) begin
            stall_pc    = 1'b1;
            flush_if_id = 1'b1;
            flush_id_ex = 1'b0;
        end else if (load_use_stall) begin
            stall_pc    = 1'b1;
            flush_if_id = 1'b0;
            flush_id_ex = 1'b1;
        end else begin
            stall_pc    = 1'b0;
            flush_if_id = 1'b0;
            flush_id_ex = 1'b0;
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            halt_pending <= 1'b0;
        end else if (ecall_halt) begin
            halt_pending <= 1'b1;
        end
    end

endmodule


// file: rtl/forwarding_unit.sv
module forwarding_unit (
    input  logic        ex_mem_valid,
    input  logic        ex_mem_reg_write,
    input  logic [4:0]  ex_mem_rd,
    input  logic        ex_mem_is_load,
    input  logic        mem_wb_valid,
    input  logic        mem_wb_reg_write,
    input  logic [4:0]  mem_wb_rd,
    input  logic [4:0]  id_ex_rs1_addr,
    input  logic [4:0]  id_ex_rs2_addr,
    output logic [1:0]  fwd_a,
    output logic [1:0]  fwd_b
);

    logic ex_mem_hit_a;
    logic ex_mem_hit_b;
    logic mem_wb_hit_a;
    logic mem_wb_hit_b;

    always_comb begin
        ex_mem_hit_a = ex_mem_valid && ex_mem_reg_write && (ex_mem_rd != 5'd0) &&
                       !ex_mem_is_load && (ex_mem_rd == id_ex_rs1_addr);
        ex_mem_hit_b = ex_mem_valid && ex_mem_reg_write && (ex_mem_rd != 5'd0) &&
                       !ex_mem_is_load && (ex_mem_rd == id_ex_rs2_addr);
        mem_wb_hit_a = mem_wb_valid && mem_wb_reg_write && (mem_wb_rd != 5'd0) &&
                       (mem_wb_rd == id_ex_rs1_addr);
        mem_wb_hit_b = mem_wb_valid && mem_wb_reg_write && (mem_wb_rd != 5'd0) &&
                       (mem_wb_rd == id_ex_rs2_addr);

        if (ex_mem_hit_a)
            fwd_a = 2'b01;
        else if (mem_wb_hit_a)
            fwd_a = 2'b10;
        else
            fwd_a = 2'b00;

        if (ex_mem_hit_b)
            fwd_b = 2'b01;
        else if (mem_wb_hit_b)
            fwd_b = 2'b10;
        else
            fwd_b = 2'b00;
    end

endmodule


// file: rtl/regfile.sv
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


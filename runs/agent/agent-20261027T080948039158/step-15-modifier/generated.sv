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

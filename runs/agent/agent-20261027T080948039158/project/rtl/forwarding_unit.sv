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

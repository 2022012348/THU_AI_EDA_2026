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

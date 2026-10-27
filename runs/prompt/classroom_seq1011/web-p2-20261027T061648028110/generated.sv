module seq1011 (
    input  logic clk,
    input  logic rst_n,
    input  logic in_valid,
    output logic in_ready,
    input  logic in_bit,
    output logic out_valid,
    input  logic out_ready,
    output logic match
);

    typedef enum logic [1:0] {
        S_IDLE = 2'd0,
        S_1    = 2'd1,
        S_10   = 2'd2,
        S_101  = 2'd3
    } state_t;

    state_t state, next_state;
    logic detect;

    always_comb begin
        next_state = state;
        detect = 1'b0;

        case (state)
            S_IDLE: begin
                if (in_bit) next_state = S_1;
                else        next_state = S_IDLE;
            end

            S_1: begin
                if (in_bit) next_state = S_1;
                else        next_state = S_10;
            end

            S_10: begin
                if (in_bit) next_state = S_101;
                else        next_state = S_IDLE;
            end

            S_101: begin
                if (in_bit) begin
                    detect = 1'b1;
                    next_state = S_1;
                end else begin
                    next_state = S_10;
                end
            end

            default: next_state = S_IDLE;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            out_valid <= 1'b0;
        end else begin
            if (out_valid && out_ready) begin
                out_valid <= 1'b0;
            end

            if (in_valid && in_ready) begin
                state <= next_state;
                if (detect) begin
                    out_valid <= 1'b1;
                end
            end
        end
    end

    assign in_ready = ~out_valid;
    assign match = out_valid;

endmodule

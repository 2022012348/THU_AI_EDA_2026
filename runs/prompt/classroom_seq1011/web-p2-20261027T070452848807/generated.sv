module seq1011 (
    input  logic clk,
    input  logic rst_n,
    output logic in_ready,
    input  logic in_valid,
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

    logic accept;
    logic match_next;

    assign in_ready = ~out_valid | out_ready;
    assign accept   = in_valid & in_ready;

    always_comb begin
        next_state = state;
        match_next = 1'b0;

        if (accept) begin
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
                        next_state = S_1;
                        match_next = 1'b1;
                    end else begin
                        next_state = S_10;
                    end
                end
                default: next_state = S_IDLE;
            endcase
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= S_IDLE;
            out_valid <= 1'b0;
            match     <= 1'b0;
        end else begin
            state <= next_state;

            if (out_valid && out_ready)
                out_valid <= 1'b0;

            if (accept && match_next) begin
                out_valid <= 1'b1;
                match     <= 1'b1;
            end
        end
    end

endmodule

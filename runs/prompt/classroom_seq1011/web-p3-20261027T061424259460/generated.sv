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

    logic [2:0] state;
    logic [2:0] next_state;
    logic       next_match;

    assign in_ready = (~out_valid) | out_ready;

    always_comb begin
        next_state = state;
        next_match = 1'b0;

        if (in_valid && in_ready) begin
            next_state = {state[1:0], in_bit};
            next_match = (state == 3'b101) && in_bit;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= 3'b000;
            match     <= 1'b0;
            out_valid <= 1'b0;
        end else begin
            if (in_valid && in_ready) begin
                state     <= next_state;
                match     <= next_match;
                out_valid <= 1'b1;
            end else if (out_valid && out_ready) begin
                out_valid <= 1'b0;
            end
        end
    end

endmodule

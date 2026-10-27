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

    logic [2:0] hist;
    logic       match_q;

    assign in_ready = (!out_valid) || out_ready;
    assign match    = match_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            hist      <= 3'b000;
            match_q   <= 1'b0;
            out_valid <= 1'b0;
        end else begin
            if (out_valid && out_ready)
                out_valid <= 1'b0;

            if (in_valid && in_ready) begin
                match_q   <= in_bit && hist[2] && !hist[1] && hist[0];
                out_valid <= 1'b1;
                hist      <= {hist[1:0], in_bit};
            end
        end
    end

endmodule

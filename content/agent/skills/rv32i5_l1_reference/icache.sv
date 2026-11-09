module icache (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        halted,
    input  logic        flush,
    input  logic [1:0]  flush_epoch,
    input  logic        cpu_req_valid,
    input  logic [31:0] cpu_req_addr,
    output logic        cpu_req_ready,
    output logic        cpu_resp_valid,
    output logic [31:0] cpu_resp_data,
    output logic        mem_req_valid,
    output logic [31:0] mem_req_addr,
    input  logic        mem_req_ready,
    input  logic        mem_resp_valid,
    input  logic [31:0] mem_resp_data
);

    localparam logic [1:0] S_IDLE   = 2'd0;
    localparam logic [1:0] S_REFILL = 2'd1;

    logic [31:0]  tag_arr   [0:15];
    logic [127:0] data_arr  [0:15];
    logic         valid_arr [0:15];

    logic [1:0]   state;
    logic [1:0]   refill_cnt;
    logic [31:0]  refill_base;
    logic [31:0]  refill_tag;
    logic [3:0]   refill_idx;
    logic [1:0]   refill_epoch;
    logic         discard_refill;
    logic [127:0] refill_data;
    logic [1:0]   refill_word;

    logic         resp_valid_r;
    logic [1:0]   resp_epoch;
    logic [31:0]  resp_data_r;

    logic [3:0]   req_idx;
    logic [31:0]  req_tag;
    logic [1:0]   req_word;
    logic         hit;
    logic [31:0]  hit_data;

    assign req_idx  = cpu_req_addr[7:4];
    assign req_tag  = cpu_req_addr[31:8];
    assign req_word = cpu_req_addr[3:2];

    assign hit = valid_arr[req_idx] && (tag_arr[req_idx] == req_tag);

    always_comb begin
        hit_data = 32'b0;
        case (req_word)
            2'd0: hit_data = data_arr[req_idx][31:0];
            2'd1: hit_data = data_arr[req_idx][63:32];
            2'd2: hit_data = data_arr[req_idx][95:64];
            2'd3: hit_data = data_arr[req_idx][127:96];
            default: hit_data = 32'b0;
        endcase
    end

    assign cpu_req_ready = rst_n && !halted && !flush && (state == S_IDLE) && !resp_valid_r;

    assign mem_req_valid = rst_n && !halted && (state == S_REFILL);
    assign mem_req_addr  = refill_base + {refill_cnt, 2'b00};

    assign cpu_resp_valid = resp_valid_r && !flush && (resp_epoch == flush_epoch);
    assign cpu_resp_data  = resp_data_r;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state        <= S_IDLE;
            refill_cnt   <= 2'd0;
            refill_base  <= 32'b0;
            refill_tag   <= 32'b0;
            refill_idx   <= 4'b0;
            refill_epoch <= 2'b0;
            discard_refill <= 1'b0;
            refill_data  <= 128'b0;
            refill_word  <= 2'b0;
            resp_valid_r <= 1'b0;
            resp_epoch   <= 2'b0;
            resp_data_r  <= 32'b0;
            for (int i = 0; i < 16; i = i + 1) begin
                valid_arr[i] <= 1'b0;
                tag_arr[i]   <= 32'b0;
                data_arr[i]  <= 128'b0;
            end
        end else if (halted) begin
            resp_valid_r <= 1'b0;
        end else begin
            resp_valid_r <= 1'b0;

            // A request already asserted stays stable through ready. A flush
            // marks it stale and prevents additional words from being issued.
            case (state)
                S_IDLE: begin
                    if (cpu_req_valid && cpu_req_ready) begin
                        if (hit) begin
                            resp_valid_r <= 1'b1;
                            resp_epoch   <= flush_epoch;
                            resp_data_r  <= hit_data;
                        end else begin
                            state        <= S_REFILL;
                            refill_cnt   <= 2'd0;
                            refill_base  <= {cpu_req_addr[31:4], 4'b0000};
                            refill_tag   <= req_tag;
                            refill_idx   <= req_idx;
                            refill_epoch <= flush_epoch;
                            discard_refill <= 1'b0;
                            refill_data  <= 128'b0;
                            refill_word  <= req_word;
                        end
                    end
                end
                S_REFILL: begin
                    // flush may coincide with the last response, before the
                    // epoch register advances. Remember it explicitly while
                    // the currently asserted bus request waits for acceptance.
                    if (flush || flush_epoch != refill_epoch)
                        discard_refill <= 1'b1;
                    if (mem_req_valid && mem_req_ready) begin
                        if (discard_refill || flush || flush_epoch != refill_epoch) begin
                            state <= S_IDLE;
                        end else begin
                            case (refill_cnt)
                                2'd0: refill_data[31:0]   <= mem_resp_data;
                                2'd1: refill_data[63:32]  <= mem_resp_data;
                                2'd2: refill_data[95:64]  <= mem_resp_data;
                                2'd3: refill_data[127:96] <= mem_resp_data;
                                default: ;
                            endcase
                            if (refill_cnt == 2'd3) begin
                                valid_arr[refill_idx] <= 1'b1;
                                tag_arr[refill_idx]   <= refill_tag;
                                data_arr[refill_idx]  <= refill_data |
                                    ({96'b0, mem_resp_data} << {refill_cnt, 5'b00000});
                                resp_valid_r <= 1'b1;
                                resp_epoch   <= refill_epoch;
                                case (refill_word)
                                    2'd0: resp_data_r <= refill_data[31:0];
                                    2'd1: resp_data_r <= refill_data[63:32];
                                    2'd2: resp_data_r <= refill_data[95:64];
                                    default: resp_data_r <= mem_resp_data;
                                endcase
                                state <= S_IDLE;
                            end else begin
                                refill_cnt <= refill_cnt + 2'd1;
                            end
                        end
                    end
                end
                default: state <= S_IDLE;
            endcase
        end
    end

endmodule

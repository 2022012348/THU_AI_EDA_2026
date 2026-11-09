`timescale 1ns/1ps
// Black-box check: same-edge redirect on final refill response. No DUT internals.
module tb_l1_icache_flush_edge;
  reg clk = 0;
  always #5 clk = ~clk;
  reg rst_n = 0;
  reg flush = 0;
  reg [1:0] flush_epoch = 0;
  reg cpu_req_valid = 0;
  reg [31:0] cpu_req_addr = 0;
  wire cpu_req_ready, cpu_resp_valid;
  wire [31:0] cpu_resp_data;
  wire mem_req_valid;
  wire [31:0] mem_req_addr;
  reg mem_req_ready = 1;
  reg mem_resp_valid = 1;
  wire [31:0] mem_resp_data = 32'h11110000 | mem_req_addr;
  integer requests = 0;

  icache dut(
    .clk(clk), .rst_n(rst_n),
`ifdef L1_ICACHE_HAS_HALTED
    .halted(1'b0),
`endif
    .flush(flush), .flush_epoch(flush_epoch),
    .cpu_req_valid(cpu_req_valid), .cpu_req_addr(cpu_req_addr),
    .cpu_req_ready(cpu_req_ready), .cpu_resp_valid(cpu_resp_valid),
    .cpu_resp_data(cpu_resp_data), .mem_req_valid(mem_req_valid),
    .mem_req_ready(mem_req_ready), .mem_req_addr(mem_req_addr),
    .mem_resp_valid(mem_resp_valid), .mem_resp_data(mem_resp_data)
  );

  always @(posedge clk) begin
    if (!rst_n) begin flush_epoch <= 0; requests <= 0; end
    else begin
      if (flush) flush_epoch <= flush_epoch + 1'b1;
      if (mem_req_valid && mem_req_ready) requests <= requests + 1;
    end
  end

  task tick; begin @(negedge clk); #1; end endtask
  task issue(input [31:0] address);
    begin
      tick();
      cpu_req_addr = address;
      cpu_req_valid = 1;
      #1;
      while (cpu_req_ready !== 1'b1) tick();
      tick();
      cpu_req_valid = 0;
    end
  endtask
  task await_response;
    begin while (cpu_resp_valid !== 1'b1) tick(); end
  endtask

  integer before_requests;
  integer offset_case, hot_word;
  reg [31:0] test_base, test_address;
  initial begin
    tick(); tick(); rst_n = 1;
    // Check all cold-miss offsets and the four cached words of each line.
    // These are independent addresses derived from the B.1 cache geometry,
    // with no dependency on a teacher program or DUT internal signal names.
    for (offset_case = 0; offset_case < 4; offset_case = offset_case + 1) begin
      test_base = 32'h40 + offset_case * 16;
      test_address = test_base + offset_case * 4;
      issue(test_address);
      await_response();
      if (cpu_resp_data !== (32'h11110000 | test_address))
        $fatal(1, "CHECK: l1_icache_cold_word_offset — requested word offset returned wrong data");
      tick();
      for (hot_word = 0; hot_word < 4; hot_word = hot_word + 1) begin
        test_address = test_base + hot_word * 4;
        before_requests = requests;
        issue(test_address);
        await_response();
        if (cpu_resp_data !== (32'h11110000 | test_address) || requests != before_requests)
          $fatal(1, "CHECK: l1_icache_hot_word_offset — cached word data or hit reuse is wrong");
        tick();
      end
    end
    $display("L1_ICACHE_WORD_OFFSETS_PASS cold_offsets=4 cached_words=16");
    // Prime a valid line at index 0.
    issue(32'h100);
    await_response();
    if (cpu_resp_data !== 32'h11110100)
      $fatal(1, "CHECK: l1_icache_initial_refill — initial word0 data mismatch");
    tick();

    // Conflicting miss to the same index. Assert flush exactly when the last
    // word is accepted. Epoch increments on that edge, not before it.
    issue(32'h200);
    while (!(mem_req_valid && mem_req_addr === 32'h20c)) tick();
    flush = 1;
    #1;
    if (cpu_resp_valid !== 1'b0)
      $fatal(1, "CHECK: l1_icache_flush_final_word — stale CPU response during final-word flush");
    tick();
    flush = 0;
    #1;
    if (cpu_resp_valid !== 1'b0)
      $fatal(1, "CHECK: l1_icache_flush_final_word — stale CPU response after final-word flush");
    repeat (2) begin tick(); if (cpu_resp_valid !== 1'b0)
      $fatal(1, "CHECK: l1_icache_flush_final_word — delayed stale CPU response"); end

    // Observable proof that the previous valid line was not replaced.
    before_requests = requests;
    issue(32'h100);
    await_response();
    if (cpu_resp_data !== 32'h11110100 || requests != before_requests)
      $fatal(1, "CHECK: l1_icache_old_line_preserved — prior line was lost or replaced after stale refill");
    tick();

    // Observable proof that the abandoned line did not become a cache hit.
    before_requests = requests;
    issue(32'h200);
    await_response();
    if (cpu_resp_data !== 32'h11110200 || (requests - before_requests) < 4)
      $fatal(1, "CHECK: l1_icache_stale_line_not_installed — stale line became a hit or refill data is wrong");
    $display("L1_ICACHE_FLUSH_EDGE_PASS");
    $finish;
  end
  initial begin #10000; $fatal(1, "CHECK: l1_icache_flush_probe_timeout — handshake or response timed out"); end
endmodule

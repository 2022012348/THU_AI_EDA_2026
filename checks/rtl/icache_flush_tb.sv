`timescale 1ns/1ps
module tb;
  logic clk = 0;
  always #5 clk = ~clk;
  logic rst_n = 0, halted = 0, flush = 0;
  logic [1:0] flush_epoch = 0;
  logic cpu_req_valid = 0;
  logic [31:0] cpu_req_addr = 0;
  wire cpu_req_ready, cpu_resp_valid;
  wire [31:0] cpu_resp_data;
  wire mem_req_valid;
  wire [31:0] mem_req_addr;
  logic mem_req_ready = 0, mem_resp_valid = 1;
  logic [31:0] mem_resp_data = 0;
  icache dut(.*);

  task automatic tick;
    @(negedge clk);
    #1;
  endtask

  task automatic reset_cache;
    rst_n = 0; flush = 0; flush_epoch = 0;
    cpu_req_valid = 0; mem_req_ready = 0;
    tick();
    rst_n = 1;
    tick();
  endtask

  task automatic start_miss(input logic [31:0] address);
    cpu_req_addr = address;
    cpu_req_valid = 1;
    if (!cpu_req_ready) $fatal(1, "cache was not ready for a miss");
    tick();
    cpu_req_valid = 0;
    if (!mem_req_valid || mem_req_addr !== {address[31:4],4'b0})
      $fatal(1, "miss did not issue first refill word");
  endtask

  task automatic accept_word(input logic [31:0] data);
    mem_resp_data = data; mem_req_ready = 1;
    tick();
    mem_req_ready = 0;
  endtask

  task automatic check_no_install(input integer idx);
    if (dut.valid_arr[idx] !== 1'b0) $fatal(1, "stale refill installed a valid line");
    if (cpu_resp_valid) $fatal(1, "stale refill produced a CPU response");
  endtask

  initial begin
    // Normal 4-word refill, followed by a hit, remains functional.
    tick(); reset_cache(); start_miss(32'h40);
    accept_word(32'h11); accept_word(32'h22); accept_word(32'h33); accept_word(32'h44);
    if (!dut.valid_arr[4] || !cpu_resp_valid || cpu_resp_data !== 32'h11)
      $fatal(1, "normal refill failed");
    tick();
    cpu_req_valid = 1; cpu_req_addr = 32'h4c;
    if (!cpu_req_ready) $fatal(1, "normal hit was not ready");
    tick(); cpu_req_valid = 0;
    if (!cpu_resp_valid || cpu_resp_data !== 32'h44 || mem_req_valid)
      $fatal(1, "normal hit failed");
    // A redirect must suppress an outstanding one-cycle hit response immediately.
    flush = 1; #1;
    if (cpu_resp_valid) $fatal(1, "redirect leaked prior hit response");

    // Redirect while ready is low must keep the already asserted request stable
    // until accepted, then stop without issuing the remaining words.
    reset_cache(); start_miss(32'h80);
    accept_word(32'h55); // next request is word 1
    if (mem_req_addr !== 32'h84) $fatal(1, "wrong second refill address");
    flush = 1;
    repeat (2) begin
      tick();
      if (!mem_req_valid || mem_req_addr !== 32'h84)
        $fatal(1, "redirect changed an unaccepted request");
      check_no_install(8);
    end
    flush = 0; flush_epoch = 1;
    accept_word(32'h66);
    if (mem_req_valid) $fatal(1, "stale refill issued another request after acceptance");
    check_no_install(8);

    // An abandoned conflicting miss must not evict an existing valid line.
    reset_cache(); start_miss(32'h00);
    accept_word(32'h11); accept_word(32'h22); accept_word(32'h33); accept_word(32'h44);
    tick();
    start_miss(32'h100); // same index, different tag
    flush = 1; mem_req_ready = 1; mem_resp_data = 32'hdeadbeef;
    tick(); flush = 0; flush_epoch = 1; mem_req_ready = 0;
    if (!dut.valid_arr[0] || dut.tag_arr[0] !== 0 || dut.data_arr[0][31:0] !== 32'h11)
      $fatal(1, "stale conflicting refill altered an existing line");
    cpu_req_valid = 1; cpu_req_addr = 0; #1;
    if (!cpu_req_ready) $fatal(1, "old line not ready after stale conflict");
    tick(); cpu_req_valid = 0;
    if (!cpu_resp_valid || cpu_resp_data !== 32'h11 || mem_req_valid)
      $fatal(1, "old line did not remain a hit after stale conflict");

    // Flush on exactly the accepting edge is detected before epoch increments.
    reset_cache(); start_miss(32'h90);
    flush = 1; mem_req_ready = 1; mem_resp_data = 32'h77;
    tick();
    flush = 0; flush_epoch = 1; mem_req_ready = 0;
    if (mem_req_valid) $fatal(1, "flush/first-word acceptance issued another request");
    check_no_install(9);

    // Last word and redirect can arrive together: neither install nor respond.
    reset_cache(); start_miss(32'ha0);
    accept_word(32'h11); accept_word(32'h22); accept_word(32'h33);
    flush = 1; mem_req_ready = 1; mem_resp_data = 32'h44;
    tick();
    flush = 0; flush_epoch = 1; mem_req_ready = 0;
    if (mem_req_valid) $fatal(1, "last-word flush did not complete stale request");
    check_no_install(10);
    $display("ICACHE_FLUSH_PASS");
    $finish;
  end
endmodule

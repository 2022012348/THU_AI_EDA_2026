`timescale 1ns/1ps
module tb;
  logic clk=0; always #5 clk=~clk;
  logic rst_n=0;
  wire imem_valid; wire [31:0] imem_addr;
  logic imem_ready=0; logic [31:0] imem_rdata=0;
  wire dmem_valid,dmem_we; wire [31:0] dmem_addr,dmem_wdata;
  wire [3:0] dmem_be; logic dmem_ready=0; logic [31:0] dmem_rdata=0;
  logic [4:0] dbg_reg_addr=0; wire [31:0] dbg_reg_data;
  wire halted; wire [31:0] exit_code;
  wire [2:0] dbg_features; wire dbg_retire_valid; wire [31:0] dbg_retire_pc,dbg_retire_insn;
  wire dbg_bp_resolve,dbg_bp_mispredict,dbg_ooo_issue,dbg_ooo_bypass;
  rv32i5 dut(.*);
  task automatic tick; @(negedge clk); #1; endtask
  initial begin
    tick(); rst_n=1;
    // Isolate the bridge from the pipeline and present a request while the
    // downstream cache is blocked.
    force dut.if_cpu_req_valid = 1'b1;
    force dut.if_cpu_req_addr = 32'h1234;
    force dut.ic_cpu_req_ready = 1'b0;
    force dut.if2id_valid = 1'b0;
    force dut.id2ex_valid = 1'b0;
    force dut.redirect_valid = 1'b0;
    force dut.flush = 1'b0;
    #1;
    if (!dut.if_cpu_req_ready) $fatal(1,"buffer should accept a new IF request");
    tick();
    // Simulate IF deasserting valid because of stall, changing its current
    // address, and a branch appearing while the buffered cache request waits.
    force dut.if_cpu_req_valid = 1'b0;
    force dut.if_cpu_req_addr = 32'h9876;
    force dut.if2id_valid = 1'b1;
    force dut.if2id_insn = 32'h00000063;
    repeat (3) begin
      #1;
      if (!dut.ic_cpu_req_valid || dut.fetch_request_addr !== 32'h1234)
        $fatal(1,"waiting cache request lost valid or changed address");
      tick();
    end
    force dut.ic_cpu_req_ready = 1'b1;
    tick(); #1;
    if (dut.ic_cpu_req_valid) $fatal(1,"accepted request was sent more than once");
    if (dut.if_cpu_req_ready) $fatal(1,"unresolved branch did not stop new sequential fetch");
    // Flush can cancel a queued internal request.
    force dut.if2id_valid = 1'b0; force dut.ic_cpu_req_ready = 1'b0;
    force dut.if_cpu_req_valid = 1'b1; force dut.if_cpu_req_addr = 32'h5550;
    #1; if (!dut.if_cpu_req_ready) $fatal(1,"buffer not ready after cache acceptance");
    tick();
    force dut.if_cpu_req_valid = 1'b0; force dut.flush=1'b1;
    #1; if (dut.ic_cpu_req_valid) $fatal(1,"flush did not cancel queued request");
    tick(); force dut.flush=1'b0; #1;
    if (dut.ic_cpu_req_valid) $fatal(1,"flushed request returned");
    $display("FETCH_REQUEST_PASS");
    $finish;
  end
endmodule

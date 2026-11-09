`timescale 1ns/1ps
// Paired ID/hazard check for the explicitly detected id_stall/id_flush topology.
module tb_l1_id_hazard;
  reg clk = 0;
  always #5 clk = ~clk;
  reg rst_n = 0;
  reg if_id_valid = 0;
  reg [31:0] if_id_pc = 0, if_id_insn = 0;
  reg mem_stall = 0, ex_redirect_valid = 0;
  wire id_valid, id_use_rs1, id_use_rs2, id_ecall;
  wire [4:0] id_rs1, id_rs2;
  wire id_ex_valid, id_ex_mem_read;
  wire [4:0] id_ex_rd;
  wire [31:0] id_ex_insn;
  wire if_stall, if_flush, id_stall, id_flush, ex_stall, halt_pending, flush_event;
  wire if_req_valid;
  wire [31:0] if_req_addr;
`ifdef L1_IF_REDIRECT_GATED
  wire if_redirect_valid = ex_redirect_valid && !mem_stall;
`else
  wire if_redirect_valid = ex_redirect_valid;
`endif
  if_stage if_dut(.clk(clk), .rst_n(rst_n), .if_stall(if_stall), .if_flush(if_flush),
    .redirect_valid(if_redirect_valid), .redirect_pc(32'h00000100),
    .cpu_req_valid(if_req_valid), .cpu_req_addr(if_req_addr), .cpu_req_ready(1'b0),
    .cpu_resp_valid(1'b0), .cpu_resp_data(32'b0));

  id_stage id_dut(
    .clk(clk), .rst_n(rst_n), .if_id_valid(if_id_valid), .if_id_pc(if_id_pc),
    .if_id_insn(if_id_insn), .id_stall(id_stall), .id_flush(id_flush),
`ifdef L1_ID_HAS_MEM_STALL
    .mem_stall(mem_stall),
`endif
    .wb_reg_write(1'b0), .wb_rd(5'b0), .wb_data(32'b0), .dbg_reg_addr(5'b0),
    .id_valid(id_valid), .id_rs1(id_rs1), .id_rs2(id_rs2),
    .id_use_rs1(id_use_rs1), .id_use_rs2(id_use_rs2), .id_ecall(id_ecall),
    .id_ex_valid(id_ex_valid), .id_ex_insn(id_ex_insn),
    .id_ex_mem_read(id_ex_mem_read), .id_ex_rd(id_ex_rd)
  );
  hazard_unit hazard_dut(
    .clk(clk), .rst_n(rst_n), .id_ex_valid(id_ex_valid),
    .id_ex_mem_read(id_ex_mem_read), .id_ex_rd(id_ex_rd),
    .id_valid(id_valid), .id_rs1(id_rs1), .id_rs2(id_rs2),
    .id_use_rs1(id_use_rs1), .id_use_rs2(id_use_rs2), .id_ecall(id_ecall),
    .ex_redirect_valid(ex_redirect_valid), .mem_stall(mem_stall),
    .if_stall(if_stall), .if_flush(if_flush), .id_stall(id_stall), .id_flush(id_flush), .ex_stall(ex_stall),
    .halt_pending(halt_pending), .flush_event(flush_event)
  );

  task tick; begin @(negedge clk); #1; end endtask
  task reset_all; begin
    rst_n = 0; if_id_valid = 0; mem_stall = 0; ex_redirect_valid = 0;
    tick(); tick(); rst_n = 1; tick();
  end endtask

  integer failures = 0;
  task fail(input string name, input string detail);
    begin
      $display("CHECK: %s — %s", name, detail);
      failures = failures + 1;
    end
  endtask

  localparam [31:0] LW_X1 = 32'h00002083;      // lw x1, 0(x0)
  localparam [31:0] ADDI_X2_X1 = 32'h00108113; // addi x2, x1, 1
  localparam [31:0] BEQ_X0_X0 = 32'h00000463;  // beq x0, x0, +8
  initial begin
    reset_all();
    if_id_valid = 1; if_id_insn = LW_X1; if_id_pc = 32'h100;
    tick();
    if (id_ex_valid !== 1'b1 || id_ex_mem_read !== 1'b1 || id_ex_rd !== 5'd1)
      $fatal(1, "CHECK: l1_id_probe_setup — ID failed to latch the load used in the probe");

    // A younger dependent instruction is present while an older MEM operation
    // is stalled. ID/EX must retain its existing instruction and controls.
    if_id_insn = ADDI_X2_X1; if_id_pc = 32'h104; mem_stall = 1;
    #1;
    if (ex_stall !== 1'b1)
      fail("l1_mem_stall_hold", "hazard unit failed to stall EX for older MEM wait");
    repeat (2) begin
      tick();
      if (id_ex_valid !== 1'b1 || id_ex_insn !== LW_X1 || id_ex_rd !== 5'd1 || id_ex_mem_read !== 1'b1)
        fail("l1_mem_stall_hold", "ID/EX did not preserve the held load during MEM stall");
    end

    // Once older MEM releases, the same load-use hazard must hold the younger
    // fetch/decode and inject one bubble into EX, not replay the load forever.
    mem_stall = 0; #1;
    if (if_stall !== 1'b1)
      fail("l1_load_use_bubble", "load-use dependency did not stall younger fetch");
    tick();
    if (id_ex_valid !== 1'b0)
      fail("l1_load_use_bubble", "load-use dependency failed to inject ID/EX bubble");
    tick();
    if (id_ex_valid !== 1'b1 || id_ex_insn !== ADDI_X2_X1)
      fail("l1_load_use_release", "dependent instruction did not advance after the bubble");

    // Redirect from a valid branch in EX coincident with an older MEM stall:
    // the held branch must not be destroyed by the ID flush signal.
    reset_all();
    if_id_valid = 1; if_id_insn = BEQ_X0_X0; if_id_pc = 32'h200;
    tick();
    if (id_ex_valid !== 1'b1 || id_ex_insn !== BEQ_X0_X0)
      $fatal(1, "CHECK: l1_redirect_probe_setup — ID failed to latch the branch used in the probe");
    mem_stall = 1; ex_redirect_valid = 1; if_id_valid = 0; #1;
    if (ex_stall !== 1'b1)
      fail("l1_redirect_mem_stall", "EX did not remain stalled during older MEM wait");
    tick();
    if (id_ex_valid !== 1'b1 || id_ex_insn !== BEQ_X0_X0)
      fail("l1_redirect_mem_stall", "ID/EX lost the branch during simultaneous redirect and older MEM stall");
    // IF/ID can retain the just-recognized ECALL while fetch is stopped.
    // It must enter EX exactly once, even if IF/ID remains valid.
    reset_all();
    if_id_valid = 1; if_id_insn = 32'h00000073; if_id_pc = 32'h300; #1;
    if (id_stall !== 1'b0 || ex_stall !== 1'b0)
      fail("l1_ecall_once", "ECALL cannot enter ID/EX when downstream is ready");
    tick();
    if (halt_pending !== 1'b1 || id_ex_valid !== 1'b1 || id_ex_insn !== 32'h00000073)
      fail("l1_ecall_once", "ECALL did not enter ID/EX exactly once");
    if (flush_event !== 1'b0)
      fail("l1_ecall_once", "held ECALL retriggered halt/flush after halt_pending");
    tick();
    if (ex_stall !== 1'b1 && id_ex_valid !== 1'b0)
      fail("l1_ecall_once", "ECALL remained valid in ID/EX after EX advanced");
    // A redirect cannot revoke an already-presented IF request while an older
    // MEM operation holds the pipeline and defers that redirect.
    reset_all();
    repeat (2) tick();
    if (if_req_valid !== 1'b1 || if_req_addr !== 32'b0)
      $fatal(1, "CHECK: l1_if_probe_setup — IF did not present its initial request");
    mem_stall = 1; ex_redirect_valid = 1; tick();
    if (if_req_valid !== 1'b1 || if_req_addr !== 32'b0)
      fail("l1_if_redirect_mem_stall", "IF changed or withdrew a pending request during older MEM stall");
    if (failures != 0) $fatal(1, "L1_ID_HAZARD_FAILED: %0d checks", failures);
    $display("L1_ID_HAZARD_PASS");
    $finish;
  end
  initial begin #10000; fail("l1_id_hazard_timeout", "directed probe timed out"); end
endmodule

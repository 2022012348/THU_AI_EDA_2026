请实现项目中模块 `id_stage`，写入文件 `rtl/id_stage.sv`。只输出该文件的完整 SystemVerilog RTL，不要输出 Markdown 围栏或解释。

项目计划（必须严格遵守 modules[].interfaces 的端口名/方向/位宽；跨模块信号在该模块中也必须使用同一套名称和宽度，不能自行改名或增删端口）。
语法自检：端口列表已经声明的 output/input 信号不要在模块体内再次用 logic/wire 声明；每个信号只能有一个 driver；不要出现重复声明或多驱动。
{
  "project_name": "rv32i5_pipeline",
  "top_module": "rv32i5",
  "modules": [
    {
      "name": "rv32i5",
      "file": "rtl/rv32i5.sv",
      "description": "Top level: instantiates if/id/ex/mem/wb stages, hazard_unit, forwarding_unit, regfile; wires only, plus final combinational rst_n masking of dmem_valid/dmem_we.",
      "interfaces": "clk: input logic; rst_n: input logic; imem_addr: output logic [31:0]; imem_rdata: input logic [31:0]; dmem_valid: output logic; dmem_we: output logic; dmem_addr: output logic [31:0]; dmem_wdata: output logic [31:0]; dmem_be: output logic [3:0]; dmem_rdata: input logic [31:0]; dbg_reg_addr: input logic [4:0]; dbg_reg_data: output logic [31:0]; halted: output logic; exit_code: output logic [31:0]"
    },
    {
      "name": "if_stage",
      "file": "rtl/if_stage.sv",
      "description": "PC register and instruction fetch. PC priority: reset > halt > redirect > stall > pc+4. Drives imem_addr combinationally from PC; latches imem_rdata into IF outputs.",
      "interfaces": "clk: input logic; rst_n: input logic; halt: input logic; stall: input logic; redirect: input logic; redirect_pc: input logic [31:0]; imem_addr: output logic [31:0]; imem_rdata: input logic [31:0]; if_valid: output logic; if_pc: output logic [31:0]; if_pc_plus4: output logic [31:0]; if_instr: output logic [31:0]"
    },
    {
      "name": "id_stage",
      "file": "rtl/id_stage.sv",
      "description": "Owns IF/ID pipeline register (valid, pc, pc+4, instr). Decodes RV32I subset, generates immediates and all control fields, drives register-file read addresses, detects ECALL and rs1/rs2 usage for the hazard unit. flush clears IF/ID valid, stall holds IF/ID, halt freezes it.",
      "interfaces": "clk: input logic; rst_n: input logic; halt: input logic; flush: input logic; stall: input logic; if_valid: input logic; if_pc: input logic [31:0]; if_pc_plus4: input logic [31:0]; if_instr: input logic [31:0]; rs1_data: input logic [31:0]; rs2_data: input logic [31:0]; rs1_addr: output logic [4:0]; rs2_addr: output logic [4:0]; id_valid: output logic; id_pc: output logic [31:0]; id_pc_plus4: output logic [31:0]; id_rs1_data: output logic [31:0]; id_rs2_data: output logic [31:0]; id_rs1_addr: output logic [4:0]; id_rs2_addr: output logic [4:0]; id_imm: output logic [31:0]; id_rd: output logic [4:0]; id_alu_op: output logic [3:0]; id_alu_a_sel: output logic; id_alu_b_sel: output logic; id_reg_write: output logic; id_is_load: output logic; id_is_store: output logic; id_mem_to_reg: output logic; id_br_op: output logic [2:0]; id_is_branch: output logic; id_is_jal: output logic; id_is_jalr: output logic; id_is_ecall: output logic; id_funct3: output logic [2:0]; id_uses_rs1: output logic; id_"
    },
    {
      "name": "ex_stage",
      "file": "rtl/ex_stage.sv",
      "description": "Owns ID/EX pipeline register. Applies EX operand forwarding (fwd_a/fwd_b), ALU, branch compare and target, JAL/JALR target/link, store data. Emits ex_redirect/ex_redirect_pc and EX/MEM payload (ex_*). flush clears ID/EX valid (bubble). Also exports registered source addresses id_ex_rs1_addr/id_ex_rs2_addr for the forwarding unit.",
      "interfaces": "clk: input logic; rst_n: input logic; halt: input logic; flush: input logic; id_valid: input logic; id_pc: input logic [31:0]; id_pc_plus4: input logic [31:0]; id_rs1_data: input logic [31:0]; id_rs2_data: input logic [31:0]; id_rs1_addr: input logic [4:0]; id_rs2_addr: input logic [4:0]; id_imm: input logic [31:0]; id_rd: input logic [4:0]; id_alu_op: input logic [3:0]; id_alu_a_sel: input logic; id_alu_b_sel: input logic; id_reg_write: input logic; id_is_load: input logic; id_is_store: input logic; id_mem_to_reg: input logic; id_br_op: input logic [2:0]; id_is_branch: input logic; id_is_jal: input logic; id_is_jalr: input logic; id_is_ecall: input logic; id_funct3: input logic [2:0]; fwd_a: input logic [1:0]; fwd_b: input logic [1:0]; ex_mem_alu_result: input logic [31:0]; mem_wb_wdata: input logic [31:0]; id_ex_rs1_addr: output logic [4:0]; id_ex_rs2_addr: output logic [4:0]; ex_redirect: output logic; ex_redirect_pc: output logic [31:0]; ex_valid: output logic; ex_pc_plus4: output "
    },
    {
      "name": "mem_stage",
      "file": "rtl/mem_stage.sv",
      "description": "Owns EX/MEM pipeline register. Drives data-memory request (dmem_valid/we/addr/wdata/be) from EX/MEM fields, masked combinationally by rst_n and ~halt; performs load byte/half/word selection and sign/zero extension. Exports registered EX/MEM fields for forwarding (ex_mem_*) and MEM/WB payload (mem_*).",
      "interfaces": "clk: input logic; rst_n: input logic; halt: input logic; ex_valid: input logic; ex_pc_plus4: input logic [31:0]; ex_alu_result: input logic [31:0]; ex_store_data: input logic [31:0]; ex_rd: input logic [4:0]; ex_reg_write: input logic; ex_is_load: input logic; ex_is_store: input logic; ex_mem_to_reg: input logic; ex_funct3: input logic [2:0]; ex_is_ecall: input logic; dmem_rdata: input logic [31:0]; dmem_valid: output logic; dmem_we: output logic; dmem_addr: output logic [31:0]; dmem_wdata: output logic [31:0]; dmem_be: output logic [3:0]; ex_mem_valid: output logic; ex_mem_alu_result: output logic [31:0]; ex_mem_reg_write: output logic; ex_mem_rd: output logic [4:0]; ex_mem_is_load: output logic; mem_valid: output logic; mem_wdata: output logic [31:0]; mem_rd: output logic [4:0]; mem_reg_write: output logic; mem_is_ecall: output logic"
    },
    {
      "name": "wb_stage",
      "file": "rtl/wb_stage.sv",
      "description": "Owns MEM/WB pipeline register. Produces register-file write port (wb_we, wb_rd, wb_wdata) gated by rd!=0 and ~halted; commits ECALL at the WB clock edge by setting halted=1 and latching exit_code from x10_value. Once halted, MEM/WB holds and all outputs stay stable.",
      "interfaces": "clk: input logic; rst_n: input logic; mem_valid: input logic; mem_wdata: input logic [31:0]; mem_rd: input logic [4:0]; mem_reg_write: input logic; mem_is_ecall: input logic; x10_value: input logic [31:0]; mem_wb_valid: output logic; mem_wb_reg_write: output logic; mem_wb_rd: output logic [4:0]; mem_wb_wdata: output logic [31:0]; wb_we: output logic; wb_rd: output logic [4:0]; wb_wdata: output logic [31:0]; halted: output logic; exit_code: output logic [31:0]"
    },
    {
      "name": "hazard_unit",
      "file": "rtl/hazard_unit.sv",
      "description": "Load-use stall detection and control-hazard flush generation, plus ECALL halt-pending state. Priority: redirect > ECALL halt-pending > load-use stall > PC+4. Emits stall_pc (freeze PC and IF/ID), flush_if_id (clear IF/ID valid) and flush_id_ex (clear ID/EX valid).",
      "interfaces": "clk: input logic; rst_n: input logic; halt: input logic; id_valid: input logic; id_rs1_addr: input logic [4:0]; id_rs2_addr: input logic [4:0]; id_uses_rs1: input logic; id_uses_rs2: input logic; id_is_ecall: input logic; ex_valid: input logic; ex_is_load: input logic; ex_rd: input logic [4:0]; ex_redirect: input logic; stall_pc: output logic; flush_if_id: output logic; flush_id_ex: output logic; halt_pending: output logic"
    },
    {
      "name": "forwarding_unit",
      "file": "rtl/forwarding_unit.sv",
      "description": "Combinational EX operand forwarding select. Priority EX/MEM over MEM/WB; skips rd==0, invalid or non-writing sources, and never forwards an EX/MEM load result. fwd encoding: 2'b00 = ID/EX register value, 2'b01 = EX/MEM alu result, 2'b10 = MEM/WB writeback data.",
      "interfaces": "ex_mem_valid: input logic; ex_mem_reg_write: input logic; ex_mem_rd: input logic [4:0]; ex_mem_is_load: input logic; mem_wb_valid: input logic; mem_wb_reg_write: input logic; mem_wb_rd: input logic [4:0]; id_ex_rs1_addr: input logic [4:0]; id_ex_rs2_addr: input logic [4:0]; fwd_a: output logic [1:0]; fwd_b: output logic [1:0]"
    },
    {
      "name": "regfile",
      "file": "rtl/regfile.sv",
      "description": "32x32 architectural register file with two combinational read ports (write-first bypass from WB), one synchronous WB write port, a combinational debug read port, and a combinationally exported x10 for exit_code capture. x0 is hardwired to zero.",
      "interfaces": "clk: input logic; rst_n: input logic; wb_we: input logic; wb_rd: input logic [4:0]; wb_wdata: input logic [31:0]; rs1_addr: input logic [4:0]; rs1_data: output logic [31:0]; rs2_addr: input logic [4:0]; rs2_data: output logic [31:0]; dbg_addr: input logic [4:0]; dbg_data: output logic [31:0]; x10_value: output logic [31:0]"
    }
  ],
  "notes": "Pipeline registers live inside stages: if_stage owns PC; id_stage owns IF/ID; ex_stage owns ID/EX; mem_stage owns EX/MEM; wb_stage owns MEM/WB. Stage-to-stage nets: id_* (ID->EX inputs), ex_* (EX->MEM inputs), mem_* (MEM->WB inputs); registered copies are ex_mem_* (EX/MEM, exported by mem_stage for forwarding) and mem_wb_* (exported by wb_stage). Control encodings frozen: id_alu_op 0=ADD,1=SUB,2=SLL,3=SLT,4=SLTU,5=XOR,6=SRL,7=SRA,8=OR,9=AND,10=PASS_B(LUI); id_alu_a_sel 0=rs1,1=pc; id_alu_b_sel 0=rs2,1=imm; id_br_op 0=BEQ,1=BNE,2=BLT,3=BGE,4=BLTU,5=BGEU; id_mem_to_reg 0=alu result (also LUI/AUIPC/JAL/JALR, whose link value is forced into ex_alu_result), 1=load data; fwd 2'b00 none, 2'b01 EX/MEM, 2'b10 MEM/WB. EX forces ex_alu_result=pc_plus4 for JAL/JALR so forwarding from EX/MEM is never wrong. Store rs2 dependency is handled by the load-use stall (spec 7.3 permits stalling instead of MEM store-data forwarding), so no MEM-stage store-data mux is implemented. Hazard priority: ex_redirect (flush_if_id+flush_id_ex, PC<=redirect_pc) > ECALL halt-pending (stall_pc+flush_if_id only, ECALL keeps flowing) > load-use (stall_pc + flush_id_ex) > PC+4. halt_pending is set by id_valid&id_is_ecall&~ex_redirect and clears only on reset; halted is produced in wb_stage and fed back as halt to if/id/ex/mem to freeze state after commit; dmem_valid is combinationally masked by rst_n and ~halted inside mem_stage and again at top level."
}

Spec：
# 课后作业：RV32I 五级流水线处理器

> 本文件是独立的 L0 Spec，包含完整实现要求；不需要读取或参考其他 Spec 文件。

## 1. 任务目标

实现一个可综合的 RV32I 五级流水线处理器，顶层模块名为 `rv32i5`。处理器采用分离的指令 / 数据存储器接口（Harvard），每级一拍、无等待状态；外部 testbench 通过固定的顶层端口提供指令与数据存储模型，并通过 `halted` / `exit_code` 观测停机。

必须按 IF / ID / EX / MEM / WB 拆分模块，实现数据前递、load-use 暂停与控制冒险冲刷；不得实现成逐条串行的多周期状态机。

## 2. 顶层接口（固定）

端口名、方向、位宽固定，不得增删或改名；内部子模块端口由实现者自行规划。

```systemverilog
module rv32i5 (
    input  logic        clk,
    input  logic        rst_n,
    output logic [31:0] imem_addr,
    input  logic [31:0] imem_rdata,
    output logic        dmem_valid,
    output logic        dmem_we,
    output logic [31:0] dmem_addr,
    output logic [31:0] dmem_wdata,
    output logic [3:0]  dmem_be,
    input  logic [31:0] dmem_rdata,
    input  logic [4:0]  dbg_reg_addr,
    output logic [31:0] dbg_reg_data,
    output logic        halted,
    output logic [31:0] exit_code
);
```

## 3. 存储器接口语义

### 3.1 指令存储器

- `imem_addr` 为当前 IF 级取指字节地址，低 2 位恒为 0（字对齐）。
- 指令存储器为组合读、零等待：同一拍内 `imem_rdata` 返回 `imem_addr` 所指的 32-bit 指令字。
- IF 级只在时钟沿更新 PC，因此 `imem_addr` 在一拍内保持稳定。
- 程序从地址 0 开始；不要求支持非对齐取指。

### 3.2 数据存储器

- `dmem_valid` 在 MEM 级存在有效 load/store 时拉高恰好一个周期；复位期间及 `halted=1` 期间必须为 0。
- load：`dmem_we=0`，`dmem_addr` 为访存字节地址；`dmem_be`、`dmem_wdata` 不参与写（可为任意值）。
- store：`dmem_we=1`，外部存储器在 `dmem_valid && dmem_we` 的时钟上升沿按 `dmem_be` 逐字节写入。
- `dmem_rdata` 为组合读、零等待：在 `dmem_valid=1` 的整个时钟周期内，`dmem_rdata` 必须等于以 `{dmem_addr[31:2], 2'b00}` 为起始的小端 32-bit 字；load 在 MEM 级当拍末（MEM/WB 寄存器沿）采样，并按 `dmem_addr[1:0]` 选择字节 / 半字并做符号或零扩展。
- `dmem_addr` 在 `dmem_valid=1` 的周期内必须保持稳定。`dmem_valid=0` 时 `dmem_we` / `dmem_addr` / `dmem_wdata` / `dmem_be` 为 don't-care，外部存储模型不得据此写入；`dmem_we` 仅在有效 store 且 `dmem_valid=1` 时为 1。
- `dmem_wdata` 按访问宽度复制到四个字节 lane，`dmem_be` 选择真正写入的 lane（`be[i]` 对应字节地址 `addr[1:0]==i`）：
  - `SW`：`dmem_wdata = store_data[31:0]`，`dmem_be = 4'b1111`
  - `SH`：`dmem_wdata = {2{store_data[15:0]}}`，`dmem_be = dmem_addr[1] ? 4'b1100 : 4'b0011`
  - `SB`：`dmem_wdata = {4{store_data[7:0]}}`，`dmem_be = 4'b0001 << dmem_addr[1:0]`
- 所有 load/store 均自然对齐（`LH/SH` 要求 `addr[0]=0`，`LW/SW` 要求 `addr[1:0]=00`）；程序保证不出现非对齐访问，非对齐行为不作要求。
- 写数据 `store_data` 为经过前递的 `rs2` 值；`SB/SH` 只使用其低位。

### 3.3 调试端口与时钟

- `dbg_reg_addr` 选择架构寄存器 `x0..x31`，`dbg_reg_data` 组合读出其当前值；`x0` 恒读 0；不含前递；只读，不要求调试写端口。
- 单时钟域，`clk` 周期 10 ns（100 MHz），由外部 testbench 驱动。

## 4. 复位与停机协议

- `rst_n` 为同步低有效复位，只在 `clk` 上升沿生效；不实现异步复位。
- 复位沿（采样到 `rst_n=0` 的上升沿）：PC 清零到 `0x0000_0000`、32 个架构寄存器清零、全部流水线 valid 清零、`halted=0`、`exit_code=0`，且不产生任何数据存储器写（`dmem_valid=0`）。
- `rst_n=0` 期间（包括第一个复位上升沿之前）`dmem_valid` 必须为 0；实现应在输出级用 `rst_n` 组合屏蔽已进入 MEM 的 store，避免复位沿写入外部存储器。复位期间不检查 `imem_addr` / `dmem_addr` / `dmem_wdata` / `dmem_be` 的具体值。
- 复位优先于所有控制动作：`rst_n=0` 的上升沿丢弃同拍的分支重定向、`ECALL` 提交和 store 写请求，`halted` / `exit_code` 清零。复位释放后从 PC 0 开始取指。
- `halted` / `exit_code` 是寄存器输出；在 ECALL 提交沿之后（从下一拍起）才要求 `halted=1` 且 `exit_code` 等于最终 `x10`。
- `ECALL`（指令字恰为 `32'h0000_0073`）是本任务唯一的停机约定：它按普通指令流经流水线，不进入异常 / CSR / trap 流程，自身不写寄存器、不访问数据存储器。
- `ECALL` 在 ID 级被识别、且当拍没有更老的控制转移重定向时进入 halt-pending 状态：PC 保持，IF/ID 每拍写入 `valid=0`（后续取到的指令全部丢弃），不得产生新的数据存储器事务；比它更老的指令继续完成并提交。
- 在 halt-pending 期间，`ECALL` 自身必须作为有效指令继续经 EX → MEM → WB 前进，不得在 ID/MEM 级提前置位 `halted`，也不得写寄存器或访问数据存储器。
- 当 `ECALL` 到达 WB 级并在该时钟沿提交时：置 `halted=1`，同时 `exit_code ← x10`。该时刻所有更老指令均已提交，`x10` 已是最终值。
- 若更老的控制转移冲刷掉 ID 级的 `ECALL`，则该 `ECALL` 不产生停机；只有实际提交到 WB 的 `ECALL` 才置位 `halted`。
- `halted=1` 后保持到下一次复位：流水线停止推进（或全部 valid 清零），WB 不得再写寄存器，`dmem_valid=0`，PC 与 `imem_addr` 保持停机时的值；架构寄存器保持稳定，因此同一 `dbg_reg_addr` 下 `dbg_reg_data` 保持稳定，`exit_code` 保持稳定。
- `halted=0` 时 `exit_code=0`；`halted=1` 期间 `exit_code` 稳定等于停机时的 `x10`。

## 5. 指令集范围与语义

仅实现 RV32I 的下列子集，指令均为 32-bit 定长、4 字节对齐。

### 5.1 整数运算 / 逻辑 / 移位

- R 型：`ADD`、`SUB`、`SLL`、`SLT`、`SLTU`、`XOR`、`SRL`、`SRA`、`OR`、`AND`
- I 型：`ADDI`、`SLTI`、`SLTIU`、`XORI`、`ORI`、`ANDI`
- 立即数移位：`SLLI`、`SRLI`、`SRAI`，移位量取 `imm[4:0]`；寄存器移位 `SLL/SRL/SRA` 的移位量取 `rs2[4:0]`
- `SLT/SLTI` 按 32 位补码有符号比较；`SLTU/SLTIU` 按无符号比较（`SLTIU` 的立即数先按标准符号扩展、再按无符号比较）；`SRA/SRAI` 为算术右移。

### 5.2 上位立即数

- `LUI`：`rd = {inst[31:12], 12'b0}`
- `AUIPC`：`rd = pc + {inst[31:12], 12'b0}`，`pc` 为 `AUIPC` 自身的地址。

### 5.3 Load / Store

- Load：`LB`、`LH`、`LW`、`LBU`、`LHU`；Store：`SB`、`SH`、`SW`
- load / store 的有效地址 = 前递后的 `rs1 + sext(imm[11:0])`。
- load 数据按 `funct3` 符号 / 零扩展后写回；store 写数据取自前递后的 `rs2`。

### 5.4 控制转移

- 条件分支：`BEQ`、`BNE`、`BLT`、`BGE`、`BLTU`、`BGEU`；无条件跳转：`JAL`、`JALR`
- 分支条件与跳转目标在 EX 级用前递后的操作数解析；没有分支延迟槽。
- `JAL`：`rd = pc + 4`（`pc` 为 `JAL` 自身地址），目标 = `pc + sext(J 型立即数)`。
- `JALR`：`rd = pc + 4`，目标 = `(rs1 + sext(I 型立即数)) & 32'hFFFF_FFFE`。
- 有效程序保证所有控制转移目标 4 字节对齐（PC[1:0] 恒为 00）。

### 5.5 不支持

- 不支持 `M`/`A`/`F`/`D` 扩展、压缩指令、`FENCE`、CSR、异常、中断和调试指令。
- 除 `ECALL` 外的 system 指令无需实现；非法指令行为不作要求，但不得破坏已定义指令的正确性。

### 5.6 有效程序假设

- 程序从地址 0 开始，并以一条可提交到 WB 的 `ECALL` 结束；因此 `halted` 最终必然出现。
- 所有指令地址、分支目标和跳转目标均 4 字节对齐；load/store 自然对齐且地址位于外部存储模型范围内。
- 不出现非法指令、非对齐访问或越界访问；这些情况的行为不在本 Spec 定义范围内。

## 6. 标准编码、立即数与地址规则

### 6.1 编码

| 类型 | opcode | funct3 / funct7 |
|---|---|---|
| R 型 | `0110011` | ADD `000/0000000`、SUB `000/0100000`、SLL `001/0000000`、SLT `010/0000000`、SLTU `011/0000000`、XOR `100/0000000`、SRL `101/0000000`、SRA `101/0100000`、OR `110/0000000`、AND `111/0000000` |
| I 型 ALU | `0010011` | ADDI `000`、SLTI `010`、SLTIU `011`、XORI `100`、ORI `110`、ANDI `111`；SLLI `001/0000000`、SRLI `101/0000000`、SRAI `101/0100000` |
| Load | `0000011` | LB `000`、LH `001`、LW `010`、LBU `100`、LHU `101` |
| Store | `0100011` | SB `000`、SH `001`、SW `010` |
| Branch | `1100011` | BEQ `000`、BNE `001`、BLT `100`、BGE `101`、BLTU `110`、BGEU `111` |
| JAL | `1101111` | — |
| JALR | `1100111` | `000` |
| LUI | `0110111` | — |
| AUIPC | `0010111` | — |
| ECALL | `1110011` | 指令字恰为 `32'h0000_0073` |

### 6.2 立即数格式（均按 RV32I 标准）

- I 型：`imm = sext(inst[31:20])`；S 型：`imm = sext({inst[31:25], inst[11:7]})`
- B 型：`imm = sext({inst[31], inst[7], inst[30:25], inst[11:8], 1'b0})`
- U 型：`imm = {inst[31:12], 12'b0}`；J 型：`imm = sext({inst[31], inst[19:12], inst[20], inst[30:21], 1'b0})`

### 6.3 访存与字节 lane

- 小端：字节地址 `a` 的数据位于 `dmem_rdata` 的 `[8*a[1:0] +: 8]`。
- 扩展规则：`LB/LBU` 取 `dmem_rdata` 的一个字节，`LH/LHU` 取由 `addr[1]` 选中的半字，`LW` 取整字；`LB/LH` 符号扩展，`LBU/LHU` 零扩展。
- 字节使能与 `dmem_wdata` 的复制规则见 §3.2。

### 6.4 分支 / 跳转目标

- Taken 条件：`BEQ` 为 `rs1==rs2`、`BNE` 为 `rs1!=rs2`；`BLT/BGE` 按补码有符号比较；`BLTU/BGEU` 按无符号比较。
- 分支目标 = 分支指令 PC + B 型立即数；`JAL` 目标 = PC + J 型立即数；`JALR` 目标 = `(rs1 + I 型立即数) & 32'hFFFF_FFFE`。
- 链接地址 = 跳转指令 PC + 4。
- `x0` 恒为 0：读恒为 0，任何写 `x0` 的结果被丢弃；`rd=x0` 不产生写回、前递或 load-use 暂停。

## 7. 五级流水线与冒险处理

### 7.1 各级职责

| 级 | 职责 |
|---|---|
| IF | 维护 PC，驱动 `imem_addr`，锁存 `imem_rdata`；重定向后从目标取指 |
| ID | 译码、读寄存器堆、生成立即数与全部控制信号；识别 `ECALL` |
| EX | 操作数前递、ALU 运算、分支判断与目标计算、`JAL/JALR` 目标与链接值、store data 准备 |
| MEM | load/store 访问 `dmem`；load 数据选择与扩展；store data 前递 |
| WB | 写回寄存器堆（`rd!=0` 才生效）；`ECALL` 提交并置 `halted` |

- 所有控制判断都必须以源级 `valid=1` 为前提：Taken 分支、`JAL`/`JALR` 重定向、`ECALL` 识别、load-use 暂停、前递命中均不得被无效流水线项触发。
- MEM/WB 寄存器保存最终写回值，EX 级 MEM/WB 前递直接使用该值。写回数据选择如下：

| 指令类别 | WB 写回数据 |
|---|---|
| ALU 型、`LUI` | ALU 结果（`LUI` 为 `inst[31:12] << 12`） |
| `AUIPC` | `pc + {inst[31:12], 12'b0}` |
| `LB/LH/LW/LBU/LHU` | MEM 级按字节/半字选择并扩展后的 load 数据 |
| `JAL/JALR` | 跳转指令 `pc + 4` |

- `wb_stage` 至少负责写回数据选择、寄存器堆写使能、`rd=x0` 丢弃以及 `halted` / `exit_code` 寄存器。
- 性能要求：直线 ALU 程序应达到稳态 CPI = 1；load-use 最多暂停 1 拍；Taken 控制转移最多 2 个 bubble；不得实现为逐条多周期串行状态机。
- 每个流水线寄存器均携带 valid 位；bubble / flush 一律通过清除 valid 实现，不依赖数据值。
- 流水线寄存器至少携带：PC、PC+4、指令、`rs1/rs2` 值与编号、立即数、ALU/访存/写回控制、目标寄存器号、valid。
- 每级每拍推进；PC 更新优先级为：复位 > 控制转移重定向 > `ECALL` 停机冻结 > load-use 暂停 > `PC+4`。
- 除 load-use 暂停与重定向冲刷外不得停顿，不允许逐条多周期执行。

### 7.2 数据前递

- EX 级两个源操作数 `rs1`、`rs2` 需从 EX/MEM 与 MEM/WB 前递；`x0` 不参与前递。
- 前递条件：来源有效、`reg_write=1`、`rd != 0`、且 `rd` 等于 EX 级源寄存器号。
- 优先级：EX/MEM 高于 MEM/WB。
- EX/MEM 中的 load 结果不可用于 EX 前递（load 数据在 MEM 级末才有效）；load-use 暂停保证 load 结果总是经 MEM/WB 前递。
- store data 在 MEM 级前递：若 MEM/WB 有效且其 `rd` 等于 store 的 `rs2`（且非 0、写回有效），则 `store_data` 取 MEM/WB 的写回值，否则取 EX/MEM 传来的 `rs2` 值。
- 分支比较、`JALR` 的 `rs1`、store 地址计算均使用前递后的值。
- 寄存器堆写回在 WB 级时钟沿生效；同一拍 ID 读口与 WB 写口命中同一寄存器时，读口必须返回正在写入的新值（写优先，或等价的旁路），以保证间隔 ≥3 条指令的 RAW 依赖正确。

### 7.3 Load-use 冒险

- 若 EX 级是有效 load（将在 MEM 级产生 `dmem_valid`、`rd != 0`），且 ID 级有效指令的 `rs1` 或 `rs2` 等于该 `rd`（store 的 `rs2` 见下条），则暂停一拍：冻结 PC 与 IF/ID、清除 ID/EX 的 valid（插入 bubble），不冲刷更老指令。
- 暂停解除后 load 已到 MEM/WB，通过 MEM/WB 前递供 EX 使用。
- store 的 `rs2` 依赖可用 MEM 级 store data 前递消除而不暂停；若实现仍按上条暂停，同样正确，但写出数据必须正确。
- 同一拍同时发生重定向与 load-use 暂停时，重定向优先：被暂停的指令在目标路径重新取指。

### 7.4 控制冒险

- 分支、`JAL`、`JALR` 在 EX 级解析。判定 Taken（`JAL/JALR` 恒 Taken）时：下一拍 PC 更新为目标地址，并在该时钟沿清除 IF/ID 与 ID/EX 的 valid，使更年轻的 IF、ID 两级指令不产生任何架构副作用。
- 无分支延迟槽；Taken 转移最多产生 2 个 bubble（IF、ID 两级），Not-Taken 分支不产生额外 bubble。
- `JALR` 目标依赖前递后的 `rs1`；分支 / `JAL` 目标由 EX 级 PC 与立即数计算，均在下一拍取指前给出。

## 8. 模块与文件划分

```text
rtl/rv32i5.sv           module rv32i5             // 顶层
rtl/if_stage.sv         module if_stage
rtl/id_stage.sv         module id_stage
rtl/ex_stage.sv         module ex_stage
rtl/mem_stage.sv        module mem_stage
rtl/wb_stage.sv         module wb_stage
rtl/hazard_unit.sv      module hazard_unit         // load-use 暂停 / 控制冒险 flush
rtl/forwarding_unit.sv  module forwarding_unit     // EX/MEM、MEM/WB 前递选择
```

- 上述 8 个文件必须存在、模块名一致，并由顶层 `rv32i5` 实例化使用。
- 内部端口由 Planner 在规划阶段一次性冻结；各 stage 文件之间使用同一套端口名、位宽与 valid 语义，Coder 按冻结接口逐文件实现。顶层只负责例化与连线。
- 可增加辅助模块 / 文件（如 ALU、立即数生成、寄存器堆），但不得把全部逻辑塞进顶层单个模块。
- 允许将寄存器堆放在 `id_stage` 内，或将 ALU 独立成模块；流水线寄存器建议归属于各 stage 模块。

## 9. 实现约束

- 仅使用可综合的 SystemVerilog 子集：`logic`、`always_ff`、`always_comb`、`localparam`、`function` 等；所有时序状态在 `always_ff @(posedge clk)` 中更新。
- 不使用异步复位、锁存器、`initial`、DPI、`$readmemh`、延时、外部 IP；RTL 中不使用 `include`、`package` 或 `import`（避免 Yosys/Icarus 行为分叉，跨文件常量用 `localparam` 或 parameter 传递）。
- 面向 Yosys 前端：`function` 内不使用 `return`，用过程赋值给出返回值。
- 位宽显式：立即数扩展、比较、移位均按 RV32I 语义处理，避免隐式截断。
- 面积 / 功耗优先：不做不必要的大位宽复制、不保留无用流水字段，组合路径保持简单。
- 交付为 `rtl/` 下上述文件；代码需可被 Icarus Verilog 编译、被 Yosys 综合。

## Parser 补充与修正（优先于上文冲突内容）

## 实现假设（非阻断）

- 内部 stage 端口名、位宽、valid 语义及流水线寄存器归属由 Planner 一次性冻结；Coder 按冻结接口实现，顶层仅例化连线。
- Halt-pending 期间：PC 冻结在取到 ECALL 后的当前值；IF/ID 每拍写入 valid=0；ECALL 自身继续 ID→EX→MEM→WB 前进；更年轻指令不得产生寄存器写、dmem 事务或控制重定向。
- `halted` / `exit_code` 为寄存器输出：ECALL 在 WB 沿提交时置 `halted=1` 并从当时 `x10` 锁存 `exit_code`；TB 可在下一拍起采样。
- `dbg_reg_data` 为组合读架构寄存器堆（x0 恒 0，不包含前递）；TB 在时钟沿后采样其稳定值。
- 允许 WB→ID 同拍写读旁路；具体实现方式（写优先或显式 bypass）由 Coder 选择。
- store 的 rs2 依赖既可用 MEM 级 store-data 前递消除，也可保守暂停一拍；两者均满足 Spec，由 Coder 选择。
- 外部 TB 提供零等待组合读的 imem/dmem，并在至少一个上升沿保持 `rst_n=0`；RTL 必须在输出级用 `rst_n` 组合屏蔽 `dmem_valid` 及 store 写请求。
- 面积/功耗优化、是否独立 ALU 模块、寄存器堆放置位置等由 Coder 选择；§8 要求的 8 个文件及模块名必须存在并由顶层使用。

本模块说明：Owns IF/ID pipeline register (valid, pc, pc+4, instr). Decodes RV32I subset, generates immediates and all control fields, drives register-file read addresses, detects ECALL and rs1/rs2 usage for the hazard unit. flush clears IF/ID valid, stall holds IF/ID, halt freezes it.
本模块接口契约：clk: input logic; rst_n: input logic; halt: input logic; flush: input logic; stall: input logic; if_valid: input logic; if_pc: input logic [31:0]; if_pc_plus4: input logic [31:0]; if_instr: input logic [31:0]; rs1_data: input logic [31:0]; rs2_data: input logic [31:0]; rs1_addr: output logic [4:0]; rs2_addr: output logic [4:0]; id_valid: output logic; id_pc: output logic [31:0]; id_pc_plus4: output logic [31:0]; id_rs1_data: output logic [31:0]; id_rs2_data: output logic [31:0]; id_rs1_addr: output logic [4:0]; id_rs2_addr: output logic [4:0]; id_imm: output logic [31:0]; id_rd: output logic [4:0]; id_alu_op: output logic [3:0]; id_alu_a_sel: output logic; id_alu_b_sel: output logic; id_reg_write: output logic; id_is_load: output logic; id_is_store: output logic; id_mem_to_reg: output logic; id_br_op: output logic [2:0]; id_is_branch: output logic; id_is_jal: output logic; id_is_jalr: output logic; id_is_ecall: output logic; id_funct3: output logic [2:0]; id_uses_rs1: output logic; id_

RV32I L1/L2 implementation hard checks:
- One-cycle response pulses: if a cache/bus producer asserts resp_valid for one cycle, the consumer must capture resp_valid unconditionally before checking a wait/ready flag; never rely on a wait flag that is set only on the following cycle.
- Stall/freeze: while load_use_stall, mem_stall, or structural stall is active, hold IF/ID valid and ID/EX valid; never clear a valid instruction just because the downstream stage is stalled.
- ECALL/halt: ECALL must stay valid through ID -> EX -> MEM -> WB while stalls are active; only WB may set halted/exit_code. Do not drop an ECALL that is waiting in IF/ID while ID is frozen.
- Cache word lanes: for a 128-bit line, word selection is wsel*32 bits, e.g. line_data[{wsel,5'b00000} +: 32], not wsel*4 bit.
- Store merge: write-through store hit must merge only byte-enable lanes into the line; store miss should either merge the requested word explicitly or invalidate the line (no-write-allocate) so a later load refills correct data.
- Cache line refill: never abort an already-issued external refill before ready; hold valid/address stable until ready, finish all words, then install valid/tag/data (a redirect may suppress only the response, not destroy the line).
- I-Cache refill word3: use the current last memory response for word3, not an old/empty refill register.
- Forwarding: implement BOTH EX/MEM (fwd=2'b10) and MEM/WB (fwd=2'b01) paths; JAL/JALR EX/MEM result must select pc4/pc according to wb_sel, never blindly forward ALU result.
- Halt/reset: synchronous active-low reset, dmem_valid=0 during reset; halted/exit_code are registered and stable after ECALL commits.


RV32I L1 tactical patterns (use these structures; keep interfaces from the plan):
1) IF response / stall:
  always_ff @(posedge clk) begin
    if (!rst_n) ...
    else if (redirect_valid) ...
    else if (ecall_in_id && !halt_pending && !mem_stall) begin
      halt_pending <= 1'b1; req_pending <= 1'b0; end
    else if (cpu_resp_valid) begin
      if2id_valid<=1; if2id_pc<=pc; if2id_pc4<=pc+4; if2id_insn<=cpu_resp_data;
      pc<=pc+4; req_pending<=1; end
    else if (stall) begin if2id_valid<=if2id_valid; end
    else begin if (req_pending && cpu_req_ready) begin req_pending<=0; if2id_valid<=0; end end
  end
  Never put a stall branch before the one-cycle cpu_resp_valid branch, and never clear if2id_valid on stall.
2) MEM response:
  if (mem_active) begin
    if (cpu_resp_valid) begin mem2wb_valid<=1; ...; mem_active<=0; mem_wait_resp<=0; end
    else if (!mem_wait_resp && cpu_req_ready) mem_wait_resp<=1;
  end
3) DCache word/store:
  assign hit_word = line_data[{wsel,5'b00000} +: 32];
  // store hit: merge only enabled bytes into the selected word, then write back
  // store miss: do not claim a valid line with stale data; either merge the refilled word
  // or invalidate the line and refill on the next load.
4) ICache refill:
  // do not return state to IDLE on flush. Keep mem_req_valid/addr stable until mem_req_ready.
  // On the last word always install valid/tag/data; gate only resp_valid_r/resp_data_r
  // with flush_epoch==refill_epoch. For refill_word==3 use the current mem_resp_data.
5) EX forwarding:
  rs1_fwd = id2ex_rs1_val;
  if (fwd_a==2'b10) rs1_fwd = ex2mem_result;       // EX/MEM ALU result
  else if (fwd_a==2'b01) rs1_fwd = mem2wb_wdata;   // MEM/WB result
  // same for rs2; ex2mem_result for JAL/JALR must be pc4, not the address ALU output.
6) Halt: only WB sees mem2wb_valid && mem2wb_is_ecall and sets halted/exit_code; preserve is_ecall through stall.

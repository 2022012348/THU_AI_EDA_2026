"""The IF boundary probe must follow the actual top-level redirect wiring."""
import unittest
from ai_eda.agent.skills.l1_id_hazard_probe import _redirect_is_gated

IF = '''module if_stage(input logic clk, input logic rst_n, input logic if_stall,
 input logic if_flush, input logic redirect_valid, input logic [31:0] redirect_pc,
 output logic cpu_req_valid, output logic [31:0] cpu_req_addr, input logic cpu_req_ready,
 input logic cpu_resp_valid, input logic [31:0] cpu_resp_data); endmodule'''

class IfRedirectWiringTests(unittest.TestCase):
    def check_wiring(self, expression, extra=''):
        plan={'top_module':'top','modules':[{'name':'top','file':'rtl/top.sv'}, {'name':'if_stage','file':'rtl/if.sv'}]}
        top=f'module top; hazard_unit h(.ex_redirect_valid(redir), .mem_stall(stall)); if_stage i(.redirect_valid({expression})); {extra} endmodule'
        return _redirect_is_gated(plan, {'rtl/top.sv':top, 'rtl/if.sv':IF})

    def test_direct(self):
        self.assertIs(self.check_wiring('redir')[0],False)

    def test_guarded_expression_and_alias(self):
        self.assertIs(self.check_wiring('redir && !stall')[0],True)
        self.assertIs(self.check_wiring('guarded','assign guarded = redir && !stall;')[0],True)
        self.assertIs(self.check_wiring('guarded','assign guarded = redir & ~stall;')[0],True)

    def test_unknown_gate_is_not_guessed(self):
        self.assertIsNone(self.check_wiring('unknown')[0])

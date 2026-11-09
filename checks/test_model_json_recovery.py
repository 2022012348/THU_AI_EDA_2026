import unittest
from ai_eda.agent.subagents.common import extract_json_payload


class ModelJsonRecoveryTests(unittest.TestCase):
    def test_extra_closing_delimiters_after_complete_object(self):
        answer = '{"files":[{"path":"rtl/a.sv","content":"module a; endmodule"}],"notes":"ok"}]}'
        self.assertEqual(extract_json_payload(answer)['notes'], 'ok')

    def test_does_not_silently_accept_second_json_object(self):
        with self.assertRaises(ValueError):
            extract_json_payload('{"a":1}{"b":2}')

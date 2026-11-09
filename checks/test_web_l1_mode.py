import unittest
from ai_eda.web.server import _agent_options


class WebL1ModeTests(unittest.TestCase):
    def test_reference_mode_is_explicitly_configurable(self):
        self.assertTrue(_agent_options({"project_id": "rv32i5_cache"})["use_l1_reference"])
        self.assertFalse(_agent_options({"project_id": "rv32i5_cache", "use_l1_reference": False})["use_l1_reference"])
        with self.assertRaises(ValueError):
            _agent_options({"use_l1_reference": "false"})

    def test_selected_tester_round_requires_resume_and_positive_integer(self):
        self.assertEqual(_agent_options({"resume_from": "agent-test", "resume_tester_attempt": 7})["resume_tester_attempt"], 7)
        for request in ({"resume_tester_attempt": 7}, {"resume_from": "agent-test", "resume_tester_attempt": True}, {"resume_from": "agent-test", "resume_tester_attempt": 0}):
            with self.assertRaises(ValueError):
                _agent_options(request)

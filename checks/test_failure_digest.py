"""Offline checks for the failure digest that heads every Modifier prompt."""

import unittest

from ai_eda.agent.subagents.modifier import _bus_counts, _failure_digest


class FailureDigestTests(unittest.TestCase):
    def test_empty_report_produces_no_digest(self):
        self.assertEqual(_failure_digest({}), "")
        self.assertEqual(_failure_digest({"checks": []}), "")

    def test_counts_are_ranked_and_carry_the_sample_detail(self):
        report = {
            "checks": [
                {"name": "t08_store_fwd", "detail": "x5 期望 0x7ab 得到 0xa5a5a5a5"},
                {"name": "t08_store_fwd", "detail": "x6 期望 0xffffffff 得到 0x7ab"},
                {"name": "t11_halt", "detail": "x10 期望 0xab 得到 0x00"},
            ]
        }
        digest = _failure_digest(report)
        first, second = digest.splitlines()[1:3]
        self.assertIn("t08_store_fwd x2", first)
        self.assertIn("x5 期望 0x7ab", first)
        self.assertIn("t11_halt x1", second)

    def test_bus_counts_are_attached_to_each_failing_test(self):
        report = {
            "checks": [{"name": "t08_store_fwd", "detail": "x5 期望 0x7ab 得到 0xa5a5a5a5"}],
            "data_bus_observation": {
                "status": "observed",
                "tests": [
                    {
                        "test": "t08_store_fwd",
                        "summary": {
                            "reads": "8", "writes": "4", "retired_loads": "5",
                            "retired_stores": "2", "retired": "17",
                            "adjacent_same": "3", "waiting_cycles": "0",
                        },
                    },
                    {"test": "unrelated_case", "summary": {"reads": "1"}},
                ],
            },
        }
        digest = _failure_digest(report)
        self.assertIn("D 总线", digest)
        self.assertIn("写=4", digest)
        self.assertIn("相邻重复退休=3", digest)
        # Only the failing test's counters are attached, not every observed test.
        self.assertNotIn("unrelated_case", digest)

    def test_bus_counts_tolerate_flat_records(self):
        """Older observers put the counters at the top level, not under summary."""
        counts = _bus_counts(
            {"data_bus_observation": {"tests": [{"test": "t01", "reads": 3, "writes": 1}]}}
        )
        self.assertEqual(counts, {"t01": "读=3 写=1"})

    def test_missing_observation_is_not_an_error(self):
        self.assertEqual(_bus_counts({}), {})
        self.assertEqual(_bus_counts({"data_bus_observation": None}), {})


if __name__ == "__main__":
    unittest.main()

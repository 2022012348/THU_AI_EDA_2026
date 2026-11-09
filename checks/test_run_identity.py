import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ai_eda.agent import orchestrator


class RunIdentityTests(unittest.TestCase):
    def test_concurrent_timestamp_collision_retries_without_overwriting(self):
        class FixedDate:
            @classmethod
            def now(cls, *args):
                return cls()
            def strftime(self, fmt):
                return "20261027T153830370344"
        class Identifier:
            def __init__(self, value): self.hex = value
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(orchestrator, "AGENT_RUNS_ROOT", Path(tmp)), \
             patch.object(orchestrator, "datetime", FixedDate), \
             patch.object(orchestrator.uuid, "uuid4", side_effect=[Identifier("same"), Identifier("same"), Identifier("new")]):
            first, first_dir = orchestrator._create_run_directory()
            (first_dir / "marker").write_text("preserved")
            second, second_dir = orchestrator._create_run_directory()
            self.assertNotEqual(first, second)
            self.assertEqual((first_dir / "marker").read_text(), "preserved")
            self.assertTrue(second_dir.is_dir())

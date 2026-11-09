"""Directed L1 cache redirect/refill regression using Icarus Verilog."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"), "Icarus Verilog unavailable")
class ICacheRedirectTests(unittest.TestCase):
    def test_refill_redirect_and_hit_response(self):
        with tempfile.TemporaryDirectory(prefix="eda-icache-test-") as tmp:
            binary = Path(tmp) / "test.vvp"
            subprocess.run(
                ["iverilog", "-g2012", "-s", "tb", "-o", str(binary),
                 str(ROOT / "checks/rtl/icache_flush_tb.sv"),
                 str(ROOT / "content/agent/skills/rv32i5_l1_reference/icache.sv")],
                check=True, capture_output=True, text=True, timeout=20,
            )
            result = subprocess.run(["vvp", str(binary)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("ICACHE_FLUSH_PASS", result.stdout)

    def test_fetch_request_survives_stall_and_branch(self):
        with tempfile.TemporaryDirectory(prefix="eda-fetch-test-") as tmp:
            binary = Path(tmp) / "test.vvp"
            files = sorted((ROOT / "content/agent/skills/rv32i5_l1_reference").glob("*.sv"))
            subprocess.run(
                ["iverilog", "-g2012", "-s", "tb", "-o", str(binary),
                 str(ROOT / "checks/rtl/fetch_request_tb.sv"), *(str(f) for f in files)],
                check=True, capture_output=True, text=True, timeout=20,
            )
            result = subprocess.run(["vvp", str(binary)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("FETCH_REQUEST_PASS", result.stdout)

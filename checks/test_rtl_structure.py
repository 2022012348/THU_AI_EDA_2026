import shutil
import tempfile
import unittest
from pathlib import Path

from ai_eda.agent.skills.rtl_structure import inspect_rtl_structure


@unittest.skipUnless(shutil.which('yosys'), 'yosys is required')
class StructuralEvidenceTests(unittest.TestCase):
    def test_undriven_signal_is_reported_without_changing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'generated.sv'
            rtl = 'module core(output wire value); wire missing; assign value=missing; endmodule\n'
            source.write_text(rtl)
            report = inspect_rtl_structure(source, 'core', root / 'check')
            self.assertEqual(report['status'], 'completed')
            self.assertTrue(any('no driver' in issue for issue in report['issues']))
            self.assertEqual(source.read_text(), rtl)
            self.assertTrue((root / 'check/yosys.log').is_file())

    def test_valid_design_is_not_labelled_as_a_behavioral_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'generated.sv'
            source.write_text('module core(input wire a, output wire y); assign y=a; endmodule')
            report = inspect_rtl_structure(source, 'core', root / 'check')
            self.assertEqual(report['issues'], [])
            self.assertNotIn('passed', report)

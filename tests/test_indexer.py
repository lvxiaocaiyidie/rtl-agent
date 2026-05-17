import unittest
from pathlib import Path

from rtl_agent.indexer import build_index
from rtl_agent.parser import _looks_like_reset
from rtl_agent.reports import run_basic_checks


class IndexerTests(unittest.TestCase):
    def test_tiny_soc_index(self):
        index = build_index(Path("examples/tiny_soc"))
        self.assertIn("soc_top", index.modules)
        self.assertIn("axi_fabric", index.modules)
        self.assertIn("llc_slice", index.modules)
        self.assertEqual(index.top_modules, ["soc_top"])
        self.assertEqual(len(index.modules["soc_top"].instances), 2)

    def test_tiny_soc_checks_run(self):
        index = build_index(Path("examples/tiny_soc"))
        findings = run_basic_checks(index)
        self.assertIsInstance(findings, list)

    def test_reset_name_boundaries(self):
        self.assertTrue(_looks_like_reset("pad_cpu_rst_b"))
        self.assertTrue(_looks_like_reset("rst_n"))
        self.assertFalse(_looks_like_reset("hburst"))
        self.assertFalse(_looks_like_reset("awburst_s1"))


if __name__ == "__main__":
    unittest.main()

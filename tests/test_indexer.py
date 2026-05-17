import unittest
from pathlib import Path

from rtl_agent.indexer import build_index
from rtl_agent.parser import _looks_like_reset
from rtl_agent.reducer import reduced_design_dict
from rtl_agent.reports import run_basic_checks


class IndexerTests(unittest.TestCase):
    def test_tiny_soc_index(self):
        index = build_index(Path("examples/tiny_soc"))
        self.assertIn("soc_top", index.modules)
        self.assertIn("axi_fabric", index.modules)
        self.assertIn("llc_slice", index.modules)
        self.assertEqual(index.top_modules, ["soc_top"])
        self.assertEqual(index.candidate_top_modules, ["soc_top"])
        self.assertEqual(set(index.reachable_modules), {"soc_top", "axi_fabric", "llc_slice"})
        self.assertEqual(len(index.modules["soc_top"].instances), 2)

    def test_explicit_top_limits_reachable_hierarchy(self):
        index = build_index(Path("examples/tiny_soc"), top=["axi_fabric"])
        self.assertEqual(index.top_modules, ["axi_fabric"])
        self.assertEqual(index.reachable_modules, ["axi_fabric"])
        self.assertIn("soc_top", index.orphan_modules)

    def test_tiny_soc_checks_run(self):
        index = build_index(Path("examples/tiny_soc"))
        findings = run_basic_checks(index)
        self.assertIsInstance(findings, list)

    def test_reset_name_boundaries(self):
        self.assertTrue(_looks_like_reset("pad_cpu_rst_b"))
        self.assertTrue(_looks_like_reset("rst_n"))
        self.assertFalse(_looks_like_reset("hburst"))
        self.assertFalse(_looks_like_reset("awburst_s1"))

    def test_reducer_keeps_interface_stubs_for_omitted_modules(self):
        index = build_index(Path("examples/tiny_soc"), top=["soc_top"])
        reduced = reduced_design_dict(index, max_modules=1, max_interface_stubs=4)
        self.assertEqual([module["name"] for module in reduced["modules"]], ["soc_top"])
        stub_names = {stub["name"] for stub in reduced["interface_stubs"]}
        self.assertEqual(stub_names, {"axi_fabric", "llc_slice"})
        axi_stub = next(stub for stub in reduced["interface_stubs"] if stub["name"] == "axi_fabric")
        self.assertTrue(any("m_awvalid" in port for port in axi_stub["ports"]))


if __name__ == "__main__":
    unittest.main()

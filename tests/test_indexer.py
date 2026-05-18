import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rtl_agent.indexer import build_index
from rtl_agent.llm import LLMConfig, get_api_key
from rtl_agent.modeler import build_rtl_model
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
        from rtl_agent.parser import _looks_like_clock

        self.assertTrue(_looks_like_clock("forever_cpuclk"))
        self.assertTrue(_looks_like_clock("SCK"))
        self.assertFalse(_looks_like_clock("axim_clk_en"))
        self.assertFalse(_looks_like_clock("ipctrl_pipe_vld_for_gateclk"))

    def test_reducer_keeps_interface_stubs_for_omitted_modules(self):
        index = build_index(Path("examples/tiny_soc"), top=["soc_top"])
        reduced = reduced_design_dict(index, max_modules=1, max_interface_stubs=4)
        self.assertEqual([module["name"] for module in reduced["modules"]], ["soc_top"])
        stub_names = {stub["name"] for stub in reduced["interface_stubs"]}
        self.assertEqual(stub_names, {"axi_fabric", "llc_slice"})
        axi_stub = next(stub for stub in reduced["interface_stubs"] if stub["name"] == "axi_fabric")
        self.assertTrue(any("m_awvalid" in port for port in axi_stub["ports"]))

    def test_positional_instance_does_not_trigger_named_port_rule(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "top.sv").write_text(
                """
module child(clk, rst_n, a, b);
input clk;
input rst_n;
input a;
output b;
endmodule

module top(input clk, input rst_n, input a, output b);
  child u_child(clk, rst_n, a, b);
endmodule
""",
                encoding="utf-8",
            )
            index = build_index(root, top=["top"])
            self.assertEqual(index.modules["top"].instances[0].connection_style, "positional")
            findings = run_basic_checks(index)
            self.assertFalse(any(finding.rule_id == "RTL002" for finding in findings))

    def test_multiple_ports_on_one_declaration_line(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "top.sv").write_text(
                """
module top(
  input clk, resetn,
  output reg trap
);
endmodule
""",
                encoding="utf-8",
            )
            index = build_index(root, top=["top"])
            self.assertEqual({port.name for port in index.modules["top"].ports}, {"clk", "resetn", "trap"})
            self.assertIn("clk", index.modules["top"].clocks)
            self.assertIn("resetn", index.modules["top"].resets)

    def test_env_file_with_bom_is_supported(self):
        with TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env.local"
            env_path.write_text("\ufeffOPENAI_API_KEY=dummy-bom-key\n", encoding="utf-8")
            config = LLMConfig(env_file=str(env_path))
            self.assertEqual(get_api_key(config), "dummy-bom-key")

    def test_critical_clock_reset_tieoff_is_reported(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "top.sv").write_text(
                """
module child(clk, rst_n, a, b);
input clk;
input rst_n;
input a;
output b;
endmodule

module top(input clk, input rst_n, input a, output b);
  child u_child(.clk(1'b0), .rst_n(), .a(a), .b(b));
endmodule
""",
                encoding="utf-8",
            )
            index = build_index(root, top=["top"])
            findings = run_basic_checks(index)
            self.assertTrue(any(finding.rule_id == "RTL006" for finding in findings))

    def test_layered_model_l2_contains_review_queries(self):
        index = build_index(Path("examples/tiny_soc"), top=["soc_top"])
        model = build_rtl_model(index, level="l2", max_modules=5)
        self.assertEqual(model["level"], "l2")
        self.assertIn("components", model)
        self.assertIn("integration_intent", model)


if __name__ == "__main__":
    unittest.main()

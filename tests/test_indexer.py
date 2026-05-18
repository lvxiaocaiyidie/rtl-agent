import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rtl_agent.indexer import build_index
from rtl_agent.contracts import build_contract_graph
from rtl_agent.interrupts import build_interrupt_graph
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

    def test_interrupt_contract_graph_tracks_vector_aggregation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "top.sv").write_text(
                """
module cpu(input clk, input [31:0] irq);
endmodule

module top(input clk, input irq_5, input irq_6);
  localparam ENABLE_IRQ = 1;
  reg [31:0] irq;
  reg [5:0] regfile_size;
  wire [31:0] status_rdata;
  always @* begin
    regfile_size = ENABLE_IRQ ? 32 : 16;
    status_rdata = irq;
    irq = 0;
    irq[5] = irq_5;
    irq[6] = irq_6;
  end
  cpu u_cpu(.clk(clk), .irq(irq));
endmodule
""",
                encoding="utf-8",
            )
            index = build_index(root, top=["top"])
            graph = build_interrupt_graph(index, root=root)
            edges = {(edge.source, edge.target, edge.kind) for edge in graph.edges}
            self.assertIn(("top.irq_5", "top.irq[5]", "aggregates_bit"), edges)
            self.assertIn(("top.irq", "cpu.irq", "instance_connection"), edges)
            self.assertIn(("top.irq", "top.status_rdata", "state_observation"), edges)
            self.assertNotIn(("top.ENABLE_IRQ", "top.regfile_size", "state_observation"), edges)

    def test_contract_graph_merges_tables_with_rtl_interrupts(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "top.sv").write_text(
                """
module cpu(input [31:0] irq);
endmodule

module top(input spi_irq);
  reg [31:0] irq;
  wire [31:0] irq_status_rdata;
  always @* begin
    irq = 0;
    irq[6] = spi_irq;
    irq_status_rdata = irq;
  end
  cpu u_cpu(.irq(irq));
endmodule
""",
                encoding="utf-8",
            )
            interrupt_csv = root / "interrupts.csv"
            interrupt_csv.write_text(
                "block,register,field,interrupt,irq_number,signal,description\n"
                "soc,IRQ_STATUS,SPI_IRQ,spi_irq,6,spi_irq,SPI interrupt\n",
                encoding="utf-8",
            )
            regs_csv = root / "regs.csv"
            regs_csv.write_text(
                "block,base_address,offset,register,field,bits,access\n"
                "soc,0x40000000,0x10,IRQ_STATUS,SPI_IRQ,6,RO\n",
                encoding="utf-8",
            )
            index = build_index(root, top=["top"])
            graph = build_contract_graph(index, root=root, reg_tables=[regs_csv], interrupt_tables=[interrupt_csv])
            edge_kinds = {(edge.source, edge.target, edge.kind) for edge in graph.edges}
            self.assertTrue(any(edge.kind == "matches_rtl_signal" and edge.target == "rtl:top.spi_irq" for edge in graph.edges))
            self.assertTrue(any(edge.kind == "maps_to_sw_irq" for edge in graph.edges))
            self.assertIn(("rtl:top.spi_irq", "rtl:top.irq[6]", "rtl_aggregates_bit"), edge_kinds)
            self.assertFalse(any(issue["kind"] == "table_interrupt_without_rtl_match" for issue in graph.issues))


if __name__ == "__main__":
    unittest.main()

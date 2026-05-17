# rtl-agent

`rtl-agent` is an early MVP for automated Verilog/SystemVerilog code analysis aimed at SOC integration quality review and future model-driven RTL generation.

The first version focuses on reliable navigation over low-information-density RTL:

- scans `.v`, `.sv`, `.vh`, `.svh`
- extracts modules, parameters, ports, instances, includes, clocks, resets, assignments, and procedural blocks
- builds hierarchy and module summaries with source line references
- emits layered memory artifacts for later LLM reasoning
- reserves an OpenAI-compatible API client so OpenAI, Azure OpenAI, vLLM, LiteLLM, Qwen, DeepSeek, or internal gateways can be swapped by config

## Quick Start

```powershell
python -m rtl_agent index examples/tiny_soc -o out
python -m rtl_agent check examples/tiny_soc -o out
python -m rtl_agent check examples/tiny_soc --top soc_top -o out
python -m rtl_agent ask examples/tiny_soc "which modules look like bus fabric?"
python -m unittest discover -s tests -v
```

Artifacts:

- `out/design_index.json`: structured RTL facts
- `out/design_overview.md`: compact design-scale overview for large RTL trees
- `out/hierarchy.md`: module hierarchy
- `out/module_summary.md`: high-density module memory
- `out/esl_model.yaml`: ESL-like intermediate model with source line tags
- `out/soc_integration_report.md`: integration-oriented findings

For large RTL libraries, explicitly specify the integration top when you know it:

```powershell
python -m rtl_agent check path/to/rtl --top my_soc_top -o out/my_soc
python -m rtl_agent check path/to/rtl --top-file path/to/top.sv -o out/my_soc
```

Without `--top`, `rtl-agent` treats modules that are not instantiated by any scanned module as candidate tops. With `--top` or `--top-file`, hierarchy and integration checks are scoped to modules reachable from the selected top, while unreachable modules are reported separately as orphan candidates.

## Architecture

```text
RTL source
  -> lexical cleanup
  -> lightweight Verilog/SystemVerilog extraction
  -> design index and hierarchy
  -> ESL-like model with file:line evidence
  -> SOC integration checks
  -> optional OpenAI-compatible reasoning layer
```

This parser is intentionally conservative. It is not a replacement for a full SystemVerilog compiler. The roadmap is to add optional backends such as Surelog/UHDM, slang, tree-sitter, or Yosys for stronger syntax and elaboration while keeping the same memory/model interface.

## OpenAI-Compatible Configuration

Create `rtl-agent.toml`:

```toml
[llm]
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
model = "gpt-4.1"
```

The current MVP can run without an API key. LLM calls are isolated behind `OpenAICompatibleClient`.

## Roadmap

1. Robust local RTL indexing
2. SOC integration checks: ports, widths, resets, clocks, hierarchy, protocols
3. ESL-like model extraction for NoC, LLC, bus fabric, CSR, interrupt, and address-map structures
4. GitHub PR workflow integration
5. Model-driven patch generation for wrappers, adapters, top-level wiring, CSR glue, and testbench skeletons

## Open-Source RTL Smoke Test

For real RTL validation, clone a small public repository outside the tracked tree and run the same CLI:

```powershell
git clone https://github.com/alexforencich/verilog-uart.git third_party/verilog-uart
python -m rtl_agent check third_party/verilog-uart/rtl -o out/verilog-uart
```

The GitHub connector was able to read `alexforencich/verilog-uart/rtl/uart_rx.v`, which is a useful Verilog-2001 style smoke case with parameterized module headers, typed ports, registers, continuous assignments, and a sequential `always @(posedge clk)` block. The local network sandbox blocked direct `git clone` during initial development, so this command is documented as the first external validation step once network access is available.

## Publish To GitHub

Create an empty GitHub repository named `rtl-agent`, then from this directory run:

```powershell
git remote add origin https://github.com/<owner>/rtl-agent.git
git add .gitignore README.md pyproject.toml src examples tests
git commit -m "Initial rtl-agent MVP"
git branch -M main
git push -u origin main
```

If Git reports dubious ownership for a OneDrive checkout, add this workspace as a safe directory first:

```powershell
git config --global --add safe.directory D:/OneDrive/Documents/FE_IC
```

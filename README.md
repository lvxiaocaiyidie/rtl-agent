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
python -m rtl_agent list-rules
python -m rtl_agent list-reduction-rules
python -m rtl_agent list-model-levels
python -m rtl_agent reduce examples/tiny_soc --top soc_top --max-modules 80
python -m rtl_agent model examples/tiny_soc --top soc_top --level l3 -o out
python -m rtl_agent interrupts examples/tiny_soc --top soc_top -o out/interrupts
python -m rtl_agent contracts examples/irq_soc --top irq_top --address-map examples/contracts/address_map.csv --reg-table examples/contracts/registers.csv --interrupt-table examples/contracts/interrupts.csv --noc-table examples/contracts/noc.csv --crg-table examples/contracts/crg.csv --eda-connectivity examples/contracts/eda_connectivity.csv --blackbox-table examples/contracts/blackboxes.csv -o out/contracts
python -m rtl_agent ui examples/tiny_soc --top soc_top -o out/ui
python -m rtl_agent check examples/tiny_soc --top soc_top --llm -o out
python -m rtl_agent slice examples/tiny_soc --module soc_top --instance u_fabric
python -m rtl_agent ask examples/tiny_soc "which modules look like bus fabric?"
python -m unittest discover -s tests -v
```

Artifacts:

- `out/design_index.json`: structured RTL facts
- `out/design_overview.md`: compact design-scale overview for large RTL trees
- `out/hierarchy.md`: module hierarchy
- `out/module_summary.md`: high-density module memory
- `out/esl_model.yaml`: ESL-like intermediate model with source line tags
- `out/rtl_model_l1.yaml`: layered RTL model for script, LLM, or agent workflows
- `out/interrupt_graph.md`: interrupt contract graph with source evidence
- `out/interrupt_graph.json`: machine-readable interrupt contract graph
- `out/contract_graph.md`: merged SoC contract graph from RTL and project tables
- `out/contract_graph.json`: machine-readable contract graph for agents
- `out/contract_dashboard.html`: interactive contract graph browser
- `out/agent_handoff.md`: concise handoff prompt for LLM or coding-agent review
- `out/reduced_context.md`: LLM-facing reduced RTL context
- `out/reduced_context.json`: machine-readable reduced RTL context
- `out/reduction_rules.md`: explicit reduction policy
- `out/soc_integration_report.md`: integration-oriented findings
- `out/llm_review.md`: optional concise model review when `--llm` is enabled
- `out/dashboard.html`: interactive static UI from the `ui` command

For large RTL libraries, explicitly specify the integration top when you know it:

```powershell
python -m rtl_agent check path/to/rtl --top my_soc_top -o out/my_soc
python -m rtl_agent check path/to/rtl --top-file path/to/top.sv -o out/my_soc
```

Without `--top`, `rtl-agent` treats modules that are not instantiated by any scanned module as candidate tops. With `--top` or `--top-file`, hierarchy and integration checks are scoped to modules reachable from the selected top, while unreachable modules are reported separately as orphan candidates.

## Rule-Based Checks

Checks are script-first and reproducible. List the active rules with:

```powershell
python -m rtl_agent list-rules
```

Initial rule set:

- `RTL001` unknown instantiated module type
- `RTL002` named instance connection missing declared target ports
- `RTL003` container module has no detected clock
- `RTL004` container module has no detected reset
- `RTL005` module is unreachable from the selected top, opt-in via `--include-orphans`
- `RTL006` named child clock/reset port is explicitly open or tied to a constant
- `RTL007` non-trivial module spans multiple detected clock domains

Rules are tagged by value:

- `compile_overlap`: useful hygiene, but VCS/elaboration/lint can often catch it.
- `architecture_insight`: intended to point at integration intent, CDC/reset/clock risks, or modeling gaps that compilers do not fully judge.

Use `--insight-only` to focus on the second category:

```powershell
python -m rtl_agent check path/to/rtl --top my_soc_top --insight-only -o out/insight
```

Run a subset by ID or category:

```powershell
python -m rtl_agent check path/to/rtl --top my_soc_top --rule RTL001 -o out/hierarchy_only
python -m rtl_agent check path/to/rtl --top my_soc_top --rule hierarchy -o out/hierarchy_only
```

The current checks do not depend on an LLM. An optional OpenAI-compatible review rule is reserved for later stages, where the model should consume reduced context and explain or generalize script findings rather than replace structural extraction.

To run the optional LLM review:

```powershell
copy .env.example .env.local
copy rtl-agent.example.toml rtl-agent.toml
# edit .env.local and set OPENAI_API_KEY
python -m rtl_agent check path/to/rtl --top my_soc_top --llm -o out/my_soc
```

The model output is written to `out/my_soc/llm_review.md`. The API key file is ignored by git.

LLM token usage is controlled by preprocessing budgets rather than by dropping traceability:

```powershell
python -m rtl_agent check path/to/rtl --top my_soc_top --llm `
  --llm-max-modules 40 `
  --llm-max-interface-stubs 160 `
  --llm-max-findings 40 `
  --report-style brief `
  -o out/my_soc
```

If a model or future agent is uncertain, fetch original RTL only for the referenced area:

```powershell
python -m rtl_agent slice path/to/rtl --module plic_top --instance x_plic_sec_busif --context-lines 30
```

The LLM review path is intentionally backend-shaped: `LLMIntegrationReviewRule` consumes a small `ReviewBackend` interface, so an OpenAI-compatible chat client, Claude Code-style agent, or internal multi-turn reviewer can be swapped behind the same reduced-context and script-finding evidence.

## RTL Reduction

Large RTL trees are reduced before any model-facing workflow. List the active reduction rules with:

```powershell
python -m rtl_agent list-reduction-rules
```

The reducer emits high-density context containing selected tops, reachable/orphan counts, unresolved module types, module roles, ports, clocks/resets, and instance edges with source line labels:

```powershell
python -m rtl_agent reduce path/to/rtl --top my_soc_top --format md --max-modules 120
python -m rtl_agent reduce path/to/rtl --top my_soc_top --format json --max-modules 120
```

To avoid over-compressing away interfaces, omitted reachable modules are retained as interface stubs. A full module summary keeps ports, parameters, clocks, resets, instance edges, role, subsystem, and source lines. An interface stub keeps source, role, subsystem, full parsed port signatures, clocks, resets, parameters, and instance count. Use `--max-interface-stubs` to tune that second budget.

The generated `reduced_context.md` and `reduced_context.json` are intended as the first prompt input for LLM analysis. The original RTL remains available through file and line references when detailed inspection is needed.

## Layered RTL Modeling

Use `model` when you want a higher-density representation than RTL, but more structure than a prose summary:

```powershell
python -m rtl_agent list-model-levels
python -m rtl_agent model path/to/rtl --top my_soc_top --level l0 -o out/my_soc
python -m rtl_agent model path/to/rtl --top my_soc_top --level l1 --format yaml -o out/my_soc
python -m rtl_agent model path/to/rtl --top my_soc_top --level l3 --format json -o out/my_soc
python -m rtl_agent model path/to/rtl --top my_soc_top --level l4 --format yaml -o out/my_soc
```

Model levels are intentionally layered:

- `l0`: design inventory, tops, unresolved modules, subsystem and role counts.
- `l1`: structural component model with interfaces, clock/reset domains, and instance edges.
- `l2`: interface and protocol graph with protocol hints and clock/reset summaries.
- `l3`: architecture intent model for CPU, bus, memory, peripheral, clock/reset, and integration-risk views.
- `l4`: generation planning model with blackbox, wrapper, tie-off, and source-slice tasks for future agent-driven RTL generation.

The current modeler is script-first. Later LLM or agent passes should annotate this model rather than replace it, so facts remain traceable back to RTL line ranges.

## Interrupt Contract Graph

The most useful near-term direction is not another generic RTL lint pass. It is contract modeling for SoC integration objects that are hard to flatten manually. Interrupts are the first supported slice because they often involve event sources, status or pending bits, mask or enable logic, vector aggregation, top-level interrupt pins, interrupt-controller inputs, and software-visible IRQ names.

Generate the graph with:

```powershell
python -m rtl_agent interrupts path/to/rtl --top my_soc_top -o out/my_soc_interrupts
python -m rtl_agent interrupts path/to/rtl --top my_soc_top --format json -o out/my_soc_interrupts
```

The current graph is RTL-derived and script-first. It records:

- interrupt-like ports and signals (`irq`, `intr`, `interrupt`)
- named instance interrupt connections
- interrupt vector bit aggregation such as `irq[5] = irq_5`
- constant or open interrupt tie-offs
- file and line evidence for each node and edge

This is deliberately shaped as an extendable contract graph. The next meaningful importers should merge project-owned evidence into the same graph instead of creating separate reports: interrupt spreadsheet rows, register table rows, address-map ownership, NoC endpoint metadata, clock/reset ownership from diagrams, and EDA-resolved connectivity from Verdi or simulation databases. LLM or agent reviewers should then explain gaps and naming mismatches on top of this graph, while scripts keep the traceable facts.

## SoC Contract Graph

Use `contracts` when you have project-owned tables or EDA/script outputs in addition to RTL. The command accepts CSV, TSV, or XLSX files and merges parsed facts with RTL-derived hierarchy, interface, clock/reset, and interrupt evidence:

```powershell
python -m rtl_agent contracts path/to/rtl --top my_soc_top `
  --address-map path/to/address_map.xlsx `
  --reg-table path/to/registers.xlsx `
  --interrupt-table path/to/interrupts.xlsx `
  --noc-table path/to/noc.xlsx `
  --crg-table path/to/crg.xlsx `
  --eda-connectivity path/to/verdi_connectivity.csv `
  --blackbox-table path/to/blackboxes.xlsx `
  -o out/my_soc_contract
```

The table importer uses header aliases, so columns such as `block`, `base address`, `offset`, `register`, `field`, `bits`, `access`, `interrupt`, `irq number`, `rtl signal`, `master`, `slave`, `route id`, `clock`, `reset`, `domain`, `endpoint`, and `source/target` are normalized into one schema. The output graph adds nodes such as address blocks, registers, fields, interrupt specs, software IRQ numbers, NoC endpoints, route IDs, clock/reset signals, blackboxes, EDA objects, and RTL objects. It then creates edges such as:

- `contains_register`
- `has_field`
- `documents_interrupt`
- `maps_to_sw_irq`
- `matches_rtl_signal`
- `matches_rtl_object`
- `noc_route`
- `uses_route_id`
- `drives_clock`
- `drives_reset`
- `has_interface_contract`
- `eda_*`
- `rtl_instance_connection`
- `rtl_aggregates_bit`
- `rtl_state_observation`

This starts catching integration-contract issues that VCS does not judge semantically:

- table interrupt exists but no RTL interrupt signal matches it
- top-level RTL interrupt exists but no table/software-visible entry matches it
- documented interrupt appears tied off in RTL
- register field names and RTL signal names need fuzzy semantic review
- software IRQ number assignment needs review against aggregation bits
- NoC endpoint or route ID metadata cannot be matched to RTL/EDA evidence
- blackbox metadata lacks interface, clock, or reset contracts
- EDA-resolved connectivity disagrees with lightweight RTL parsing

`--eda-connectivity` is intentionally generic so project scripts can feed the graph without a hard Verdi dependency. A simple exported CSV with `source,target,kind,signal,description` is enough to ingest outputs from flows around `simv.daidir`, `signalSearch.pl`, `findInstDefwild.pl`, or internal wrappers. EDA evidence should be treated as stronger than lightweight RTL parsing when the two disagree.

The graph is intentionally evidence-first. Each node and edge keeps either an RTL file:line label or a table row label, so an LLM or agent can reason from compact facts and then request only the original slices it needs.

Optional OpenAI-compatible review is available:

```powershell
python -m rtl_agent contracts path/to/rtl --top my_soc_top `
  --address-map path/to/address_map.xlsx `
  --reg-table path/to/registers.xlsx `
  --interrupt-table path/to/interrupts.xlsx `
  --noc-table path/to/noc.xlsx `
  --crg-table path/to/crg.xlsx `
  --eda-connectivity path/to/verdi_connectivity.csv `
  --blackbox-table path/to/blackboxes.xlsx `
  --llm `
  -o out/my_soc_contract
```

The LLM receives only a compact graph payload: summary, issues, high-value edges, and agent handoff rules. The full RTL is not sent unless a later agent step explicitly calls `slice`.

## Claude Code / Agent Handoff

`contracts` writes `agent_handoff.md` next to the graph. That file is designed to be pasted or referenced as the first task for Claude Code or another coding agent:

```powershell
python -m rtl_agent contracts path/to/rtl --top my_soc_top `
  --address-map path/to/address_map.xlsx `
  --reg-table path/to/registers.xlsx `
  --interrupt-table path/to/interrupts.xlsx `
  -o out/my_soc_contract
```

Recommended collaboration pattern:

1. Run `rtl-agent contracts` locally.
2. Give Claude Code `out/my_soc_contract/contract_graph.json`, `contract_graph.md`, and `agent_handoff.md`.
3. Ask it to review contract mismatches first, not to parse the whole RTL tree from scratch.
4. When it is uncertain, have it run `rtl-agent slice path/to/rtl --module <module> --context-lines 40`.
5. Keep all fixes or conclusions tied to graph evidence plus exact RTL/table rows.

The intended split is:

- scripts extract reproducible facts from RTL, spreadsheets, and future EDA outputs
- LLMs or agents perform semantic matching, naming judgement, explanation, and patch planning
- source slices are fetched only when the graph evidence is insufficient

For Claude Code specifically, a good first instruction is:

```text
Read contract_graph.md, contract_graph.json, and agent_handoff.md. Review SoC integration contract mismatches first. Do not parse the whole RTL tree from scratch. If an edge or issue is uncertain, ask to run the suggested rtl-agent slice command and cite the graph evidence you used.
```

## Interactive UI

Generate a static dashboard when you want to browse findings and models interactively:

```powershell
python -m rtl_agent ui path/to/rtl --top my_soc_top -o out/my_soc_ui
python -m rtl_agent ui path/to/rtl --top my_soc_top --insight-only --model-level l3 -o out/my_soc_ui
```

Open `out/my_soc_ui/dashboard.html` in a browser, or serve that directory with any static file server. The UI includes metrics, finding filters, a hierarchy view, module search, interrupt graph exploration, model JSON, and rule metadata.

For projects using Emacs verilog-mode AUTOINST/AUTOWIRE/AUTO_TEMPLATE flows, run `rtl-agent` on the expanded or generated RTL whenever possible. The current lightweight parser reads concrete module instances and named connections present in the scanned files; it does not yet execute verilog-mode expansion itself.

## Architecture

```text
RTL source
  -> lexical cleanup
  -> lightweight Verilog/SystemVerilog extraction
  -> design index and hierarchy
  -> fact IR and layered RTL models with file:line evidence
  -> contract graphs for interrupt/register/address/NoC/CRG evidence
  -> SOC integration checks split into compile-overlap and architecture-insight classes
  -> optional OpenAI-compatible or agent reasoning layer
  -> interactive dashboard
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
2. SOC integration checks: hierarchy, clock/reset intent, cross-domain and contract consistency
3. Contract graph extraction for interrupt, register, address-map, NoC, CRG, debug, and DFT relationships
4. Importers for project evidence: spreadsheets, generated register metadata, Verdi/sim database connectivity, and script outputs
5. ESL-like model extraction for NoC, LLC, bus fabric, CSR, interrupt, and address-map structures
6. GitHub PR workflow integration
7. Model-driven patch generation for wrappers, adapters, top-level wiring, CSR glue, and testbench skeletons

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

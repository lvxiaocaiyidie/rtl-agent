from __future__ import annotations

import argparse
from pathlib import Path

from .checks import render_rule_list, run_checks
from .checks.llm_rules import LLMIntegrationReviewRule
from .contracts import contract_llm_messages, render_contract_json, render_contract_markdown, write_contract_artifacts
from .dashboard import render_dashboard
from .interrupts import render_interrupt_json, render_interrupt_markdown
from .indexer import build_index
from .llm import OpenAICompatibleClient, has_api_key, load_llm_config
from .modeler import render_model_json, render_model_levels, render_model_yaml
from .reducer import render_llm_context, render_reduced_json, render_reduction_rules
from .reports import render_module_summary, render_soc_report, write_artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rtl-agent", description="Analyze Verilog/SystemVerilog RTL for SOC integration.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    index_p = sub.add_parser("index", help="Build layered RTL memory artifacts.")
    index_p.add_argument("rtl_root")
    index_p.add_argument("-o", "--out", default="out")
    index_p.add_argument("--top", action="append", default=[], help="Explicit top module name. Can be repeated.")
    index_p.add_argument("--top-file", help="Treat all modules defined in this file as explicit top modules.")

    check_p = sub.add_parser("check", help="Run MVP SOC integration checks.")
    check_p.add_argument("rtl_root")
    check_p.add_argument("-o", "--out", default="out")
    check_p.add_argument("--top", action="append", default=[], help="Explicit top module name. Can be repeated.")
    check_p.add_argument("--top-file", help="Treat all modules defined in this file as explicit top modules.")
    check_p.add_argument("--rule", action="append", default=[], help="Run only one rule ID or category. Can be repeated.")
    check_p.add_argument("--include-orphans", action="store_true", help="Report unreachable modules as findings.")
    check_p.add_argument("--insight-only", action="store_true", help="Run only architecture/integration insight checks.")
    check_p.add_argument("--report-style", choices=["brief", "full"], default="brief", help="Control SOC report verbosity.")
    check_p.add_argument("--max-findings-per-rule", type=int, default=12, help="Brief report sample budget per rule.")
    check_p.add_argument("--llm", action="store_true", help="Run optional OpenAI-compatible LLM review over reduced context.")
    check_p.add_argument("--llm-config", default="rtl-agent.toml", help="Path to LLM config file.")
    check_p.add_argument("--env-file", default=".env.local", help="Path to env file containing the API key.")
    check_p.add_argument("--llm-max-modules", type=int, default=80)
    check_p.add_argument("--llm-max-interface-stubs", type=int, default=120)
    check_p.add_argument("--llm-max-findings", type=int, default=40, help="Script finding budget passed to the LLM.")

    ask_p = sub.add_parser("ask", help="Answer with local structured memory. LLM wiring is reserved for the next phase.")
    ask_p.add_argument("rtl_root")
    ask_p.add_argument("question")
    ask_p.add_argument("--top", action="append", default=[], help="Explicit top module name. Can be repeated.")
    ask_p.add_argument("--top-file", help="Treat all modules defined in this file as explicit top modules.")

    reduce_p = sub.add_parser("reduce", help="Emit reduced high-density RTL context for LLM review.")
    reduce_p.add_argument("rtl_root")
    reduce_p.add_argument("--top", action="append", default=[], help="Explicit top module name. Can be repeated.")
    reduce_p.add_argument("--top-file", help="Treat all modules defined in this file as explicit top modules.")
    reduce_p.add_argument("--format", choices=["md", "json"], default="md")
    reduce_p.add_argument("--max-modules", type=int, default=120)
    reduce_p.add_argument("--max-interface-stubs", type=int, default=200)

    slice_p = sub.add_parser("slice", help="Print original RTL around a module or instance for multi-turn review.")
    slice_p.add_argument("rtl_root")
    slice_p.add_argument("--module", required=True, help="Module name to inspect.")
    slice_p.add_argument("--instance", help="Optional instance name inside the module.")
    slice_p.add_argument("--context-lines", type=int, default=20, help="Extra lines around an instance source line.")

    model_p = sub.add_parser("model", help="Emit layered RTL model for script or agent workflows.")
    model_p.add_argument("rtl_root")
    model_p.add_argument("-o", "--out", default="out")
    model_p.add_argument("--top", action="append", default=[], help="Explicit top module name. Can be repeated.")
    model_p.add_argument("--top-file", help="Treat all modules defined in this file as explicit top modules.")
    model_p.add_argument("--level", choices=["l0", "l1", "l2", "l3", "l4"], default="l1", help="Model abstraction level.")
    model_p.add_argument("--format", choices=["yaml", "json"], default="yaml")
    model_p.add_argument("--max-modules", type=int, default=200)

    ui_p = sub.add_parser("ui", help="Write an interactive static HTML dashboard.")
    ui_p.add_argument("rtl_root")
    ui_p.add_argument("-o", "--out", default="out")
    ui_p.add_argument("--top", action="append", default=[], help="Explicit top module name. Can be repeated.")
    ui_p.add_argument("--top-file", help="Treat all modules defined in this file as explicit top modules.")
    ui_p.add_argument("--include-orphans", action="store_true", help="Include orphan findings in the dashboard.")
    ui_p.add_argument("--insight-only", action="store_true", help="Show only architecture/integration insight checks.")
    ui_p.add_argument("--model-level", choices=["l0", "l1", "l2", "l3", "l4"], default="l3")

    intr_p = sub.add_parser("interrupts", help="Emit an interrupt contract graph from RTL hierarchy and connections.")
    intr_p.add_argument("rtl_root")
    intr_p.add_argument("-o", "--out", default="out")
    intr_p.add_argument("--top", action="append", default=[], help="Explicit top module name. Can be repeated.")
    intr_p.add_argument("--top-file", help="Treat all modules defined in this file as explicit top modules.")
    intr_p.add_argument("--format", choices=["md", "json"], default="md")

    contract_p = sub.add_parser("contracts", help="Merge RTL, address-map, register, and interrupt evidence into a SoC contract graph.")
    contract_p.add_argument("rtl_root")
    contract_p.add_argument("-o", "--out", default="out/contract")
    contract_p.add_argument("--top", action="append", default=[], help="Explicit top module name. Can be repeated.")
    contract_p.add_argument("--top-file", help="Treat all modules defined in this file as explicit top modules.")
    contract_p.add_argument("--address-map", action="append", default=[], help="CSV/TSV/XLSX address map. Can be repeated.")
    contract_p.add_argument("--reg-table", action="append", default=[], help="CSV/TSV/XLSX register table. Can be repeated.")
    contract_p.add_argument("--interrupt-table", action="append", default=[], help="CSV/TSV/XLSX interrupt table. Can be repeated.")
    contract_p.add_argument("--format", choices=["md", "json"], default="md")
    contract_p.add_argument("--stdout", action="store_true", help="Print the selected format instead of writing artifacts.")
    contract_p.add_argument("--llm", action="store_true", help="Run optional OpenAI-compatible LLM review over the contract graph.")
    contract_p.add_argument("--llm-config", default="rtl-agent.toml", help="Path to LLM config file.")
    contract_p.add_argument("--env-file", default=".env.local", help="Path to env file containing the API key.")

    sub.add_parser("list-rules", help="List script and reserved LLM check rules.")
    sub.add_parser("list-reduction-rules", help="List RTL reduction rules used for model-facing context.")
    sub.add_parser("list-model-levels", help="List layered RTL modeling levels.")

    args = parser.parse_args(argv)
    if args.cmd == "list-rules":
        print(render_rule_list())
        return 0
    if args.cmd == "list-reduction-rules":
        print(render_reduction_rules())
        return 0
    if args.cmd == "list-model-levels":
        print(render_model_levels())
        return 0
    root = Path(args.rtl_root)
    if args.cmd == "index":
        index = _build_index_from_args(root, args)
        write_artifacts(index, Path(args.out))
        print(f"Indexed {len(index.files)} RTL files, {len(index.modules)} modules. Top modules: {', '.join(index.top_modules) or 'none'}")
        return 0
    if args.cmd == "check":
        index = _build_index_from_args(root, args)
        out = Path(args.out)
        write_artifacts(index, out)
        (out / "soc_integration_report.md").write_text(
            render_soc_report(
                index,
                rule_ids=args.rule,
                include_orphan=args.include_orphans,
                style=args.report_style,
                max_per_rule=args.max_findings_per_rule,
                insight_only=args.insight_only,
            ),
            encoding="utf-8",
        )
        if args.llm:
            llm_review = _run_llm_review(index, args)
            (out / "llm_review.md").write_text(llm_review, encoding="utf-8")
        print(f"Wrote SOC integration report to {out / 'soc_integration_report.md'}")
        return 0
    if args.cmd == "ask":
        index = _build_index_from_args(root, args)
        question = args.question.lower()
        print(_local_answer(index, question))
        return 0
    if args.cmd == "reduce":
        index = _build_index_from_args(root, args)
        if args.format == "json":
            print(render_reduced_json(index, max_modules=args.max_modules, max_interface_stubs=args.max_interface_stubs))
        else:
            print(render_llm_context(index, max_modules=args.max_modules, max_interface_stubs=args.max_interface_stubs))
        return 0
    if args.cmd == "slice":
        index = build_index(root)
        print(_source_slice(index, root.resolve(), args.module, args.instance, args.context_lines))
        return 0
    if args.cmd == "model":
        index = _build_index_from_args(root, args)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        text = (
            render_model_json(index, level=args.level, max_modules=args.max_modules)
            if args.format == "json"
            else render_model_yaml(index, level=args.level, max_modules=args.max_modules)
        )
        suffix = "json" if args.format == "json" else "yaml"
        path = out / f"rtl_model_{args.level}.{suffix}"
        path.write_text(text, encoding="utf-8")
        print(f"Wrote RTL model to {path}")
        return 0
    if args.cmd == "ui":
        index = _build_index_from_args(root, args)
        findings = run_checks(index, include_orphan=args.include_orphans, insight_only=args.insight_only)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        path = out / "dashboard.html"
        path.write_text(render_dashboard(index, findings, model_level=args.model_level), encoding="utf-8")
        print(f"Wrote interactive dashboard to {path}")
        return 0
    if args.cmd == "interrupts":
        index = _build_index_from_args(root, args)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        text = render_interrupt_json(index, root=root.resolve()) if args.format == "json" else render_interrupt_markdown(index, root=root.resolve())
        suffix = "json" if args.format == "json" else "md"
        path = out / f"interrupt_graph.{suffix}"
        path.write_text(text, encoding="utf-8")
        print(f"Wrote interrupt graph to {path}")
        return 0
    if args.cmd == "contracts":
        index = _build_index_from_args(root, args)
        address_maps = [Path(path) for path in args.address_map]
        reg_tables = [Path(path) for path in args.reg_table]
        interrupt_tables = [Path(path) for path in args.interrupt_table]
        if args.stdout:
            text = (
                render_contract_json(index, root=root.resolve(), address_maps=address_maps, reg_tables=reg_tables, interrupt_tables=interrupt_tables)
                if args.format == "json"
                else render_contract_markdown(index, root=root.resolve(), address_maps=address_maps, reg_tables=reg_tables, interrupt_tables=interrupt_tables)
            )
            print(text)
            return 0
        graph = write_contract_artifacts(
            index,
            Path(args.out),
            root=root.resolve(),
            address_maps=address_maps,
            reg_tables=reg_tables,
            interrupt_tables=interrupt_tables,
        )
        if args.llm:
            (Path(args.out) / "llm_contract_review.md").write_text(_run_contract_llm_review(graph, args), encoding="utf-8")
        print(f"Wrote contract graph to {Path(args.out) / 'contract_graph.md'} ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")
        return 0
    return 1


def _local_answer(index, question: str) -> str:
    if "bus" in question or "axi" in question or "fabric" in question:
        hits = []
        for module in index.modules.values():
            hay = " ".join([module.name] + [p.name for p in module.ports] + [i.module for i in module.instances]).lower()
            if module.role == "bus_or_protocol_logic" or any(token in hay for token in ("axi", "ahb", "apb", "fabric")):
                hits.append((len(module.instances), module.name, module.source.label(), module.role))
        hits.sort(reverse=True)
        lines = [f"- {name}: {source} ({role}, {inst_count} instances)" for inst_count, name, source, role in hits[:60]]
        if len(hits) > 60:
            lines.append(f"- ... {len(hits) - 60} more")
        return "Possible bus/fabric-related modules:\n" + ("\n".join(lines) if lines else "- none detected")
    if "top" in question:
        ranked = sorted(index.top_modules, key=lambda n: len(index.modules[n].instances) if n in index.modules else 0, reverse=True)
        lines = [
            f"- {name}: {index.modules[name].source.label()} ({len(index.modules[name].instances)} instances)"
            for name in ranked[:40]
        ]
        return "Selected top modules:\n" + ("\n".join(lines) if lines else "- none")
    if "orphan" in question or "unreachable" in question:
        return "Orphan/unreachable modules:\n" + "\n".join(f"- {name}" for name in index.orphan_modules[:80])
    return render_module_summary(index)


def _build_index_from_args(root: Path, args) -> object:
    top_file = Path(args.top_file) if getattr(args, "top_file", None) else None
    return build_index(root, top=args.top, top_file=top_file)


def _run_llm_review(index, args) -> str:
    config = load_llm_config(Path(args.llm_config), Path(args.env_file))
    if not has_api_key(config):
        return (
            "# LLM Review\n\n"
            f"LLM review was requested, but no usable API key was found for `{config.api_key_env}`.\n\n"
            "Add a local `.env.local` file or set the environment variable, then rerun with `--llm`.\n"
        )
    client = OpenAICompatibleClient(config)
    rule = LLMIntegrationReviewRule(
        client=client,
        max_modules=args.llm_max_modules,
        max_interface_stubs=args.llm_max_interface_stubs,
        max_findings=args.llm_max_findings,
    )
    findings = rule.run(index)
    lines = ["# LLM Review", ""]
    for finding in findings:
        lines.extend([finding.message, ""])
    return "\n".join(lines).rstrip() + "\n"


def _run_contract_llm_review(graph, args) -> str:
    config = load_llm_config(Path(args.llm_config), Path(args.env_file))
    if not has_api_key(config):
        return (
            "# LLM Contract Review\n\n"
            f"Contract review was requested, but no usable API key was found for `{config.api_key_env}`.\n\n"
            "Add a local `.env.local` file or set the environment variable, then rerun `rtl-agent contracts ... --llm`.\n"
        )
    client = OpenAICompatibleClient(config)
    review = client.chat(contract_llm_messages(graph), temperature=0.1)
    return "# LLM Contract Review\n\n" + review.rstrip() + "\n"


def _source_slice(index, root: Path, module_name: str, instance_name: str | None = None, context_lines: int = 20) -> str:
    module = index.modules.get(module_name)
    if not module:
        return f"Module {module_name} was not found."
    source = module.source
    title = f"# RTL Slice: {module_name}"
    if instance_name:
        inst = next((item for item in module.instances if item.name == instance_name), None)
        if not inst or not inst.source:
            return f"Instance {module_name}.{instance_name} was not found."
        source = inst.source
        title = f"# RTL Slice: {module_name}.{instance_name}"
        start_line = max(module.source.start_line, source.start_line - context_lines)
        end_line = min(module.source.end_line, source.end_line + context_lines)
    else:
        start_line = source.start_line
        end_line = source.end_line
    path = root / source.file
    if not path.exists():
        return f"Source file {source.file} was not found."
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    body = []
    for line_no in range(start_line, min(end_line, len(lines)) + 1):
        body.append(f"{line_no:6d}: {lines[line_no - 1]}")
    return title + f"\nSource: {source.file}:{start_line}-{end_line}\n\n" + "\n".join(body)


if __name__ == "__main__":
    raise SystemExit(main())

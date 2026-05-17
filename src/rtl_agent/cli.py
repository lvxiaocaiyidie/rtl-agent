from __future__ import annotations

import argparse
from pathlib import Path

from .checks import render_rule_list
from .indexer import build_index
from .reducer import render_llm_context, render_reduced_json
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

    sub.add_parser("list-rules", help="List script and reserved LLM check rules.")

    args = parser.parse_args(argv)
    if args.cmd == "list-rules":
        print(render_rule_list())
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
            render_soc_report(index, rule_ids=args.rule, include_orphan=args.include_orphans),
            encoding="utf-8",
        )
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
            print(render_reduced_json(index, max_modules=args.max_modules))
        else:
            print(render_llm_context(index, max_modules=args.max_modules))
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


if __name__ == "__main__":
    raise SystemExit(main())

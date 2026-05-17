from __future__ import annotations

import argparse
from pathlib import Path

from .indexer import build_index
from .reports import render_module_summary, render_soc_report, write_artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rtl-agent", description="Analyze Verilog/SystemVerilog RTL for SOC integration.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    index_p = sub.add_parser("index", help="Build layered RTL memory artifacts.")
    index_p.add_argument("rtl_root")
    index_p.add_argument("-o", "--out", default="out")

    check_p = sub.add_parser("check", help="Run MVP SOC integration checks.")
    check_p.add_argument("rtl_root")
    check_p.add_argument("-o", "--out", default="out")

    ask_p = sub.add_parser("ask", help="Answer with local structured memory. LLM wiring is reserved for the next phase.")
    ask_p.add_argument("rtl_root")
    ask_p.add_argument("question")

    args = parser.parse_args(argv)
    root = Path(args.rtl_root)
    if args.cmd == "index":
        index = build_index(root)
        write_artifacts(index, Path(args.out))
        print(f"Indexed {len(index.files)} RTL files, {len(index.modules)} modules. Top modules: {', '.join(index.top_modules) or 'none'}")
        return 0
    if args.cmd == "check":
        index = build_index(root)
        out = Path(args.out)
        write_artifacts(index, out)
        (out / "soc_integration_report.md").write_text(render_soc_report(index), encoding="utf-8")
        print(f"Wrote SOC integration report to {out / 'soc_integration_report.md'}")
        return 0
    if args.cmd == "ask":
        index = build_index(root)
        question = args.question.lower()
        print(_local_answer(index, question))
        return 0
    return 1


def _local_answer(index, question: str) -> str:
    if "bus" in question or "axi" in question or "fabric" in question:
        hits = []
        for module in index.modules.values():
            hay = " ".join([module.name] + [p.name for p in module.ports] + [i.module for i in module.instances]).lower()
            if any(token in hay for token in ("axi", "ahb", "apb", "bus", "fabric")):
                hits.append(f"- {module.name}: {module.source.label()}")
        return "Possible bus/fabric-related modules:\n" + ("\n".join(hits) if hits else "- none detected")
    if "top" in question:
        return "Top modules: " + (", ".join(index.top_modules) or "none")
    return render_module_summary(index)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from pathlib import Path

from .checks import run_checks
from .checks.base import Finding
from .models import DesignIndex, Module
from .reducer import render_llm_context, render_reduced_json


def write_artifacts(index: DesignIndex, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "design_index.json").write_text(json.dumps(index.to_dict(), indent=2), encoding="utf-8")
    (out_dir / "design_overview.md").write_text(render_design_overview(index), encoding="utf-8")
    (out_dir / "hierarchy.md").write_text(render_hierarchy(index), encoding="utf-8")
    (out_dir / "module_summary.md").write_text(render_module_summary(index), encoding="utf-8")
    (out_dir / "esl_model.yaml").write_text(render_esl_model(index), encoding="utf-8")
    (out_dir / "reduced_context.md").write_text(render_llm_context(index), encoding="utf-8")
    (out_dir / "reduced_context.json").write_text(render_reduced_json(index), encoding="utf-8")


def render_design_overview(index: DesignIndex) -> str:
    modules = list(index.modules.values())
    instance_count = sum(len(module.instances) for module in modules)
    role_counts = _count_by(modules, "role")
    subsystem_counts = _count_by(modules, "subsystem")
    lines = [
        "# Design Overview",
        "",
        f"- RTL files: {len(index.files)}",
        f"- Modules: {len(modules)}",
        f"- Instances: {instance_count}",
        f"- Selected top modules: {len(index.top_modules)}",
        f"- Candidate top modules: {len(index.candidate_top_modules)}",
        f"- Reachable modules from selected top: {len(index.reachable_modules)}",
        f"- Orphan/unreachable modules: {len(index.orphan_modules)}",
        f"- Unresolved instantiated module types: {len(index.unresolved_modules)}",
        f"- Diagnostics: {len(index.diagnostics)}",
        "",
        "## Selected Top Modules",
        "",
    ]
    for name in _rank_modules_by_instances(index, index.top_modules)[:40]:
        source = index.modules[name].source.label() if name in index.modules else ""
        inst_count = len(index.modules[name].instances) if name in index.modules else 0
        lines.append(f"- {name} ({inst_count} instances) `{source}`")
    lines.extend(["", "## Candidate Top Modules", ""])
    for name in _rank_modules_by_instances(index, index.candidate_top_modules)[:40]:
        module = index.modules[name]
        lines.append(f"- {name} ({len(module.instances)} instances) `{module.source.label()}`")
    if len(index.candidate_top_modules) > 40:
        lines.append(f"- ... {len(index.candidate_top_modules) - 40} more")
    if index.unresolved_modules:
        lines.extend(["", "## Unresolved Module Types", ""])
        for name in index.unresolved_modules[:40]:
            lines.append(f"- {name}")
        if len(index.unresolved_modules) > 40:
            lines.append(f"- ... {len(index.unresolved_modules) - 40} more")
    lines.extend(["", "## Roles", ""])
    for role, count in sorted(role_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {role}: {count}")
    lines.extend(["", "## Subsystems", ""])
    for subsystem, count in sorted(subsystem_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {subsystem}: {count}")
    return "\n".join(lines) + "\n"


def render_hierarchy(index: DesignIndex) -> str:
    lines = ["# RTL Hierarchy", ""]
    for top in index.top_modules or sorted(index.modules):
        _render_tree(index, top, lines, 0, set())
    return "\n".join(lines) + "\n"


def _render_tree(index: DesignIndex, name: str, lines: list[str], depth: int, stack: set[str]) -> None:
    module = index.modules.get(name)
    prefix = "  " * depth + "- "
    if not module:
        lines.append(prefix + f"{name} *(external/unknown)*")
        return
    if name in stack:
        lines.append(prefix + f"{name} *(recursive reference)*")
        return
    lines.append(prefix + f"{name} `{module.source.label()}`")
    next_stack = set(stack)
    next_stack.add(name)
    for inst in module.instances:
        lines.append("  " * (depth + 1) + f"- {inst.name}: {inst.module} `{inst.source.label() if inst.source else ''}`")
        if inst.module in index.modules:
            _render_tree(index, inst.module, lines, depth + 2, next_stack)


def render_module_summary(index: DesignIndex) -> str:
    lines = ["# Module Summary", ""]
    for module in sorted(index.modules.values(), key=lambda m: m.name):
        lines.extend(_module_summary_lines(module))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _module_summary_lines(module: Module) -> list[str]:
    return [
        f"## {module.name}",
        "",
        f"- Source: `{module.source.label()}`",
        f"- Ports: {len(module.ports)} ({_dir_count(module, 'input')} input, {_dir_count(module, 'output')} output, {_dir_count(module, 'inout')} inout)",
        f"- Parameters: {', '.join(p.name for p in module.parameters) or 'none'}",
        f"- Clocks: {', '.join(module.clocks) or 'not detected'}",
        f"- Resets: {', '.join(module.resets) or 'not detected'}",
        f"- Subsystem: {module.subsystem}",
        f"- Role: {module.role}",
        f"- Instances: {', '.join(f'{i.name}:{i.module}' for i in module.instances) or 'none'}",
        f"- Assigns: {len(module.assigns)}",
        f"- Procedural blocks: {', '.join(b.kind for b in module.procedural_blocks) or 'none'}",
    ]


def render_esl_model(index: DesignIndex) -> str:
    lines = ["design:", f"  root: {index.root}", "  top_modules:"]
    for top in index.top_modules:
        lines.append(f"    - {top}")
    lines.append("modules:")
    for module in sorted(index.modules.values(), key=lambda m: m.name):
        lines.extend(
            [
                f"  - name: {module.name}",
                f"    source: {module.source.label()}",
                f"    role: {_infer_role(module)}",
                f"    subsystem: {module.subsystem}",
                "    ports:",
            ]
        )
        for port in module.ports:
            lines.append(f"      - {{name: {port.name}, dir: {port.direction}, width: \"{port.width}\", source: {port.source.label() if port.source else ''}}}")
        lines.append("    clock_domains:")
        for clk in module.clocks or ["unknown"]:
            reset = module.resets[0] if module.resets else "unknown"
            lines.append(f"      - {{clock: {clk}, reset: {reset}}}")
        lines.append("    instances:")
        for inst in module.instances:
            lines.append(f"      - {{name: {inst.name}, module: {inst.module}, source: {inst.source.label() if inst.source else ''}}}")
        lines.append("    behavior:")
        for block in module.procedural_blocks:
            lines.append(f"      - {{kind: {block.kind}, sensitivity: \"{block.sensitivity}\", source: {block.source.label()}}}")
        for assign in module.assigns:
            lines.append(f"      - {{kind: continuous_assign, source: {assign.label()}}}")
    return "\n".join(lines) + "\n"


def render_soc_report(index: DesignIndex, rule_ids: list[str] | None = None, include_orphan: bool = False) -> str:
    findings = run_basic_checks(index, rule_ids=rule_ids, include_orphan=include_orphan)
    lines = ["# SOC Integration Report", ""]
    if not findings:
        lines.append("No basic integration findings were detected by the MVP rule set.")
    for idx, finding in enumerate(findings, 1):
        lines.extend(
            [
                f"## {idx}. [{finding.severity}] {finding.rule_id}: {finding.title}",
                "",
                finding.message,
                "",
                f"Source: `{finding.source}`",
                "",
            ]
        )
        if finding.evidence:
            lines.append("Evidence:")
            lines.extend(f"- `{item}`" for item in finding.evidence)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_basic_checks(index: DesignIndex, rule_ids: list[str] | None = None, include_orphan: bool = False) -> list[Finding]:
    return run_checks(index, rule_ids=rule_ids, include_orphan=include_orphan)


def _dir_count(module: Module, direction: str) -> int:
    return sum(1 for port in module.ports if port.direction == direction)


def _infer_role(module: Module) -> str:
    return module.role


def _count_by(modules: list[Module], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for module in modules:
        key = getattr(module, attr)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _rank_modules_by_instances(index: DesignIndex, names: list[str]) -> list[str]:
    return sorted(names, key=lambda n: len(index.modules[n].instances) if n in index.modules else 0, reverse=True)

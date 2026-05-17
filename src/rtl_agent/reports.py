from __future__ import annotations

import json
from pathlib import Path

from .models import DesignIndex, Module


def write_artifacts(index: DesignIndex, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "design_index.json").write_text(json.dumps(index.to_dict(), indent=2), encoding="utf-8")
    (out_dir / "hierarchy.md").write_text(render_hierarchy(index), encoding="utf-8")
    (out_dir / "module_summary.md").write_text(render_module_summary(index), encoding="utf-8")
    (out_dir / "esl_model.yaml").write_text(render_esl_model(index), encoding="utf-8")


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


def render_soc_report(index: DesignIndex) -> str:
    findings = run_basic_checks(index)
    lines = ["# SOC Integration Report", ""]
    if not findings:
        lines.append("No basic integration findings were detected by the MVP rule set.")
    for idx, finding in enumerate(findings, 1):
        lines.extend(
            [
                f"## {idx}. [{finding['severity']}] {finding['title']}",
                "",
                finding["message"],
                "",
                f"Source: `{finding['source']}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def run_basic_checks(index: DesignIndex) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for module in index.modules.values():
        if module.instances and not module.clocks:
            findings.append(_finding("P2", "No clock detected", f"{module.name} contains sub-instances but no clock-like signal was detected.", module.source.label()))
        if module.instances and not module.resets:
            findings.append(_finding("P3", "No reset detected", f"{module.name} contains sub-instances but no reset-like signal was detected.", module.source.label()))
        for inst in module.instances:
            target = index.modules.get(inst.module)
            if not target:
                findings.append(_finding("P2", "Unknown instance module", f"{module.name}.{inst.name} instantiates {inst.module}, but that module was not found in scanned RTL.", inst.source.label() if inst.source else module.source.label()))
                continue
            required_ports = [p for p in target.ports if p.direction in {"input", "output", "inout"}]
            missing = [p.name for p in required_ports if p.name not in inst.connections]
            if missing:
                findings.append(_finding("P1", "Instance port appears unconnected", f"{module.name}.{inst.name} is missing named connections for: {', '.join(missing)}.", inst.source.label() if inst.source else module.source.label()))
    return findings


def _dir_count(module: Module, direction: str) -> int:
    return sum(1 for port in module.ports if port.direction == direction)


def _infer_role(module: Module) -> str:
    text = " ".join([module.name] + [p.name for p in module.ports] + [i.module for i in module.instances]).lower()
    if "axi" in text or "ahb" in text or "apb" in text:
        return "bus_or_protocol_logic"
    if "noc" in text or "router" in text:
        return "noc_component"
    if "llc" in text or "cache" in text:
        return "cache_component"
    if module.instances:
        return "integration_wrapper"
    return "leaf_rtl"


def _finding(severity: str, title: str, message: str, source: str) -> dict[str, str]:
    return {"severity": severity, "title": title, "message": message, "source": source}

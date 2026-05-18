from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .models import DesignIndex, Module

MODEL_LEVELS = [
    {
        "id": "l0",
        "title": "Design inventory",
        "description": "Project-scale facts: tops, counts, unresolved modules, subsystems, and roles.",
    },
    {
        "id": "l1",
        "title": "Structural component model",
        "description": "L0 plus module components, clock/reset domains, interface summaries, and instance edges.",
    },
    {
        "id": "l2",
        "title": "Behavior and integration intent model",
        "description": "L1 plus protocol hints, state/behavior hints, semantic risks, and source-slice queries for multi-turn review.",
    },
]


def build_rtl_model(index: DesignIndex, level: str = "l1", max_modules: int = 200) -> dict[str, Any]:
    level = level.lower()
    if level not in {"l0", "l1", "l2"}:
        raise ValueError(f"unknown model level: {level}")
    modules = _ordered_modules(index)[:max_modules]
    model: dict[str, Any] = {
        "schema": "rtl-agent-model/v1",
        "level": level,
        "root": index.root,
        "design": {
            "tops": index.top_modules,
            "candidate_tops": index.candidate_top_modules[:80],
            "module_count": len(index.modules),
            "file_count": len(index.files),
            "instance_count": sum(len(module.instances) for module in index.modules.values()),
            "reachable_module_count": len(index.reachable_modules),
            "orphan_module_count": len(index.orphan_modules),
            "unresolved_modules": index.unresolved_modules[:80],
        },
        "subsystems": _count_attr(index, "subsystem"),
        "roles": _count_attr(index, "role"),
    }
    if level in {"l1", "l2"}:
        model["components"] = [_component_model(module, include_behavior=level == "l2") for module in modules]
        model["truncated_components"] = max(0, len(_ordered_modules(index)) - len(modules))
    if level == "l2":
        model["integration_intent"] = {
            "protocol_hints": _protocol_hints(modules),
            "clock_domains": _clock_domain_summary(modules),
            "review_queries": _review_queries(index, modules[:40]),
        }
    return model


def render_model_json(index: DesignIndex, level: str = "l1", max_modules: int = 200) -> str:
    return json.dumps(build_rtl_model(index, level=level, max_modules=max_modules), indent=2)


def render_model_yaml(index: DesignIndex, level: str = "l1", max_modules: int = 200) -> str:
    return _to_yaml(build_rtl_model(index, level=level, max_modules=max_modules))


def render_model_levels() -> str:
    lines = ["# RTL Model Levels", ""]
    for level in MODEL_LEVELS:
        lines.extend([f"## {level['id']}: {level['title']}", "", level["description"], ""])
    return "\n".join(lines).rstrip() + "\n"


def _component_model(module: Module, include_behavior: bool = False) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": module.name,
        "source": module.source.label(),
        "role": module.role,
        "subsystem": module.subsystem,
        "interfaces": _interface_summary(module),
        "clock_domains": [{"clock": clk, "reset": module.resets[0] if module.resets else "unknown"} for clk in module.clocks or ["unknown"]],
        "instances": [
            {
                "name": inst.name,
                "module": inst.module,
                "source": inst.source.label() if inst.source else "",
                "connection_style": inst.connection_style,
            }
            for inst in module.instances
        ],
    }
    if include_behavior:
        item["behavior_hints"] = {
            "assign_count": len(module.assigns),
            "procedural_blocks": [block.kind for block in module.procedural_blocks],
            "protocols": _module_protocols(module),
        }
    return item


def _interface_summary(module: Module) -> dict[str, Any]:
    by_dir: dict[str, list[str]] = {"input": [], "output": [], "inout": []}
    for port in module.ports:
        by_dir.setdefault(port.direction, []).append(port.name)
    return {
        "port_count": len(module.ports),
        "inputs": by_dir.get("input", [])[:80],
        "outputs": by_dir.get("output", [])[:80],
        "inouts": by_dir.get("inout", [])[:80],
        "parameters": [param.name for param in module.parameters],
    }


def _protocol_hints(modules: list[Module]) -> list[dict[str, Any]]:
    hints = []
    for module in modules:
        protocols = _module_protocols(module)
        if protocols:
            hints.append({"module": module.name, "source": module.source.label(), "protocols": protocols})
    return hints


def _module_protocols(module: Module) -> list[str]:
    text = " ".join([module.name] + [port.name for port in module.ports] + [inst.module for inst in module.instances]).lower()
    protocols = []
    for name, tokens in {
        "axi": ("awvalid", "arvalid", "wvalid", "rvalid", "bvalid"),
        "apb": ("psel", "penable", "pready", "prdata"),
        "wishbone": ("wb_", "wbs_", "wbd_", "cyc", "stb", "ack"),
        "spi": ("sck", "mosi", "miso", "csb", "sdi", "sdo"),
        "uart": ("uart", "ser_tx", "ser_rx"),
        "gpio": ("gpio",),
    }.items():
        if any(token in text for token in tokens):
            protocols.append(name)
    return protocols


def _clock_domain_summary(modules: list[Module]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for module in modules:
        for clock in module.clocks or ["unknown"]:
            counts[clock] += 1
    return [{"clock": clock, "modules": count} for clock, count in counts.most_common(80)]


def _review_queries(index: DesignIndex, modules: list[Module]) -> list[str]:
    queries = []
    for module in modules:
        if len(module.clocks) > 1:
            queries.append(f"rtl-agent slice {index.root} --module {module.name} --context-lines 40")
        for inst in module.instances[:4]:
            if inst.module in index.unresolved_modules:
                queries.append(f"rtl-agent slice {index.root} --module {module.name} --instance {inst.name} --context-lines 30")
    return queries[:60]


def _ordered_modules(index: DesignIndex) -> list[Module]:
    names = index.reachable_modules or sorted(index.modules)
    return [index.modules[name] for name in names if name in index.modules]


def _count_attr(index: DesignIndex, attr: str) -> dict[str, int]:
    counts: Counter[str] = Counter(getattr(module, attr) for module in index.modules.values())
    return dict(counts.most_common())


def _to_yaml(value: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(_to_yaml(item, indent + 1))
            else:
                lines.append(f"{pad}{key}: {_yaml_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{pad}[]"
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(_to_yaml(item, indent + 1))
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{pad}{_yaml_scalar(value)}"


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or any(ch in text for ch in ":#{}[],&*?|-<>=!%@\\\"'") or text.strip() != text:
        return json.dumps(text)
    return text

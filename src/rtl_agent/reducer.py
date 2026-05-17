from __future__ import annotations

import json

from .models import DesignIndex, Module

REDUCTION_RULES = [
    {
        "id": "RED001",
        "title": "Top-down reachable order",
        "description": "Select full module summaries by walking from selected top modules through instance edges before falling back to remaining modules.",
    },
    {
        "id": "RED002",
        "title": "Preserve full interfaces",
        "description": "Every full module summary keeps all parsed ports, parameters, clocks, resets, instances, role, subsystem, and source line labels.",
    },
    {
        "id": "RED003",
        "title": "Preserve omitted module interface stubs",
        "description": "Modules omitted from the full summary budget still keep source, role, subsystem, full port signatures, clocks, resets, parameter names, and instance count.",
    },
    {
        "id": "RED004",
        "title": "Keep traceability labels",
        "description": "Reduced facts keep file:line source labels so detailed RTL can be re-read when the reduced view is insufficient.",
    },
    {
        "id": "RED005",
        "title": "Separate hierarchy metadata",
        "description": "Candidate tops, selected tops, reachable count, orphan count, and unresolved instantiated module types are kept outside module summaries.",
    },
    {
        "id": "RED006",
        "title": "Do not use LLM for fact extraction",
        "description": "The reducer only uses parsed structural facts; LLM review may consume the reduced context later but does not create the base hierarchy or port facts.",
    },
]


def reduced_design_dict(index: DesignIndex, max_modules: int = 200, max_interface_stubs: int = 300) -> dict[str, object]:
    active_names = _ordered_active_names(index)
    selected = active_names[:max_modules]
    omitted = active_names[max_modules:]
    stubs = omitted[:max_interface_stubs]
    return {
        "root": index.root,
        "tops": index.top_modules,
        "candidate_tops": index.candidate_top_modules[:80],
        "reachable_module_count": len(index.reachable_modules),
        "orphan_module_count": len(index.orphan_modules),
        "unresolved_modules": index.unresolved_modules[:80],
        "reduction_rules": [rule["id"] for rule in REDUCTION_RULES],
        "modules": [_reduce_module(index.modules[name]) for name in selected if name in index.modules],
        "interface_stubs": [_interface_stub(index.modules[name]) for name in stubs if name in index.modules],
        "truncated_modules": max(0, len(active_names) - len(selected)),
        "truncated_interface_stubs": max(0, len(omitted) - len(stubs)),
    }


def render_reduced_json(index: DesignIndex, max_modules: int = 200, max_interface_stubs: int = 300) -> str:
    return json.dumps(reduced_design_dict(index, max_modules=max_modules, max_interface_stubs=max_interface_stubs), indent=2)


def render_llm_context(index: DesignIndex, max_modules: int = 120, max_interface_stubs: int = 200) -> str:
    data = reduced_design_dict(index, max_modules=max_modules, max_interface_stubs=max_interface_stubs)
    lines = [
        "# Reduced RTL Context",
        "",
        f"Root: {data['root']}",
        f"Tops: {', '.join(data['tops']) if data['tops'] else 'none'}",
        f"Reachable modules: {data['reachable_module_count']}",
        f"Orphan modules: {data['orphan_module_count']}",
        f"Unresolved module types: {', '.join(data['unresolved_modules']) if data['unresolved_modules'] else 'none'}",
        f"Reduction rules: {', '.join(data['reduction_rules'])}",
        "",
        "## Modules",
        "",
    ]
    for module in data["modules"]:
        lines.append(f"### {module['name']} ({module['role']}, {module['subsystem']})")
        lines.append(f"Source: {module['source']}")
        lines.append(f"Ports: {', '.join(module['ports']) if module['ports'] else 'none'}")
        lines.append(f"Clocks: {', '.join(module['clocks']) if module['clocks'] else 'none'}")
        lines.append(f"Resets: {', '.join(module['resets']) if module['resets'] else 'none'}")
        lines.append(f"Instances: {', '.join(module['instances']) if module['instances'] else 'none'}")
        lines.append("")
    if data["truncated_modules"]:
        lines.append(f"... {data['truncated_modules']} modules omitted from full summaries")
        lines.append("")
    if data["interface_stubs"]:
        lines.extend(["## Interface Stubs For Omitted Modules", ""])
        for stub in data["interface_stubs"]:
            lines.append(f"### {stub['name']} ({stub['role']}, {stub['subsystem']})")
            lines.append(f"Source: {stub['source']}")
            lines.append(f"Ports: {', '.join(stub['ports']) if stub['ports'] else 'none'}")
            lines.append(f"Clocks: {', '.join(stub['clocks']) if stub['clocks'] else 'none'}")
            lines.append(f"Resets: {', '.join(stub['resets']) if stub['resets'] else 'none'}")
            lines.append(f"Parameters: {', '.join(stub['parameters']) if stub['parameters'] else 'none'}")
            lines.append(f"Instance count: {stub['instance_count']}")
            lines.append("")
    if data["truncated_interface_stubs"]:
        lines.append(f"... {data['truncated_interface_stubs']} interface stubs omitted by interface-stub budget")
    return "\n".join(lines).rstrip() + "\n"


def render_reduction_rules() -> str:
    lines = ["# RTL Reduction Rules", ""]
    for rule in REDUCTION_RULES:
        lines.extend([f"## {rule['id']}: {rule['title']}", "", rule["description"], ""])
    return "\n".join(lines).rstrip() + "\n"


def _reduce_module(module: Module) -> dict[str, object]:
    return {
        "name": module.name,
        "source": module.source.label(),
        "role": module.role,
        "subsystem": module.subsystem,
        "ports": [f"{port.direction} {port.width} {port.name}".strip() for port in module.ports],
        "parameters": [param.name for param in module.parameters],
        "clocks": module.clocks,
        "resets": module.resets,
        "instances": [f"{inst.name}:{inst.module}@{inst.source.label() if inst.source else ''}" for inst in module.instances],
        "assign_count": len(module.assigns),
        "procedural_blocks": [block.kind for block in module.procedural_blocks],
    }


def _interface_stub(module: Module) -> dict[str, object]:
    return {
        "name": module.name,
        "source": module.source.label(),
        "role": module.role,
        "subsystem": module.subsystem,
        "ports": [f"{port.direction} {port.width} {port.name}".strip() for port in module.ports],
        "parameters": [param.name for param in module.parameters],
        "clocks": module.clocks,
        "resets": module.resets,
        "instance_count": len(module.instances),
    }


def _ordered_active_names(index: DesignIndex) -> list[str]:
    if not index.reachable_modules:
        return sorted(index.modules)
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        if name in seen or name not in index.modules:
            return
        seen.add(name)
        ordered.append(name)
        for inst in index.modules[name].instances:
            visit(inst.module)

    for top in index.top_modules:
        visit(top)
    for name in index.reachable_modules:
        if name not in seen:
            ordered.append(name)
    return ordered

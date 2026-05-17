from __future__ import annotations

import json

from .models import DesignIndex, Module


def reduced_design_dict(index: DesignIndex, max_modules: int = 200) -> dict[str, object]:
    active_names = index.reachable_modules or sorted(index.modules)
    selected = active_names[:max_modules]
    return {
        "root": index.root,
        "tops": index.top_modules,
        "candidate_tops": index.candidate_top_modules[:80],
        "reachable_module_count": len(index.reachable_modules),
        "orphan_module_count": len(index.orphan_modules),
        "unresolved_modules": index.unresolved_modules[:80],
        "modules": [_reduce_module(index.modules[name]) for name in selected if name in index.modules],
        "truncated_modules": max(0, len(active_names) - len(selected)),
    }


def render_reduced_json(index: DesignIndex, max_modules: int = 200) -> str:
    return json.dumps(reduced_design_dict(index, max_modules=max_modules), indent=2)


def render_llm_context(index: DesignIndex, max_modules: int = 120) -> str:
    data = reduced_design_dict(index, max_modules=max_modules)
    lines = [
        "# Reduced RTL Context",
        "",
        f"Root: {data['root']}",
        f"Tops: {', '.join(data['tops']) if data['tops'] else 'none'}",
        f"Reachable modules: {data['reachable_module_count']}",
        f"Orphan modules: {data['orphan_module_count']}",
        f"Unresolved module types: {', '.join(data['unresolved_modules']) if data['unresolved_modules'] else 'none'}",
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
        lines.append(f"... {data['truncated_modules']} modules omitted from reduced context")
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

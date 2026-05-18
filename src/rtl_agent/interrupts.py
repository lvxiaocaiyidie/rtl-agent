from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import DesignIndex, Module, SourceRange


@dataclass(slots=True)
class InterruptNode:
    id: str
    kind: str
    name: str
    module: str
    source: str
    direction: str = ""
    width: str = ""
    confidence: str = "medium"


@dataclass(slots=True)
class InterruptEdge:
    source: str
    target: str
    kind: str
    evidence: str
    confidence: str = "medium"


@dataclass(slots=True)
class InterruptGraph:
    nodes: list[InterruptNode]
    edges: list[InterruptEdge]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "nodes": [asdict(node) for node in self.nodes],
            "edges": [asdict(edge) for edge in self.edges],
        }


def build_interrupt_graph(index: DesignIndex, root: Path | None = None) -> InterruptGraph:
    root_path = root or Path(index.root)
    nodes: dict[str, InterruptNode] = {}
    edges: list[InterruptEdge] = []

    for module in _active_modules(index):
        _add_interrupt_objects(module, nodes)
        _add_instance_edges(index, module, nodes, edges)
        _add_assignment_edges(root_path, module, nodes, edges)

    edges = _dedupe_edges(edges)
    edges.sort(key=_edge_sort_key)
    summary = _summarize(index, list(nodes.values()), edges)
    return InterruptGraph(nodes=sorted(nodes.values(), key=lambda n: n.id), edges=edges, summary=summary)


def render_interrupt_json(index: DesignIndex, root: Path | None = None) -> str:
    return json.dumps(build_interrupt_graph(index, root=root).to_dict(), indent=2)


def render_interrupt_markdown(index: DesignIndex, root: Path | None = None) -> str:
    graph = build_interrupt_graph(index, root=root)
    lines = ["# Interrupt Contract Graph", ""]
    lines.extend(
        [
            f"- Top modules: {', '.join(index.top_modules) or 'none'}",
            f"- Interrupt-like nodes: {len(graph.nodes)}",
            f"- Edges: {len(graph.edges)}",
            f"- Aggregation edges: {graph.summary['edge_kinds'].get('aggregates_bit', 0)}",
            f"- Instance connection edges: {graph.summary['edge_kinds'].get('instance_connection', 0)}",
            f"- Constant/tie-off edges: {graph.summary['edge_kinds'].get('constant_assignment', 0)}",
            "",
        ]
    )
    if graph.summary["top_level_interrupts"]:
        lines.extend(["## Top-Level Interrupt Ports", ""])
        for item in graph.summary["top_level_interrupts"]:
            lines.append(f"- `{item['module']}.{item['name']}` ({item['direction']}) at `{item['source']}`")
        lines.append("")
    if graph.edges:
        lines.extend(["## Edges", ""])
        for edge in graph.edges[:120]:
            lines.append(f"- `{edge.source}` -> `{edge.target}` ({edge.kind}) `{edge.evidence}`")
        if len(graph.edges) > 120:
            lines.append(f"- ... {len(graph.edges) - 120} more")
    return "\n".join(lines).rstrip() + "\n"


def _active_modules(index: DesignIndex) -> list[Module]:
    names = index.reachable_modules or sorted(index.modules)
    return [index.modules[name] for name in names if name in index.modules]


def _add_interrupt_objects(module: Module, nodes: dict[str, InterruptNode]) -> None:
    for port in module.ports:
        if _looks_interrupt_like(port.name):
            _ensure_node(
                nodes,
                _node_id(module.name, port.name),
                "port",
                port.name,
                module.name,
                port.source.label() if port.source else module.source.label(),
                direction=port.direction,
                width=port.width,
                confidence="high",
            )
    for signal in module.signals:
        if _looks_interrupt_like(signal.name):
            _ensure_node(
                nodes,
                _node_id(module.name, signal.name),
                "signal",
                signal.name,
                module.name,
                signal.source.label() if signal.source else module.source.label(),
                width=signal.width,
                confidence="medium",
            )


def _add_instance_edges(index: DesignIndex, module: Module, nodes: dict[str, InterruptNode], edges: list[InterruptEdge]) -> None:
    for inst in module.instances:
        target = index.modules.get(inst.module)
        if not target or inst.connection_style != "named":
            continue
        target_ports = {port.name: port for port in target.ports}
        for formal, actual in inst.connections.items():
            port = target_ports.get(formal)
            if not port:
                continue
            if not (_looks_interrupt_like(formal) or _looks_interrupt_expr(actual)):
                continue
            parent_id = _node_id(module.name, _clean_expr_name(actual) or actual or "open")
            child_id = _node_id(target.name, formal)
            if _is_constant(actual) or actual.strip() == "":
                const_id = _node_id(module.name, actual.strip() or "open")
                _ensure_node(nodes, const_id, "constant", actual.strip() or "open", module.name, inst.source.label() if inst.source else module.source.label(), confidence="high")
                _ensure_node(nodes, child_id, "port", formal, target.name, port.source.label() if port.source else target.source.label(), direction=port.direction, width=port.width, confidence="high")
                edges.append(InterruptEdge(const_id, child_id, "constant_assignment", inst.source.label() if inst.source else module.source.label(), confidence="high"))
                continue
            _ensure_node(nodes, parent_id, "signal_ref", _clean_expr_name(actual) or actual, module.name, inst.source.label() if inst.source else module.source.label())
            _ensure_node(nodes, child_id, "port", formal, target.name, port.source.label() if port.source else target.source.label(), direction=port.direction, width=port.width, confidence="high")
            if port.direction == "output":
                edges.append(InterruptEdge(child_id, parent_id, "instance_connection", inst.source.label() if inst.source else module.source.label()))
            else:
                edges.append(InterruptEdge(parent_id, child_id, "instance_connection", inst.source.label() if inst.source else module.source.label()))


def _add_assignment_edges(root: Path, module: Module, nodes: dict[str, InterruptNode], edges: list[InterruptEdge]) -> None:
    path = root / module.source.file
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line_no in range(module.source.start_line, min(module.source.end_line, len(lines)) + 1):
        text = lines[line_no - 1].split("//", 1)[0]
        for match in re.finditer(r"\b(?P<dst>[a-zA-Z_][\w$]*)(?:\s*\[\s*(?P<bit>\d+)\s*\])?\s*(?:<=|=)\s*(?P<src>[^;]+);", text):
            dst = match.group("dst")
            bit = match.group("bit")
            src = match.group("src").strip()
            dst_is_interrupt = _looks_interrupt_like(dst)
            dst_is_contract_state = _looks_contract_state_like(dst)
            if not (dst_is_interrupt or (dst_is_contract_state and _looks_interrupt_expr(src))):
                continue
            dst_name = f"{dst}[{bit}]" if bit else dst
            dst_id = _node_id(module.name, dst_name)
            _ensure_node(nodes, dst_id, "signal_bit" if bit else "signal_ref", dst_name, module.name, f"{module.source.file}:{line_no}-{line_no}")
            if _is_constant(src):
                src_id = _node_id(module.name, src)
                _ensure_node(nodes, src_id, "constant", src, module.name, f"{module.source.file}:{line_no}-{line_no}", confidence="high")
                edges.append(InterruptEdge(src_id, dst_id, "constant_assignment", f"{module.source.file}:{line_no}-{line_no}", confidence="high"))
                continue
            for src_name in _interrupt_names_in_expr(src):
                src_id = _node_id(module.name, src_name)
                _ensure_node(nodes, src_id, "signal_ref", src_name, module.name, f"{module.source.file}:{line_no}-{line_no}")
                kind = "aggregates_bit" if bit else ("state_observation" if dst_is_contract_state and not dst_is_interrupt else "assigns")
                edges.append(InterruptEdge(src_id, dst_id, kind, f"{module.source.file}:{line_no}-{line_no}"))


def _summarize(index: DesignIndex, nodes: list[InterruptNode], edges: list[InterruptEdge]) -> dict[str, Any]:
    edge_kinds: dict[str, int] = {}
    for edge in edges:
        edge_kinds[edge.kind] = edge_kinds.get(edge.kind, 0) + 1
    top_set = set(index.top_modules)
    top_level = [
        {"module": node.module, "name": node.name, "direction": node.direction, "source": node.source}
        for node in nodes
        if node.module in top_set and node.kind == "port"
    ]
    return {
        "top_level_interrupts": sorted(top_level, key=lambda item: (item["module"], item["name"])),
        "edge_kinds": edge_kinds,
        "source_like_count": sum(1 for node in nodes if node.direction in {"input", ""} and node.kind != "constant"),
        "sink_like_count": sum(1 for node in nodes if node.direction == "output" or any(edge.target == node.id for edge in edges)),
    }


def _ensure_node(
    nodes: dict[str, InterruptNode],
    node_id: str,
    kind: str,
    name: str,
    module: str,
    source: str,
    direction: str = "",
    width: str = "",
    confidence: str = "medium",
) -> None:
    if node_id not in nodes:
        nodes[node_id] = InterruptNode(node_id, kind, name, module, source, direction=direction, width=width, confidence=confidence)


def _node_id(module: str, name: str) -> str:
    return f"{module}.{name}".replace(" ", "")


def _looks_interrupt_like(name: str) -> bool:
    low = name.lower()
    if "integer" in low or "pcpi_int" in low or low.startswith("instr_"):
        return False
    return bool(re.search(r"(^|_)(irq|intr|interrupt)(_|$|\d)", low) or re.search(r"(irq|intr)$", low))


def _looks_contract_state_like(name: str) -> bool:
    low = name.lower()
    if low.startswith("instr_"):
        return False
    return any(token in low for token in ("pending", "status", "mask", "enable", "clear", "eoi", "rdata", "rddata", "wdata"))


def _looks_interrupt_expr(expr: str) -> bool:
    return any(_looks_interrupt_like(name) for name in re.findall(r"[a-zA-Z_][\w$]*(?:\[\d+\])?", expr))


def _interrupt_names_in_expr(expr: str) -> list[str]:
    return [name for name in re.findall(r"[a-zA-Z_][\w$]*(?:\[\d+\])?", expr) if _looks_interrupt_like(name)]


def _clean_expr_name(expr: str) -> str:
    expr = expr.strip()
    match = re.fullmatch(r"([a-zA-Z_][\w$]*(?:\[\d+\])?)", expr)
    return match.group(1) if match else ""


def _is_constant(expr: str) -> bool:
    compact = expr.replace("_", "").replace(" ", "").lower()
    return bool(re.fullmatch(r"(?:\d+)?'[bdh][0-9a-fxz]+|\d+", compact))


def _dedupe_edges(edges: list[InterruptEdge]) -> list[InterruptEdge]:
    seen = set()
    out = []
    for edge in edges:
        key = (edge.source, edge.target, edge.kind, edge.evidence)
        if key in seen:
            continue
        seen.add(key)
        out.append(edge)
    return out


def _edge_sort_key(edge: InterruptEdge) -> tuple[int, str, str, str]:
    priority = {
        "instance_connection": 0,
        "aggregates_bit": 1,
        "state_observation": 2,
        "constant_assignment": 3,
        "assigns": 4,
    }
    return (priority.get(edge.kind, 9), edge.source, edge.target, edge.evidence)

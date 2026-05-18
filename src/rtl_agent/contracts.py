from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .indexer import build_index
from .interrupts import InterruptGraph, build_interrupt_graph
from .models import DesignIndex
from .tables import TableData, TableRow, parse_int, read_table, row_source, row_value, table_summary, to_hex


@dataclass(slots=True)
class ContractNode:
    id: str
    kind: str
    name: str
    source: str
    attrs: dict[str, Any] = field(default_factory=dict)
    confidence: str = "medium"


@dataclass(slots=True)
class ContractEdge:
    source: str
    target: str
    kind: str
    evidence: str
    attrs: dict[str, Any] = field(default_factory=dict)
    confidence: str = "medium"


@dataclass(slots=True)
class ContractGraph:
    nodes: list[ContractNode]
    edges: list[ContractEdge]
    issues: list[dict[str, Any]]
    summary: dict[str, Any]
    agent_handoff: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "nodes": [asdict(node) for node in self.nodes],
            "edges": [asdict(edge) for edge in self.edges],
            "issues": self.issues,
            "agent_handoff": self.agent_handoff,
        }


def build_contract_graph(
    index: DesignIndex,
    root: Path | None = None,
    address_maps: list[Path] | None = None,
    reg_tables: list[Path] | None = None,
    interrupt_tables: list[Path] | None = None,
    noc_tables: list[Path] | None = None,
    crg_tables: list[Path] | None = None,
    eda_tables: list[Path] | None = None,
    blackbox_tables: list[Path] | None = None,
) -> ContractGraph:
    root_path = root or Path(index.root)
    tables = _load_tables(address_maps or [], "address_map")
    tables.extend(_load_tables(reg_tables or [], "register_table"))
    tables.extend(_load_tables(interrupt_tables or [], "interrupt_table"))
    tables.extend(_load_tables(noc_tables or [], "noc_table"))
    tables.extend(_load_tables(crg_tables or [], "crg_table"))
    tables.extend(_load_tables(eda_tables or [], "eda_connectivity"))
    tables.extend(_load_tables(blackbox_tables or [], "blackbox_table"))

    nodes: dict[str, ContractNode] = {}
    edges: list[ContractEdge] = []
    intr_graph = build_interrupt_graph(index, root=root_path)
    _merge_rtl_interfaces(index, nodes, edges)
    _merge_interrupt_graph(intr_graph, nodes, edges)
    for table in tables:
        _merge_table(table, nodes, edges)
    _add_name_matches(nodes, edges)
    edges = _dedupe_edges(edges)
    edges.sort(key=lambda e: (_edge_priority(e.kind), e.source, e.target, e.evidence))
    issues = _contract_issues(intr_graph, nodes, edges)
    summary = _summary(index, tables, nodes, edges, issues)
    handoff = _agent_handoff(index, summary, issues)
    return ContractGraph(
        nodes=sorted(nodes.values(), key=lambda n: n.id),
        edges=edges,
        issues=issues,
        summary=summary,
        agent_handoff=handoff,
    )


def render_contract_json(
    index: DesignIndex,
    root: Path | None = None,
    address_maps: list[Path] | None = None,
    reg_tables: list[Path] | None = None,
    interrupt_tables: list[Path] | None = None,
    noc_tables: list[Path] | None = None,
    crg_tables: list[Path] | None = None,
    eda_tables: list[Path] | None = None,
    blackbox_tables: list[Path] | None = None,
) -> str:
    graph = build_contract_graph(
        index,
        root=root,
        address_maps=address_maps,
        reg_tables=reg_tables,
        interrupt_tables=interrupt_tables,
        noc_tables=noc_tables,
        crg_tables=crg_tables,
        eda_tables=eda_tables,
        blackbox_tables=blackbox_tables,
    )
    return json.dumps(graph.to_dict(), indent=2)


def render_contract_markdown(
    index: DesignIndex,
    root: Path | None = None,
    address_maps: list[Path] | None = None,
    reg_tables: list[Path] | None = None,
    interrupt_tables: list[Path] | None = None,
    noc_tables: list[Path] | None = None,
    crg_tables: list[Path] | None = None,
    eda_tables: list[Path] | None = None,
    blackbox_tables: list[Path] | None = None,
) -> str:
    graph = build_contract_graph(
        index,
        root=root,
        address_maps=address_maps,
        reg_tables=reg_tables,
        interrupt_tables=interrupt_tables,
        noc_tables=noc_tables,
        crg_tables=crg_tables,
        eda_tables=eda_tables,
        blackbox_tables=blackbox_tables,
    )
    lines = ["# SoC Contract Graph", ""]
    lines.extend(
        [
            f"- Top modules: {', '.join(index.top_modules) or 'none'}",
            f"- Nodes: {len(graph.nodes)}",
            f"- Edges: {len(graph.edges)}",
            f"- Issues: {len(graph.issues)}",
            "",
            "## Edge Kinds",
            "",
        ]
    )
    for kind, count in sorted(graph.summary["edge_kinds"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {kind}: {count}")
    if graph.summary["tables"]:
        lines.extend(["", "## Table Inputs", ""])
        for table in graph.summary["tables"]:
            lines.append(f"- `{table['path']}` ({table['kind']}, {table['rows']} rows)")
    if graph.issues:
        lines.extend(["", "## Review Issues", ""])
        for issue in graph.issues[:80]:
            lines.append(f"- [{issue['severity']}] {issue['kind']}: {issue['message']} `{issue.get('source', '')}`")
    lines.extend(["", "## High-Value Edges", ""])
    for edge in _high_value_edges(graph.edges)[:160]:
        lines.append(f"- `{edge.source}` -> `{edge.target}` ({edge.kind}) `{edge.evidence}`")
    if len(graph.edges) > 160:
        lines.append(f"- ... {len(graph.edges) - 160} more")
    lines.extend(["", "## Agent Handoff", "", render_agent_handoff_markdown(graph)])
    return "\n".join(lines).rstrip() + "\n"


def render_agent_handoff_markdown(graph: ContractGraph) -> str:
    handoff = graph.agent_handoff
    lines = [
        "Use this as the first prompt/context for an LLM or coding agent. Do not ask the model to parse full RTL first; ask it to inspect this graph, then request source slices only for uncertain edges.",
        "",
        "### Suggested Agent Tasks",
        "",
    ]
    for task in handoff["tasks"]:
        lines.append(f"- {task}")
    lines.extend(["", "### Required Evidence Discipline", ""])
    for rule in handoff["evidence_rules"]:
        lines.append(f"- {rule}")
    lines.extend(["", "### Useful Commands", ""])
    for command in handoff["commands"]:
        lines.append(f"- `{command}`")
    return "\n".join(lines)


def contract_llm_messages(graph: ContractGraph) -> list[dict[str, str]]:
    payload = {
        "summary": graph.summary,
        "issues": graph.issues[:80],
        "high_value_edges": [asdict(edge) for edge in _high_value_edges(graph.edges)[:140]],
        "agent_handoff": graph.agent_handoff,
    }
    return [
        {
            "role": "system",
            "content": (
                "You are reviewing SoC integration contracts. Use the provided graph facts first. "
                "Do not invent RTL behavior beyond cited edges or table rows. Separate hard evidence, "
                "semantic guesses, and requested source-slice follow-ups."
            ),
        },
        {
            "role": "user",
            "content": (
                "Review this contract graph for SoC integration risk. Focus on issues VCS does not judge semantically: "
                "interrupt table vs RTL path mismatches, software IRQ numbering, register field association, tied-off documented interrupts, "
                "NoC route/QoS/security metadata, CRG ownership, blackbox interface completeness, EDA connectivity disagreement, "
                "and naming inconsistencies. Keep the report concise.\n\n"
                + json.dumps(payload, indent=2)
            ),
        },
    ]


def write_contract_artifacts(
    index: DesignIndex,
    out_dir: Path,
    root: Path | None = None,
    address_maps: list[Path] | None = None,
    reg_tables: list[Path] | None = None,
    interrupt_tables: list[Path] | None = None,
    noc_tables: list[Path] | None = None,
    crg_tables: list[Path] | None = None,
    eda_tables: list[Path] | None = None,
    blackbox_tables: list[Path] | None = None,
) -> ContractGraph:
    out_dir.mkdir(parents=True, exist_ok=True)
    graph = build_contract_graph(
        index,
        root=root,
        address_maps=address_maps,
        reg_tables=reg_tables,
        interrupt_tables=interrupt_tables,
        noc_tables=noc_tables,
        crg_tables=crg_tables,
        eda_tables=eda_tables,
        blackbox_tables=blackbox_tables,
    )
    (out_dir / "contract_graph.json").write_text(json.dumps(graph.to_dict(), indent=2), encoding="utf-8")
    (out_dir / "contract_graph.md").write_text(_render_existing_contract_markdown(index, graph), encoding="utf-8")
    (out_dir / "agent_handoff.md").write_text(render_agent_handoff_markdown(graph) + "\n", encoding="utf-8")
    from .contract_dashboard import render_contract_dashboard

    (out_dir / "contract_dashboard.html").write_text(render_contract_dashboard(graph), encoding="utf-8")
    return graph


def _render_existing_contract_markdown(index: DesignIndex, graph: ContractGraph) -> str:
    lines = ["# SoC Contract Graph", ""]
    lines.extend(
        [
            f"- Top modules: {', '.join(index.top_modules) or 'none'}",
            f"- Nodes: {len(graph.nodes)}",
            f"- Edges: {len(graph.edges)}",
            f"- Issues: {len(graph.issues)}",
            "",
            "## Edge Kinds",
            "",
        ]
    )
    for kind, count in sorted(graph.summary["edge_kinds"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {kind}: {count}")
    if graph.summary["tables"]:
        lines.extend(["", "## Table Inputs", ""])
        for table in graph.summary["tables"]:
            lines.append(f"- `{table['path']}` ({table['kind']}, {table['rows']} rows)")
    if graph.issues:
        lines.extend(["", "## Review Issues", ""])
        for issue in graph.issues[:80]:
            lines.append(f"- [{issue['severity']}] {issue['kind']}: {issue['message']} `{issue.get('source', '')}`")
    lines.extend(["", "## High-Value Edges", ""])
    for edge in _high_value_edges(graph.edges)[:160]:
        lines.append(f"- `{edge.source}` -> `{edge.target}` ({edge.kind}) `{edge.evidence}`")
    lines.extend(["", "## Agent Handoff", "", render_agent_handoff_markdown(graph)])
    return "\n".join(lines).rstrip() + "\n"


def _load_tables(paths: list[Path], kind: str) -> list[TableData]:
    return [read_table(path, kind) for path in paths]


def _merge_rtl_interfaces(index: DesignIndex, nodes: dict[str, ContractNode], edges: list[ContractEdge]) -> None:
    names = index.reachable_modules or sorted(index.modules)
    for module_name in names:
        module = index.modules.get(module_name)
        if not module:
            continue
        module_id = f"rtl:{module.name}"
        _ensure_node(nodes, module_id, "rtl_module", module.name, module.source.label(), attrs={"role": module.role, "subsystem": module.subsystem}, confidence="high")
        for port in module.ports:
            port_id = f"rtl:{module.name}.{port.name}"
            kind = "rtl_clock_signal" if port.name in module.clocks else "rtl_reset_signal" if port.name in module.resets else "rtl_port"
            _ensure_node(
                nodes,
                port_id,
                kind,
                port.name,
                port.source.label() if port.source else module.source.label(),
                attrs={"module": module.name, "direction": port.direction, "width": port.width, "data_type": port.data_type},
                confidence="high",
            )
            edges.append(ContractEdge(module_id, port_id, "rtl_has_port", port.source.label() if port.source else module.source.label(), confidence="high"))
        for name in module.clocks:
            clock_id = f"rtl:{module.name}.{name}"
            _ensure_node(nodes, clock_id, "rtl_clock_signal", name, module.source.label(), attrs={"module": module.name}, confidence="high")
        for name in module.resets:
            reset_id = f"rtl:{module.name}.{name}"
            _ensure_node(nodes, reset_id, "rtl_reset_signal", name, module.source.label(), attrs={"module": module.name}, confidence="high")


def _merge_interrupt_graph(graph: InterruptGraph, nodes: dict[str, ContractNode], edges: list[ContractEdge]) -> None:
    for node in graph.nodes:
        _ensure_node(
            nodes,
            f"rtl:{node.id}",
            f"rtl_interrupt_{node.kind}",
            node.name,
            node.source,
            attrs={"module": node.module, "direction": node.direction, "width": node.width},
            confidence=node.confidence,
        )
    for edge in graph.edges:
        edges.append(
            ContractEdge(
                f"rtl:{edge.source}",
                f"rtl:{edge.target}",
                f"rtl_{edge.kind}",
                edge.evidence,
                confidence=edge.confidence,
            )
        )


def _merge_table(table: TableData, nodes: dict[str, ContractNode], edges: list[ContractEdge]) -> None:
    if table.kind == "noc_table":
        _merge_noc_table(table, nodes, edges)
        return
    if table.kind == "crg_table":
        _merge_crg_table(table, nodes, edges)
        return
    if table.kind == "eda_connectivity":
        _merge_eda_table(table, nodes, edges)
        return
    if table.kind == "blackbox_table":
        _merge_blackbox_table(table, nodes, edges)
        return
    for row in table.rows:
        block = row_value(row, "block") or "unknown_block"
        register = row_value(row, "register")
        field = row_value(row, "field")
        signal = row_value(row, "signal")
        interrupt = row_value(row, "interrupt")
        irq_number = row_value(row, "irq_number")
        base = parse_int(row_value(row, "base_address"))
        offset = parse_int(row_value(row, "offset"))
        address = parse_int(row_value(row, "address"))
        if address is None and base is not None and offset is not None:
            address = base + offset
        evidence = row_source(row)

        block_id = f"table:block:{_slug(block)}"
        _ensure_node(nodes, block_id, "address_block", block, evidence, attrs={"base_address": to_hex(base)})

        reg_id = ""
        if register:
            reg_id = f"table:reg:{_slug(block)}.{_slug(register)}"
            _ensure_node(
                nodes,
                reg_id,
                "register",
                register,
                evidence,
                attrs={"block": block, "offset": to_hex(offset), "address": to_hex(address), "access": row_value(row, "access")},
            )
            edges.append(ContractEdge(block_id, reg_id, "contains_register", evidence))

        field_id = ""
        if field:
            parent = reg_id or block_id
            field_id = f"table:field:{_slug(block)}.{_slug(register or 'unknown_reg')}.{_slug(field)}"
            _ensure_node(
                nodes,
                field_id,
                "register_field",
                field,
                evidence,
                attrs={"block": block, "register": register, "bits": row_value(row, "bits"), "access": row_value(row, "access"), "reset": row_value(row, "reset")},
            )
            edges.append(ContractEdge(parent, field_id, "has_field", evidence))

        if interrupt or _looks_interrupt_table_row(row):
            name = interrupt or signal or field or register
            intr_id = f"table:irq:{_slug(name)}"
            _ensure_node(
                nodes,
                intr_id,
                "interrupt_spec",
                name,
                evidence,
                attrs={
                    "block": block,
                    "register": register,
                    "field": field,
                    "signal": signal,
                    "irq_number": irq_number,
                    "address": to_hex(address),
                    "description": row_value(row, "description"),
                },
                confidence="high",
            )
            if field_id:
                edges.append(ContractEdge(field_id, intr_id, "documents_interrupt", evidence, confidence="high"))
            elif reg_id:
                edges.append(ContractEdge(reg_id, intr_id, "documents_interrupt", evidence, confidence="high"))
            if irq_number:
                sw_id = f"table:sw_irq:{_slug(irq_number)}"
                _ensure_node(nodes, sw_id, "software_irq", irq_number, evidence, attrs={"name": name})
                edges.append(ContractEdge(intr_id, sw_id, "maps_to_sw_irq", evidence, confidence="high"))


def _merge_noc_table(table: TableData, nodes: dict[str, ContractNode], edges: list[ContractEdge]) -> None:
    for row in table.rows:
        evidence = row_source(row)
        master = row_value(row, "master", "source", "block")
        slave = row_value(row, "slave", "target")
        endpoint = row_value(row, "endpoint", "signal")
        route_id = row_value(row, "route_id")
        protocol = row_value(row, "protocol")
        qos = row_value(row, "qos")
        security = row_value(row, "security")
        width = row_value(row, "width")
        if master:
            master_id = f"table:noc_ep:{_slug(master)}"
            _ensure_node(nodes, master_id, "noc_endpoint", master, evidence, attrs={"role": "master", "protocol": protocol, "qos": qos, "security": security, "width": width})
        else:
            master_id = ""
        if slave:
            slave_id = f"table:noc_ep:{_slug(slave)}"
            _ensure_node(nodes, slave_id, "noc_endpoint", slave, evidence, attrs={"role": "slave", "protocol": protocol, "qos": qos, "security": security, "width": width})
        else:
            slave_id = ""
        if endpoint and not master and not slave:
            endpoint_id = f"table:noc_ep:{_slug(endpoint)}"
            _ensure_node(nodes, endpoint_id, "noc_endpoint", endpoint, evidence, attrs={"protocol": protocol, "qos": qos, "security": security, "width": width})
        if master_id and slave_id:
            edge_attrs = {"route_id": route_id, "protocol": protocol, "qos": qos, "security": security, "width": width}
            edges.append(ContractEdge(master_id, slave_id, "noc_route", evidence, attrs=edge_attrs, confidence="high"))
        if route_id:
            route_node = f"table:noc_route:{_slug(route_id)}"
            _ensure_node(nodes, route_node, "noc_route_id", route_id, evidence, attrs={"protocol": protocol, "qos": qos, "security": security})
            for endpoint_id in (master_id, slave_id):
                if endpoint_id:
                    edges.append(ContractEdge(endpoint_id, route_node, "uses_route_id", evidence, confidence="high"))


def _merge_crg_table(table: TableData, nodes: dict[str, ContractNode], edges: list[ContractEdge]) -> None:
    for row in table.rows:
        evidence = row_source(row)
        block = row_value(row, "block", "target") or "unknown_block"
        clock = row_value(row, "clock", "source")
        reset = row_value(row, "reset_signal")
        domain = row_value(row, "domain")
        frequency = row_value(row, "frequency")
        polarity = row_value(row, "polarity")
        block_id = f"table:block:{_slug(block)}"
        _ensure_node(nodes, block_id, "integration_block", block, evidence)
        if clock:
            clk_id = f"table:clock:{_slug(clock)}"
            _ensure_node(nodes, clk_id, "clock_signal", clock, evidence, attrs={"domain": domain, "frequency": frequency})
            edges.append(ContractEdge(clk_id, block_id, "drives_clock", evidence, attrs={"domain": domain, "frequency": frequency}, confidence="high"))
        if reset:
            rst_id = f"table:reset:{_slug(reset)}"
            _ensure_node(nodes, rst_id, "reset_signal", reset, evidence, attrs={"domain": domain, "polarity": polarity})
            edges.append(ContractEdge(rst_id, block_id, "drives_reset", evidence, attrs={"domain": domain, "polarity": polarity}, confidence="high"))


def _merge_eda_table(table: TableData, nodes: dict[str, ContractNode], edges: list[ContractEdge]) -> None:
    for row in table.rows:
        evidence = row_source(row)
        source = row_value(row, "source", "master")
        target = row_value(row, "target", "slave")
        kind = row_value(row, "edge_kind") or "eda_connects"
        signal = row_value(row, "signal")
        if not source and signal:
            source = signal
        if not source or not target:
            continue
        src_id = f"eda:{_slug(source)}"
        dst_id = f"eda:{_slug(target)}"
        _ensure_node(nodes, src_id, "eda_object", source, evidence, attrs={"signal": signal, "tool": "eda"})
        _ensure_node(nodes, dst_id, "eda_object", target, evidence, attrs={"tool": "eda"})
        edges.append(ContractEdge(src_id, dst_id, f"eda_{_slug(kind)}", evidence, attrs={"signal": signal, "description": row_value(row, "description")}, confidence="high"))


def _merge_blackbox_table(table: TableData, nodes: dict[str, ContractNode], edges: list[ContractEdge]) -> None:
    for row in table.rows:
        evidence = row_source(row)
        name = row_value(row, "blackbox", "block") or "unknown_blackbox"
        protocol = row_value(row, "protocol")
        endpoint = row_value(row, "endpoint")
        clock = row_value(row, "clock")
        reset = row_value(row, "reset_signal")
        interrupt = row_value(row, "interrupt")
        bb_id = f"table:blackbox:{_slug(name)}"
        _ensure_node(nodes, bb_id, "blackbox", name, evidence, attrs={"protocol": protocol, "description": row_value(row, "description")}, confidence="high")
        if endpoint:
            ep_id = f"table:interface:{_slug(name)}.{_slug(endpoint)}"
            _ensure_node(nodes, ep_id, "interface_contract", endpoint, evidence, attrs={"protocol": protocol, "width": row_value(row, "width")})
            edges.append(ContractEdge(bb_id, ep_id, "has_interface_contract", evidence, confidence="high"))
        if clock:
            clk_id = f"table:clock:{_slug(clock)}"
            _ensure_node(nodes, clk_id, "clock_signal", clock, evidence)
            edges.append(ContractEdge(clk_id, bb_id, "blackbox_clock", evidence))
        if reset:
            rst_id = f"table:reset:{_slug(reset)}"
            _ensure_node(nodes, rst_id, "reset_signal", reset, evidence)
            edges.append(ContractEdge(rst_id, bb_id, "blackbox_reset", evidence))
        if interrupt:
            irq_id = f"table:irq:{_slug(interrupt)}"
            _ensure_node(nodes, irq_id, "interrupt_spec", interrupt, evidence, attrs={"block": name, "signal": row_value(row, "signal")}, confidence="high")
            edges.append(ContractEdge(bb_id, irq_id, "blackbox_interrupt", evidence, confidence="high"))


def _add_name_matches(nodes: dict[str, ContractNode], edges: list[ContractEdge]) -> None:
    rtl_nodes = [node for node in nodes.values() if node.id.startswith("rtl:")]
    table_irqs = [node for node in nodes.values() if node.kind == "interrupt_spec"]
    matchable_specs = [
        node
        for node in nodes.values()
        if node.kind in {"noc_endpoint", "clock_signal", "reset_signal", "blackbox", "interface_contract", "eda_object"}
    ]
    rtl_by_norm: dict[str, list[ContractNode]] = {}
    for node in rtl_nodes:
        for key in _match_keys(node.name, node.attrs.get("module", "")):
            rtl_by_norm.setdefault(key, []).append(node)
    rtl_objects_by_norm: dict[str, list[ContractNode]] = {}
    for node in rtl_nodes:
        for key in _rtl_object_match_keys(node):
            rtl_objects_by_norm.setdefault(key, []).append(node)
    for irq in table_irqs:
        candidates = [irq.name, str(irq.attrs.get("signal", "")), str(irq.attrs.get("field", ""))]
        seen: set[str] = set()
        for candidate in candidates:
            for key in _match_keys(candidate, ""):
                for rtl in rtl_by_norm.get(key, []):
                    if rtl.id in seen:
                        continue
                    seen.add(rtl.id)
                    edges.append(ContractEdge(irq.id, rtl.id, "matches_rtl_signal", irq.source, attrs={"match_key": key}, confidence="medium"))
    for spec in matchable_specs:
        candidates = [spec.name, str(spec.attrs.get("signal", "")), str(spec.attrs.get("module", ""))]
        seen = set()
        for candidate in candidates:
            for key in _object_match_keys(candidate):
                for rtl in rtl_objects_by_norm.get(key, []):
                    if rtl.id in seen:
                        continue
                    seen.add(rtl.id)
                    edges.append(ContractEdge(spec.id, rtl.id, "matches_rtl_object", spec.source, attrs={"match_key": key}, confidence="low"))


def _contract_issues(intr_graph: InterruptGraph, nodes: dict[str, ContractNode], edges: list[ContractEdge]) -> list[dict[str, Any]]:
    matched_table_irqs = {edge.source for edge in edges if edge.kind == "matches_rtl_signal"}
    matched_rtl = {edge.target for edge in edges if edge.kind == "matches_rtl_signal"}
    matched_objects = {edge.source for edge in edges if edge.kind == "matches_rtl_object"}
    issues: list[dict[str, Any]] = []
    for node in nodes.values():
        if node.kind == "interrupt_spec" and node.id not in matched_table_irqs:
            issues.append(
                {
                    "severity": "P2",
                    "kind": "table_interrupt_without_rtl_match",
                    "message": f"Table interrupt `{node.name}` has no matched RTL interrupt signal yet.",
                    "source": node.source,
                }
            )
    for item in intr_graph.summary.get("top_level_interrupts", []):
        rtl_id = f"rtl:{item['module']}.{item['name']}"
        if rtl_id not in matched_rtl:
            issues.append(
                {
                    "severity": "P3",
                    "kind": "rtl_top_interrupt_without_table_match",
                    "message": f"Top-level RTL interrupt `{item['module']}.{item['name']}` has no table match yet.",
                    "source": item["source"],
                }
            )
    for edge in edges:
        if edge.kind == "matches_rtl_signal" and any(tie.target == edge.target and tie.kind == "rtl_constant_assignment" for tie in edges):
            source = nodes.get(edge.source)
            issues.append(
                {
                    "severity": "P2",
                    "kind": "documented_interrupt_tied_off_in_rtl",
                    "message": f"Documented interrupt `{source.name if source else edge.source}` appears tied to a constant in RTL.",
                    "source": edge.evidence,
                }
            )
    route_users: dict[str, list[ContractEdge]] = {}
    for edge in edges:
        if edge.kind == "uses_route_id":
            route_users.setdefault(edge.target, []).append(edge)
    for route_id, users in route_users.items():
        sources = sorted({edge.source for edge in users})
        if len(sources) > 2:
            route_name = nodes.get(route_id).name if route_id in nodes else route_id
            issues.append(
                {
                    "severity": "P2",
                    "kind": "noc_route_id_used_by_multiple_endpoints",
                    "message": f"NoC route ID `{route_name}` is referenced by {len(sources)} endpoints; check uniqueness or intended multicast.",
                    "source": users[0].evidence,
                }
            )
    for node in nodes.values():
        if node.kind == "noc_endpoint" and node.id not in matched_objects:
            issues.append(
                {
                    "severity": "P3",
                    "kind": "noc_endpoint_without_rtl_match",
                    "message": f"NoC endpoint `{node.name}` has no matched RTL object yet.",
                    "source": node.source,
                }
            )
        if node.kind == "blackbox":
            outgoing = [edge.kind for edge in edges if edge.source == node.id]
            incoming = [edge.kind for edge in edges if edge.target == node.id]
            if "has_interface_contract" not in outgoing:
                issues.append(
                    {
                        "severity": "P2",
                        "kind": "blackbox_missing_interface_contract",
                        "message": f"Blackbox `{node.name}` has no interface contract row.",
                        "source": node.source,
                    }
                )
            if "blackbox_clock" not in incoming or "blackbox_reset" not in incoming:
                issues.append(
                    {
                        "severity": "P3",
                        "kind": "blackbox_missing_crg_contract",
                        "message": f"Blackbox `{node.name}` is missing clock or reset metadata.",
                        "source": node.source,
                    }
                )
    return issues


def _summary(index: DesignIndex, tables: list[TableData], nodes: dict[str, ContractNode], edges: list[ContractEdge], issues: list[dict[str, Any]]) -> dict[str, Any]:
    edge_kinds: dict[str, int] = {}
    node_kinds: dict[str, int] = {}
    for edge in edges:
        edge_kinds[edge.kind] = edge_kinds.get(edge.kind, 0) + 1
    for node in nodes.values():
        node_kinds[node.kind] = node_kinds.get(node.kind, 0) + 1
    return {
        "top_modules": index.top_modules,
        "tables": [table_summary(table) for table in tables],
        "node_kinds": node_kinds,
        "edge_kinds": edge_kinds,
        "issue_count": len(issues),
    }


def _agent_handoff(index: DesignIndex, summary: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "purpose": "Review SoC integration contracts using script-extracted facts before requesting source slices.",
        "tasks": [
            "Check whether table interrupts, software IRQ numbers, and RTL interrupt paths agree.",
            "Check NoC endpoint bindings, route IDs, QoS/security attributes, and address ownership against RTL or EDA evidence.",
            "Check clock/reset domain rows against RTL clock/reset objects and blackbox metadata.",
            "Use EDA connectivity rows as stronger evidence than lightweight RTL parsing when the two disagree.",
            "Prioritize table_interrupt_without_rtl_match and documented_interrupt_tied_off_in_rtl issues.",
            "Prioritize blackbox_missing_interface_contract and blackbox_missing_crg_contract before generating integration code.",
            "Use fuzzy naming judgment only after preserving exact graph evidence.",
            "Ask for rtl-agent slice commands when a graph edge is uncertain.",
        ],
        "evidence_rules": [
            "Every conclusion must cite contract_graph node or edge evidence.",
            "Do not claim an RTL bug from a table mismatch without checking line-level RTL evidence.",
            "Separate compiler/elaboration issues from architecture contract issues.",
        ],
        "commands": [
            f"rtl-agent slice {index.root} --module <module> --context-lines 40",
            f"rtl-agent contracts {index.root} --top {' --top '.join(index.top_modules) if index.top_modules else '<top>'} -o out/contract",
        ],
        "summary": summary,
        "top_issues": issues[:20],
    }


def _ensure_node(
    nodes: dict[str, ContractNode],
    node_id: str,
    kind: str,
    name: str,
    source: str,
    attrs: dict[str, Any] | None = None,
    confidence: str = "medium",
) -> None:
    if node_id not in nodes:
        nodes[node_id] = ContractNode(node_id, kind, name, source, attrs or {}, confidence)
    elif attrs:
        nodes[node_id].attrs.update({key: value for key, value in attrs.items() if value})


def _looks_interrupt_table_row(row: TableRow) -> bool:
    text = " ".join(row.values.values()).lower()
    return bool(re.search(r"(^|[_\s])(irq|intr|interrupt)([_\s]|$|\d)", text))


def _match_keys(name: str, module: str) -> set[str]:
    keys = set()
    for text in {name, f"{module}_{name}" if module else name}:
        norm = _slug(text)
        if norm:
            keys.add(norm)
        stripped = re.sub(r"^(rtl|sw|hw|int|irq|intr|interrupt)_*", "", norm)
        stripped = re.sub(r"_*(irq|intr|interrupt)$", "", stripped)
        if stripped:
            keys.add(stripped)
    return keys


def _object_match_keys(name: str) -> set[str]:
    key = _slug(name)
    return {key} if key and key != "unknown" else set()


def _rtl_object_match_keys(node: ContractNode) -> set[str]:
    keys = {_slug(node.name)}
    module = str(node.attrs.get("module", ""))
    if module and node.name:
        keys.add(_slug(f"{module}_{node.name}"))
        keys.add(_slug(f"{module}.{node.name}"))
    if node.kind == "rtl_module":
        keys.add(_slug(node.name))
    return {key for key in keys if key and key != "unknown"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_") or "unknown"


def _dedupe_edges(edges: list[ContractEdge]) -> list[ContractEdge]:
    seen = set()
    out = []
    for edge in edges:
        key = (edge.source, edge.target, edge.kind, edge.evidence)
        if key in seen:
            continue
        seen.add(key)
        out.append(edge)
    return out


def _edge_priority(kind: str) -> int:
    return {
        "matches_rtl_signal": 0,
        "matches_rtl_object": 1,
        "maps_to_sw_irq": 2,
        "documents_interrupt": 3,
        "noc_route": 4,
        "uses_route_id": 5,
        "drives_clock": 6,
        "drives_reset": 7,
        "rtl_instance_connection": 8,
        "rtl_aggregates_bit": 9,
        "rtl_state_observation": 10,
        "contains_register": 11,
        "has_field": 12,
    }.get(kind, 20)


def _high_value_edges(edges: list[ContractEdge]) -> list[ContractEdge]:
    high = {
        "matches_rtl_signal",
        "matches_rtl_object",
        "maps_to_sw_irq",
        "documents_interrupt",
        "noc_route",
        "uses_route_id",
        "drives_clock",
        "drives_reset",
        "has_interface_contract",
        "blackbox_clock",
        "blackbox_reset",
        "blackbox_interrupt",
        "rtl_instance_connection",
        "rtl_aggregates_bit",
        "rtl_state_observation",
    }
    return [edge for edge in edges if edge.kind in high] + [edge for edge in edges if edge.kind not in high]


def build_contract_graph_from_paths(
    rtl_root: Path,
    top: list[str] | None = None,
    top_file: Path | None = None,
    address_maps: list[Path] | None = None,
    reg_tables: list[Path] | None = None,
    interrupt_tables: list[Path] | None = None,
    noc_tables: list[Path] | None = None,
    crg_tables: list[Path] | None = None,
    eda_tables: list[Path] | None = None,
    blackbox_tables: list[Path] | None = None,
) -> ContractGraph:
    index = build_index(rtl_root, top=top, top_file=top_file)
    return build_contract_graph(
        index,
        root=rtl_root.resolve(),
        address_maps=address_maps,
        reg_tables=reg_tables,
        interrupt_tables=interrupt_tables,
        noc_tables=noc_tables,
        crg_tables=crg_tables,
        eda_tables=eda_tables,
        blackbox_tables=blackbox_tables,
    )

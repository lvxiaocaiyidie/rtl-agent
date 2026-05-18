from __future__ import annotations

from rtl_agent.models import DesignIndex
from rtl_agent.parser import _looks_like_clock, _looks_like_reset

from .base import Finding, ScriptRule


class UnknownInstanceModuleRule(ScriptRule):
    rule_id = "RTL001"
    title = "Unknown instance module"
    severity = "P2"
    category = "hierarchy"
    description = "An instantiated module type is not defined in the scanned RTL scope."

    def run(self, index: DesignIndex) -> list[Finding]:
        findings: list[Finding] = []
        for module in self.active_modules(index):
            for inst in module.instances:
                if inst.module not in index.modules:
                    findings.append(
                        Finding(
                            rule_id=self.rule_id,
                            severity=self.severity,
                            title=self.title,
                            message=f"{module.name}.{inst.name} instantiates {inst.module}, but that module was not found in scanned RTL.",
                            source=inst.source.label() if inst.source else module.source.label(),
                            module=module.name,
                            evidence=[f"instance={inst.name}", f"type={inst.module}"],
                        )
                    )
        return findings


class MissingNamedPortRule(ScriptRule):
    rule_id = "RTL002"
    title = "Instance port appears unconnected"
    severity = "P1"
    category = "integration"
    description = "A named instance connection omits ports declared by the target module."

    def run(self, index: DesignIndex) -> list[Finding]:
        findings: list[Finding] = []
        for module in self.active_modules(index):
            for inst in module.instances:
                target = index.modules.get(inst.module)
                if not target:
                    continue
                if inst.connection_style != "named":
                    continue
                required_ports = [p for p in target.ports if p.direction in {"input", "output", "inout"}]
                missing = [p.name for p in required_ports if p.name not in inst.connections]
                if missing:
                    findings.append(
                        Finding(
                            rule_id=self.rule_id,
                            severity=self.severity,
                            title=self.title,
                            message=f"{module.name}.{inst.name} is missing named connections for: {', '.join(missing)}.",
                            source=inst.source.label() if inst.source else module.source.label(),
                            module=module.name,
                            evidence=[f"target={target.name}", "missing=" + ",".join(missing)],
                        )
                    )
        return findings


class MissingClockOnContainerRule(ScriptRule):
    rule_id = "RTL003"
    title = "No clock detected on container module"
    severity = "P2"
    category = "clock_reset"
    description = "A module has sub-instances that appear clocked, but no clock-like port or signal is detected locally."

    def run(self, index: DesignIndex) -> list[Finding]:
        findings: list[Finding] = []
        for module in self.active_modules(index):
            if (
                module.instances
                and not module.clocks
                and module.role not in {"memory_or_cache"}
                and _children_require_clock(index, module)
            ):
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        title=self.title,
                        message=f"{module.name} contains sub-instances but no clock-like signal was detected.",
                        source=module.source.label(),
                        module=module.name,
                    )
                )
        return findings


class MissingResetOnContainerRule(ScriptRule):
    rule_id = "RTL004"
    title = "No reset detected on container module"
    severity = "P3"
    category = "clock_reset"
    description = "A module has sub-instances that appear reset-aware, but no reset-like port or signal is detected locally."

    def run(self, index: DesignIndex) -> list[Finding]:
        findings: list[Finding] = []
        for module in self.active_modules(index):
            if (
                module.instances
                and not module.resets
                and module.role not in {"clocking", "memory_or_cache"}
                and _children_require_reset(index, module)
            ):
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        title=self.title,
                        message=f"{module.name} contains sub-instances but no reset-like signal was detected.",
                        source=module.source.label(),
                        module=module.name,
                    )
                )
        return findings


def _children_require_clock(index: DesignIndex, module) -> bool:
    for inst in module.instances:
        child = index.modules.get(inst.module)
        if not child:
            continue
        if child.clocks or any(block.kind in {"always_ff", "always"} and ("posedge" in block.sensitivity or "negedge" in block.sensitivity) for block in child.procedural_blocks):
            return True
    return False


def _children_require_reset(index: DesignIndex, module) -> bool:
    for inst in module.instances:
        child = index.modules.get(inst.module)
        if not child:
            continue
        if child.resets:
            return True
        if any("reset" in block.sensitivity.lower() or "rst" in block.sensitivity.lower() for block in child.procedural_blocks):
            return True
    return False


class OrphanModuleRule(ScriptRule):
    rule_id = "RTL005"
    title = "Unreachable module under selected top"
    severity = "P3"
    category = "hierarchy"
    description = "A scanned module is not reachable from the selected top hierarchy."

    def run(self, index: DesignIndex) -> list[Finding]:
        if not index.orphan_modules:
            return []
        findings: list[Finding] = []
        for name in index.orphan_modules[:200]:
            module = index.modules[name]
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    title=self.title,
                    message=f"{name} is scanned but not reachable from selected top module(s).",
                    source=module.source.label(),
                    module=name,
                )
            )
        return findings


class CriticalClockResetConnectionRule(ScriptRule):
    rule_id = "RTL006"
    title = "Critical clock/reset connection is open or constant"
    severity = "P1"
    category = "semantic"
    description = "A named child clock/reset port is explicitly left open or tied to a constant, which may compile but is usually an integration bug."

    def run(self, index: DesignIndex) -> list[Finding]:
        findings: list[Finding] = []
        for module in self.active_modules(index):
            for inst in module.instances:
                if inst.connection_style != "named":
                    continue
                target = index.modules.get(inst.module)
                if not target:
                    continue
                for port in target.ports:
                    if not (_looks_like_clock(port.name) or _looks_like_reset(port.name)):
                        continue
                    if port.name not in inst.connections:
                        continue
                    expr = inst.connections[port.name].strip()
                    if expr == "" or _is_constant_expr(expr):
                        findings.append(
                            Finding(
                                rule_id=self.rule_id,
                                severity=self.severity,
                                title=self.title,
                                message=f"{module.name}.{inst.name} connects critical port {port.name} to `{expr or 'open'}`.",
                                source=inst.source.label() if inst.source else module.source.label(),
                                module=module.name,
                                evidence=[f"target={target.name}", f"port={port.name}", f"expr={expr or 'open'}"],
                            )
                        )
        return findings


class MultiClockDomainRule(ScriptRule):
    rule_id = "RTL007"
    title = "Module spans multiple clock domains"
    severity = "P3"
    category = "semantic"
    description = "A non-trivial module has multiple detected clocks; VCS can compile it, but CDC intent still needs review."

    def run(self, index: DesignIndex) -> list[Finding]:
        findings: list[Finding] = []
        focus_modules = _top_neighborhood(index, depth=2)
        for module in self.active_modules(index):
            if focus_modules and module.name not in focus_modules:
                continue
            if len(module.clocks) < 2:
                continue
            if not module.instances and not module.procedural_blocks:
                continue
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    title=self.title,
                    message=f"{module.name} has multiple detected clocks: {', '.join(module.clocks[:8])}.",
                    source=module.source.label(),
                    module=module.name,
                    evidence=[f"clock_count={len(module.clocks)}"],
                )
            )
        return findings


def _is_constant_expr(expr: str) -> bool:
    compact = expr.replace("_", "").replace(" ", "").lower()
    return compact in {"0", "1", "1'b0", "1'b1", "1'bx", "1'bz", "1'h0", "1'h1"}


def _top_neighborhood(index: DesignIndex, depth: int = 2) -> set[str]:
    if not index.top_modules:
        return set()
    focus: set[str] = set()
    frontier = set(index.top_modules)
    for _ in range(depth + 1):
        next_frontier: set[str] = set()
        for name in frontier:
            if name in focus or name not in index.modules:
                continue
            focus.add(name)
            next_frontier.update(inst.module for inst in index.modules[name].instances if inst.module in index.modules)
        frontier = next_frontier
    return focus

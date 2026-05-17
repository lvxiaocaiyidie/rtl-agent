from __future__ import annotations

from collections import defaultdict

from rtl_agent.models import DesignIndex

from .base import CheckRule, Finding
from .rules import (
    MissingClockOnContainerRule,
    MissingNamedPortRule,
    MissingResetOnContainerRule,
    OrphanModuleRule,
    UnknownInstanceModuleRule,
)

CHECK_RULES: list[CheckRule] = [
    UnknownInstanceModuleRule(),
    MissingNamedPortRule(),
    MissingClockOnContainerRule(),
    MissingResetOnContainerRule(),
    OrphanModuleRule(),
]


def get_rules(rule_ids: list[str] | None = None, include_orphan: bool = False) -> list[CheckRule]:
    rules = CHECK_RULES
    if not include_orphan:
        rules = [rule for rule in rules if rule.rule_id != "RTL005"]
    if not rule_ids:
        return rules
    wanted = {rule_id.upper() for rule_id in rule_ids}
    return [rule for rule in rules if rule.rule_id.upper() in wanted or rule.category.upper() in wanted]


def run_checks(index: DesignIndex, rule_ids: list[str] | None = None, include_orphan: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    for rule in get_rules(rule_ids, include_orphan=include_orphan):
        findings.extend(rule.run(index))
    return findings


def render_findings_digest(findings: list[Finding], limit: int = 40) -> str:
    if not findings:
        return "No script-rule findings were detected."
    by_rule: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        by_rule[finding.rule_id].append(finding)
    lines = ["Script finding counts:"]
    for rule_id in sorted(by_rule):
        first = by_rule[rule_id][0]
        lines.append(f"- {rule_id} [{first.severity}] {first.title}: {len(by_rule[rule_id])}")
    lines.append("")
    lines.append("Representative findings:")
    for idx, finding in enumerate(findings[:limit], 1):
        evidence = "; ".join(finding.evidence or [])
        lines.append(f"{idx}. [{finding.severity}] {finding.rule_id} {finding.title}: {finding.message}")
        lines.append(f"   Source: {finding.source}")
        if evidence:
            lines.append(f"   Evidence: {evidence}")
    if len(findings) > limit:
        lines.append(f"... {len(findings) - limit} more script findings omitted by finding budget.")
    return "\n".join(lines)


def render_rule_list() -> str:
    lines = ["# RTL Check Rules", ""]
    for rule in CHECK_RULES:
        llm = "yes" if rule.requires_llm else "no"
        lines.extend(
            [
                f"## {rule.rule_id}: {rule.title}",
                "",
                f"- Severity: {rule.severity}",
                f"- Category: {rule.category}",
                f"- LLM required: {llm}",
                f"- Description: {rule.description}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"

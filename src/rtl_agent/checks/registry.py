from __future__ import annotations

from collections import defaultdict

from rtl_agent.models import DesignIndex

from .base import CheckRule, Finding
from .rules import (
    CriticalClockResetConnectionRule,
    MissingClockOnContainerRule,
    MissingNamedPortRule,
    MissingResetOnContainerRule,
    MultiClockDomainRule,
    OrphanModuleRule,
    UnknownInstanceModuleRule,
)

CHECK_RULES: list[CheckRule] = [
    UnknownInstanceModuleRule(),
    MissingNamedPortRule(),
    MissingClockOnContainerRule(),
    MissingResetOnContainerRule(),
    OrphanModuleRule(),
    CriticalClockResetConnectionRule(),
    MultiClockDomainRule(),
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
    samples = _balanced_finding_samples(by_rule, limit)
    for idx, finding in enumerate(samples, 1):
        lines.extend(_finding_digest_lines(idx, finding))
    omitted = len(findings) - len(samples)
    if omitted > 0:
        lines.append(f"... {omitted} more script findings omitted by balanced finding budget.")
    return "\n".join(lines)


def _balanced_finding_samples(by_rule: dict[str, list[Finding]], limit: int) -> list[Finding]:
    if limit <= 0:
        return []
    rule_ids = sorted(by_rule)
    per_rule = max(1, limit // max(1, len(rule_ids)))
    samples: list[Finding] = []
    for rule_id in rule_ids:
        samples.extend(by_rule[rule_id][:per_rule])
    remaining = limit - len(samples)
    if remaining <= 0:
        return samples[:limit]
    already = {id(finding) for finding in samples}
    for finding in [item for rule_id in rule_ids for item in by_rule[rule_id]]:
        if id(finding) in already:
            continue
        samples.append(finding)
        if len(samples) >= limit:
            break
    return samples


def _finding_digest_lines(idx: int, finding: Finding) -> list[str]:
    evidence = "; ".join(finding.evidence or [])
    lines = [f"{idx}. [{finding.severity}] {finding.rule_id} {finding.title}: {finding.message}", f"   Source: {finding.source}"]
    if evidence:
        lines.append(f"   Evidence: {evidence}")
    return lines


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

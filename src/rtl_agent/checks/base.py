from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rtl_agent.models import DesignIndex


@dataclass(slots=True)
class Finding:
    rule_id: str
    severity: str
    title: str
    message: str
    source: str
    module: str = ""
    evidence: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "source": self.source,
            "module": self.module,
            "evidence": self.evidence or [],
        }


class CheckRule(Protocol):
    rule_id: str
    title: str
    severity: str
    category: str
    value: str
    description: str
    requires_llm: bool

    def run(self, index: DesignIndex) -> list[Finding]:
        ...


class ScriptRule:
    rule_id = ""
    title = ""
    severity = "P3"
    category = "general"
    value = "architecture_insight"
    description = ""
    requires_llm = False

    def active_modules(self, index: DesignIndex):
        active_names = set(index.reachable_modules or index.modules)
        for name in sorted(active_names):
            if name in index.modules:
                yield index.modules[name]

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rtl_agent.llm import OpenAICompatibleClient
from rtl_agent.models import DesignIndex
from rtl_agent.reducer import render_llm_context

from .base import Finding, ScriptRule
from .registry import render_findings_digest, run_checks


LLM_REVIEW_POLICY = """\
You are reviewing RTL integration evidence. Follow these rules:
- Treat script findings as hard evidence; treat reduced RTL as context.
- Prefer concise risk statements over long descriptions.
- Do not repeat the full port list or module list.
- Return at most 6 risks.
- For each risk use exactly four bullets: Evidence, Impact, Confidence, Next check.
- Confidence must be High, Medium, or Low with one short reason.
- If evidence is insufficient, say what extra RTL slice or file line is needed.
- Do not propose RTL edits unless the evidence directly supports them.
"""


@dataclass(slots=True)
class ReviewRequest:
    script_findings: str
    reduced_context: str
    policy: str = LLM_REVIEW_POLICY


class ReviewBackend(Protocol):
    def review(self, request: ReviewRequest) -> str:
        ...


class OpenAIChatReviewBackend:
    def __init__(self, client: OpenAICompatibleClient):
        self.client = client

    def review(self, request: ReviewRequest) -> str:
        prompt = (
            request.policy
            + "\n## Script Findings\n\n"
            + request.script_findings
            + "\n\n## Reduced RTL Context\n\n"
            + request.reduced_context
        )
        return self.client.chat(
            [
                {"role": "system", "content": "You are a concise RTL/SOC integration review agent."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )


class LLMIntegrationReviewRule(ScriptRule):
    rule_id = "LLM001"
    title = "LLM integration review"
    severity = "INFO"
    category = "llm"
    description = "Optional OpenAI-compatible review over reduced RTL context. Disabled unless an LLM client is supplied."
    requires_llm = True

    def __init__(
        self,
        client: OpenAICompatibleClient | None = None,
        backend: ReviewBackend | None = None,
        max_modules: int = 80,
        max_interface_stubs: int = 120,
        max_findings: int = 40,
    ):
        self.backend = backend or (OpenAIChatReviewBackend(client) if client else None)
        self.max_modules = max_modules
        self.max_interface_stubs = max_interface_stubs
        self.max_findings = max_findings

    def run(self, index: DesignIndex) -> list[Finding]:
        if self.backend is None:
            return []
        context = render_llm_context(index, max_modules=self.max_modules, max_interface_stubs=self.max_interface_stubs)
        script_findings = render_findings_digest(run_checks(index), limit=self.max_findings)
        response = self.backend.review(
            ReviewRequest(
                script_findings=script_findings,
                reduced_context=context,
            )
        )
        return [
            Finding(
                rule_id=self.rule_id,
                severity=self.severity,
                title=self.title,
                message=response,
                source="reduced_context",
                evidence=["llm_generated=true"],
            )
        ]

from __future__ import annotations

from rtl_agent.llm import OpenAICompatibleClient
from rtl_agent.models import DesignIndex
from rtl_agent.reducer import render_llm_context

from .base import Finding, ScriptRule


class LLMIntegrationReviewRule(ScriptRule):
    rule_id = "LLM001"
    title = "LLM integration review"
    severity = "INFO"
    category = "llm"
    description = "Optional OpenAI-compatible review over reduced RTL context. Disabled unless an LLM client is supplied."
    requires_llm = True

    def __init__(self, client: OpenAICompatibleClient | None = None, max_modules: int = 80, max_interface_stubs: int = 120):
        self.client = client
        self.max_modules = max_modules
        self.max_interface_stubs = max_interface_stubs

    def run(self, index: DesignIndex) -> list[Finding]:
        if self.client is None:
            return []
        context = render_llm_context(index, max_modules=self.max_modules, max_interface_stubs=self.max_interface_stubs)
        prompt = (
            "Review this reduced RTL integration context. Return concise findings with rule-like titles, "
            "source references, and uncertainty. Do not invent facts beyond the context.\n\n"
            + context
        )
        response = self.client.chat(
            [
                {"role": "system", "content": "You are an RTL/SOC integration review assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
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

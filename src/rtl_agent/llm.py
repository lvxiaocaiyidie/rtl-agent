from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass


@dataclass(slots=True)
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4.1"


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig):
        self.config = config

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.1) -> str:
        api_key = os.getenv(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key in environment variable {self.config.api_key_env}")
        payload = json.dumps({"model": self.config.model, "messages": messages, "temperature": temperature}).encode("utf-8")
        req = urllib.request.Request(
            self.config.base_url.rstrip("/") + "/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

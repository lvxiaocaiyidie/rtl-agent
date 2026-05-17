from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4.1"
    env_file: str = ".env.local"


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig):
        self.config = config

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.1) -> str:
        api_key = get_api_key(self.config)
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


def load_llm_config(config_path: Path | None = None, env_file: Path | None = None) -> LLMConfig:
    config = LLMConfig()
    path = config_path or Path("rtl-agent.toml")
    if path.exists():
        values = _read_simple_toml_section(path, "llm")
        config = LLMConfig(
            base_url=values.get("base_url", config.base_url),
            api_key_env=values.get("api_key_env", config.api_key_env),
            model=values.get("model", config.model),
            env_file=values.get("env_file", config.env_file),
        )
    if env_file:
        config.env_file = str(env_file)
    return config


def get_api_key(config: LLMConfig) -> str | None:
    key = os.getenv(config.api_key_env)
    if key:
        return key
    env_path = Path(config.env_file)
    if not env_path.exists():
        return None
    return _read_env_value(env_path, config.api_key_env)


def has_api_key(config: LLMConfig) -> bool:
    return bool(get_api_key(config))


def _read_env_value(path: Path, name: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*=\s*(.*)\s*$")
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        value = match.group(1).strip().strip('"').strip("'")
        if value and "replace_with" not in value:
            return value
    return None


def _read_simple_toml_section(path: Path, section: str) -> dict[str, str]:
    values: dict[str, str] = {}
    in_section = False
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = line.strip("[]").strip() == section
            continue
        if not in_section or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values

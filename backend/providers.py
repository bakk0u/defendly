from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .models import ProviderInfo


def _json_object(value: str) -> dict[str, Any] | None:
    value = value.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.I)
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, re.S)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


class LLMProvider(ABC):
    id = "provider"
    label = "Provider"
    local = False

    def __init__(self, model: str, enabled: bool = True) -> None:
        self.model = model
        self.enabled = enabled

    @property
    def display_model(self) -> str:
        return f"{self.label} · {self.model}"

    def info(self) -> ProviderInfo:
        return ProviderInfo(id=self.id, label=self.label, model=self.model, available=self.enabled, local=self.local)

    @abstractmethod
    async def structured(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError


class DeterministicProvider(LLMProvider):
    id = "fallback"
    label = "Fast fallback"
    local = True

    def __init__(self) -> None:
        super().__init__("heuristics-v2", True)

    async def structured(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any] | None:
        return None


class OllamaProvider(LLMProvider):
    id = "ollama"
    label = "Ollama"
    local = True

    def __init__(self) -> None:
        super().__init__(
            os.getenv("OLLAMA_MODEL", "qwen3:14b"),
            os.getenv("OLLAMA_ENABLED", "true").lower() == "true",
        )
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")

    async def structured(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        payload = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "options": {"temperature": 0.15, "num_ctx": 8192},
        }
        try:
            timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                return _json_object(response.json()["message"]["content"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None


class OpenAIProvider(LLMProvider):
    id = "openai"
    label = "OpenAI"

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        super().__init__(os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), bool(self.api_key))

    async def structured(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0.15,
            "response_format": {"type": "json_schema", "json_schema": {"name": "interview_agent_response", "strict": True, "schema": schema}},
        }
        try:
            async with httpx.AsyncClient(timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                return _json_object(response.json()["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None


class AnthropicProvider(LLMProvider):
    id = "anthropic"
    label = "Anthropic"

    def __init__(self) -> None:
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        super().__init__(os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"), bool(self.api_key))

    async def structured(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        schema_instruction = "Return only JSON matching this schema:\n" + json.dumps(schema)
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": 0.15,
            "system": f"{system}\n\n{schema_instruction}",
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            async with httpx.AsyncClient(timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                    json=payload,
                )
                response.raise_for_status()
                return _json_object(response.json()["content"][0]["text"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None


class GeminiProvider(LLMProvider):
    id = "gemini"
    label = "Google Gemini"

    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        super().__init__(os.getenv("GEMINI_MODEL", "gemini-2.0-flash"), bool(self.api_key))

    async def structured(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.15, "responseMimeType": "application/json", "responseSchema": schema},
        }
        try:
            async with httpx.AsyncClient(timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                    params={"key": self.api_key},
                    json=payload,
                )
                response.raise_for_status()
                return _json_object(response.json()["candidates"][0]["content"]["parts"][0]["text"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None


class ProviderRegistry:
    def __init__(self) -> None:
        self.providers: dict[str, LLMProvider] = {
            provider.id: provider
            for provider in (OllamaProvider(), OpenAIProvider(), AnthropicProvider(), GeminiProvider(), DeterministicProvider())
        }

    def get(self, provider_id: str | None) -> LLMProvider:
        selected = self.providers.get((provider_id or "").lower())
        if selected and selected.enabled:
            return selected
        default = self.providers.get(os.getenv("DEFAULT_LLM_PROVIDER", "ollama").lower())
        if default and default.enabled:
            return default
        return self.providers["fallback"]

    def infos(self) -> list[ProviderInfo]:
        return [provider.info() for provider in self.providers.values()]


provider_registry = ProviderRegistry()


# Compatibility for existing imports and local scripts.
OllamaClient = OllamaProvider

"""Model provider settings shared by both runtimes.

Canvases reference model *profiles* (enterprise-reasoning, enterprise-fast,
local-open-weight). Each tenant allowlists profiles; this module maps a
profile to a concrete provider model from environment variables.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

PROFILE_COST_USD_PER_1K = {"enterprise-reasoning": 0.010, "enterprise-fast": 0.002, "local-open-weight": 0.0006, "experimental-preview": 0.02}


@dataclass
class LLMSettings:
    provider: str = "mock"  # mock | openai | azure_openai | ollama
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    azure_endpoint: str | None = None
    azure_api_key: str | None = None
    azure_api_version: str = "2024-10-21"
    ollama_base_url: str = "http://localhost:11434"
    profiles: dict[str, str] = field(default_factory=dict)
    temperature: float = 0.1

    @classmethod
    def from_env(cls) -> "LLMSettings":
        return cls(
            provider=os.getenv("LLM_PROVIDER", "mock"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            azure_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            azure_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            profiles={
                "enterprise-reasoning": os.getenv("MODEL_ENTERPRISE_REASONING", "gpt-4o"),
                "enterprise-fast": os.getenv("MODEL_ENTERPRISE_FAST", "gpt-4o-mini"),
                "local-open-weight": os.getenv("MODEL_LOCAL_OPEN_WEIGHT", "llama3.1:8b"),
                "experimental-preview": os.getenv("MODEL_EXPERIMENTAL_PREVIEW", "gpt-4o-mini"),
            },
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
        )

    def model_for(self, profile: str) -> str:
        return self.profiles.get(profile) or self.profiles.get("enterprise-fast", "gpt-4o-mini")

    def provider_for(self, profile: str) -> str:
        """local-open-weight always goes to Ollama unless the provider is mock."""
        if self.provider == "mock":
            return "mock"
        if profile == "local-open-weight":
            return "ollama"
        return self.provider

    @staticmethod
    def cost(profile: str, tokens: int, fx_rate: float = 1.0) -> float:
        return round(tokens / 1000 * PROFILE_COST_USD_PER_1K.get(profile, 0.002) * fx_rate, 4)

"""Minimal OpenAI-compatible chat client used by the AIVANTA model gateway.

n8n's AI Agent nodes talk to AIVANTA's gateway (`/gateway/v1/chat/completions`)
exactly as they would talk to OpenAI. The gateway resolves the tenant's model
profile and forwards the call here: OpenAI, Azure OpenAI or an
OpenAI-compatible local server (Ollama, vLLM). `LLM_PROVIDER=mock` never
reaches this module.
"""
from __future__ import annotations

from typing import Any

import httpx

from .llm_settings import LLMSettings


class ProviderError(RuntimeError):
    def __init__(self, message: str, transient: bool = True):
        super().__init__(message)
        self.transient = transient


def _endpoint(llm: LLMSettings, profile: str) -> tuple[str, dict[str, str], str]:
    provider = llm.provider_for(profile)
    model = llm.model_for(profile)
    if provider == "openai":
        base = (llm.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        return f"{base}/chat/completions", {"Authorization": f"Bearer {llm.openai_api_key}"}, model
    if provider == "azure_openai":
        base = (llm.azure_endpoint or "").rstrip("/")
        return (f"{base}/openai/deployments/{model}/chat/completions?api-version={llm.azure_api_version}",
                {"api-key": llm.azure_api_key or ""}, model)
    if provider == "ollama":
        return f"{llm.ollama_base_url.rstrip('/')}/v1/chat/completions", {}, model
    raise ProviderError(f"Unsupported LLM provider '{provider}'", transient=False)


async def chat(llm: LLMSettings, profile: str, messages: list[dict[str, Any]], json_mode: bool = True,
               timeout_s: float = 180, client: httpx.AsyncClient | None = None) -> tuple[str, dict[str, int], str]:
    """Return (content, usage, provider_model)."""
    url, headers, model = _endpoint(llm, profile)
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": llm.temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    own = client is None
    client = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        r = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise ProviderError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        if own:
            await client.aclose()
    if r.status_code >= 400:
        raise ProviderError(f"provider HTTP {r.status_code}: {r.text[:300]}", transient=r.status_code in (408, 409, 429) or r.status_code >= 500)
    data = r.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    usage = data.get("usage") or {}
    return content, {"prompt_tokens": int(usage.get("prompt_tokens", 0)), "completion_tokens": int(usage.get("completion_tokens", 0)),
                     "total_tokens": int(usage.get("total_tokens", 0))}, model

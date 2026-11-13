"""AIVANTA Relay agent runtime (n8n)."""
from .contract import Decision, RunContext, RunOutcome, RuntimeAdapter
from .llm_settings import LLMSettings

RUNTIME_NAME = "AIVANTA Relay"
RUNTIME_FRAMEWORK = "n8n"
_adapter = None


def get_adapter():
    """Process-wide adapter (it owns the n8n API clients and the emulator)."""
    global _adapter
    if _adapter is None:
        from .relay_adapter import RelayAdapter
        _adapter = RelayAdapter()
    return _adapter


__all__ = ["Decision", "LLMSettings", "RunContext", "RunOutcome", "RuntimeAdapter", "RUNTIME_FRAMEWORK", "RUNTIME_NAME", "get_adapter"]

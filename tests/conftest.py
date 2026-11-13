"""Test configuration: isolated SQLite database, mock LLM, inline run execution."""
from __future__ import annotations

import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="aivanta-test-")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
    "STORAGE_DIR": f"{_tmp}/objects",
    "LLM_PROVIDER": "mock",
    "AUTH_MODE": "dev",
    "SEED_DEMO": "true",
    "RUN_EXECUTION": "inline",
    "N8N_MODE": "emulated",                  # Relay edition: in-process n8n (ignored by the other editions)
    "JWT_SECRET": "test-secret-for-ci-only-32-bytes!!",
})


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from aivanta_api.main import app

    with TestClient(app) as c:
        yield c

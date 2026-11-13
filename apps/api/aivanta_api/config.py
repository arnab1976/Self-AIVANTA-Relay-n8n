"""Application settings (environment variables, see .env.example)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AIVANTA Relay"
    environment: str = "development"
    database_url: str = "sqlite:///./aivanta.db"
    storage_dir: str = "./.data/objects"
    cors_origins: str = "http://localhost:3000"
    seed_demo: bool = True

    # auth: "dev" issues HS256 tokens from /auth/dev-login; "oidc" validates Entra ID / OIDC tokens
    auth_mode: str = "dev"
    jwt_secret: str = "change-me-in-production-please-32b"
    jwt_ttl_minutes: int = 720
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_tenant_claim: str = "aivanta_tenant"
    oidc_roles_claim: str = "roles"

    # run execution: "inline" runs in the API process; "worker" queues runs for `python -m aivanta_api.worker`
    run_execution: str = "inline"
    worker_poll_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()

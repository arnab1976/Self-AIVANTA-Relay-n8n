"""AIVANTA Relay API (FastAPI). Agent runtime: n8n."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from aivanta_runtime import RUNTIME_FRAMEWORK, RUNTIME_NAME, get_adapter
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import SessionLocal, init_db
from .routers import agent_studio, approvals, artifacts, auth, bridge, catalog, commercials, governance, graphs, onboarding, projects, runs, tenants
from .services.seed import seed_demo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
OPEN_PREFIXES = ("/api/health", "/api/meta", "/api/auth", "/api/public", "/api/provider", "/internal", "/gateway", "/docs", "/openapi")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if get_settings().seed_demo:
        with SessionLocal() as db:
            seed_demo(db)
            from .services.seed_relay import seed_relay
            seed_relay(db)
    adapter = get_adapter()
    await adapter.setup()
    logging.getLogger("aivanta").info("%s ready · runtime %s (%s)", RUNTIME_NAME, RUNTIME_FRAMEWORK, adapter.framework_version())
    yield
    await adapter.close()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=f"{RUNTIME_NAME} API", version="1.0.0", lifespan=lifespan,
                  description=f"AIVANTA presales-to-delivery platform API. Agent runtime: {RUNTIME_FRAMEWORK}. "
                              "`/internal/n8n/*` and `/gateway/v1/*` are called by n8n only (bridge token).")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def suspended_tenants(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and not path.startswith(OPEN_PREFIXES) and onboarding.suspended_from_request(request):
            return JSONResponse({"detail": "This tenant is suspended. Contact your provider."}, status_code=403)
        return await call_next(request)

    routers = (
        governance, auth, tenants, projects, catalog, graphs, runs, approvals,
        artifacts, commercials, onboarding, agent_studio,
    )
    api_prefix = "/api"
    for r in routers:
        app.include_router(r.router, prefix=api_prefix)
    app.include_router(bridge.router)
    return app


app = create_app()

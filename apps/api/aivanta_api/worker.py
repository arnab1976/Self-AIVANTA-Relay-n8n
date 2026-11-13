"""Run worker for RUN_EXECUTION=worker deployments.

    python -m aivanta_api.worker

Polls for runs whose `pending_action` is set by the API (start / resume /
retry) and executes them. Run more than one worker for throughput; a row-level
claim prevents two workers from taking the same run. With Conductor
(LangGraph), use LANGGRAPH_CHECKPOINTER=postgres so every worker shares
checkpoints; Ensemble keeps its run state in the AIVANTA database.
"""
from __future__ import annotations

import asyncio
import logging

from aivanta_runtime import get_adapter
from sqlalchemy import select, update

from .config import get_settings
from .db import SessionLocal, init_db
from .models import ExecutionRun
from .services.run_service import execute

log = logging.getLogger("aivanta.worker")


def claim() -> tuple[str, str] | None:
    with SessionLocal() as db:
        row = db.scalars(select(ExecutionRun).where(ExecutionRun.pending_action.is_not(None)).order_by(ExecutionRun.started_at).limit(1)).first()
        if not row:
            return None
        action = row.pending_action
        res = db.execute(update(ExecutionRun).where(ExecutionRun.id == row.id, ExecutionRun.pending_action == action)
                         .values(pending_action=None, status="running"))
        db.commit()
        return (row.id, action) if res.rowcount else None


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    init_db()
    adapter = get_adapter()
    await adapter.setup()
    log.info("worker started · %s", adapter.framework_version())
    try:
        while True:
            job = claim()
            if job is None:
                await asyncio.sleep(get_settings().worker_poll_seconds)
                continue
            run_id, action = job
            log.info("executing %s (%s)", run_id, action)
            outcome = await execute(run_id, action)
            log.info("run %s -> %s", run_id, outcome.status)
    finally:
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(main())

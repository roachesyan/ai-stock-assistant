"""Node E: Error_Handler_Node — 捕获上游异常，标记 run 为 ERROR。"""
from __future__ import annotations

import logging

from src.db.connection import get_connection
from src.db.repository import AnalysisRepository
from src.models.state import AgentState
from src.utils.dates import today

logger = logging.getLogger(__name__)


async def error_handler_node(state: AgentState) -> dict:
    run_id = state.get("run_id")
    error_message = state.get("error_message") or "Unknown error"

    if run_id:
        conn = await get_connection()
        try:
            repo = AnalysisRepository(conn)
            await repo.ensure_run(run_id, today())
            await repo.update_run_status(run_id, "ERROR", error_message=error_message)
        finally:
            await conn.close()

    print(f"⚠️ RUN FAILED: {error_message}")
    return {}

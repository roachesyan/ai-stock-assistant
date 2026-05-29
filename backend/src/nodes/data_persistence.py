"""Node 5: Data_Persistence_Node — 写入 run（含风控结论）+ recommendations。"""
from __future__ import annotations

import json
import logging

from src.db.connection import get_connection
from src.db.repository import AnalysisRepository
from src.models.state import AgentState
from src.utils.dates import today

logger = logging.getLogger(__name__)


def _determine_verdict(state: AgentState) -> str:
    review = state.get("risk_review")
    if review and review.get("approved"):
        return "APPROVED"
    # 进入持久化但未通过 → 必为风控反思轮次用尽
    return "REJECTED_AT_LIMIT"


async def data_persistence_node(state: AgentState) -> dict:
    run_id = state["run_id"]
    run_date = today()
    analyses = state.get("analyses") or []
    review = state.get("risk_review")
    verdict = _determine_verdict(state)

    review_notes = json.dumps(review, ensure_ascii=False) if review else None

    conn = await get_connection()
    try:
        repo = AnalysisRepository(conn)
        await repo.create_run(
            run_id=run_id,
            run_date=run_date,
            status="EXECUTED",
            risk_verdict=verdict,
            risk_rounds=state.get("risk_rounds", 0),
            evidence_rounds=state.get("evidence_rounds", 0),
            review_notes=review_notes,
        )
        await repo.save_recommendations(run_id, run_date, analyses)
    finally:
        await conn.close()

    return {"risk_verdict": verdict}

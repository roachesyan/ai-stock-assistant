"""持久化节点测试：写 run（含风控结论）+ recommendations。"""
from __future__ import annotations

import pytest

from src.db.connection import get_connection
from src.db.repository import AnalysisRepository
from src.nodes.data_persistence import data_persistence_node


@pytest.mark.asyncio
async def test_persist_approved(file_db):
    state = {
        "run_id": "run-p1",
        "analyses": [
            {"ticker": "AAPL", "reasoning": "x", "sentiment_score": 8, "action": "BUY", "price_at_analysis": 200.0},
        ],
        "risk_review": {"approved": True, "issues": [], "overall_notes": "ok"},
        "risk_rounds": 1,
        "evidence_rounds": 2,
    }
    out = await data_persistence_node(state)
    assert out["risk_verdict"] == "APPROVED"

    conn = await get_connection()
    try:
        repo = AnalysisRepository(conn)
        detail = await repo.get_run_with_details("run-p1")
        assert detail["status"] == "EXECUTED"
        assert detail["risk_verdict"] == "APPROVED"
        assert detail["risk_rounds"] == 1
        assert detail["evidence_rounds"] == 2
        assert detail["recommendation_count"] == 1
        assert detail["review_notes"] is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_persist_rejected_at_limit(file_db):
    state = {
        "run_id": "run-p2",
        "analyses": [],
        "risk_review": {"approved": False, "issues": [], "overall_notes": "no"},
        "risk_rounds": 3,
        "evidence_rounds": 0,
    }
    out = await data_persistence_node(state)
    assert out["risk_verdict"] == "REJECTED_AT_LIMIT"

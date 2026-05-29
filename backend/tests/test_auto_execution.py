"""自动执行节点测试：BUY/SELL 生成 trades，HOLD 不生成；DOWNGRADE 策略。"""
from __future__ import annotations

import pytest

from src.config import settings
from src.db.connection import get_connection
from src.db.repository import AnalysisRepository
from src.nodes.auto_execution import auto_execution_node
from src.nodes.data_persistence import data_persistence_node
from src.utils.dates import today


def _state(verdict="APPROVED", review=None):
    return {
        "run_id": "run-exec",
        "analyses": [
            {"ticker": "AAPL", "reasoning": "x", "sentiment_score": 8, "action": "BUY", "price_at_analysis": 200.0},
            {"ticker": "MSFT", "reasoning": "y", "sentiment_score": 5, "action": "HOLD", "price_at_analysis": 400.0},
            {"ticker": "NVDA", "reasoning": "z", "sentiment_score": 2, "action": "SELL", "price_at_analysis": 100.0},
        ],
        "risk_review": review or {"approved": True, "issues": [], "overall_notes": ""},
        "risk_verdict": verdict,
        "evidence_rounds": 0,
        "risk_rounds": 0,
    }


@pytest.mark.asyncio
async def test_buy_sell_create_trades_hold_skipped(file_db):
    state = _state()
    await data_persistence_node(state)
    out = await auto_execution_node(state)

    assert len(out["executed_trades"]) == 2  # BUY + SELL, HOLD 跳过
    sides = {t["ticker"]: t["side"] for t in out["executed_trades"]}
    assert sides == {"AAPL": "BUY", "NVDA": "SELL"}

    conn = await get_connection()
    try:
        repo = AnalysisRepository(conn)
        rows, total = await repo.list_trades(run_id="run-exec")
        assert total == 2
        run = await repo.get_run_by_id("run-exec")
        assert run["risk_verdict"] == "APPROVED"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_downgrade_to_hold_policy(file_db, monkeypatch):
    monkeypatch.setattr(settings, "RISK_LIMIT_POLICY", "DOWNGRADE_TO_HOLD")
    review = {"approved": False, "issues": [{"ticker": "NVDA", "issue": "bad"}], "overall_notes": "no"}
    state = _state(verdict="REJECTED_AT_LIMIT", review=review)

    await data_persistence_node(state)
    out = await auto_execution_node(state)

    # NVDA 被风控点名 → 降级为 HOLD 不下单；仅 AAPL 执行
    tickers = {t["ticker"] for t in out["executed_trades"]}
    assert tickers == {"AAPL"}

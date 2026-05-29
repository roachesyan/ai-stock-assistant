"""Node 6: Auto_Execution_Node — 对 BUY/SELL 自动写入 trades（模拟成交）。"""
from __future__ import annotations

import logging

from src.config import settings
from src.db.connection import get_connection
from src.db.repository import AnalysisRepository
from src.models.state import AgentState
from src.utils.dates import today

logger = logging.getLogger(__name__)


def _rejected_tickers(state: AgentState) -> set[str]:
    review = state.get("risk_review") or {}
    return {issue["ticker"] for issue in review.get("issues", [])}


async def auto_execution_node(state: AgentState) -> dict:
    run_id = state["run_id"]
    run_date = today()
    analyses = state.get("analyses") or []
    verdict = state.get("risk_verdict")

    candidates = [a for a in analyses if a["action"] in ("BUY", "SELL")]

    # DOWNGRADE_TO_HOLD 策略：轮次用尽时剔除被风控点名的 ticker
    if settings.RISK_LIMIT_POLICY == "DOWNGRADE_TO_HOLD" and verdict == "REJECTED_AT_LIMIT":
        rejected = _rejected_tickers(state)
        skipped = [a["ticker"] for a in candidates if a["ticker"] in rejected]
        candidates = [a for a in candidates if a["ticker"] not in rejected]
        if skipped:
            logger.info("DOWNGRADE_TO_HOLD：跳过被风控否决的交易 %s", skipped)

    trades = [
        {"ticker": a["ticker"], "side": a["action"], "price": a["price_at_analysis"]}
        for a in candidates
    ]

    if trades:
        conn = await get_connection()
        try:
            repo = AnalysisRepository(conn)
            await repo.save_trades(run_id, run_date, trades)
        finally:
            await conn.close()
        summary = ", ".join(f"{t['ticker']}: {t['side']}" for t in trades)
        print(f"✅ AUTO-EXECUTED TRADES: [{summary}]")
    else:
        print("No actionable trades (all HOLD or downgraded).")

    if verdict == "REJECTED_AT_LIMIT":
        print("⚠️ RISK NOT APPROVED — executed under EXECUTE_AND_FLAG policy. Review advised.")

    return {"executed_trades": trades}

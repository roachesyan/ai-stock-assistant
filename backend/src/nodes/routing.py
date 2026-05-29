"""图的条件路由函数。"""
from __future__ import annotations

from src.config import settings
from src.models.state import AgentState


def route_after_analyst(state: AgentState) -> str:
    """证据补充环路由：需补证据且未超轮 → evidence_gatherer；否则 → risk_reviewer。"""
    needs = state.get("needs_more_evidence") or []
    if needs and state.get("evidence_rounds", 0) < settings.MAX_EVIDENCE_ROUNDS:
        return "evidence_gatherer"
    return "risk_reviewer"


def route_after_risk(state: AgentState) -> str:
    """风控反思环路由：

    - 通过 → data_persistence
    - 驳回且未超轮 → quant_analyst（修订）
    - 驳回但轮次用尽 → data_persistence（按策略执行/降级）
    """
    review = state.get("risk_review")
    if review and review.get("approved"):
        return "data_persistence"
    if state.get("risk_rounds", 0) < settings.MAX_RISK_ROUNDS:
        return "quant_analyst"
    return "data_persistence"

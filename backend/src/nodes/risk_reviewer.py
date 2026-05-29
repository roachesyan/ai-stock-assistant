"""Node 4: Risk_Reviewer_Node — 独立风控 Agent 审查交易方案（风控反思环）。"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import settings
from src.config.llm import get_llm
from src.models.schemas import RiskReviewModel
from src.models.state import AgentState
from src.prompts import risk_reviewer as P
from src.prompts.quant_analyst import build_market_data

logger = logging.getLogger(__name__)


def _format_feedback(review: RiskReviewModel) -> str:
    lines = [f"Overall: {review.overall_notes}"] if review.overall_notes else []
    for issue in review.issues:
        lines.append(f"- {issue.ticker}: {issue.issue}")
    return "\n".join(lines) or "Revise the plan to address risk concerns."


async def risk_reviewer_node(state: AgentState) -> dict:
    analyses = state.get("analyses") or []
    market_data = build_market_data(state["raw_news_data"])
    plan = P.build_plan(analyses)

    llm = get_llm()
    structured = llm.with_structured_output(RiskReviewModel)

    review: RiskReviewModel | None = None
    last_err: Exception | None = None
    extra = ""
    for attempt in range(settings.MAX_SCHEMA_RETRIES + 1):
        messages = [
            SystemMessage(content=P.SYSTEM_PROMPT),
            HumanMessage(content=P.HUMAN_TEMPLATE.format(plan=plan, market_data=market_data) + extra),
        ]
        try:
            review = await structured.ainvoke(messages)
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("风控结构化输出第 %d 次失败: %s", attempt + 1, exc)
            extra = f"\n\nYour previous output failed schema validation: {exc}. Return strictly valid output."

    if review is None:
        raise RuntimeError(f"风控结构化输出在重试 {settings.MAX_SCHEMA_RETRIES} 次后仍失败: {last_err}")

    review_dict = {
        "approved": review.approved,
        "issues": [{"ticker": i.ticker, "issue": i.issue} for i in review.issues],
        "overall_notes": review.overall_notes,
    }

    result: dict = {"risk_review": review_dict}
    if review.approved:
        result["risk_feedback"] = None
    else:
        result["risk_feedback"] = _format_feedback(review)
        # 仅当还会回到分析师修订时才计入轮数
        if state.get("risk_rounds", 0) < settings.MAX_RISK_ROUNDS:
            result["risk_rounds"] = state.get("risk_rounds", 0) + 1

    return result

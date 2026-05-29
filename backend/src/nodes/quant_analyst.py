"""Node 2: Quant_Analyst_Node — LLM 结构化输出交易建议（含结构化输出自修复循环）。"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import settings
from src.config.llm import get_llm
from src.models.schemas import QuantReport
from src.models.state import AgentState
from src.prompts import quant_analyst as P

logger = logging.getLogger(__name__)


async def quant_analyst_node(state: AgentState) -> dict:
    raw = state["raw_news_data"]
    market_data = P.build_market_data(raw)

    risk_feedback = state.get("risk_feedback")
    prev_analyses = state.get("analyses") or []

    if risk_feedback:
        human = P.REVISION_TEMPLATE.format(
            previous=P.build_previous(prev_analyses),
            risk_feedback=risk_feedback,
            market_data=market_data,
        )
    else:
        human = P.HUMAN_TEMPLATE.format(market_data=market_data)

    llm = get_llm()
    structured = llm.with_structured_output(QuantReport)

    # —— 结构化输出自修复循环 ——
    report: QuantReport | None = None
    last_err: Exception | None = None
    extra_feedback = ""
    for attempt in range(settings.MAX_SCHEMA_RETRIES + 1):
        messages = [
            SystemMessage(content=P.SYSTEM_PROMPT),
            HumanMessage(content=human + extra_feedback),
        ]
        try:
            report = await structured.ainvoke(messages)
            break
        except Exception as exc:  # noqa: BLE001 - 校验/解析失败
            last_err = exc
            logger.warning("分析师结构化输出第 %d 次失败: %s", attempt + 1, exc)
            extra_feedback = (
                f"\n\nYour previous output failed schema validation: {exc}. "
                "Return STRICTLY valid structured output matching the schema."
            )

    if report is None:
        raise RuntimeError(f"分析师结构化输出在重试 {settings.MAX_SCHEMA_RETRIES} 次后仍失败: {last_err}")

    analyses = []
    for rec in report.recommendations:
        price = float(raw.get(rec.ticker, {}).get("price", 0.0))
        analyses.append(
            {
                "ticker": rec.ticker,
                "reasoning": rec.reasoning,
                "sentiment_score": rec.sentiment_score,
                "action": rec.action,
                "price_at_analysis": price,
            }
        )

    report_text = P.build_previous(analyses)
    # 仅保留仍在目标范围内的证据缺口
    needs = [t for t in report.needs_more_evidence if t in raw]

    return {
        "analyses": analyses,
        "analysis_report": report_text,
        "needs_more_evidence": needs,
        # 消费完反馈后清空，避免影响下一轮判断
        "risk_feedback": None,
    }

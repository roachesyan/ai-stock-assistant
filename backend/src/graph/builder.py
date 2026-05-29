"""StateGraph 构建：多 Agent + 三个有界循环（无 checkpointer）。"""
from __future__ import annotations

import uuid

from langgraph.graph import END, StateGraph

from src.models.state import AgentState
from src.nodes.auto_execution import auto_execution_node
from src.nodes.data_persistence import data_persistence_node
from src.nodes.error_handler import error_handler_node
from src.nodes.evidence_gatherer import evidence_gatherer_node
from src.nodes.news_scraper import news_scraper_node
from src.nodes.quant_analyst import quant_analyst_node
from src.nodes.risk_reviewer import risk_reviewer_node
from src.nodes.routing import route_after_analyst, route_after_risk


def build_graph():
    """构建并编译图。返回 CompiledStateGraph。"""
    g = StateGraph(AgentState)

    g.add_node("news_scraper", news_scraper_node)
    g.add_node("quant_analyst", quant_analyst_node)
    g.add_node("evidence_gatherer", evidence_gatherer_node)
    g.add_node("risk_reviewer", risk_reviewer_node)
    g.add_node("data_persistence", data_persistence_node)
    g.add_node("auto_execution", auto_execution_node)

    g.set_entry_point("news_scraper")
    g.add_edge("news_scraper", "quant_analyst")

    # 证据补充环
    g.add_conditional_edges(
        "quant_analyst",
        route_after_analyst,
        {"evidence_gatherer": "evidence_gatherer", "risk_reviewer": "risk_reviewer"},
    )
    g.add_edge("evidence_gatherer", "quant_analyst")

    # 风控反思环
    g.add_conditional_edges(
        "risk_reviewer",
        route_after_risk,
        {"quant_analyst": "quant_analyst", "data_persistence": "data_persistence"},
    )

    g.add_edge("data_persistence", "auto_execution")
    g.add_edge("auto_execution", END)

    return g.compile()


def initial_state(run_id: str | None, tickers: list[str]) -> AgentState:
    """构造图的初始状态。"""
    return {
        "tickers": list(tickers),
        "raw_news_data": {},
        "analyses": [],
        "analysis_report": "",
        "needs_more_evidence": [],
        "evidence_rounds": 0,
        "risk_review": None,
        "risk_feedback": None,
        "risk_rounds": 0,
        "risk_verdict": None,
        "executed_trades": [],
        "run_id": run_id or str(uuid.uuid4()),
        "error_message": None,
    }


async def run_pipeline(tickers: list[str], run_id: str | None = None) -> AgentState:
    """运行完整流水线。异常时调用 error_handler 兜底（标记 run=ERROR），不抛出。"""
    graph = build_graph()
    state = initial_state(run_id, tickers)
    try:
        result = await graph.ainvoke(state)
        return result  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001 - 全局兜底
        state["error_message"] = str(exc)
        await error_handler_node(state)
        return state

"""LangGraph 共享状态定义（TypedDict）。"""
from __future__ import annotations

from typing import Dict, List, Optional, TypedDict


class TickerNews(TypedDict):
    """单个 ticker 的原始抓取数据。"""
    ticker: str
    price: float
    price_change_pct: float
    articles: List[str]          # 最新前 N 条新闻（证据补充环会追加）


class TickerAnalysis(TypedDict):
    """单个 ticker 的结构化分析结果（与 Pydantic QuantReport 对应）。"""
    ticker: str
    reasoning: str
    sentiment_score: int         # 1-10
    action: str                  # "BUY" / "HOLD" / "SELL"
    price_at_analysis: float


class RiskIssue(TypedDict):
    ticker: str
    issue: str


class RiskReview(TypedDict):
    approved: bool
    issues: List[RiskIssue]
    overall_notes: str


class TradeExecution(TypedDict):
    """自动执行产生的单笔交易。"""
    ticker: str
    side: str                    # "BUY" / "SELL"
    price: float


class AgentState(TypedDict, total=False):
    """在各 Graph Node 之间传递的状态。

    使用 total=False 以便节点只返回 partial dict，由 LangGraph 合并。
    """
    tickers: List[str]
    raw_news_data: Dict[str, TickerNews]
    analyses: List[TickerAnalysis]
    analysis_report: str
    needs_more_evidence: List[str]
    evidence_rounds: int
    risk_review: Optional[RiskReview]
    risk_feedback: Optional[str]
    risk_rounds: int
    risk_verdict: Optional[str]               # "APPROVED" / "REJECTED_AT_LIMIT"
    executed_trades: List[TradeExecution]
    run_id: Optional[str]
    error_message: Optional[str]

"""Pydantic 模型：LLM 结构化输出 + API 请求/响应。"""
from __future__ import annotations

from typing import Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ============================================================
# LLM 结构化输出模型（分析师 / 风控）
# ============================================================
class TickerRecommendation(BaseModel):
    ticker: str
    reasoning: str = Field(..., description="2-3 句分析推理")
    sentiment_score: int = Field(..., ge=1, le=10, description="情绪评分 1-10")
    action: Literal["BUY", "HOLD", "SELL"]


class QuantReport(BaseModel):
    """分析师 Agent 的结构化输出。"""
    recommendations: List[TickerRecommendation]
    needs_more_evidence: List[str] = Field(
        default_factory=list,
        description="信息不足、需要补充搜索的 ticker 列表；若全部充分则为空",
    )


class RiskIssueModel(BaseModel):
    ticker: str
    issue: str = Field(..., description="具体、可执行的问题描述")


class RiskReviewModel(BaseModel):
    """风控 Agent 的结构化输出。"""
    approved: bool
    issues: List[RiskIssueModel] = Field(default_factory=list)
    overall_notes: str = ""


# ============================================================
# API 响应信封
# ============================================================
class ApiError(BaseModel):
    code: str
    message: str


class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: Optional[T] = None
    error: Optional[ApiError] = None
    meta: Optional[dict] = None


# ============================================================
# API 输出模型
# ============================================================
class RecommendationOut(BaseModel):
    id: int
    run_id: str
    run_date: str
    ticker: str
    reasoning: str
    sentiment_score: int
    action: str
    price_at_analysis: float
    created_at: str


class TradeOut(BaseModel):
    id: int
    run_id: str
    run_date: str
    ticker: str
    side: str
    price: float
    status: str
    executed_at: str
    cancelled_at: Optional[str] = None
    cancellable: bool = False


class RiskIssueOut(BaseModel):
    ticker: str
    issue: str


class RiskReviewOut(BaseModel):
    approved: bool
    issues: List[RiskIssueOut] = Field(default_factory=list)
    overall_notes: str = ""


class RunOut(BaseModel):
    id: str
    run_date: str
    status: str
    risk_verdict: Optional[str] = None
    risk_rounds: int = 0
    evidence_rounds: int = 0
    error_message: Optional[str] = None
    created_at: str
    recommendation_count: int = 0
    trade_count: int = 0


class RunDetailOut(RunOut):
    risk_review: Optional[RiskReviewOut] = None
    recommendations: List[RecommendationOut] = Field(default_factory=list)
    trades: List[TradeOut] = Field(default_factory=list)


class CancelResultOut(BaseModel):
    cancelled_count: int


class TriggerResultOut(BaseModel):
    run_id: str
    status: str


# ============================================================
# API 请求模型
# ============================================================
class TriggerIn(BaseModel):
    tickers: Optional[List[str]] = None     # 不传则用配置默认

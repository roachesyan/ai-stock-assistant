"""DB 行 → Pydantic Out 模型的转换工具。"""
from __future__ import annotations

import json
from typing import Any

from src.models.schemas import (
    RecommendationOut,
    RiskReviewOut,
    RunDetailOut,
    RunOut,
    TradeOut,
)
from src.utils.dates import today


def to_recommendation_out(row: dict[str, Any]) -> RecommendationOut:
    return RecommendationOut(**{k: row[k] for k in RecommendationOut.model_fields if k in row})


def to_trade_out(row: dict[str, Any], today_str: str | None = None) -> TradeOut:
    today_str = today_str or today()
    cancellable = row["run_date"] == today_str and row["status"] == "EXECUTED"
    return TradeOut(
        id=row["id"],
        run_id=row["run_id"],
        run_date=row["run_date"],
        ticker=row["ticker"],
        side=row["side"],
        price=row["price"],
        status=row["status"],
        executed_at=row["executed_at"],
        cancelled_at=row.get("cancelled_at"),
        cancellable=cancellable,
    )


def _parse_review(review_notes: str | None) -> RiskReviewOut | None:
    if not review_notes:
        return None
    try:
        data = json.loads(review_notes)
        return RiskReviewOut(**data)
    except Exception:  # noqa: BLE001
        return None


def to_run_out(row: dict[str, Any]) -> RunOut:
    return RunOut(
        id=row["id"],
        run_date=row["run_date"],
        status=row["status"],
        risk_verdict=row.get("risk_verdict"),
        risk_rounds=row.get("risk_rounds", 0),
        evidence_rounds=row.get("evidence_rounds", 0),
        error_message=row.get("error_message"),
        created_at=row["created_at"],
        recommendation_count=row.get("recommendation_count", 0),
        trade_count=row.get("trade_count", 0),
    )


def to_run_detail_out(row: dict[str, Any]) -> RunDetailOut:
    today_str = today()
    recs = [to_recommendation_out(r) for r in row.get("recommendations", [])]
    trades = [to_trade_out(t, today_str) for t in row.get("trades", [])]
    return RunDetailOut(
        id=row["id"],
        run_date=row["run_date"],
        status=row["status"],
        risk_verdict=row.get("risk_verdict"),
        risk_rounds=row.get("risk_rounds", 0),
        evidence_rounds=row.get("evidence_rounds", 0),
        error_message=row.get("error_message"),
        created_at=row["created_at"],
        recommendation_count=row.get("recommendation_count", len(recs)),
        trade_count=row.get("trade_count", len(trades)),
        risk_review=_parse_review(row.get("review_notes")),
        recommendations=recs,
        trades=trades,
    )

"""推荐相关路由。"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_repository
from src.api.errors import invalid_parameter, resource_not_found
from src.api.serializers import to_recommendation_out
from src.config import settings
from src.db.repository import AnalysisRepository, total_pages
from src.models.schemas import ApiResponse, RecommendationOut

router = APIRouter(tags=["recommendations"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.get("/recommendations/latest", response_model=ApiResponse[list[RecommendationOut]])
async def latest(repo: AnalysisRepository = Depends(get_repository)):
    rows = await repo.get_latest_recommendations()
    data = [to_recommendation_out(r) for r in rows]
    meta = {"total": len(data), "date": rows[0]["run_date"] if rows else None}
    return ApiResponse(success=True, data=data, meta=meta)


@router.get("/recommendations/{date}", response_model=ApiResponse[list[RecommendationOut]])
async def by_date(date: str, repo: AnalysisRepository = Depends(get_repository)):
    if not _DATE_RE.match(date):
        raise invalid_parameter("日期格式应为 YYYY-MM-DD")
    rows = await repo.get_recommendations_by_date(date)
    if not rows:
        raise resource_not_found(f"{date} 无推荐数据")
    data = [to_recommendation_out(r) for r in rows]
    return ApiResponse(success=True, data=data, meta={"total": len(data), "date": date})


@router.get(
    "/recommendations/ticker/{ticker}/latest",
    response_model=ApiResponse[RecommendationOut],
)
async def ticker_latest(ticker: str, repo: AnalysisRepository = Depends(get_repository)):
    ticker = ticker.upper()
    row = await repo.get_latest_by_ticker(ticker)
    if row is None:
        raise resource_not_found(f"{ticker} 无推荐数据")
    return ApiResponse(success=True, data=to_recommendation_out(row))


@router.get(
    "/recommendations/ticker/{ticker}/history",
    response_model=ApiResponse[list[RecommendationOut]],
)
async def ticker_history(
    ticker: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    repo: AnalysisRepository = Depends(get_repository),
):
    ticker = ticker.upper()
    rows, total = await repo.get_ticker_history(ticker, page, page_size)
    data = [to_recommendation_out(r) for r in rows]
    meta = {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages(total, page_size),
    }
    return ApiResponse(success=True, data=data, meta=meta)

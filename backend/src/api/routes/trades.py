"""交易查询与撤销路由。"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_repository
from src.api.errors import invalid_parameter, trade_not_cancellable, trade_not_found
from src.api.serializers import to_trade_out
from src.db.repository import AnalysisRepository, total_pages
from src.models.schemas import ApiResponse, TradeOut
from src.utils.dates import now_iso, today

router = APIRouter(tags=["trades"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.get("/trades/today", response_model=ApiResponse[list[TradeOut]])
async def trades_today(repo: AnalysisRepository = Depends(get_repository)):
    today_str = today()
    rows = await repo.list_today_trades(today_str)
    data = [to_trade_out(r, today_str) for r in rows]
    return ApiResponse(success=True, data=data, meta={"total": len(data), "date": today_str})


@router.get("/trades", response_model=ApiResponse[list[TradeOut]])
async def list_trades(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    run_id: str | None = Query(None),
    ticker: str | None = Query(None),
    status: str | None = Query(None),
    date: str | None = Query(None),
    repo: AnalysisRepository = Depends(get_repository),
):
    if date and not _DATE_RE.match(date):
        raise invalid_parameter("日期格式应为 YYYY-MM-DD")
    rows, total = await repo.list_trades(
        page, page_size, run_id, ticker.upper() if ticker else None, status, date
    )
    today_str = today()
    data = [to_trade_out(r, today_str) for r in rows]
    meta = {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages(total, page_size),
    }
    return ApiResponse(success=True, data=data, meta=meta)


@router.post("/trades/{trade_id}/cancel", response_model=ApiResponse[TradeOut])
async def cancel_trade(trade_id: int, repo: AnalysisRepository = Depends(get_repository)):
    trade = await repo.get_trade_by_id(trade_id)
    if trade is None:
        raise trade_not_found()
    if trade["run_date"] != today():
        raise trade_not_cancellable("跨天交易不可撤销")
    if trade["status"] != "EXECUTED":
        raise trade_not_cancellable("该交易已撤销，无法重复撤销")

    await repo.cancel_trade(trade_id, now_iso())
    updated = await repo.get_trade_by_id(trade_id)
    return ApiResponse(success=True, data=to_trade_out(updated))

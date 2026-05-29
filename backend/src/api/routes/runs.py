"""运行管理路由（含触发与 run 级撤销）。"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_repository
from src.api.errors import invalid_parameter, run_not_found
from src.api.serializers import to_run_detail_out, to_run_out
from src.config import settings
from src.db.repository import AnalysisRepository, total_pages
from src.graph.builder import run_pipeline
from src.models.schemas import (
    ApiResponse,
    CancelResultOut,
    RunDetailOut,
    RunOut,
    TriggerIn,
    TriggerResultOut,
)
from src.utils.dates import now_iso, today

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


async def _background_run(run_id: str, tickers: list[str]) -> None:
    try:
        await run_pipeline(tickers, run_id=run_id)
    except Exception:  # noqa: BLE001
        logger.exception("后台分析任务异常 run_id=%s", run_id)


@router.post("/run/trigger", status_code=202, response_model=ApiResponse[TriggerResultOut])
async def trigger(body: TriggerIn | None = None):
    tickers = (body.tickers if body and body.tickers else None) or settings.TICKERS
    run_id = str(uuid.uuid4())
    # 后台异步执行，立即返回 202
    asyncio.create_task(_background_run(run_id, tickers))
    return ApiResponse(
        success=True,
        data=TriggerResultOut(run_id=run_id, status="STARTED"),
        meta={"run_id": run_id},
    )


@router.get("/runs", response_model=ApiResponse[list[RunOut]])
async def list_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    date: str | None = Query(None),
    risk_verdict: str | None = Query(None),
    repo: AnalysisRepository = Depends(get_repository),
):
    if date and not _DATE_RE.match(date):
        raise invalid_parameter("日期格式应为 YYYY-MM-DD")
    rows, total = await repo.list_runs(page, page_size, status, date, risk_verdict)
    data = [to_run_out(r) for r in rows]
    meta = {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages(total, page_size),
    }
    return ApiResponse(success=True, data=data, meta=meta)


@router.get("/runs/{run_id}", response_model=ApiResponse[RunDetailOut])
async def get_run(run_id: str, repo: AnalysisRepository = Depends(get_repository)):
    row = await repo.get_run_with_details(run_id)
    if row is None:
        raise run_not_found()
    return ApiResponse(success=True, data=to_run_detail_out(row), meta={"run_id": run_id})


@router.post("/runs/{run_id}/cancel", response_model=ApiResponse[CancelResultOut])
async def cancel_run(run_id: str, repo: AnalysisRepository = Depends(get_repository)):
    run = await repo.get_run_by_id(run_id)
    if run is None:
        raise run_not_found()
    count = await repo.cancel_run_trades(run_id, today(), now_iso())
    return ApiResponse(success=True, data=CancelResultOut(cancelled_count=count), meta={"run_id": run_id})

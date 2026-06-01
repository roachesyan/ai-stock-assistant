"""FastAPI app factory（含 CORS 与统一错误处理）。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.errors import ApiException
from src.api.routes import recommendations, runs, trades
from src.config import settings
from src.db.init_db import init_db
from src.scheduler import build_scheduler

logger = logging.getLogger(__name__)


def _envelope_error(code: str, message: str) -> dict:
    return {"success": False, "data": None, "error": {"code": code, "message": message}, "meta": None}


@asynccontextmanager
async def _lifespan(_: FastAPI):
    await init_db()
    scheduler = build_scheduler()
    if scheduler is not None:
        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="AI Stock Assistant", version="1.4.0", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApiException)
    async def _api_exc_handler(_: Request, exc: ApiException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_envelope_error(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content=_envelope_error("VALIDATION_ERROR", str(exc.errors())))

    @app.exception_handler(Exception)
    async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常: %s", exc)
        return JSONResponse(status_code=500, content=_envelope_error("INTERNAL_ERROR", "服务内部错误"))

    app.include_router(recommendations.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(trades.router, prefix="/api")

    @app.get("/api/health")
    async def health() -> dict:
        return {"success": True, "data": {"status": "ok"}, "error": None, "meta": None}

    return app

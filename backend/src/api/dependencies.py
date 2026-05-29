"""FastAPI 依赖注入：提供 Repository（每请求一个连接，结束自动关闭）。"""
from __future__ import annotations

from typing import AsyncIterator

from src.db.connection import get_connection
from src.db.repository import AnalysisRepository


async def get_repository() -> AsyncIterator[AnalysisRepository]:
    conn = await get_connection()
    try:
        yield AnalysisRepository(conn)
    finally:
        await conn.close()

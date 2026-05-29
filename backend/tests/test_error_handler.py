"""错误处理节点测试。"""
from __future__ import annotations

import pytest

from src.db.connection import get_connection
from src.db.repository import AnalysisRepository
from src.nodes.error_handler import error_handler_node


@pytest.mark.asyncio
async def test_error_handler_marks_run_error(file_db):
    state = {"run_id": "run-err", "error_message": "boom"}
    await error_handler_node(state)

    conn = await get_connection()
    try:
        repo = AnalysisRepository(conn)
        run = await repo.get_run_by_id("run-err")
        assert run is not None
        assert run["status"] == "ERROR"
        assert run["error_message"] == "boom"
    finally:
        await conn.close()

"""pytest 公共 fixture。"""
from __future__ import annotations

import aiosqlite
import pytest
import pytest_asyncio

from src.db.init_db import SCHEMA
from src.db.repository import AnalysisRepository


@pytest_asyncio.fixture
async def conn():
    """内存 SQLite 连接（含表结构与外键）。"""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys=ON")
    await db.executescript(SCHEMA)
    await db.commit()
    try:
        yield db
    finally:
        await db.close()


@pytest_asyncio.fixture
async def repo(conn):
    return AnalysisRepository(conn)


@pytest_asyncio.fixture
async def file_db(tmp_path, monkeypatch):
    """把 settings.DB_PATH 指向临时文件并初始化表结构，
    供「自开连接」的节点（data_persistence / auto_execution / error_handler）使用。"""
    from src.config import settings
    from src.db.init_db import init_db

    db_path = tmp_path / "test.db"
    monkeypatch.setattr(settings, "DB_PATH", db_path)
    await init_db()
    return db_path

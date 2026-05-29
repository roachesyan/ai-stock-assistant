"""SQLite 异步连接管理。"""
from __future__ import annotations

import aiosqlite

from src.config import settings


async def get_connection() -> aiosqlite.Connection:
    """获取一个 SQLite 异步连接，启用 WAL 与外键约束。

    调用方负责关闭连接（或使用依赖注入管理生命周期）。
    """
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(settings.DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db

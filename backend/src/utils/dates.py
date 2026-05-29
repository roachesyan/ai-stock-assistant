"""日期/时间工具。撤销「当日判定」的唯一来源。"""
from __future__ import annotations

from datetime import datetime


def today() -> str:
    """服务器本地日期 YYYY-MM-DD。"""
    return datetime.now().strftime("%Y-%m-%d")


def now_iso() -> str:
    """当前时间的 ISO 8601 字符串。"""
    return datetime.now().isoformat()

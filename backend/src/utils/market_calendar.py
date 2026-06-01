"""交易日判断（基于 pandas-market-calendars）。"""
from __future__ import annotations

import logging
from datetime import date, datetime
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _get_calendar(name: str):
    import pandas_market_calendars as mcal

    return mcal.get_calendar(name)


def is_trading_day(calendar_name: str, day: date | None = None) -> bool:
    """判断指定日期是否为该市场的交易日（排除周末与节假日）。

    出错时保守返回 True（宁可多跑一次，也不静默漏掉），并记录日志。
    """
    day = day or datetime.now().date()
    try:
        cal = _get_calendar(calendar_name)
        sched = cal.schedule(start_date=day.isoformat(), end_date=day.isoformat())
        return not sched.empty
    except Exception as exc:  # noqa: BLE001
        logger.warning("交易日历 %s 判断失败（默认按交易日处理）: %s", calendar_name, exc)
        return True

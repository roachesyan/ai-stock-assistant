"""定时调度：在 Server 模式下按 cron 触发每日分析（交易日才跑）。

复用 graph.run_pipeline，与 /api/run/trigger 同一执行路径。
仅本进程内调度；多副本部署时需额外的分布式锁（MVP 单实例）。
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import settings
from src.utils.dates import today
from src.utils.market_calendar import is_trading_day

logger = logging.getLogger(__name__)

# 防重入：上一次调度任务还没跑完时，跳过本次
_running = False


async def scheduled_run() -> None:
    """调度回调：交易日校验 → 跑流水线。"""
    global _running

    if settings.SKIP_NON_TRADING_DAYS and not is_trading_day(settings.MARKET_CALENDAR):
        logger.info("今天 (%s) 非 %s 交易日，跳过定时分析。", today(), settings.MARKET_CALENDAR)
        return

    if _running:
        logger.warning("上一次定时分析仍在运行，跳过本次触发。")
        return

    _running = True
    run_id = str(uuid.uuid4())
    try:
        from src.graph.builder import run_pipeline

        logger.info("定时分析开始 run_id=%s tickers=%s", run_id, settings.TICKERS)
        result = await run_pipeline(settings.TICKERS, run_id=run_id)
        logger.info(
            "定时分析完成 run_id=%s verdict=%s trades=%d",
            run_id,
            result.get("risk_verdict"),
            len(result.get("executed_trades", [])),
        )
    except Exception:  # noqa: BLE001
        logger.exception("定时分析异常 run_id=%s", run_id)
    finally:
        _running = False


def build_scheduler() -> AsyncIOScheduler | None:
    """根据配置构建并返回调度器；未启用时返回 None。"""
    if not settings.SCHEDULE_ENABLED:
        logger.info("SCHEDULE_ENABLED=false，未启用定时调度。")
        return None

    scheduler = AsyncIOScheduler(timezone=settings.SCHEDULE_TIMEZONE)
    trigger = CronTrigger.from_crontab(settings.SCHEDULE_CRON, timezone=settings.SCHEDULE_TIMEZONE)
    scheduler.add_job(
        scheduled_run,
        trigger=trigger,
        id="daily_analysis",
        max_instances=1,
        coalesce=True,         # 错过多次只补一次
        replace_existing=True,
    )
    logger.info(
        "定时调度已启用：cron=%r tz=%s calendar=%s",
        settings.SCHEDULE_CRON,
        settings.SCHEDULE_TIMEZONE,
        settings.MARKET_CALENDAR,
    )
    return scheduler

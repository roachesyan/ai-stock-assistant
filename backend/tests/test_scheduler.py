"""定时调度与交易日判断测试。"""
from __future__ import annotations

import datetime

import pytest

from src import scheduler as sched
from src.config import settings
from src.utils.market_calendar import is_trading_day


def test_trading_day_calendar():
    # 美股：元旦休市、周四交易、周六休市
    assert is_trading_day("XNYS", datetime.date(2025, 1, 1)) is False
    assert is_trading_day("XNYS", datetime.date(2025, 1, 2)) is True
    assert is_trading_day("XNYS", datetime.date(2025, 1, 4)) is False


def test_build_scheduler_disabled(monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULE_ENABLED", False)
    assert sched.build_scheduler() is None


def test_build_scheduler_enabled(monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULE_ENABLED", True)
    monkeypatch.setattr(settings, "SCHEDULE_CRON", "30 9 * * 1-5")
    s = sched.build_scheduler()
    assert s is not None
    jobs = s.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "daily_analysis"


@pytest.mark.asyncio
async def test_scheduled_run_skips_non_trading_day(monkeypatch):
    monkeypatch.setattr(settings, "SKIP_NON_TRADING_DAYS", True)
    monkeypatch.setattr(sched, "is_trading_day", lambda *_a, **_k: False)

    called = {"ran": False}

    async def _fake_pipeline(*_a, **_k):
        called["ran"] = True
        return {}

    # 即使 patch 了 run_pipeline，也不应被调用（因非交易日提前 return）
    monkeypatch.setattr("src.graph.builder.run_pipeline", _fake_pipeline)
    await sched.scheduled_run()
    assert called["ran"] is False


@pytest.mark.asyncio
async def test_scheduled_run_executes_on_trading_day(monkeypatch, file_db):
    monkeypatch.setattr(settings, "SKIP_NON_TRADING_DAYS", True)
    monkeypatch.setattr(sched, "is_trading_day", lambda *_a, **_k: True)

    called = {"ran": False}

    async def _fake_pipeline(tickers, run_id=None):
        called["ran"] = True
        return {"risk_verdict": "APPROVED", "executed_trades": []}

    import src.graph.builder as builder
    monkeypatch.setattr(builder, "run_pipeline", _fake_pipeline)
    await sched.scheduled_run()
    assert called["ran"] is True

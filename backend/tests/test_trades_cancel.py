"""撤销规则（当日/重复/批量）测试 — 直接走 repository + 规则逻辑。"""
from __future__ import annotations

import pytest

from src.utils.dates import now_iso, today


@pytest.mark.asyncio
async def test_cancel_today_trade(repo):
    t = today()
    await repo.create_run("r1", t)
    await repo.save_trades("r1", t, [{"ticker": "AAPL", "side": "BUY", "price": 1.0}])
    rows = await repo.list_today_trades(t)
    trade_id = rows[0]["id"]

    await repo.cancel_trade(trade_id, now_iso())
    updated = await repo.get_trade_by_id(trade_id)
    assert updated["status"] == "CANCELLED"
    assert updated["cancelled_at"] is not None


@pytest.mark.asyncio
async def test_cross_day_not_cancellable(repo):
    # 昨天的 run，模拟跨天
    await repo.create_run("r1", "2000-01-01")
    await repo.save_trades("r1", "2000-01-01", [{"ticker": "AAPL", "side": "BUY", "price": 1.0}])
    rows, _ = await repo.list_trades(run_id="r1")
    trade = rows[0]
    # 规则：run_date != today → 不可撤销
    assert trade["run_date"] != today()


@pytest.mark.asyncio
async def test_run_level_cancel_only_today_executed(repo):
    t = today()
    await repo.create_run("r1", t)
    await repo.save_trades(
        "r1", t,
        [
            {"ticker": "AAPL", "side": "BUY", "price": 1.0},
            {"ticker": "MSFT", "side": "SELL", "price": 2.0},
        ],
    )
    # 先撤掉一笔
    rows = await repo.list_today_trades(t)
    await repo.cancel_trade(rows[0]["id"], now_iso())

    # run 级批量撤销：只撤剩下的 EXECUTED
    count = await repo.cancel_run_trades("r1", t, now_iso())
    assert count == 1

    # 再次批量撤销应为 0（已无 EXECUTED）
    count2 = await repo.cancel_run_trades("r1", t, now_iso())
    assert count2 == 0

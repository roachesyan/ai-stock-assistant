"""Repository CRUD 与外键 CASCADE 测试。"""
from __future__ import annotations

import pytest

from src.db.repository import total_pages


@pytest.mark.asyncio
async def test_create_run_and_recommendations(repo):
    await repo.create_run("r1", "2025-01-15", status="EXECUTED", risk_verdict="APPROVED")
    await repo.save_recommendations(
        "r1", "2025-01-15",
        [
            {"ticker": "AAPL", "reasoning": "ok", "sentiment_score": 8,
             "action": "BUY", "price_at_analysis": 200.0},
            {"ticker": "MSFT", "reasoning": "hold", "sentiment_score": 5,
             "action": "HOLD", "price_at_analysis": 400.0},
        ],
    )
    detail = await repo.get_run_with_details("r1")
    assert detail["risk_verdict"] == "APPROVED"
    assert detail["recommendation_count"] == 2
    by_date = await repo.get_recommendations_by_date("2025-01-15")
    assert len(by_date) == 2


@pytest.mark.asyncio
async def test_cascade_delete(repo, conn):
    await repo.create_run("r1", "2025-01-15")
    await repo.save_recommendations(
        "r1", "2025-01-15",
        [{"ticker": "AAPL", "reasoning": "x", "sentiment_score": 7,
          "action": "BUY", "price_at_analysis": 1.0}],
    )
    await repo.save_trades("r1", "2025-01-15", [{"ticker": "AAPL", "side": "BUY", "price": 1.0}])

    await conn.execute("DELETE FROM analysis_runs WHERE id = 'r1'")
    await conn.commit()

    recs = await repo.get_recommendations_by_date("2025-01-15")
    trades, total = await repo.list_trades(run_id="r1")
    assert recs == []
    assert total == 0


@pytest.mark.asyncio
async def test_ticker_history_pagination(repo):
    for i in range(5):
        await repo.create_run(f"r{i}", f"2025-01-0{i+1}")
        await repo.save_recommendations(
            f"r{i}", f"2025-01-0{i+1}",
            [{"ticker": "AAPL", "reasoning": "x", "sentiment_score": 6,
              "action": "HOLD", "price_at_analysis": float(i)}],
        )
    rows, total = await repo.get_ticker_history("AAPL", page=1, page_size=2)
    assert total == 5
    assert len(rows) == 2


def test_total_pages():
    assert total_pages(0, 20) == 0
    assert total_pages(1, 20) == 1
    assert total_pages(21, 20) == 2

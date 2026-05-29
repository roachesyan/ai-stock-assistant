"""API 端点测试（TestClient + 临时文件 DB）。"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.db.connection import get_connection
from src.db.repository import AnalysisRepository
from src.utils.dates import today


@pytest.fixture
def client(file_db):
    app = create_app()
    with TestClient(app) as c:
        yield c


async def _seed():
    """种入一条当天 run + 1 BUY trade。"""
    conn = await get_connection()
    try:
        repo = AnalysisRepository(conn)
        t = today()
        await repo.create_run("seed-run", t, status="EXECUTED", risk_verdict="APPROVED")
        await repo.save_recommendations(
            "seed-run", t,
            [{"ticker": "AAPL", "reasoning": "x", "sentiment_score": 8,
              "action": "BUY", "price_at_analysis": 200.0}],
        )
        await repo.save_trades("seed-run", t, [{"ticker": "AAPL", "side": "BUY", "price": 200.0}])
    finally:
        await conn.close()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_run_detail_and_recommendations(client):
    asyncio.get_event_loop().run_until_complete(_seed())

    r = client.get("/api/runs/seed-run")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["risk_verdict"] == "APPROVED"
    assert len(body["data"]["recommendations"]) == 1
    assert len(body["data"]["trades"]) == 1
    assert body["data"]["trades"][0]["cancellable"] is True

    r2 = client.get("/api/recommendations/latest")
    assert r2.status_code == 200
    assert r2.json()["data"][0]["ticker"] == "AAPL"


def test_run_not_found(client):
    r = client.get("/api/runs/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_invalid_date(client):
    r = client.get("/api/recommendations/2025-99")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_PARAMETER"


def test_cancel_today_trade(client):
    asyncio.get_event_loop().run_until_complete(_seed())
    trades = client.get("/api/trades/today").json()["data"]
    trade_id = trades[0]["id"]

    r = client.post(f"/api/trades/{trade_id}/cancel")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "CANCELLED"

    # 重复撤销 → 409
    r2 = client.post(f"/api/trades/{trade_id}/cancel")
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "TRADE_NOT_CANCELLABLE"


def test_cancel_trade_not_found(client):
    r = client.post("/api/trades/999999/cancel")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "TRADE_NOT_FOUND"


def test_trigger_returns_202(client, monkeypatch):
    # 避免真正跑流水线：mock run_pipeline
    import src.api.routes.runs as runs_mod

    async def _fake(tickers, run_id=None):
        return {}

    monkeypatch.setattr(runs_mod, "run_pipeline", _fake)
    r = client.post("/api/run/trigger", json={"tickers": ["AAPL"]})
    assert r.status_code == 202
    assert r.json()["data"]["status"] == "STARTED"

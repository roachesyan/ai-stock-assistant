"""新闻抓取节点测试（mock 工具）。"""
from __future__ import annotations

import pytest

from src.nodes import news_scraper as ns


@pytest.mark.asyncio
async def test_scraper_aggregates(monkeypatch):
    monkeypatch.setattr(ns, "get_stock_price", lambda t: {"price": 100.0, "price_change_pct": 1.0})
    monkeypatch.setattr(ns, "search_news", lambda q, n: ["headline 1", "headline 2"])

    out = await ns.news_scraper_node({"tickers": ["AAPL", "MSFT"]})
    raw = out["raw_news_data"]
    assert set(raw.keys()) == {"AAPL", "MSFT"}
    assert raw["AAPL"]["price"] == 100.0
    assert len(raw["AAPL"]["articles"]) == 2


@pytest.mark.asyncio
async def test_scraper_partial_failure_does_not_block(monkeypatch):
    def price(t):
        if t == "AAPL":
            raise RuntimeError("network")
        return {"price": 50.0, "price_change_pct": 0.0}

    monkeypatch.setattr(ns, "get_stock_price", price)
    monkeypatch.setattr(ns, "search_news", lambda q, n: ["ok"])

    out = await ns.news_scraper_node({"tickers": ["AAPL", "MSFT"]})
    raw = out["raw_news_data"]
    assert raw["AAPL"]["price"] == 0.0
    assert raw["AAPL"]["articles"][0].startswith("ERROR")
    assert raw["MSFT"]["price"] == 50.0


@pytest.mark.asyncio
async def test_scraper_all_fail_raises(monkeypatch):
    def price(t):
        raise RuntimeError("down")

    monkeypatch.setattr(ns, "get_stock_price", price)
    monkeypatch.setattr(ns, "search_news", lambda q, n: [])

    with pytest.raises(RuntimeError):
        await ns.news_scraper_node({"tickers": ["AAPL"]})

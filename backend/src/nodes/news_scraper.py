"""Node 1: News_Scraper_Node — 并发抓取每个 ticker 的股价与新闻。"""
from __future__ import annotations

import asyncio
import logging

from src.models.state import AgentState
from src.tools.news_search import search_news
from src.tools.stock_data import get_stock_price

logger = logging.getLogger(__name__)

_NEWS_PER_TICKER = 3


async def _fetch_one(ticker: str) -> dict:
    """抓取单个 ticker；失败时返回带 ERROR 标记的占位，不阻塞其余。"""
    try:
        price_info = await asyncio.to_thread(get_stock_price, ticker)
        articles = await asyncio.to_thread(
            search_news, f"{ticker} stock news", _NEWS_PER_TICKER
        )
        return {
            "ticker": ticker,
            "price": price_info["price"],
            "price_change_pct": price_info["price_change_pct"],
            "articles": articles or ["(no news found)"],
        }
    except Exception as exc:  # noqa: BLE001 - 部分失败策略
        logger.warning("ticker %s 抓取失败: %s", ticker, exc)
        return {
            "ticker": ticker,
            "price": 0.0,
            "price_change_pct": 0.0,
            "articles": [f"ERROR: {exc}"],
        }


async def news_scraper_node(state: AgentState) -> dict:
    tickers = state["tickers"]
    results = await asyncio.gather(*[_fetch_one(t) for t in tickers])

    raw = {r["ticker"]: r for r in results}

    # 若所有 ticker 都失败（价格全为 0 且无新闻），视为整体失败
    if tickers and all(
        r["price"] == 0.0 and r["articles"] and r["articles"][0].startswith("ERROR")
        for r in results
    ):
        raise RuntimeError("所有 ticker 数据抓取失败，请检查网络或外部接口。")

    return {"raw_news_data": raw}

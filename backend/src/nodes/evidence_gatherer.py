"""Node 3: Evidence_Gatherer_Node — 证据补充环，对信息不足的 ticker 追加搜索。"""
from __future__ import annotations

import asyncio
import logging

from src.models.state import AgentState
from src.tools.news_search import search_news

logger = logging.getLogger(__name__)

_EXTRA_RESULTS = 5


async def _gather(ticker: str) -> tuple[str, list[str]]:
    query = f"{ticker} latest earnings guidance analyst outlook news"
    articles = await asyncio.to_thread(search_news, query, _EXTRA_RESULTS)
    return ticker, articles or []


async def evidence_gatherer_node(state: AgentState) -> dict:
    needs = state.get("needs_more_evidence") or []
    raw = dict(state["raw_news_data"])  # 浅拷贝

    results = await asyncio.gather(*[_gather(t) for t in needs])

    for ticker, extra in results:
        if ticker not in raw or not extra:
            continue
        entry = dict(raw[ticker])
        existing = list(entry.get("articles", []))
        # 合并去重，去掉之前的 "(no news found)" 占位
        existing = [a for a in existing if a and a != "(no news found)"]
        merged = existing[:]
        for art in extra:
            if art not in merged:
                merged.append(art)
        entry["articles"] = merged or ["(no news found)"]
        raw[ticker] = entry

    return {
        "raw_news_data": raw,
        "evidence_rounds": state.get("evidence_rounds", 0) + 1,
        "needs_more_evidence": [],   # 清空，回到分析师重新评估
    }

"""新闻搜索封装：优先 Tavily，回退 DuckDuckGo。"""
from __future__ import annotations

import logging
import time

from src.config import settings

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_BACKOFF_BASE = 0.5


def search_news(query: str, max_results: int = 3) -> list[str]:
    """搜索新闻，返回 top N 文章摘要列表（字符串）。

    优先使用 Tavily（需 TAVILY_API_KEY），回退到 DuckDuckGo（免费）。
    任一来源失败时返回空列表，不阻塞调用方（部分失败策略）。
    """
    if settings.TAVILY_API_KEY:
        try:
            return _search_tavily(query, max_results)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tavily 搜索失败，回退 DuckDuckGo: %s", exc)

    try:
        return _search_ddg(query, max_results)
    except Exception as exc:  # noqa: BLE001
        logger.warning("DuckDuckGo 搜索失败: %s", exc)
        return []


def _search_tavily(query: str, max_results: int) -> list[str]:
    from tavily import TavilyClient

    client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = client.search(query=query, max_results=max_results, topic="news")
            results = resp.get("results", []) if isinstance(resp, dict) else []
            out: list[str] = []
            for r in results[:max_results]:
                title = r.get("title", "").strip()
                content = r.get("content", "").strip()
                out.append(f"{title} — {content}" if title else content)
            return [s for s in out if s]
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(_BACKOFF_BASE * (2 ** attempt))
    raise RuntimeError(f"Tavily 搜索失败: {last_err}")


def _search_ddg(query: str, max_results: int) -> list[str]:
    from duckduckgo_search import DDGS

    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            out: list[str] = []
            with DDGS() as ddgs:
                for r in ddgs.news(query, max_results=max_results):
                    title = (r.get("title") or "").strip()
                    body = (r.get("body") or "").strip()
                    text = f"{title} — {body}" if title else body
                    if text:
                        out.append(text)
            return out[:max_results]
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(_BACKOFF_BASE * (2 ** attempt))
    raise RuntimeError(f"DuckDuckGo 搜索失败: {last_err}")

"""yfinance 封装：获取股价与涨跌幅。"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE = 0.5


def get_stock_price(ticker: str) -> dict:
    """返回 {"price": float, "price_change_pct": float}。

    失败时重试（指数退避）；全部失败抛出异常由上层（节点）处理。
    """
    import yfinance as yf

    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            t = yf.Ticker(ticker)
            info = getattr(t, "fast_info", None) or {}
            price = _extract(info, "last_price") or _extract(info, "lastPrice")
            prev_close = _extract(info, "previous_close") or _extract(info, "previousClose")

            if price is None:
                # 回退到历史收盘价
                hist = t.history(period="2d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
                    if len(hist) >= 2:
                        prev_close = float(hist["Close"].iloc[-2])

            if price is None:
                raise ValueError(f"无法获取 {ticker} 的价格")

            price = float(price)
            change_pct = 0.0
            if prev_close:
                prev_close = float(prev_close)
                if prev_close:
                    change_pct = round((price - prev_close) / prev_close * 100, 2)
            return {"price": round(price, 4), "price_change_pct": change_pct}
        except Exception as exc:  # noqa: BLE001 - 需要捕获 yfinance 的多种异常
            last_err = exc
            logger.warning("get_stock_price(%s) 第 %d 次失败: %s", ticker, attempt + 1, exc)
            time.sleep(_BACKOFF_BASE * (2 ** attempt))

    raise RuntimeError(f"获取 {ticker} 价格失败（已重试 {_MAX_RETRIES} 次）: {last_err}")


def _extract(info, key: str):
    try:
        if isinstance(info, dict):
            return info.get(key)
        return getattr(info, key, None)
    except Exception:  # noqa: BLE001
        return None

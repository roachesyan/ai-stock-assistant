"""环境变量与全局配置。

从 backend/.env 加载（python-dotenv），暴露一个 `settings` 单例供全项目使用。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# backend/ 目录（settings.py 在 backend/src/config/ 下，向上三级）
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BACKEND_DIR / ".env")

# 默认追踪的全球 Top 10 AI 公司
DEFAULT_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META",
    "TSLA", "AMD", "TSM", "ASML", "AVGO",
]


def _get(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _get_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    """全局配置单例。所有字段在实例化时从环境变量读取。"""

    def __init__(self) -> None:
        # —— LLM 提供商 ——
        self.LLM_PROVIDER: str = (_get("LLM_PROVIDER", "glm") or "glm").lower()

        # GLM（默认，Anthropic 兼容端点）
        self.GLM_API_KEY: str | None = _get("GLM_API_KEY")
        self.GLM_BASE_URL: str = _get("GLM_BASE_URL", "https://open.bigmodel.cn/api/anthropic")
        self.GLM_MODEL: str = _get("GLM_MODEL", "glm-5.1")

        # 官方 Anthropic
        self.ANTHROPIC_API_KEY: str | None = _get("ANTHROPIC_API_KEY")
        self.ANTHROPIC_MODEL: str = _get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

        # OpenAI / GLM 的 OpenAI 兼容端点
        self.OPENAI_API_KEY: str | None = _get("OPENAI_API_KEY")
        self.OPENAI_MODEL: str = _get("OPENAI_MODEL", "gpt-4o")
        self.OPENAI_BASE_URL: str | None = _get("OPENAI_BASE_URL")

        self.LLM_TIMEOUT_MS: int = _get_int("LLM_TIMEOUT_MS", 300_000)

        # —— 新闻搜索 ——
        self.TAVILY_API_KEY: str | None = _get("TAVILY_API_KEY")

        # —— 数据库 / 服务 ——
        # DATABASE_PATH 相对于 backend/ 解析
        db_path = _get("DATABASE_PATH", "./data/quant.db")
        self.DB_PATH: Path = (BACKEND_DIR / db_path).resolve()
        self.API_HOST: str = _get("API_HOST", "0.0.0.0")
        self.API_PORT: int = _get_int("API_PORT", 8000)

        # —— 跨域 ——
        self.CORS_ORIGINS: list[str] = _get_list("CORS_ORIGINS", ["http://localhost:5173"])

        # —— 多 Agent 循环上限 ——
        self.MAX_SCHEMA_RETRIES: int = _get_int("MAX_SCHEMA_RETRIES", 2)
        self.MAX_EVIDENCE_ROUNDS: int = _get_int("MAX_EVIDENCE_ROUNDS", 2)
        self.MAX_RISK_ROUNDS: int = _get_int("MAX_RISK_ROUNDS", 3)
        self.RISK_LIMIT_POLICY: str = _get("RISK_LIMIT_POLICY", "EXECUTE_AND_FLAG")

        # —— 定时调度（仅 Server 模式生效）——
        self.SCHEDULE_ENABLED: bool = _get_bool("SCHEDULE_ENABLED", False)
        self.SCHEDULE_CRON: str = _get("SCHEDULE_CRON", "30 9 * * 1-5")
        self.SCHEDULE_TIMEZONE: str = _get("SCHEDULE_TIMEZONE", "America/New_York")
        # 交易日历名（pandas-market-calendars），如 XNYS（纽交所）、NASDAQ
        self.MARKET_CALENDAR: str = _get("MARKET_CALENDAR", "XNYS")
        # 是否在非交易日跳过（节假日/周末）
        self.SKIP_NON_TRADING_DAYS: bool = _get_bool("SKIP_NON_TRADING_DAYS", True)

        # —— 目标股票 ——
        self.TICKERS: list[str] = _get_list("TICKERS", DEFAULT_TICKERS)

    @property
    def llm_timeout_seconds(self) -> float:
        return self.LLM_TIMEOUT_MS / 1000.0


settings = Settings()

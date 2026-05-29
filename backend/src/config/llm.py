"""LLM 客户端工厂。

默认 provider=glm：通过智谱 GLM 的 Anthropic 兼容端点复用 ChatAnthropic。
也支持官方 anthropic 与 openai（或 GLM 的 OpenAI 兼容端点）。
"""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from src.config import settings


def get_llm() -> BaseChatModel:
    """根据 LLM_PROVIDER 返回对应的 LangChain ChatModel。"""
    timeout_s = settings.llm_timeout_seconds
    provider = settings.LLM_PROVIDER

    if provider == "glm":
        from langchain_anthropic import ChatAnthropic

        if not settings.GLM_API_KEY:
            raise RuntimeError("LLM_PROVIDER=glm 但未设置 GLM_API_KEY，请在 backend/.env 中配置。")
        return ChatAnthropic(
            model=settings.GLM_MODEL,
            api_key=settings.GLM_API_KEY,
            base_url=settings.GLM_BASE_URL,
            timeout=timeout_s,
            max_retries=2,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("LLM_PROVIDER=anthropic 但未设置 ANTHROPIC_API_KEY。")
        return ChatAnthropic(
            model=settings.ANTHROPIC_MODEL,
            api_key=settings.ANTHROPIC_API_KEY,
            timeout=timeout_s,
            max_retries=2,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        if not settings.OPENAI_API_KEY:
            raise RuntimeError("LLM_PROVIDER=openai 但未设置 OPENAI_API_KEY。")
        kwargs: dict = {
            "model": settings.OPENAI_MODEL,
            "api_key": settings.OPENAI_API_KEY,
            "timeout": timeout_s,
            "max_retries": 2,
        }
        if settings.OPENAI_BASE_URL:
            kwargs["base_url"] = settings.OPENAI_BASE_URL
        return ChatOpenAI(**kwargs)

    raise RuntimeError(f"未知的 LLM_PROVIDER: {provider!r}（应为 glm | anthropic | openai）。")

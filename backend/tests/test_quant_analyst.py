"""分析师节点测试：含结构化输出自修复循环。"""
from __future__ import annotations

import pytest

from src.models.schemas import QuantReport, TickerRecommendation
from src.nodes import quant_analyst as qa


class _FakeStructured:
    """模拟 with_structured_output 的返回对象：前 fail_times 次抛错，之后成功。"""

    def __init__(self, report, fail_times=0):
        self.report = report
        self.fail_times = fail_times
        self.calls = 0

    async def ainvoke(self, _messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ValueError("schema validation failed")
        return self.report


class _FakeLLM:
    def __init__(self, structured):
        self._structured = structured

    def with_structured_output(self, _schema):
        return self._structured


def _report():
    return QuantReport(
        recommendations=[
            TickerRecommendation(ticker="AAPL", reasoning="bullish", sentiment_score=8, action="BUY"),
        ],
        needs_more_evidence=[],
    )


def _state():
    return {
        "raw_news_data": {"AAPL": {"ticker": "AAPL", "price": 200.0,
                                   "price_change_pct": 1.0, "articles": ["good"]}},
        "analyses": [],
        "risk_feedback": None,
    }


@pytest.mark.asyncio
async def test_analyst_success(monkeypatch):
    structured = _FakeStructured(_report(), fail_times=0)
    monkeypatch.setattr(qa, "get_llm", lambda: _FakeLLM(structured))

    out = await qa.quant_analyst_node(_state())
    assert out["analyses"][0]["ticker"] == "AAPL"
    assert out["analyses"][0]["price_at_analysis"] == 200.0
    assert out["needs_more_evidence"] == []


@pytest.mark.asyncio
async def test_analyst_self_repair(monkeypatch):
    # 第一次失败，重试后成功（MAX_SCHEMA_RETRIES 默认 2）
    structured = _FakeStructured(_report(), fail_times=1)
    monkeypatch.setattr(qa, "get_llm", lambda: _FakeLLM(structured))

    out = await qa.quant_analyst_node(_state())
    assert structured.calls == 2
    assert out["analyses"][0]["action"] == "BUY"


@pytest.mark.asyncio
async def test_analyst_persistent_failure_raises(monkeypatch):
    structured = _FakeStructured(_report(), fail_times=99)
    monkeypatch.setattr(qa, "get_llm", lambda: _FakeLLM(structured))

    with pytest.raises(RuntimeError):
        await qa.quant_analyst_node(_state())

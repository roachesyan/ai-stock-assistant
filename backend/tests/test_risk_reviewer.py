"""风控节点测试：approve / reject 路径。"""
from __future__ import annotations

import pytest

from src.models.schemas import RiskIssueModel, RiskReviewModel
from src.nodes import risk_reviewer as rr


class _FakeStructured:
    def __init__(self, review):
        self.review = review

    async def ainvoke(self, _messages):
        return self.review


class _FakeLLM:
    def __init__(self, review):
        self._s = _FakeStructured(review)

    def with_structured_output(self, _schema):
        return self._s


def _state():
    return {
        "analyses": [
            {"ticker": "AAPL", "reasoning": "x", "sentiment_score": 8,
             "action": "BUY", "price_at_analysis": 200.0},
        ],
        "raw_news_data": {"AAPL": {"ticker": "AAPL", "price": 200.0,
                                   "price_change_pct": 1.0, "articles": ["good"]}},
        "risk_rounds": 0,
    }


@pytest.mark.asyncio
async def test_risk_approved(monkeypatch):
    review = RiskReviewModel(approved=True, issues=[], overall_notes="fine")
    monkeypatch.setattr(rr, "get_llm", lambda: _FakeLLM(review))

    out = await rr.risk_reviewer_node(_state())
    assert out["risk_review"]["approved"] is True
    assert out["risk_feedback"] is None
    assert "risk_rounds" not in out  # approve 不计轮


@pytest.mark.asyncio
async def test_risk_rejected_increments_round(monkeypatch):
    review = RiskReviewModel(
        approved=False,
        issues=[RiskIssueModel(ticker="AAPL", issue="score 8 but reasoning weak")],
        overall_notes="revise",
    )
    monkeypatch.setattr(rr, "get_llm", lambda: _FakeLLM(review))

    out = await rr.risk_reviewer_node(_state())
    assert out["risk_review"]["approved"] is False
    assert out["risk_feedback"]
    assert out["risk_rounds"] == 1

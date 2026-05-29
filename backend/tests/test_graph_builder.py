"""全图集成测试：mock LLM + 工具，覆盖证据补充环与风控反思环。"""
from __future__ import annotations

import pytest

from src.config import settings
from src.db.connection import get_connection
from src.db.repository import AnalysisRepository
from src.models.schemas import (
    QuantReport,
    RiskIssueModel,
    RiskReviewModel,
    TickerRecommendation,
)


class _ScriptedStructured:
    """按调用次数依次返回脚本中的对象。"""

    def __init__(self, script):
        self.script = script
        self.idx = 0

    async def ainvoke(self, _messages):
        item = self.script[min(self.idx, len(self.script) - 1)]
        self.idx += 1
        return item


class _ScriptedLLM:
    """根据 schema 类型分派到 analyst / risk 的脚本。"""

    def __init__(self, quant_script, risk_script):
        self.quant = _ScriptedStructured(quant_script)
        self.risk = _ScriptedStructured(risk_script)

    def with_structured_output(self, schema):
        if schema is QuantReport:
            return self.quant
        if schema is RiskReviewModel:
            return self.risk
        raise AssertionError("unexpected schema")


def _quant(action="BUY", score=8, needs=None):
    return QuantReport(
        recommendations=[
            TickerRecommendation(ticker="AAPL", reasoning="r", sentiment_score=score, action=action),
        ],
        needs_more_evidence=needs or [],
    )


@pytest.fixture(autouse=True)
def _mock_tools(monkeypatch):
    from src.nodes import news_scraper as ns
    from src.nodes import evidence_gatherer as eg

    monkeypatch.setattr(ns, "get_stock_price", lambda t: {"price": 200.0, "price_change_pct": 1.0})
    monkeypatch.setattr(ns, "search_news", lambda q, n: ["headline"])
    monkeypatch.setattr(eg, "search_news", lambda q, n: ["more evidence"])


@pytest.mark.asyncio
async def test_happy_path_approved(file_db, monkeypatch):
    llm = _ScriptedLLM(
        quant_script=[_quant("BUY", 8)],
        risk_script=[RiskReviewModel(approved=True, issues=[], overall_notes="ok")],
    )
    import src.nodes.quant_analyst as qa
    import src.nodes.risk_reviewer as rr
    monkeypatch.setattr(qa, "get_llm", lambda: llm)
    monkeypatch.setattr(rr, "get_llm", lambda: llm)

    from src.graph.builder import run_pipeline
    result = await run_pipeline(["AAPL"], run_id="g-happy")

    assert result["risk_verdict"] == "APPROVED"
    assert len(result["executed_trades"]) == 1


@pytest.mark.asyncio
async def test_risk_reflection_then_approve(file_db, monkeypatch):
    # 风控先驳回一次（分析师改 HOLD→无交易），第二次通过
    llm = _ScriptedLLM(
        quant_script=[_quant("BUY", 8), _quant("HOLD", 5)],
        risk_script=[
            RiskReviewModel(approved=False,
                            issues=[RiskIssueModel(ticker="AAPL", issue="too aggressive")],
                            overall_notes="revise"),
            RiskReviewModel(approved=True, issues=[], overall_notes="ok"),
        ],
    )
    import src.nodes.quant_analyst as qa
    import src.nodes.risk_reviewer as rr
    monkeypatch.setattr(qa, "get_llm", lambda: llm)
    monkeypatch.setattr(rr, "get_llm", lambda: llm)

    from src.graph.builder import run_pipeline
    result = await run_pipeline(["AAPL"], run_id="g-reflect")

    assert result["risk_verdict"] == "APPROVED"
    assert result["risk_rounds"] == 1
    # 最终 HOLD → 无交易
    assert result["executed_trades"] == []


@pytest.mark.asyncio
async def test_risk_rejected_at_limit_executes_and_flags(file_db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_RISK_ROUNDS", 2)
    monkeypatch.setattr(settings, "RISK_LIMIT_POLICY", "EXECUTE_AND_FLAG")
    # 风控始终驳回
    reject = RiskReviewModel(approved=False,
                             issues=[RiskIssueModel(ticker="AAPL", issue="risky")],
                             overall_notes="no")
    llm = _ScriptedLLM(quant_script=[_quant("BUY", 8)], risk_script=[reject])
    import src.nodes.quant_analyst as qa
    import src.nodes.risk_reviewer as rr
    monkeypatch.setattr(qa, "get_llm", lambda: llm)
    monkeypatch.setattr(rr, "get_llm", lambda: llm)

    from src.graph.builder import run_pipeline
    result = await run_pipeline(["AAPL"], run_id="g-limit")

    assert result["risk_verdict"] == "REJECTED_AT_LIMIT"
    assert result["risk_rounds"] == 2
    # EXECUTE_AND_FLAG：仍执行
    assert len(result["executed_trades"]) == 1

    conn = await get_connection()
    try:
        repo = AnalysisRepository(conn)
        run = await repo.get_run_by_id("g-limit")
        assert run["risk_verdict"] == "REJECTED_AT_LIMIT"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_evidence_loop(file_db, monkeypatch):
    # 第一次分析标记需要证据，补充后第二次不再需要并通过
    llm = _ScriptedLLM(
        quant_script=[_quant("BUY", 7, needs=["AAPL"]), _quant("BUY", 7)],
        risk_script=[RiskReviewModel(approved=True, issues=[], overall_notes="ok")],
    )
    import src.nodes.quant_analyst as qa
    import src.nodes.risk_reviewer as rr
    monkeypatch.setattr(qa, "get_llm", lambda: llm)
    monkeypatch.setattr(rr, "get_llm", lambda: llm)

    from src.graph.builder import run_pipeline
    result = await run_pipeline(["AAPL"], run_id="g-evidence")

    assert result["evidence_rounds"] == 1
    assert result["risk_verdict"] == "APPROVED"

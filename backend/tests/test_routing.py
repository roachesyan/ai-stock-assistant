"""路由函数与循环终止条件测试。"""
from __future__ import annotations

from src.config import settings
from src.nodes.routing import route_after_analyst, route_after_risk


def _base_state(**kw):
    state = {
        "needs_more_evidence": [],
        "evidence_rounds": 0,
        "risk_review": None,
        "risk_rounds": 0,
    }
    state.update(kw)
    return state


def test_analyst_routes_to_evidence_when_needed():
    s = _base_state(needs_more_evidence=["AAPL"], evidence_rounds=0)
    assert route_after_analyst(s) == "evidence_gatherer"


def test_analyst_routes_to_risk_when_sufficient():
    s = _base_state(needs_more_evidence=[], evidence_rounds=0)
    assert route_after_analyst(s) == "risk_reviewer"


def test_analyst_evidence_loop_terminates_at_limit():
    s = _base_state(needs_more_evidence=["AAPL"], evidence_rounds=settings.MAX_EVIDENCE_ROUNDS)
    # 即便仍需证据，超限后也进入风控（防失控）
    assert route_after_analyst(s) == "risk_reviewer"


def test_risk_approved_goes_to_persistence():
    s = _base_state(risk_review={"approved": True, "issues": [], "overall_notes": ""})
    assert route_after_risk(s) == "data_persistence"


def test_risk_rejected_under_limit_goes_back_to_analyst():
    s = _base_state(
        risk_review={"approved": False, "issues": [], "overall_notes": "no"},
        risk_rounds=0,
    )
    assert route_after_risk(s) == "quant_analyst"


def test_risk_rejected_at_limit_goes_to_persistence():
    s = _base_state(
        risk_review={"approved": False, "issues": [], "overall_notes": "no"},
        risk_rounds=settings.MAX_RISK_ROUNDS,
    )
    assert route_after_risk(s) == "data_persistence"

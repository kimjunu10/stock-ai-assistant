"""뉴스 처리 v2 단위 테스트: 역할분류 게이트, event_signature 배정, 멱등 스킵."""

from __future__ import annotations

import numpy as np

from experiments.exp_b_factual_summaries import assign_llm_v2, classify_role


def test_rule_gate_flags_opinion_as_ineligible():
    r = classify_role.rule_gate("[정동칼럼]아! 삼전닉스 레버리지 ETF")
    assert r is not None
    assert r["article_role"] == "opinion"
    assert r["event_eligible"] is False
    assert r["role_source"] == "rule"


def test_rule_gate_passes_event_article_to_llm():
    # 사건 기사(광장 오탐 방지 포함)는 규칙으로 확정하지 않고 LLM 으로 넘긴다.
    assert classify_role.rule_gate("현대차, 미국 공장 착공…3조 투자") is None
    assert classify_role.rule_gate('"갤럭시로 물든 런던"…피카딜리 광장부터 이층버스까지') is None


def test_role_classifier_uses_llm_when_not_gated():
    calls = {"n": 0}

    def fake(_prompt):
        calls["n"] += 1
        return (
            {
                "article_role": "company_event",
                "event_eligible": True,
                "reason": "계약 발표",
                "event_signature": {"subject": "현대차", "action": "착공"},
                "role_source": "llm",
                "role_version": classify_role.ROLE_VERSION,
            },
            {"ok": True, "parse_success": True, "usage": {}},
        )

    clf = classify_role.RoleClassifier(call_fn=fake)
    art = {"title": "현대차 미국 공장 착공", "body": "..."}
    result, status = clf.classify("현대차", "005380", art)
    assert status == "llm"
    assert result["article_role"] == "company_event"
    assert result["event_eligible"] is True
    assert calls["n"] == 1


def test_role_classifier_pending_on_llm_failure():
    fail = ({}, {"ok": False, "parse_success": False})
    clf = classify_role.RoleClassifier(call_fn=lambda _p: fail)
    result, status = clf.classify("현대차", "005380", {"title": "현대차 뭔가", "body": "..."})
    assert result is None
    assert status == "pending_retry"


def test_parse_role_forces_eligible_consistency():
    # company_event 가 아니면 event_eligible 은 강제로 False.
    parsed, ok = classify_role.parse_role(
        '{"article_role":"opinion","event_eligible":true,"reason":"x","event_signature":{}}'
    )
    assert ok is True
    assert parsed["event_eligible"] is False


def test_v2_assigner_new_when_no_candidates():
    a = assign_llm_v2.LLMAssignerV2(call_fn=lambda _p: ({}, {"ok": True, "parse_success": True}))
    vec = np.array([1.0, 0.0], dtype=np.float32)
    res = a.assign(
        {
            "article_id": "005380:1",
            "stock_code": "005380",
            "title": "t",
            "description": "d",
            "event_signature": {"subject": "현대차"},
        },
        vec,
        100.0,
    )
    assert res.status == "assigned_new"
    assert res.llm_called is False  # 후보 0개면 LLM 미호출


def test_v2_assigner_signature_conflict_new():
    # 유사 임베딩이지만 Solar 가 event_signature 충돌로 new 판정 → 별도 클러스터.
    # (첫 기사는 후보 0개라 LLM 미호출이므로, LLM 은 항상 new 를 반환하도록 둔다.)
    def fake(_prompt):
        return (
            {"decision": "new", "matched_cluster_id": None},
            {"ok": True, "parse_success": True, "usage": {}},
        )

    a = assign_llm_v2.LLMAssignerV2(call_fn=fake)
    vec = np.array([1.0, 0.0], dtype=np.float32)
    r1 = a.assign(
        {
            "article_id": "005380:1",
            "stock_code": "005380",
            "title": "현대차 착공",
            "description": "A",
            "event_signature": {"action": "착공"},
        },
        vec,
        100.0,
    )
    r2 = a.assign(
        {
            "article_id": "005380:2",
            "stock_code": "005380",
            "title": "현대차 실적",
            "description": "B",
            "event_signature": {"action": "실적발표"},
        },
        vec,
        101.0,
    )
    assert r1.status == "assigned_new"
    assert r2.status == "assigned_new"  # 충돌 → 별도 클러스터
    assert r1.cluster_id != r2.cluster_id


def test_v2_assigner_existing_merge():
    responses = iter(
        [
            (
                {"decision": "existing", "matched_cluster_id": 1},
                {"ok": True, "parse_success": True, "usage": {}},
            ),
        ]
    )
    a = assign_llm_v2.LLMAssignerV2(call_fn=lambda _p: next(responses))
    vec = np.array([1.0, 0.0], dtype=np.float32)
    a.assign(
        {
            "article_id": "005380:1",
            "stock_code": "005380",
            "title": "현대차 착공",
            "description": "A",
            "event_signature": {"action": "착공"},
        },
        vec,
        100.0,
    )
    r2 = a.assign(
        {
            "article_id": "005380:2",
            "stock_code": "005380",
            "title": "현대차 착공 추가",
            "description": "A2",
            "event_signature": {"action": "착공"},
        },
        vec,
        101.0,
    )
    assert r2.status == "assigned_existing"
    assert r2.cluster_id == 1


def test_v2_assigner_invalid_response_pending():
    a = assign_llm_v2.LLMAssignerV2(
        call_fn=lambda _p: (
            {"decision": "existing", "matched_cluster_id": 999},
            {"ok": True, "parse_success": True},
        )
    )
    vec = np.array([1.0, 0.0], dtype=np.float32)
    a.assign(
        {
            "article_id": "005380:1",
            "stock_code": "005380",
            "title": "t1",
            "description": "d",
            "event_signature": None,
        },
        vec,
        100.0,
    )
    # 후보에 없는 cluster_id(999) → pending_retry (신규 생성/임의 배정 금지)
    r2 = a.assign(
        {
            "article_id": "005380:2",
            "stock_code": "005380",
            "title": "t2",
            "description": "d",
            "event_signature": None,
        },
        vec,
        101.0,
    )
    assert r2.status == "pending_retry"
    assert r2.error == "invalid_response"

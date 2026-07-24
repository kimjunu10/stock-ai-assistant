"""뉴스 처리 v2 단위 테스트: 역할분류 게이트, event_signature 배정, 멱등 스킵."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from app.repositories.news_v2 import NewsV2Repository
from app.services import news_clustering
from app.services.news_clustering import BgeM3Embedder
from app.services.news_sentiment import SentimentResult
from experiments.exp_b_factual_summaries import assign_llm_v2, classify_role
from scripts import run_full_news_v2
from scripts.run_full_news_v2 import _cluster_one_stock, _hydrate_v2_assigner, phase_cluster


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


def test_role_classifier_does_not_gate_from_noisy_description():
    called = []

    def fake(prompt):
        called.append(prompt)
        return (
            {
                "article_role": "company_event",
                "event_eligible": True,
                "reason": "제품 공개",
                "event_signature": {
                    "core_subjects": ["삼성전자"],
                    "core_topic": "폴더블폰 공개",
                    "unique_anchors": ["갤럭시 언팩"],
                    "story_relation": "initial",
                },
            },
            {"ok": True, "parse_success": True, "usage": {}},
        )

    classifier = classify_role.RoleClassifier(call_fn=fake)
    result, status = classifier.classify(
        "삼성전자",
        "005930",
        {
            "title": "삼성전자, 런던 언팩서 폴더블폰 공개",
            "description": "[기자수첩] 검색 스니펫에 섞인 배경 문구",
        },
    )

    assert status == "llm"
    assert result["article_role"] == "company_event"
    assert called


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


def test_role_prompt_uses_title_only_and_ignores_noisy_search_snippet():
    prompt = classify_role.build_user_prompt(
        "SK하이닉스",
        "000660",
        {
            "title": "최태원, 9440억원 마련 위해 SK실트론 지분 활용 검토",
            "description": "AI 인프라 확대와 웨이퍼 생산능력 두 배 계획",
            "body": "본문에도 다른 배경 설명이 길게 포함돼 있다.",
            "published_at": "2026-07-24T01:00:00+00:00",
        },
    )

    assert "9440억원 마련" in prompt
    assert "AI 인프라 확대" not in prompt
    assert "다른 배경 설명" not in prompt
    assert "제목만 근거" in prompt


def test_parse_role_normalizes_simplified_title_event_signature():
    parsed, ok = classify_role.parse_role(
        """
        {
          "article_role": "company_event",
          "event_eligible": true,
          "reason": "제목에 구체적 후속 조치가 있음",
          "event_signature": {
            "core_subjects": ["최태원"],
            "core_topic": "재산분할금 마련",
            "unique_anchors": ["9440억원", "SK실트론"],
            "story_relation": "follow_up"
          }
        }
        """
    )

    assert ok is True
    assert parsed["event_signature"] == {
        "core_subjects": ["최태원"],
        "core_topic": "재산분할금 마련",
        "unique_anchors": ["9440억원", "SK실트론"],
        "story_relation": "follow_up",
    }


def test_legacy_event_signature_is_compatible_with_simplified_schema():
    normalized = classify_role.normalize_event_signature(
        {
            "subject": "최태원",
            "action": "재산분할 판결",
            "object": "노소영",
            "amount": "9440억원",
            "identifiers": ["재산분할"],
        }
    )

    assert normalized["core_subjects"] == ["최태원"]
    assert normalized["core_topic"] == "재산분할 판결 노소영"
    assert normalized["unique_anchors"] == ["9440억원", "재산분할"]
    assert normalized["story_relation"] == "unknown"


def test_bge_m3_embedding_uses_title_only(monkeypatch):
    captured = []

    class Model:
        def encode(self, texts, **_kwargs):
            captured.extend(texts)
            return np.array([[1.0, 0.0] for _ in texts], dtype=np.float32)

    with news_clustering._embedding_cache_lock:
        news_clustering._embedding_cache.clear()
    monkeypatch.setattr(news_clustering, "_load_embedding_model", lambda *_args: Model())

    BgeM3Embedder("cpu").encode_many(
        [
            {
                "title": "최태원, 9440억원 마련 위해 SK실트론 지분 활용 검토",
                "description": "AI 인프라 확대와 웨이퍼 생산능력 두 배 계획",
            }
        ]
    )

    assert captured == ["최태원, 9440억원 마련 위해 SK실트론 지분 활용 검토"]


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
    # 0.85 미만의 유사 임베딩은 Solar가 event_signature 충돌로 new 판정한다.
    # (첫 기사는 후보 0개라 LLM 미호출이므로, LLM 은 항상 new 를 반환하도록 둔다.)
    def fake(_prompt):
        return (
            {"decision": "new", "matched_cluster_id": None},
            {"ok": True, "parse_success": True, "usage": {}},
        )

    a = assign_llm_v2.LLMAssignerV2(call_fn=fake)
    first_vec = np.array([1.0, 0.0], dtype=np.float32)
    ambiguous_vec = np.array([0.84, (1 - 0.84**2) ** 0.5], dtype=np.float32)
    r1 = a.assign(
        {
            "article_id": "005380:1",
            "stock_code": "005380",
            "title": "현대차 착공",
            "description": "A",
            "event_signature": {"action": "착공"},
        },
        first_vec,
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
        ambiguous_vec,
        101.0,
    )
    assert r1.status == "assigned_new"
    assert r2.status == "assigned_new"  # 충돌 → 별도 클러스터
    assert r1.cluster_id != r2.cluster_id


def test_v2_assigner_auto_merges_high_dense_similarity_without_llm():
    calls = []

    def fake(_prompt):
        calls.append(_prompt)
        raise AssertionError("0.85 이상 후보는 LLM을 호출하면 안 됨")

    assigner = assign_llm_v2.LLMAssignerV2(call_fn=fake)
    first_vec = np.array([1.0, 0.0], dtype=np.float32)
    high_sim_vec = np.array([0.86, (1 - 0.86**2) ** 0.5], dtype=np.float32)
    first = assigner.assign(
        {
            "article_id": "005930:auto-1",
            "stock_code": "005930",
            "title": "삼성전자 미국 반도체 투자 확대",
            "description": "미국 AI 공급망 투자 계획",
            "event_signature": None,
        },
        first_vec,
        100.0,
    )
    merged = assigner.assign(
        {
            "article_id": "005930:auto-2",
            "stock_code": "005930",
            "title": "삼성, AI 호황 현금으로 미국 기업 인수 확대",
            "description": "같은 미국 투자 확대 보도",
            "event_signature": None,
        },
        high_sim_vec,
        101.0,
    )

    assert merged.status == "assigned_existing"
    assert merged.cluster_id == first.cluster_id
    assert merged.llm_called is False
    assert merged.reason == "auto dense similarity 0.8600 > 0.85"
    assert calls == []


def test_v2_assigner_sends_below_auto_merge_threshold_to_llm():
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return (
            {"decision": "existing", "matched_cluster_id": 1},
            {"ok": True, "parse_success": True, "usage": {}},
        )

    assigner = assign_llm_v2.LLMAssignerV2(call_fn=fake)
    first_vec = np.array([1.0, 0.0], dtype=np.float32)
    ambiguous_vec = np.array([0.84, (1 - 0.84**2) ** 0.5], dtype=np.float32)
    first = assigner.assign(
        {
            "article_id": "005930:llm-1",
            "stock_code": "005930",
            "title": "삼성전자 미국 투자",
            "description": "첫 보도",
            "event_signature": None,
        },
        first_vec,
        100.0,
    )
    merged = assigner.assign(
        {
            "article_id": "005930:llm-2",
            "stock_code": "005930",
            "title": "삼성전자 미국 공급망 확대",
            "description": "판단이 필요한 보도",
            "event_signature": None,
        },
        ambiguous_vec,
        101.0,
    )

    assert merged.status == "assigned_existing"
    assert merged.cluster_id == first.cluster_id
    assert merged.llm_called is True
    assert calls and "cluster_id=1" in calls[0]


def test_v2_assigner_defaults_to_24_hour_candidate_window():
    a = assign_llm_v2.LLMAssignerV2(
        call_fn=lambda _p: (
            {"decision": "existing", "matched_cluster_id": 1},
            {"ok": True, "parse_success": True, "usage": {}},
        )
    )
    vec = np.array([1.0, 0.0], dtype=np.float32)
    first = a.assign(
        {
            "article_id": "005930:roundtable",
            "stock_code": "005930",
            "title": "기업 총수들, 젠슨 황과 AI 비공개 간담회",
            "description": "실리콘밸리 기업인 라운드테이블",
            "event_signature": {
                "subject": "이재용·최태원·이해진·젠슨 황",
                "action": "기업인 비공개 라운드테이블",
            },
        },
        vec,
        100.0,
    )
    after_window = a.assign(
        {
            "article_id": "005930:summit",
            "stock_code": "005930",
            "title": "대통령, 샌프란시스코 AI 정상회의 참석",
            "description": "정부 공식 AI 선언",
            "event_signature": {
                "subject": "대통령·기업인",
                "action": "공식 AI 정상회의 참석",
            },
        },
        vec,
        124.01,
    )

    assert a.window_h == 24
    assert first.status == "assigned_new"
    assert after_window.status == "assigned_new"
    assert after_window.llm_called is False
    assert first.cluster_id != after_window.cluster_id


def test_v2_prompt_treats_same_participants_but_different_event_as_new():
    prompt = assign_llm_v2.build_user_prompt_v2(
        {
            "title": "대통령, 샌프란시스코 AI 정상회의 참석",
            "description": "정부 공식 AI 선언과 해외 순방 일정",
            "event_signature": {
                "subject": "대통령·이재용·젠슨 황",
                "action": "공식 AI 정상회의 참석",
                "product_or_project": "샌프란시스코 AI 선언",
                "event_date": "2026-07-24",
            },
        },
        [
            {
                "cluster_id": 6787,
                "event_signature": {
                    "subject": "이재용·최태원·이해진·젠슨 황",
                    "action": "기업인 비공개 라운드테이블",
                    "product_or_project": "AI 팩토리·HBM4",
                    "event_date": "2026-07-24",
                },
                "anchor_title": "기업 총수들, 젠슨 황과 AI 비공개 간담회",
                "anchor_description": "글로벌 AI 협력 논의",
                "rep_title": "",
                "rep_description": "",
                "recent": [],
            }
        ],
    )

    assert "핵심 주체·핵심 사건 주제·고유 식별어" in prompt
    assert "단순히 인물·회사·산업만 같으면 new" in prompt
    assert "정부 공식 AI 선언과 해외 순방 일정" not in prompt
    assert "글로벌 AI 협력 논의" not in prompt
    assert assign_llm_v2.ASSIGN_V2_PROMPT_VERSION == "same_story_title_v6_multiprototype"


def test_simplified_signature_recovers_direct_follow_up_story():
    ruling = {
        "core_subjects": ["최태원"],
        "core_topic": "노소영 재산분할 판결",
        "unique_anchors": ["9440억원"],
        "story_relation": "initial",
    }
    funding = {
        "core_subjects": ["최태원"],
        "core_topic": "재산분할금 마련",
        "unique_anchors": ["9440억원", "SK실트론"],
        "story_relation": "follow_up",
    }

    score, matches = assign_llm_v2.signature_similarity(ruling, funding)

    assert score >= 0.55
    assert matches >= 2


def test_assignment_prompt_never_includes_candidate_descriptions():
    prompt = assign_llm_v2.build_user_prompt_v2(
        {
            "title": "최태원, 9440억원 마련 위해 SK실트론 지분 활용 검토",
            "description": "새 기사 오염 문구: 웨이퍼 생산능력 확대",
            "event_signature": {
                "core_subjects": ["최태원"],
                "core_topic": "재산분할금 마련",
                "unique_anchors": ["9440억원", "SK실트론"],
                "story_relation": "follow_up",
            },
        },
        [
            {
                "cluster_id": 7043,
                "event_signature": {
                    "core_subjects": ["최태원"],
                    "core_topic": "노소영 재산분할 판결",
                    "unique_anchors": ["9440억원"],
                    "story_relation": "initial",
                },
                "anchor_title": "최태원 회장, 노소영에 9440억원 재산분할 판결",
                "anchor_description": "후보 오염 문구: AI 인프라 투자",
                "rep_title": "최태원·노소영 재산분할 판결",
                "rep_description": "후보 대표 오염 문구",
                "recent": [{"title": "9440억원 재산분할", "description": "최근 오염 문구"}],
            }
        ],
    )

    assert "SK실트론 지분 활용" in prompt
    assert "노소영에 9440억원 재산분할 판결" in prompt
    assert "웨이퍼 생산능력 확대" not in prompt
    assert "AI 인프라 투자" not in prompt
    assert "대표 오염 문구" not in prompt
    assert "최근 오염 문구" not in prompt


def test_v2_assigner_recovers_candidate_from_prototype_when_centroid_drifted():
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return (
            {"decision": "existing", "matched_cluster_id": 41},
            {"ok": True, "parse_success": True, "usage": {}},
        )

    assigner = assign_llm_v2.LLMAssignerV2(call_fn=fake)
    assigner.clusters[41] = assign_llm_v2.ClusterV2(
        cluster_id=41,
        stock_code="005930",
        centroid=np.array([0.0, 1.0], dtype=np.float32),
        anchor_title="대통령 미국 순방 출국",
        anchor_description="AI 서밋 참석 일정",
        rep_title="빅테크 CEO 회동 예정",
        rep_description="같은 순방 일정",
        event_signature=None,
        prototype_vectors=[np.array([1.0, 0.0], dtype=np.float32)],
        member_article_ids=["persisted:41:0"],
        last_active_h=100.0,
    )

    result = assigner.assign(
        {
            "article_id": "005930:99",
            "stock_code": "005930",
            "title": "샌프란시스코 AI 서밋 참석",
            "description": "같은 순방의 다른 보도 각도",
            "event_signature": None,
        },
        np.array([1.0, 0.0], dtype=np.float32),
        101.0,
    )

    assert result.status == "assigned_existing"
    assert result.cluster_id == 41
    assert result.candidates[0]["centroid"] == 0.0
    assert result.candidates[0]["prototype"] == 1.0
    assert result.llm_called is False
    assert calls == []


def test_v2_assigner_reserves_candidate_slots_for_structured_event_identity():
    assigner = assign_llm_v2.LLMAssignerV2(
        call_fn=lambda _prompt: (
            {"decision": "existing", "matched_cluster_id": 77},
            {"ok": True, "parse_success": True, "usage": {}},
        ),
        max_candidates=5,
    )
    for cluster_id, dense_score in enumerate((0.84, 0.81, 0.78, 0.75, 0.72), 1):
        assigner.clusters[cluster_id] = assign_llm_v2.ClusterV2(
            cluster_id=cluster_id,
            stock_code="005930",
            centroid=np.array([dense_score, (1 - dense_score**2) ** 0.5], dtype=np.float32),
            anchor_title=f"무관한 삼성전자 사건 {cluster_id}",
            anchor_description="서로 다른 발표",
            rep_title="",
            rep_description="",
            event_signature={"subject": "삼성전자", "action": f"별도 발표 {cluster_id}"},
            member_article_ids=[f"persisted:{cluster_id}:0"],
            last_active_h=100.0,
        )
    assigner.clusters[77] = assign_llm_v2.ClusterV2(
        cluster_id=77,
        stock_code="005930",
        centroid=np.array([0.2, 0.98], dtype=np.float32),
        anchor_title="미국 순방 AI 서밋",
        anchor_description="7박 11일 일정",
        rep_title="",
        rep_description="",
        event_signature={
            "subject": "이재명 대통령",
            "action": "미국 순방",
            "product_or_project": "샌프란시스코 AI 서밋",
            "event_date": "2026-07-24",
        },
        member_article_ids=["persisted:77:0"],
        last_active_h=100.0,
    )

    result = assigner.assign(
        {
            "article_id": "005930:100",
            "stock_code": "005930",
            "title": "대통령 AI 서밋 참석",
            "description": "같은 미국 순방 일정",
            "event_signature": {
                "subject": "이재명 대통령",
                "action": "미국 순방",
                "product_or_project": "샌프란시스코 AI 서밋",
                "event_date": "2026-07-24",
            },
        },
        np.array([1.0, 0.0], dtype=np.float32),
        101.0,
    )

    assert result.status == "assigned_existing"
    assert result.cluster_id == 77
    assert len(result.candidates) <= 5
    assert 77 in {candidate["cluster_id"] for candidate in result.candidates}


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
        np.array([0.84, (1 - 0.84**2) ** 0.5], dtype=np.float32),
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
        np.array([0.84, (1 - 0.84**2) ** 0.5], dtype=np.float32),
        101.0,
    )
    assert r2.status == "pending_retry"
    assert r2.error == "invalid_response"


def test_resumed_v2_assignment_hydrates_existing_cluster():
    rows = [
        {
            "id": 41,
            "stock_code": "005380",
            "centroid": [1.0, 0.0],
            "article_count": 3,
            "last_active_at": "2026-07-21T00:00:00+00:00",
            "event_signature": {"subject": "현대차", "action": "착공"},
            "anchor": {"title": "현대차 공장 착공", "description": "첫 보도"},
            "representative": {"title": "현대차 착공 후속", "description": "후속 보도"},
        }
    ]
    assigner = _hydrate_v2_assigner(rows)
    assigner._call = lambda _prompt: (
        {"decision": "existing", "matched_cluster_id": 41},
        {"ok": True, "parse_success": True, "usage": {}},
    )

    result = assigner.assign(
        {
            "article_id": "005380:99",
            "stock_code": "005380",
            "title": "현대차 미국 공장 착공 관련 추가 보도",
            "description": "같은 착공 발표",
            "event_signature": {"subject": "현대차", "action": "착공"},
        },
        np.array([1.0, 0.0], dtype=np.float32),
        495577.0,
    )

    assert result.status == "assigned_existing"
    assert result.cluster_id == 41
    assert len(assigner.clusters[41].member_article_ids) == 4


def test_incremental_cluster_phase_can_merge_into_persisted_cluster(monkeypatch):
    persisted = {
        "id": 41,
        "stock_code": "005380",
        "centroid": [1.0, 0.0],
        "article_count": 3,
        "last_active_at": "2026-07-21T00:00:00+00:00",
        "event_signature": {"subject": "현대차", "action": "착공"},
        "anchor": {"title": "현대차 공장 착공", "description": "첫 보도"},
        "representative": {"title": "현대차 착공 후속", "description": "후속 보도"},
    }

    class Repo:
        def __init__(self):
            self.updated = []
            self.saved = []

        def get_v2_assignment_clusters(self, _stock_code, *, active_since=None):
            assert active_since == "2026-07-20T01:00:00+00:00"
            return [persisted]

        def update_v2_cluster(self, cluster_id, **values):
            self.updated.append((cluster_id, values))

        def save_v2_assignment(self, **values):
            self.saved.append(values)

    real_assigner = assign_llm_v2.LLMAssignerV2

    def build_assigner(*, api_key):
        del api_key
        return real_assigner(
            call_fn=lambda _prompt: (
                {"decision": "existing", "matched_cluster_id": 41},
                {"ok": True, "parse_success": True, "usage": {}},
            )
        )

    monkeypatch.setattr(assign_llm_v2, "LLMAssignerV2", build_assigner)
    repo = Repo()
    item = {
        "article_id": 99,
        "stock_code": "005380",
        "title": "현대차 미국 공장 착공 관련 추가 보도",
        "description": "같은 착공 발표",
        "published_at": "2026-07-21T01:00:00+00:00",
        "event_signature": {"subject": "현대차", "action": "착공"},
    }
    totals = {"cluster_pending": 0, "assigned_existing": 0, "assign_llm_calls": 0}

    _cluster_one_stock(
        repo,
        [item],
        {99: np.array([1.0, 0.0], dtype=np.float32)},
        set(),
        totals,
    )

    assert repo.updated[0][0] == 41
    assert repo.updated[0][1]["article_count"] == 4
    assert repo.saved[0]["cluster_id"] == 41
    assert repo.saved[0]["status"] == "assigned_existing"


def test_new_cluster_does_not_classify_sentiment_before_summary_exists():
    class Repo:
        def __init__(self):
            self.assignments = []

        def get_v2_assignment_clusters(self, _stock_code, *, active_since=None):
            return []

        def create_v2_cluster(self, **_values):
            return 77

        def save_v2_assignment(self, **values):
            self.assignments.append(values)

    repo = Repo()
    item = {
        "article_id": 100,
        "stock_code": "005380",
        "title": "현대차, 신규 공장 투자 발표",
        "description": "투자 계획",
        "published_at": "2026-07-22T07:00:00+00:00",
        "event_signature": {"subject": "현대차", "action": "투자"},
    }
    totals = {"cluster_pending": 0, "assigned_new": 0, "assign_llm_calls": 0}

    _cluster_one_stock(
        repo,
        [item],
        {100: np.array([1.0, 0.0], dtype=np.float32)},
        set(),
        totals,
    )

    assert repo.assignments[0]["cluster_id"] == 77
    assert "sentiment_analyzed" not in totals


def test_summary_title_is_saved_before_sentiment_classification(monkeypatch):
    events = []

    class Repo:
        def get_stock_names(self):
            return {"005930": "삼성전자"}

        def get_v2_clusters(self, *, only_unsummarized):
            assert only_unsummarized is True
            return [{"id": 77, "stock_code": "005930"}]

        def get_v2_cluster_articles(self, _cluster_id):
            return [{"title": "대표 기사에는 단종 표현", "body": "본문"}]

        def save_v2_summary(self, cluster_id, parsed, _meta, _retry_count):
            events.append(("summary", cluster_id, parsed["title"]))

        def get_cluster_sentiment_state(self, _cluster_id):
            return {}

        def save_cluster_sentiment(self, cluster_id, value, *, input_hash):
            events.append(("sentiment", cluster_id, value.label, input_hash))

    class Service:
        model_id = "test-model"
        model_revision = "test-revision"

        def __init__(self):
            self.titles = []

        def analyze(self, title):
            self.titles.append(title)
            return SentimentResult(
                label="positive",
                score=0.9,
                positive_score=0.9,
                neutral_score=0.08,
                negative_score=0.02,
                model_id=self.model_id,
                model_revision=self.model_revision,
            )

    service = Service()
    summary_title = "삼성전자, 폴드8·플립8과 첫 스마트글래스 공개"
    monkeypatch.setattr(
        run_full_news_v2.summarize,
        "call_solar",
        lambda _key, _prompt: (
            {
                "title": summary_title,
                "easy_explanation": "신제품 공개",
                "factual_body": "사실 본문",
            },
            {"ok": True, "parse_success": True},
        ),
    )
    monkeypatch.setattr(
        run_full_news_v2,
        "get_news_sentiment_service",
        lambda _settings: service,
    )
    totals = {"summaries": 0, "summary_failed": 0}

    run_full_news_v2.phase_summary(Repo(), totals)

    assert service.titles == [f"{summary_title} 신제품 공개"]
    assert events[0] == ("summary", 77, summary_title)
    assert events[1][0:3] == ("sentiment", 77, "positive")
    assert totals["summaries"] == 1
    assert totals["sentiment_analyzed"] == 1


def test_v2_assignment_persists_actual_prompt_version():
    class Query:
        def __init__(self):
            self.payload = None

        def upsert(self, payload, **_kwargs):
            self.payload = payload
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    class Client:
        def __init__(self):
            self.query = Query()

        def table(self, _name):
            return self.query

    client = Client()
    repo = NewsV2Repository(client, SimpleNamespace(news_clustering_retry_minutes=30))
    repo.save_v2_assignment(
        article_id=99,
        stock_code="005380",
        cluster_id=41,
        status="assigned_existing",
        llm_called=True,
        candidate_count=1,
        reason="same event",
        error_code=None,
    )

    assert client.query.payload["prompt_version"] == assign_llm_v2.ASSIGN_V2_PROMPT_VERSION


def test_incremental_assignment_queue_uses_one_batch_upsert():
    class Query:
        def __init__(self):
            self.payload = None
            self.execute_calls = 0

        def upsert(self, payload, **_kwargs):
            self.payload = payload
            return self

        def execute(self):
            self.execute_calls += 1
            return SimpleNamespace(data=[])

    class Client:
        def __init__(self):
            self.query = Query()

        def table(self, _name):
            return self.query

    client = Client()
    repo = NewsV2Repository(client, SimpleNamespace(news_clustering_retry_minutes=30))

    repo.queue_v2_assignments(
        [
            {"article_id": 10, "stock_code": "005930"},
            {"article_id": 11, "stock_code": "000660"},
        ]
    )

    assert client.query.execute_calls == 1
    assert [row["article_id"] for row in client.query.payload] == [10, 11]
    assert {row["status"] for row in client.query.payload} == {"pending_retry"}


def test_role_candidates_are_filtered_in_database_before_body_download():
    class Query:
        def __init__(self):
            self.or_filters = []

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def or_(self, expression):
            self.or_filters.append(expression)
            return self

        def range(self, *_args, **_kwargs):
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    class Client:
        def __init__(self):
            self.query = Query()

        def table(self, _name):
            return self.query

    client = Client()
    repo = NewsV2Repository(client, SimpleNamespace())

    assert repo.get_relevant_pairs_for_roles(only_unclassified=True) == []
    assert client.query.or_filters == [
        "role_version.is.null,role_version.neq.v2_event_role_20260721"
    ]


def test_recent_unassigned_event_pairs_recover_only_missing_assignments():
    pairs = [
        {
            "article_id": 10,
            "stock_code": "005930",
            "title": "이미 배정된 사건",
            "description": "",
            "published_at": "2026-07-24T03:00:00+00:00",
            "event_signature": {},
        },
        {
            "article_id": 11,
            "stock_code": "005930",
            "title": "재배포 중 누락된 사건",
            "description": "",
            "published_at": "2026-07-24T04:00:00+00:00",
            "event_signature": {},
        },
    ]

    class Query:
        def select(self, *_args, **_kwargs):
            return self

        def in_(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def execute(self):
            return SimpleNamespace(
                data=[
                    {
                        "article_id": 10,
                        "stock_code": "005930",
                        "status": "assigned_new",
                    }
                ]
            )

    class Client:
        def table(self, _name):
            return Query()

    repo = NewsV2Repository(Client(), SimpleNamespace())
    requested = {}

    def fake_get_event_pairs(*, published_since):
        requested["published_since"] = published_since
        return pairs

    repo.get_event_pairs = fake_get_event_pairs
    recovered = repo.get_unassigned_recent_v2_event_pairs(
        published_since="2026-07-22T05:00:00+00:00"
    )

    assert requested["published_since"] == "2026-07-22T05:00:00+00:00"
    assert [pair["article_id"] for pair in recovered] == [11]


def test_incremental_cluster_phase_does_not_scan_historical_pairs():
    class Repo:
        def get_retryable_v2_event_pairs(self):
            return []

        def get_event_pairs(self):
            raise AssertionError("incremental scheduler must not fetch all event pairs")

        def get_assigned_v2_pairs(self):
            raise AssertionError("incremental scheduler must not fetch all assignments")

    totals = {"cluster_skipped": 0}

    assert phase_cluster(Repo(), totals, candidates=[]) == {}
    assert totals["cluster_skipped"] == 0


def test_incremental_cluster_is_queued_before_embedding(monkeypatch):
    queued = []

    class Repo:
        def get_retryable_v2_event_pairs(self):
            return []

        def get_v2_assignment(self, _article_id, _stock_code):
            return None

        def queue_v2_assignments(self, pairs):
            queued.extend(pairs)

    class FailingEmbedder:
        def __init__(self, _device):
            pass

        def encode_many(self, _articles):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(run_full_news_v2, "BgeM3Embedder", FailingEmbedder)
    candidate = {
        "article_id": 99,
        "stock_code": "005380",
        "title": "현대차 신규 투자",
        "description": "신규 공장 투자 발표",
        "published_at": "2026-07-22T07:00:00+00:00",
        "event_signature": {"subject": "현대차", "action": "투자"},
    }
    totals = {
        "cluster_skipped": 0,
        "cluster_pending": 0,
        "assigned_new": 0,
        "assigned_existing": 0,
    }

    with pytest.raises(RuntimeError, match="model unavailable"):
        phase_cluster(Repo(), totals, candidates=[candidate])

    assert queued == [candidate]

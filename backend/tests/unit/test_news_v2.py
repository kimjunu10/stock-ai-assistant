"""뉴스 처리 v2 단위 테스트: 역할분류 게이트, event_signature 배정, 멱등 스킵."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from app.repositories.news_v2 import NewsV2Repository
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

    assert "행사명, 주최·초청 주체, 행사 형태와 목적" in prompt
    assert "기업인 간담회와 대통령 순방" in prompt
    assert "사건 정체성이 다르면 new" in prompt
    assert assign_llm_v2.ASSIGN_V2_PROMPT_VERSION == "same_event_sig_v4_event_identity"


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

    assert service.titles == [summary_title]
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

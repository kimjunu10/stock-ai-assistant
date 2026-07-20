"""LLM 동일사건 배정(assign_llm.LLMAssigner) 단위 테스트 — Solar 는 Mock.

prompt.md 8개 테스트:
 1. 첫 기사이고 후보 없으면 새 클러스터
 2. 동일 기업 발표 후속 기사는 기존 클러스터 배정
 3. 주제 비슷하지만 주체·행동·대상 다르면 새 클러스터
 4. 한화 군함 수주와 HD현대 방산 협력은 분리
 5. 후보 여러 개여도 Solar 호출은 기사당 1회
 6. LLM 오류 시 pending_retry
 7. 중복 재처리 시 중복 배정 없음
 8. feature flag OFF 시 기존 거리 기반 방식으로 동작

Mock 은 (parsed, meta) 를 반환하는 call_fn 으로 주입한다. 임베딩은 합성 벡터.
실행: python test_assign_llm.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
EXP_B = BASE.parent
BACKEND = EXP_B.parent.parent  # .../backend
sys.path.insert(0, str(BACKEND))

from experiments.exp_b_factual_summaries.assign_llm import LLMAssigner, parse_decision  # noqa: E402


def _norm(v):
    v = np.asarray(v, dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-12)


# 사건 방향 벡터
E1 = _norm([1, 0, 0])  # 사건 1 (예: 군함 수주)
E2 = _norm([0, 1, 0])  # 사건 2 (예: 해상풍력 착공)
E1B = _norm([0.96, 0.28, 0])  # 사건 1 과 유사(후속 기사)


def _art(aid, title, stock="042660", desc=""):
    return {"article_id": aid, "stock_code": stock, "title": title, "description": desc}


def mock_ok(decision, mcid):
    """항상 같은 결정을 내는 Mock call_fn."""

    def _f(_prompt):
        return (
            {"decision": decision, "matched_cluster_id": mcid},
            {
                "ok": True,
                "parse_success": True,
                "status": 200,
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
                "raw": "{}",
                "latency_ms": 5,
            },
        )

    return _f


def mock_fail(_prompt):
    return (
        {},
        {"ok": False, "parse_success": False, "status": 500, "raw": "boom", "latency_ms": 1},
    )


def mock_badjson(_prompt):
    return (
        {},
        {"ok": True, "parse_success": False, "status": 200, "raw": "not json", "latency_ms": 1},
    )


def mock_raw(raw):
    """실제 parse_decision 을 태워 (parsed, meta) 생성 — invalid_response 정책 검증용."""
    from experiments.exp_b_factual_summaries.assign_llm import parse_decision

    def _f(_prompt):
        parsed, ok = parse_decision(raw)
        return parsed, {"ok": True, "parse_success": ok, "status": 200, "raw": raw, "latency_ms": 1}

    return _f


def mock_existing_id(cid):
    """decision=existing 이면서 특정 matched_cluster_id 를 반환(환각 테스트용)."""

    def _f(_prompt):
        raw = f'{{"decision":"existing","matched_cluster_id":{cid}}}'
        from experiments.exp_b_factual_summaries.assign_llm import parse_decision

        parsed, ok = parse_decision(raw)
        return parsed, {"ok": True, "parse_success": ok, "status": 200, "raw": raw, "latency_ms": 1}

    return _f


def test_1_first_article_new():
    a = LLMAssigner(call_fn=mock_ok("new", None), use_llm=True)
    r = a.assign(_art("a1", "한화오션, 군함 수주"), E1, 0.0)
    assert r.status == "assigned_new" and r.n_candidates == 0 and not r.llm_called, r


def test_2_same_event_followup_assigned():
    # existing 을 반환하도록, 실제 배정된 cid 를 Mock 이 알아야 하므로 동적으로 구성
    a = LLMAssigner(use_llm=True, call_fn=mock_ok("new", None))
    r1 = a.assign(_art("a1", "한화오션, 미사일시험선 수주"), E1, 0.0)
    # 두 번째 기사: Mock 이 r1 클러스터를 선택
    a._call = mock_ok("existing", r1.cluster_id)
    r2 = a.assign(_art("a2", "한화오션 미사일시험선 수주, 세부 계약 공개"), E1B, 1.0)
    assert r2.status == "assigned_existing" and r2.cluster_id == r1.cluster_id, r2
    assert len(a.clusters[r1.cluster_id].member_article_ids) == 2


def test_3_similar_topic_diff_event_new():
    a = LLMAssigner(use_llm=True, call_fn=mock_ok("new", None))
    a.assign(_art("a1", "한화오션, 군함 수주"), E1, 0.0)
    # 임베딩은 유사(E1B)해서 후보로 잡히지만, LLM 이 new 판정 → 새 클러스터
    r2 = a.assign(_art("a2", "한화오션, 해상풍력 착공"), E1B, 1.0)
    assert r2.status == "assigned_new" and r2.llm_called and r2.n_candidates >= 1, r2
    assert len(a.clusters) == 2


def test_4_gunham_vs_bangsan_separated():
    # 군함 수주(사건1)와 방산 협력(사건2)은 임베딩이 다소 유사해도 LLM 이 분리
    a = LLMAssigner(use_llm=True, call_fn=mock_ok("new", None))
    a.assign(_art("a1", "한화오션, 미국 군함 수주"), E1, 0.0)
    r2 = a.assign(_art("a2", "HD현대, 미국과 방산 협력 협약"), _norm([0.8, 0.6, 0]), 1.0)
    assert r2.status == "assigned_new", r2
    assert len(a.clusters) == 2


def test_5_one_call_per_article_even_many_candidates():
    # 후보를 5개 만들고, 새 기사 1건 배정 시 호출 1회인지
    a = LLMAssigner(use_llm=True, call_fn=mock_ok("new", None), candidate_min_sim=0.0)
    for k in range(5):
        a.assign(_art(f"c{k}", f"사건 {k}"), _norm([1, 0.1 * k, 0]), 0.0)
    calls_before = a.calls
    a._call = mock_ok("new", None)
    a.assign(_art("x", "새 기사"), _norm([1, 0.2, 0]), 1.0)
    assert a.calls - calls_before == 1, f"호출 {a.calls - calls_before}회(기대 1)"


def test_6_llm_error_pending_retry():
    a = LLMAssigner(use_llm=True, call_fn=mock_ok("new", None))
    a.assign(_art("a1", "한화오션, 군함 수주"), E1, 0.0)
    a._call = mock_fail
    r = a.assign(_art("a2", "한화오션 군함 수주 후속"), E1B, 1.0)
    assert r.status == "pending_retry" and r.cluster_id is None, r
    # pending 은 seen 에 안 들어가 재시도 가능
    assert "a2" not in a._seen
    # 잘못된 JSON 도 pending_retry
    a._call = mock_badjson
    r2 = a.assign(_art("a3", "또 다른 후속"), E1B, 1.0)
    assert r2.status == "pending_retry", r2


def test_9_invalid_response_variants_pending_retry():
    """정책1: 후보에 없는 cluster_id / 잘못된 JSON / 필수필드 누락 / decision 오류
    → 전부 invalid_response + pending_retry. 배정도 신규 생성도 안 함."""

    # 후보 1개(cid=1) 있는 상태를 만든다.
    def fresh():
        a = LLMAssigner(use_llm=True, call_fn=mock_ok("new", None))
        a.assign(_art("a1", "한화오션, 군함 수주"), E1, 0.0)  # cid=1 생성(후보 없음)
        n_before = len(a.clusters)
        return a, n_before

    # (a) 후보에 없는 cluster_id (환각: 999)
    a, n = fresh()
    a._call = mock_existing_id(999)
    r = a.assign(_art("a2", "후속"), E1B, 1.0)
    assert r.status == "pending_retry" and r.error == "invalid_response", r
    assert len(a.clusters) == n and "a2" not in a._seen, "환각인데 신규/배정됨"

    # (b) 잘못된 JSON
    a, n = fresh()
    a._call = mock_raw("총평: 같은 사건 같아요")  # JSON 아님
    r = a.assign(_art("a3", "후속"), E1B, 1.0)
    assert r.status == "pending_retry" and r.error == "invalid_response", r
    assert len(a.clusters) == n

    # (c) 필수 필드 누락(matched_cluster_id 없음 + existing)
    a, n = fresh()
    a._call = mock_raw('{"decision":"existing"}')
    r = a.assign(_art("a4", "후속"), E1B, 1.0)
    assert r.status == "pending_retry" and r.error == "invalid_response", r
    assert len(a.clusters) == n

    # (d) decision 값 오류
    a, n = fresh()
    a._call = mock_raw('{"decision":"maybe","matched_cluster_id":1}')
    r = a.assign(_art("a5", "후속"), E1B, 1.0)
    assert r.status == "pending_retry" and r.error == "invalid_response", r
    assert len(a.clusters) == n


def test_10_anchor_fixed_on_first_article():
    """정책3: 클러스터 anchor 는 최초 기사로 고정, 새 기사가 붙어도 불변.
    판정에는 anchor title+description 만 전달된다."""
    captured = {}

    def capture_call(prompt):
        captured["prompt"] = prompt
        return (
            {"decision": "new", "matched_cluster_id": None},
            {"ok": True, "parse_success": True, "status": 200, "raw": "{}", "latency_ms": 1},
        )

    a = LLMAssigner(use_llm=True, call_fn=mock_ok("new", None))
    r1 = a.assign(_art("a1", "한화오션 군함 수주", desc="미국이 설계 요청"), E1, 0.0)
    cid = r1.cluster_id
    anchor_t0 = a.clusters[cid].anchor_title
    # 두 번째 기사 붙이기(existing)
    a._call = mock_existing_id(cid)
    a.assign(_art("a2", "군함 수주 후속 상세", desc="세부 계약"), E1B, 1.0)
    # anchor 는 그대로여야 함(rep 는 갱신될 수 있어도 anchor 불변)
    assert a.clusters[cid].anchor_title == anchor_t0 == "한화오션 군함 수주", a.clusters[cid]
    # 판정 프롬프트에 anchor 제목이 후보로 들어가는지 확인
    a._call = capture_call
    a.assign(_art("a3", "무관 기사"), E1B, 2.0)
    assert "한화오션 군함 수주" in captured["prompt"], "판정 프롬프트에 anchor 미포함"


def test_7_idempotent_no_double_assign():
    a = LLMAssigner(use_llm=True, call_fn=mock_ok("new", None))
    r1 = a.assign(_art("a1", "한화오션, 군함 수주"), E1, 0.0)
    r2 = a.assign(_art("a1", "한화오션, 군함 수주"), E1, 0.0)  # 같은 article_id 재처리
    assert r2.status == "duplicate" and r2.cluster_id == r1.cluster_id, r2
    assert len(a.clusters[r1.cluster_id].member_article_ids) == 1, "중복 배정됨"
    # a1 은 첫 기사(후보 0개)라 LLM 미호출 → calls==0. 재처리도 LLM 호출 없어야 함.
    assert a.calls == 0, f"idempotent 재처리로 LLM 호출됨(calls={a.calls})"


def test_8_flag_off_distance_based():
    # flag OFF: 유사도>=threshold 면 즉시 배정, LLM 미호출
    a = LLMAssigner(use_llm=False, call_fn=mock_fail)  # 호출되면 실패할 Mock
    r1 = a.assign(_art("a1", "한화오션, 군함 수주"), E1, 0.0)
    r2 = a.assign(_art("a2", "후속"), _norm([0.99, 0.05, 0]), 1.0)  # 매우 유사(>=0.74)
    assert r1.status == "assigned_new" and not r1.llm_called
    assert r2.status == "assigned_existing" and not r2.llm_called, r2
    assert a.calls == 0, "flag OFF 인데 LLM 호출됨"


def test_parse_decision_validation():
    # 형식 검증 단위 확인
    assert parse_decision('{"decision":"new","matched_cluster_id":null}')[1] is True
    assert parse_decision('{"decision":"existing","matched_cluster_id":3}')[1] is True
    assert parse_decision('{"decision":"existing","matched_cluster_id":null}')[1] is False
    assert parse_decision('{"decision":"maybe"}')[1] is False
    assert parse_decision("garbage")[1] is False
    # 코드펜스 섞인 출력도 복구
    assert parse_decision('```json\n{"decision":"new","matched_cluster_id":null}\n```')[1] is True


def _run_all():
    tests = [
        test_1_first_article_new,
        test_2_same_event_followup_assigned,
        test_3_similar_topic_diff_event_new,
        test_4_gunham_vs_bangsan_separated,
        test_5_one_call_per_article_even_many_candidates,
        test_6_llm_error_pending_retry,
        test_7_idempotent_no_double_assign,
        test_8_flag_off_distance_based,
        test_9_invalid_response_variants_pending_retry,
        test_10_anchor_fixed_on_first_article,
        test_parse_decision_validation,
    ]
    ok = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            ok += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{ok}/{len(tests)} passed")
    return ok == len(tests)


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)

"""Phase 8 개발셋 최종 검증: 지표 재계산 + 실패 계층 분류(모델 호출 없음, 평가 전용).

이 스크립트는 devset·gold label·grader.py·metrics.py 어느 것도 수정하지 않는다.
final-dev 실행이 만든 raw record 를 읽어 다음을 한다.

1. 기존 aggregate() 그대로 호출한 공식 지표(round2/round3 과 동일 정의).
2. 문서 검색 recall/hit@1/mrr 를 "정답 청크 hit 여부"만으로 별도 재계산해
   grader.aggregate() 의 알려진 집계 결함(§4-A. 참고)이 수치를 왜곡하는지 대조.
   - 결함: _doc_miss_is_not_retriever_fault() 가 "정답 문서의 다른 유효 청크를
     반환했다"는 조건만 보고 gold_source_hits 가 이미 있는지(=완전 적중)는
     확인하지 않는다. 그 결과 완전 적중 케이스까지 recall_total/recall_hit
     집계에서 통째로 빠져, round2/round3 의 document_retrieval.recall_at_k 가
     실제보다 낮게(0.0) 보고됐다.
   - 이 스크립트는 grader.py 를 고치지 않고, 별도 재계산으로만 실제 값을 보여준다.
3. round3 과 같은 10계층 실패 분류(phase8_round3_analysis.py 재사용 원칙과 동일).
4. PR #61 이 손댄 기능(공시 정렬 결정성, 리포트 broker/report_id/빈쿼리)이
   실행 결과에서 회귀했는지 케이스 기반으로 재확인.

실행:
    cd backend
    .venv/bin/python scripts/phase8_final_dev_analysis.py
산출: docs/rag/phase_8/eval/final_dev_analysis.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.eval.grader import (  # noqa: E402
    _DOC_SOURCE_TYPES,
    _doc_miss_is_not_retriever_fault,
    aggregate,
    grade_case,
)
from app.eval.runner import RunRecord  # noqa: E402
from app.eval.schema import EvalSuite  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"

LAYERS = [
    "Agent Tool 선택",
    "Tool 인자",
    "뉴스 Retriever",
    "리포트 Retriever",
    "구조화 조회",
    "데이터·색인",
    "Generation",
    "Validator",
    "평가기·라벨",
    "질문 자체의 모호성",
    "외부 환경",
]


def _reciprocal_rank(ranked: list[str], gold: list[str]) -> float:
    for i, rid in enumerate(ranked, start=1):
        if rid in gold:
            return 1.0 / i
    return 0.0


def corrected_document_retrieval(cases, records, grades) -> dict:
    """gold_source_hits 유무로만 문서 검색 recall/hit@1/mrr 를 재계산한다.

    grader.aggregate() 의 recall_total 산정과 달리, '적중했는데 다른 문서의
    다른 청크를 추가로 반환했다'는 이유로 제외하지 않는다 — hit 여부만 본다.
    """
    recall_hit = recall_total = 0
    hit1 = hit1_total = 0
    rr_sum = 0.0
    rr_total = 0
    excluded_bug_cases: list[str] = []

    for c, r, g in zip(cases, records, grades, strict=True):
        doc_gold = [
            gs.source_id for gs in c.gold_sources if gs.source_id and gs.source_type in _DOC_SOURCE_TYPES
        ]
        if not doc_gold:
            continue
        hits = set(g.gold_source_hits)
        has_hit = bool(hits & set(doc_gold))
        excluded = _doc_miss_is_not_retriever_fault(c, r, g)
        if excluded and has_hit:
            excluded_bug_cases.append(c.id)

        recall_total += len(doc_gold)
        recall_hit += len([d for d in doc_gold if d in hits])
        hit1_total += 1
        first = r.retrieved_ids[0] if r.retrieved_ids else None
        if first in doc_gold:
            hit1 += 1
        rr_total += 1
        rr_sum += _reciprocal_rank(r.retrieved_ids, doc_gold)

    def ratio(h, t):
        return round(h / t, 4) if t else None

    return {
        "recall_at_k": ratio(recall_hit, recall_total),
        "hit_at_1": ratio(hit1, hit1_total),
        "mrr": round(rr_sum / rr_total, 4) if rr_total else None,
        "note": (
            "gold_source_hits 유무만으로 재계산(grader.aggregate() 의 문서단위 "
            "제외 로직을 적용하지 않음). 공식 aggregate() 수치와 다르면 그 자체가 "
            "집계 결함의 증거."
        ),
        "known_aggregation_bug_cases": excluded_bug_cases,
    }


def news_report_split(cases, records, grades) -> dict:
    """뉴스/리포트 문서 검색을 분리해 recall/hit@1/mrr 를 재계산한다."""
    out = {}
    for label, type_name in (("뉴스", "뉴스 사건·영향"), ("리포트", "증권사 리포트")):
        sub = [(c, r, g) for c, r, g in zip(cases, records, grades, strict=True) if c.type == type_name]
        if not sub:
            out[label] = None
            continue
        recall_hit = recall_total = 0
        hit1 = hit1_total = 0
        rr_sum = 0.0
        rr_total = 0
        for c, r, g in sub:
            doc_gold = [
                gs.source_id
                for gs in c.gold_sources
                if gs.source_id and gs.source_type in _DOC_SOURCE_TYPES
            ]
            if not doc_gold:
                continue
            hits = set(g.gold_source_hits)
            recall_total += len(doc_gold)
            recall_hit += len([d for d in doc_gold if d in hits])
            hit1_total += 1
            first = r.retrieved_ids[0] if r.retrieved_ids else None
            if first in doc_gold:
                hit1 += 1
            rr_total += 1
            rr_sum += _reciprocal_rank(r.retrieved_ids, doc_gold)

        def ratio(h, t):
            return round(h / t, 4) if t else None

        out[label] = {
            "n_cases": len(sub),
            "recall_at_k": ratio(recall_hit, recall_total),
            "hit_at_1": ratio(hit1, hit1_total),
            "mrr": round(rr_sum / rr_total, 4) if rr_total else None,
        }
    return out


def _is_clarifying_answer(answer: str | None) -> bool:
    if not answer:
        return False
    return any(k in answer for k in ("어떤", "알려주시면", "말씀해", "확인해 드리")) and (
        "?" in answer or "습니다" in answer
    )


def classify_layer(case, rec: RunRecord, grade) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    if rec.stop_reason in ("timeout", "error", "runner_error"):
        hits.append(("외부 환경", "실행 오류"))
        return hits

    if not grade.passed_required_tools:
        hits.append(("Agent Tool 선택", "필수 Tool 누락"))
    if grade.forbidden_violated:
        hits.append(("Agent Tool 선택", "금지 Tool 호출"))
    if grade.unnecessary_tools:
        hits.append(("Agent Tool 선택", "불필요 Tool 호출"))
    if any(v is False for v in grade.arg_results.values()):
        hits.append(("Tool 인자", "인자 해석 오류"))

    if grade.gold_source_misses:
        got = set(rec.retrieved_ids) | {
            str(s.get("source_id")) for s in rec.sources if s.get("source_id")
        }
        truly_missed = [m for m in grade.gold_source_misses if m not in got]
        if truly_missed:
            if not _doc_miss_is_not_retriever_fault(case, rec, grade):
                if case.type == "뉴스 사건·영향":
                    hits.append(("뉴스 Retriever", "정답 청크 미검색"))
                elif case.type == "증권사 리포트":
                    has_specific = bool(
                        case.expected_args.get("search_research_reports", {}).get("broker")
                    ) or any(ch.isdigit() for ch in case.question)
                    if not has_specific and _is_clarifying_answer(rec.answer):
                        hits.append(("질문 자체의 모호성", "리포트 명확화(정상)"))
                    else:
                        hits.append(("리포트 Retriever", "정답 청크 미검색"))
                elif case.type in ("금융용어", "정확한 재무 숫자", "공시 설명·구조화 값"):
                    hits.append(("구조화 조회", "정답 행 미확정"))
                else:
                    hits.append(("평가기·라벨", "정답 식별자 미확정"))

    if grade.other_stock_sources:
        layer = "뉴스 Retriever" if case.type == "뉴스 사건·영향" else "리포트 Retriever"
        hits.append((layer, "타 종목 혼입"))

    fg = grade.financial_grade
    if fg and (not fg["exact"] or not fg["period_ok"]):
        hits.append(("Generation", "재무 숫자·기간 표현 오류"))
    if any(not n["matched"] for n in grade.number_results):
        hits.append(("Generation", "숫자 표현 오류"))

    errs = rec.validation_errors
    if any("제거함" in e for e in errs):
        hits.append(("Validator", "답변 삭제(재확인 필요)"))
    if any("재무성 숫자" in e for e in errs):
        hits.append(("Validator", "근거 없는 숫자 차단"))
    if any("없는 증권사" in e for e in errs):
        hits.append(("Validator", "증권사 환각 차단"))
    if grade.exclusion_violations:
        hits.append(("Generation", "제외 조건 위반"))
    if grade.unanswerable_handled is False:
        hits.append(("Generation", "답변 불가 질문 허위 답변"))

    return hits


def pr61_regression_check(cases, records, grades) -> dict:
    """PR #61 이 손댄 기능 6가지가 회귀했는지 devset 문항으로 재확인한다.

    devset 에 해당 유형 질문이 없으면 '검증됨'이라 주장하지 않고 구분해 기록한다.
    """
    by_id = {c.id: c for c in cases}
    recs_by_id = {r.case_id: r for r in records}
    grades_by_id = {g.case_id: g for g in grades}

    def rec_of(cid):
        return recs_by_id.get(cid)

    checks = {}

    # 1) 공시 검색 안정적 정렬 — devset 자체는 1회 실행이라 결정성은 targeted
    #    regression(§ PR#61)에서 이미 10회 반복으로 검증했다. 여기서는 disc
    #    문항들이 이번 실행에서 정상 동작했는지만 재확인.
    disc_cases = [c for c in cases if c.type == "공시 설명·구조화 값"]
    disc_ok = sum(
        1
        for c in disc_cases
        if grades_by_id[c.id].passed_required_tools and not grades_by_id[c.id].gold_source_misses
    )
    checks["공시_검색_정렬"] = {
        "devset_coverage": len(disc_cases),
        "정상_문항": disc_ok,
        "비고": "결정성 자체(10회 반복 동일)는 PR#61 targeted regression에서 검증됨. "
        "여기서는 이번 1회 실행의 정상 동작 여부만 재확인.",
    }

    # 2) 리포트 broker 필터
    broker_cases = [
        c
        for c in cases
        if c.type == "증권사 리포트"
        and c.expected_args.get("search_research_reports", {}).get("broker")
    ]
    broker_hit = sum(1 for c in broker_cases if not grades_by_id[c.id].gold_source_misses)
    checks["리포트_broker_필터"] = {
        "devset_coverage": len(broker_cases),
        "gold_적중": broker_hit,
    }

    # 3) 빈 리포트 검색어("목록" 요청류) — devset 에 해당 유형이 있는지 확인
    empty_query_cases = [
        c
        for c in cases
        if c.type == "증권사 리포트"
        and rec_of(c.id)
        and any(
            tc["name"] == "search_research_reports" and not (tc["args"].get("query") or "").strip()
            for tc in rec_of(c.id).tool_calls
        )
    ]
    checks["리포트_빈쿼리_목록"] = {
        "devset_coverage": len(empty_query_cases),
        "비고": "devset 문항 중 실제로 query='' 로 호출된 케이스만 집계. "
        "0건이면 devset에 순수 목록형 질문이 없다는 뜻 — targeted smoke test(§4-A)로 별도 확인됨.",
    }

    # 4) report_id 문맥 전달 — devset 에 document context 가 있는 케이스가 있는지
    report_id_context_cases = [c for c in cases if c.context.document_id]
    checks["report_id_문맥_전달"] = {
        "devset_coverage": len(report_id_context_cases),
        "비고": "0건이면 devset에 document_id 문맥 케이스가 없다는 뜻 — "
        "targeted smoke test(D케이스)로 별도 확인됨. devset으로는 검증 못 함.",
    }

    # 5) 근거 없는 목표주가 차단 / 6) 근거 있는 목표주가 보존
    tp_cases = [c for c in cases if c.type in ("증권사 리포트", "복수 기능 혼합")]
    unsupported_tp_blocked = sum(
        1
        for c in tp_cases
        if any("목표주가" in e and "일치하지 않음" in e for e in (recs_by_id.get(c.id).validation_errors if recs_by_id.get(c.id) else []))
    )
    answer_dropped = sum(
        1
        for c in tp_cases
        if any("제거함" in e for e in (recs_by_id.get(c.id).validation_errors if recs_by_id.get(c.id) else []))
    )
    checks["목표주가_검증"] = {
        "devset_coverage": len(tp_cases),
        "근거없는_목표주가_차단_건수": unsupported_tp_blocked,
        "답변_일부_삭제_건수": answer_dropped,
        "비고": "삭제 발생 시 mix-09/mix-15 처럼 원본 trace 를 봐야 오탐 여부 확정 가능(§4-B).",
    }

    return checks


def main() -> int:
    suite = EvalSuite.model_validate(json.loads((EVAL_DIR / "devset.json").read_text("utf-8")))
    by_id = {c.id: c for c in suite.cases}
    raw = json.loads((EVAL_DIR / "baseline_dev_records.json").read_text("utf-8"))
    records = [RunRecord(**r) for r in raw["records"]]
    cases = [by_id[r.case_id] for r in records]

    from app.db.client import get_supabase_client
    from app.services.facts import FactsService

    facts = FactsService(get_supabase_client())
    grades = [grade_case(c, r, facts) for c, r in zip(cases, records, strict=True)]

    official_metrics = aggregate(cases, records, grades)
    corrected_retrieval = corrected_document_retrieval(cases, records, grades)
    split_retrieval = news_report_split(cases, records, grades)

    groups: dict[str, list[dict]] = defaultdict(list)
    clean = 0
    for case, rec, grade in zip(cases, records, grades, strict=True):
        layers = classify_layer(case, rec, grade)
        real_failures = [h for h in layers if h[0] != "질문 자체의 모호성"]
        if not real_failures:
            clean += 1
        for layer, detail in layers:
            groups[layer].append(
                {
                    "id": case.id,
                    "type": case.type,
                    "detail": detail,
                    "question": case.question,
                    "gold_sources": [
                        {"type": gs.source_type, "id": gs.source_id, "ref": gs.ref}
                        for gs in case.gold_sources
                    ],
                    "tools": rec.tool_sequence,
                    "answer_head": (rec.answer or rec.error or "")[:200],
                }
            )

    layer_summary = {
        layer: {
            "count": len(groups.get(layer, [])),
            "unique_cases": len({r["id"] for r in groups.get(layer, [])}),
            "by_detail": dict(Counter(r["detail"] for r in groups.get(layer, []))),
        }
        for layer in LAYERS
    }
    unique_failure_ids = {
        r["id"] for layer in LAYERS if layer != "질문 자체의 모호성" for r in groups.get(layer, [])
    }

    pr61_checks = pr61_regression_check(cases, records, grades)

    out = {
        "note": (
            "Phase 8 최종 개발셋 검증 — 평가·분석만 수행. 운영 코드·프롬프트·"
            "Validator·Grader·devset·gold label 수정 없음."
        ),
        "n": len(cases),
        "clean_cases": clean,
        "failed_cases_unique": len(unique_failure_ids),
        "official_metrics": official_metrics,
        "corrected_document_retrieval": corrected_retrieval,
        "news_report_split_retrieval": split_retrieval,
        "by_layer": layer_summary,
        "pr61_regression_check": pr61_checks,
        "details": groups,
    }
    (EVAL_DIR / "final_dev_analysis.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"실행 {len(cases)} / 무결점 {clean} / 고유 실패 {len(unique_failure_ids)}")
    print("\n공식 aggregate() document_retrieval:", official_metrics["retrieval"]["document_retrieval"])
    print("재계산(hit 기준) document_retrieval:", corrected_retrieval)
    print("\n뉴스/리포트 분리:", json.dumps(split_retrieval, ensure_ascii=False, indent=2))
    for layer in LAYERS:
        s = layer_summary[layer]
        if s["count"]:
            print(f"  {layer:16} {s['count']:3}건(고유 {s['unique_cases']:3}) {s['by_detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 8 round2: 남은 실패를 지정된 9개 계층으로 분류 (모델 호출 없음).

계층: Agent Tool 선택 / Tool 인자 / 뉴스 Retriever / 리포트 Retriever /
      데이터·색인 정합성 / Generation / Validator / 평가기·라벨 / 외부 환경

뉴스 비현행 문서의 활성 청크(941건, 전체 뉴스 청크의 21%)가 실제 검색 실패와
연결되는지 실패 사례를 근거로 확인한다(정리·재색인은 하지 않는다).

실행:
    cd backend
    .venv/bin/python scripts/phase8_round2_analysis.py
산출: docs/rag/phase_8/eval/round2_failures.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.eval.grader import _doc_miss_is_not_retriever_fault, grade_case  # noqa: E402
from app.eval.runner import RunRecord  # noqa: E402
from app.eval.schema import EvalSuite  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"

LAYERS = [
    "Agent Tool 선택",
    "Tool 인자",
    "뉴스 Retriever",
    "리포트 Retriever",
    "데이터·색인 정합성",
    "Generation",
    "Validator",
    "평가기·라벨",
    "외부 환경",
]


def classify_layer(case, rec: RunRecord, grade) -> list[tuple[str, str]]:
    """(계층, 세부 유형) 목록을 반환한다. 문항 하나가 여러 계층에 걸릴 수 있다."""
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

    # 검색: 뉴스/리포트를 분리하고, 검증기 삭제·라벨 과잉은 제외한다(§4 재사용).
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
                    hits.append(("리포트 Retriever", "정답 청크 미검색"))
                else:
                    hits.append(("평가기·라벨", "정답 식별자 미확정"))
            # else: 같은 정답 문서의 다른 청크를 반환했거나 검증기가 지운 경우.
            # 이미 지표 집계에서 Retriever 실패로 세지 않는다(grader §4). 여기서도
            # 실패로 세면 같은 사건을 두 번 계수하게 되므로 계층에 넣지 않는다.
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


def check_stale_index_connection(cases, records, grades, client) -> dict:
    """뉴스 비현행 청크(941건)가 실제 실패와 연결되는지 확인한다(재색인 없음)."""
    by_id = {c.id: c for c in cases}
    news_fail_ids = [
        g.case_id
        for c, r, g in zip(cases, records, grades, strict=True)
        if c.type == "뉴스 사건·영향"
        and g.gold_source_misses
        and not (set(r.retrieved_ids) | {s.get("source_id") for s in r.sources})
        & set(g.gold_source_misses)
    ]
    rows = []
    stale_confirmed = 0
    for cid in news_fail_ids:
        case = by_id[cid]
        gs = case.gold_sources[0] if case.gold_sources else None
        if not gs:
            continue
        cluster_id = None
        m = re.search(r"news_clusters\.id=(\d+)", gs.note or "")
        if m:
            cluster_id = m.group(1)
        if not cluster_id:
            continue
        docs = (
            client.table("rag_documents")
            .select("id,is_current")
            .eq("source_type", "news_event")
            .eq("source_pk", cluster_id)
            .execute()
            .data
            or []
        )
        n_docs = len(docs)
        has_stale = any(not d["is_current"] for d in docs)
        if n_docs > 1 and has_stale:
            stale_confirmed += 1
        rows.append(
            {
                "case_id": cid,
                "cluster_id": cluster_id,
                "document_count": n_docs,
                "has_stale_duplicate": has_stale,
            }
        )
    return {
        "news_retriever_failures": len(news_fail_ids),
        "confirmed_stale_duplicate_cause": stale_confirmed,
        "rows": rows,
    }


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

    groups: dict[str, list[dict]] = defaultdict(list)
    clean = 0
    for case, rec, grade in zip(cases, records, grades, strict=True):
        layers = classify_layer(case, rec, grade)
        if not layers:
            clean += 1
            continue
        for layer, detail in layers:
            groups[layer].append(
                {
                    "id": case.id,
                    "type": case.type,
                    "detail": detail,
                    "question": case.question,
                    "tools": rec.tool_sequence,
                }
            )

    stale_check = check_stale_index_connection(cases, records, grades, get_supabase_client())

    summary = {
        layer: {
            "count": len(groups.get(layer, [])),
            "unique_cases": len({r["id"] for r in groups.get(layer, [])}),
            "by_detail": dict(Counter(r["detail"] for r in groups.get(layer, []))),
            "example_ids": sorted({r["id"] for r in groups.get(layer, [])})[:5],
        }
        for layer in LAYERS
    }

    out = {
        "note": "round2 남은 실패를 지정된 계층으로 분류. 재색인·정리는 하지 않았다.",
        "n": len(cases),
        "clean_cases": clean,
        "failed_cases": len(cases) - clean,
        "by_layer": summary,
        "news_stale_index_check": stale_check,
        "details": groups,
    }
    (EVAL_DIR / "round2_failures.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"실행 {len(cases)} / 무결점 {clean} / 실패 {len(cases) - clean}")
    for layer in LAYERS:
        s = summary[layer]
        if s["count"]:
            print(f"  {layer:16} {s['count']:3}건(고유 {s['unique_cases']:3}) {s['by_detail']}")
    print("\n뉴스 비현행 청크 연결 확인:")
    print(
        f"  뉴스 Retriever 실패 {stale_check['news_retriever_failures']}건 중 "
        f"비현행 중복 확인 {stale_check['confirmed_stale_duplicate_cause']}건"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

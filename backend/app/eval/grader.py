"""Phase 8 채점기 — RunRecord + EvalCase → 케이스별 채점 + 집계 지표.

정답 라벨과 실행 기록만 본다. 모델을 다시 호출하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.eval.metrics import (
    AgentMetrics,
    AnswerMetrics,
    NumberMetrics,
    OpsMetrics,
    RetrievalMetrics,
    duplicate_call_count,
    fact_covered,
    has_overclaim,
    number_matches,
)
from app.eval.runner import RunRecord
from app.eval.schema import EvalCase

# validator.py 가 내는 오류 문자열의 식별 조각(정확 문자열 결합도를 낮추려고 부분만 본다).
_CITATION_ERR = "존재하지 않는 인용"
_UNSUPPORTED_NUM_ERR = "재무성 숫자"

# 순위 기반 문서 검색 대상 vs 정확 행 조회 대상.
_DOC_SOURCE_TYPES = frozenset({"news_event", "research_report"})
_LOOKUP_SOURCE_TYPES = frozenset({"term", "financial", "structured_disclosure"})


def _doc_miss_is_not_retriever_fault(case: EvalCase, record: RunRecord, grade: CaseGrade) -> bool:
    """이 문항의 문서 검색 실패를 Retriever 탓으로 볼 수 없는지 판정한다.

    §4 가 Retriever 실패에서 빼라고 지정한 경우:
      - Tool 은 정답 문서를 반환했는데 검증기가 답변을 삭제한 경우
      - 라벨이 한 청크만 허용했지만 같은 정답 '문서'의 다른 유효 청크를 반환한 경우
    단, 실제로 다른 종목·엉뚱한 문서를 반환한 경우는 계속 실패로 남긴다.
    """
    # 다른 종목이 섞였으면 명백한 검색 실패다.
    if grade.other_stock_sources:
        return False

    # 검증기가 답변 문장을 지운 경우 — 검색은 성공했는데 답이 사라진 것.
    if any("제거함" in e for e in record.validation_errors):
        return True

    # 같은 정답 문서의 다른 청크를 반환했는가.
    # 라벨 note 에 원본 식별자(news_clusters.id / research_reports.id)가 있고,
    # 실제 출처의 locator 가 같은 원본을 가리키면 문서 단위로는 맞힌 것이다.
    want_docs = set()
    for gs in case.gold_sources:
        note = gs.note or ""
        m = re.search(r"news_clusters\.id=(\d+)", note)
        if m:
            want_docs.add(("news", m.group(1)))
        m = re.search(r"research_reports\.id=([0-9a-f-]{36})", note)
        if m:
            want_docs.add(("report", m.group(1)))
    if not want_docs:
        return False
    for s in record.sources:
        loc = s.get("locator") or {}
        rid = loc.get("report_id")
        if rid and ("report", str(rid)) in want_docs:
            return True
        pk = loc.get("source_pk")
        if pk and ("news", str(pk)) in want_docs:
            return True
    return False


@dataclass
class CaseGrade:
    """케이스 1건 채점 결과."""

    case_id: str
    type: str
    passed_required_tools: bool = True
    forbidden_violated: list[str] = field(default_factory=list)
    unnecessary_tools: list[str] = field(default_factory=list)
    arg_results: dict[str, bool] = field(default_factory=dict)
    gold_source_hits: list[str] = field(default_factory=list)
    gold_source_misses: list[str] = field(default_factory=list)
    other_stock_sources: list[str] = field(default_factory=list)
    fact_hits: int = 0
    fact_total: int = 0
    number_results: list[dict] = field(default_factory=list)
    financial_grade: dict | None = None  # expected_financial 채점(DB 기준값 대조)
    period_ok: bool | None = None
    trading_day_ok: bool | None = None
    exclusion_violations: list[str] = field(default_factory=list)
    overclaim: bool = False
    unanswerable_handled: bool | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        return d


def _arg_matches(expected: Any, actual: Any) -> bool:
    """기대 인자 1개 비교.

    - `*_contains` 규약: 실제 값 문자열에 기대 문자열이 들어 있으면 통과(표현 차이 허용)
    - 리스트: 기대 항목이 실제 리스트 어딘가에 부분 문자열로 있으면 통과
    - 그 외: 문자열화 후 완전 일치(종목코드·연도·기간 등은 정확 일치)
    """
    if isinstance(expected, list):
        actual_text = " ".join(str(a) for a in actual) if isinstance(actual, list) else str(actual)
        return all(str(e) in actual_text for e in expected)
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual
    return str(expected).strip().lower() == str(actual).strip().lower()


def grade_arguments(case: EvalCase, record: RunRecord) -> dict[str, bool]:
    """기능 입력 정확도(§8 'Tool 입력 정확도').

    expected_args 의 각 (tool, arg) 를 실제 호출 인자와 비교한다.
    `_contains` 접미사가 붙은 기대 키는 부분 일치로 본다(자연어 인자 대응).

    required_tools_any 로 여러 Tool 중 하나면 되는 문항에서, 라벨의 expected_args 는
    그중 한 Tool 만 예시로 적어둘 수 있다. 허용된 다른 Tool 로 답했다면 부르지 않은
    Tool 의 인자를 틀렸다고 셀 수 없다(제품 실패가 아니라 라벨 표현의 한계).
    이 경우만 채점에서 제외하며, 필수 Tool 자체를 안 부른 경우는 그대로 실패로 둔다.
    """
    used = {c["name"] for c in record.tool_calls}
    satisfied_by_alternative = bool(case.required_tools_any) and bool(
        used & set(case.required_tools_any)
    )
    results: dict[str, bool] = {}
    for tool_name, expected in case.expected_args.items():
        actual_calls = [c for c in record.tool_calls if c["name"] == tool_name]
        for key, want in expected.items():
            label = f"{tool_name}.{key}"
            if not actual_calls:
                if satisfied_by_alternative and tool_name in case.required_tools_any:
                    continue
                results[label] = False
                continue
            if any(c.get("args") is None for c in actual_calls):
                # 인자를 관찰하지 못한 실행(recorder 미사용) — 채점 대상에서 뺀다.
                continue
            base_key = key[: -len("_contains")] if key.endswith("_contains") else key
            ok = False
            for call in actual_calls:
                actual = (call.get("args") or {}).get(base_key)
                if actual is None:
                    continue
                if key.endswith("_contains"):
                    text = (
                        " ".join(str(a) for a in actual)
                        if isinstance(actual, list)
                        else str(actual)
                    )
                    wants = want if isinstance(want, list) else [want]
                    ok = all(str(w) in text for w in wants)
                else:
                    ok = _arg_matches(want, actual)
                if ok:
                    break
            results[label] = ok
    return results


def resolve_expected_financial(facts: Any, case: EvalCase, spec: Any = None) -> dict | None:
    """expected_financial 명세로 DB 에서 정답 재무값을 가져온다.

    정답 숫자를 라벨에 적어두지 않는 이유는 오타가 정답이 되는 걸 막기 위해서다.
    Tool 과 같은 조회 경로를 써서 기준행을 읽는다(RAG 답변을 정답으로 쓰지 않음).
    facts 가 없으면(오프라인 채점) None 을 돌려 해당 항목을 건너뛴다.
    """
    spec = spec if spec is not None else case.expected_financial
    if spec is None or facts is None:
        return None
    from app.agent.tools.financials import FinancialFactsInput, run_get_financial_facts

    res = run_get_financial_facts(
        facts,
        FinancialFactsInput(
            stock_code=spec.stock_code,
            account_name=spec.account_name,
            business_year=spec.business_year,
            report_period=spec.report_period,
            amount_type=spec.amount_type,
            fs_div=spec.fs_div,
        ),
    )
    if res.status != "ok" or not res.data.get("facts"):
        return None
    return res.data["facts"][0]


def _grade_financial_answer(answer: str, gold: dict) -> dict:
    """정답 재무값이 답변에 정확히 반영됐는지(숫자·기간·실제값 여부)."""
    value = gold.get("value_won")
    exact = bool(value) and number_matches(answer, float(value))
    period = gold.get("period") or ""
    period_ok = bool(period) and any(t in answer for t in _period_tokens(period))
    # financials 는 DART 실제값이다. 답변이 전망치로 말하면 실제/전망 혼동.
    confused = gold.get("value_kind") == "actual_value" and any(
        w in answer for w in ("전망치", "예상치", "컨센서스")
    )
    return {
        "exact": exact,
        "period_ok": period_ok,
        "unit_ok": (gold.get("unit") or "원") in answer or "조" in answer or "억" in answer,
        "value_kind_confused": confused,
    }


def _period_tokens(period: str) -> list[str]:
    """'2025년 3분기보고서 누적' → 채점용 핵심 토큰."""
    toks = [
        t for t in ("연간", "사업보고서", "1분기", "반기", "3분기", "누적", "당기") if t in period
    ]
    head = period.split("년")[0]
    if head.isdigit():
        toks.append(head)
    return toks or [period]


def grade_case(case: EvalCase, record: RunRecord, facts: Any = None) -> CaseGrade:
    """케이스 1건을 채점한다.

    facts(FactsService)를 주면 expected_financial 정답을 DB 에서 조회해 함께 채점한다.
    """
    g = CaseGrade(case_id=case.id, type=case.type)
    used = [c["name"] for c in record.tool_calls]
    used_set = set(used)

    # --- Agent trajectory ---
    required = set(case.required_tools)
    g.passed_required_tools = required.issubset(used_set)
    if case.required_tools_any:
        g.passed_required_tools = g.passed_required_tools and bool(
            set(case.required_tools_any) & used_set
        )
    g.forbidden_violated = sorted(set(case.forbidden_tools) & used_set)
    allowed = required | set(case.required_tools_any) | set(case.optional_tools)
    g.unnecessary_tools = sorted(t for t in used_set - allowed if t not in case.forbidden_tools)
    g.arg_results = grade_arguments(case, record)

    # --- 검색: 정답 식별자 ---
    got_ids = set(record.retrieved_ids) | {
        str(s.get("source_id")) for s in record.sources if s.get("source_id")
    }
    for gs in case.gold_sources:
        if not gs.source_id:
            continue  # 식별자 미확정 라벨은 검색 채점에서 제외(수동 검토 대상)
        if gs.source_id in got_ids:
            g.gold_source_hits.append(gs.source_id)
        else:
            g.gold_source_misses.append(gs.source_id)

    # 다른 종목 혼입: 출처의 stock_code 가 기대 종목과 다른 경우
    want_stock = case.context.stock_code or case.stock_code
    if want_stock:
        g.other_stock_sources = sorted(
            {
                str(s.get("source_id"))
                for s in record.sources
                if s.get("stock_code") and str(s.get("stock_code")) != want_stock
            }
        )

    # --- 답변 사실·숫자 ---
    g.fact_total = len(case.expected_facts)
    g.fact_hits = sum(1 for f in case.expected_facts if fact_covered(record.answer, f))
    for num in case.expected_numbers:
        g.number_results.append(
            {
                "label": num.label,
                "value": num.value,
                "unit": num.unit,
                "matched": number_matches(record.answer, num.value, num.tolerance),
                "unit_ok": num.unit in record.answer if num.unit else True,
            }
        )

    # --- 재무 정답(DB 기준값과 대조) ---
    # 질문이 객관적으로 모호하면 허용 해석 중 하나라도 맞으면 정답으로 본다.
    specs = [case.expected_financial, *case.acceptable_financials]
    graded: list[dict] = []
    for spec in [s for s in specs if s is not None]:
        gold = resolve_expected_financial(facts, case, spec)
        if not gold:
            continue
        got = _grade_financial_answer(record.answer, gold)
        got["gold_value_won"] = gold.get("value_won")
        graded.append(got)
    if graded:
        # 정답으로 인정되는 해석이 있으면 그것을, 없으면 첫 번째를 기록한다.
        g.financial_grade = next((x for x in graded if x["exact"]), graded[0])
        if len(graded) > 1:
            g.financial_grade["accepted_interpretations"] = len(graded)

    # --- 기간·거래일 ---
    if case.expected_period:
        p = case.expected_period
        # 기간 정확도는 '틀린 기간을 말했는가'를 봐야 한다. 질문에 없는 낱말을
        # 답변에 쓰라고 요구하면 안 된다 — "연간 매출액" 질문에 "누적"이라고
        # 적지 않았다는 이유로 정답이 실패 처리되던 채점기 결함(fin-02 등 11건).
        tokens = [
            t
            for t in (p.business_year, p.report_period, p.amount_type)
            if t and (t in case.question or t in record.answer)
        ]
        g.period_ok = all(t in record.answer for t in tokens) if tokens else None
        days = [d for d in (p.start_trading_day, p.end_trading_day, p.event_date) if d]
        if days:
            # 거래일은 정확 일치. 답변이 "2026-07-24" 또는 "7월 24일" 로 쓸 수 있어 둘 다 본다.
            g.trading_day_ok = all(_date_in_answer(d, record.answer) for d in days)

    # --- 제외 조건·과도한 단정 ---
    g.exclusion_violations = [c for c in case.forbidden_claims if _claim_asserted(record.answer, c)]
    g.overclaim = has_overclaim(record.answer)

    # --- 답변 불가능 질문 ---
    if not case.is_answerable:
        g.unanswerable_handled = _handled_as_unanswerable(record)

    if record.error:
        g.notes.append(f"실행 오류: {record.error}")
    return g


# 금지어가 이 표현들과 같은 문장에 있으면 '금지 내용을 말한 것'이 아니라
# '제외했다/없다/아니다'고 밝힌 것이다(예: "실적 관련 내용은 제외했습니다").
_NEGATION_MARKERS = (
    "제외",
    "빼고",
    "없습니다",
    "없어",
    "없음",
    "확인할 수 없",
    "제공되지",
    "포함하지 않",
    "말고",
    "필요 없",
    "아닙니다",
    "아님",
    "아닌",
    "하지 않",
    "해당하지 않",
)


def _claim_excluded_by_suffix(sentence: str, claim: str) -> bool:
    """'실적 외 주요 이슈', 'OO 외에는 사용하지 않았다'처럼 금지어 바로 뒤에
    '외'가 붙어 그 내용을 논의 대상에서 뺐다고 밝히는 표현을 잡는다.

    금지어와 무관한 '해외/이외' 같은 단어의 '외'까지 잡지 않도록 금지어 바로
    뒤(공백 허용)에 오는 '외'만 인정한다.
    """
    return re.search(re.escape(claim) + r"\s*외(?:에는)?", sentence) is not None


def _claim_asserted(answer: str, claim: str) -> bool:
    """금지 주장이 실제로 '주장'됐는지 판정한다.

    단순 부분 문자열 검사는 "실적 관련 내용은 제외했습니다"처럼 제외를 지켰다고
    밝힌 문장까지 위반으로 세어 오탐이 난다. 금지어가 등장한 문장에 부정·제외
    표현이 함께 있으면 위반으로 보지 않는다.
    """
    for sentence in re.split(r"[.!?\n]", answer):
        if claim not in sentence:
            continue
        if any(marker in sentence for marker in _NEGATION_MARKERS):
            continue
        if _claim_excluded_by_suffix(sentence, claim):
            continue
        return True
    return False


def _date_in_answer(day: str, answer: str) -> bool:
    """YYYY-MM-DD 를 답변 표기(ISO 또는 'M월 D일')로 찾는다."""
    if day in answer:
        return True
    try:
        y, m, d = day.split("-")
    except ValueError:
        return False
    return f"{int(m)}월 {int(d)}일" in answer


def _handled_as_unanswerable(record: RunRecord) -> bool:
    """답변 불가능 질문을 올바로 처리했는지.

    통과: 데이터 없음을 밝히거나(없/불가/확인되지 않), 되묻거나, 근거 없이 답하지 않음.
    실패: 출처 없이 단정적으로 답을 만들어낸 경우.
    """
    text = record.answer
    # timeout·step_limit·error 로 끝났으면 허위 답변을 만들지 않은 것이다.
    if record.stop_reason in ("timeout", "step_limit", "error", "runner_error"):
        return True
    if any(k in text for k in ("없", "불가", "확인되지", "알려주", "어떤 종목", "제공하지")):
        return True
    # 출처가 하나도 없는데 서술형 답을 냈다면 허위 답변으로 본다.
    made_up_answer = bool(text.strip()) and not record.sources
    return not made_up_answer


def aggregate(cases: list[EvalCase], records: list[RunRecord], grades: list[CaseGrade]) -> dict:
    """집계 지표(§8)."""
    by_id = {c.id: c for c in cases}
    agent = AgentMetrics(n=len(grades))
    retr = RetrievalMetrics(n=len(grades))
    nums = NumberMetrics()
    ans = AnswerMetrics()
    ops = OpsMetrics()

    for rec, g in zip(records, grades, strict=True):
        case = by_id[g.case_id]
        used = [c["name"] for c in rec.tool_calls]

        # Agent
        req_units = len(case.required_tools) + (1 if case.required_tools_any else 0)
        agent.required_total += req_units
        agent.required_hit += len(set(case.required_tools) & set(used))
        if case.required_tools_any and set(case.required_tools_any) & set(used):
            agent.required_hit += 1
        if g.forbidden_violated:
            agent.forbidden_cases += 1
        agent.tool_calls_total += len(used)
        agent.unnecessary_tool_calls += sum(1 for u in used if u in g.unnecessary_tools)
        agent.arg_hit += sum(1 for v in g.arg_results.values() if v)
        agent.arg_total += len(g.arg_results)
        if len(case.required_tools) + len(case.required_tools_any) >= 2:
            agent.multistep_total += 1
            if g.passed_required_tools:
                agent.multistep_done += 1
        if duplicate_call_count(used):
            agent.duplicate_cases += 1

        # 검색: 문서 검색과 구조화 조회를 나눠 집계한다(성격이 다른 실패다).
        doc_gold = [
            gs.source_id
            for gs in case.gold_sources
            if gs.source_id and gs.source_type in _DOC_SOURCE_TYPES
        ]
        lookup_gold = [
            gs.source_id
            for gs in case.gold_sources
            if gs.source_id and gs.source_type in _LOOKUP_SOURCE_TYPES
        ]
        hits = set(g.gold_source_hits)

        if doc_gold and not _doc_miss_is_not_retriever_fault(case, rec, g):
            retr.recall_total += len(doc_gold)
            retr.recall_hit += len([d for d in doc_gold if d in hits])
            retr.hit_at_1_total += 1
            first = rec.retrieved_ids[0] if rec.retrieved_ids else None
            if first in doc_gold:
                retr.hit_at_1 += 1
            retr.rr_total += 1
            retr.rr_sum += _reciprocal_rank(rec.retrieved_ids, doc_gold)

        if lookup_gold:
            # 구조화 조회는 순위가 아니라 '정확한 행을 집었는가'다.
            retr.lookup_total += len(lookup_gold)
            retr.lookup_hit += len([x for x in lookup_gold if x in hits])
        if g.other_stock_sources:
            retr.other_stock_cases += 1
        for gs in case.gold_sources:
            if gs.source_type == "research_report" and gs.page:
                retr.page_total += 1
                if any(
                    s.get("source_type") == "research_report" and s.get("page") == gs.page
                    for s in rec.sources
                ):
                    retr.page_ok += 1

        # 숫자·기간
        for nr in g.number_results:
            nums.exact_total += 1
            nums.unit_total += 1
            if nr["matched"]:
                nums.exact_hit += 1
            if nr["unit_ok"]:
                nums.unit_hit += 1
        # expected_financial 채점(DB 기준값 대조)도 숫자 지표에 합산한다.
        if g.financial_grade:
            fg = g.financial_grade
            nums.exact_total += 1
            nums.exact_hit += int(fg["exact"])
            nums.unit_total += 1
            nums.unit_hit += int(fg["unit_ok"])
            nums.period_total += 1
            nums.period_hit += int(fg["period_ok"])
            nums.value_kind_confusions += int(fg["value_kind_confused"])
        if g.period_ok is not None:
            nums.period_total += 1
            nums.period_hit += int(g.period_ok)
        if g.trading_day_ok is not None:
            nums.trading_day_total += 1
            nums.trading_day_hit += int(g.trading_day_ok)

        # 답변·출처
        ans.fact_total += g.fact_total
        ans.fact_hit += g.fact_hits
        if any(_CITATION_ERR in e for e in rec.validation_errors):
            ans.nonexistent_citations += 1
        if any(_UNSUPPORTED_NUM_ERR in e for e in rec.validation_errors):
            ans.unsupported_numbers += 1
        ans.exclusion_violations += len(g.exclusion_violations)
        if g.overclaim:
            ans.overclaim_cases += 1
        if g.unanswerable_handled is False:
            ans.false_answer_on_unanswerable += 1
        # Citation Precision: 답변이 인용한 출처가 실제 근거 목록에 있는지(검증기 기준)
        if rec.sources:
            ans.citation_precision_total += 1
            if not any(_CITATION_ERR in e for e in rec.validation_errors):
                ans.citation_precision_hit += 1
        # Citation Coverage: 답변 가능 질문이 출처를 하나라도 달았는지
        if case.is_answerable and rec.answer.strip():
            ans.citation_cov_total += 1
            if rec.sources:
                ans.citation_covered += 1

        # 운영
        ops.latencies.append(rec.total_latency_ms)
        ops.tool_calls.append(len(used))
        ops.model_calls.append(rec.model_calls)
        ops.costs.append(rec.cost_usd)

    return {
        "n": len(grades),
        "agent": agent.as_dict(),
        "retrieval": retr.as_dict(),
        "numbers": nums.as_dict(),
        "answer": ans.as_dict(),
        "ops": ops.as_dict(),
    }


def _reciprocal_rank(retrieved: list[str], gold: list[str]) -> float:
    for i, r in enumerate(retrieved, start=1):
        if r in gold:
            return 1.0 / i
    return 0.0

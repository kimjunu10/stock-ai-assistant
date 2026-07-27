"""Phase 8 채점기 — RunRecord + EvalCase → 케이스별 채점 + 집계 지표.

정답 라벨과 실행 기록만 본다. 모델을 다시 호출하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.agent.time_context import resolve_relative_date_range
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
from app.eval.news_gold import canonical_news_cluster_id
from app.eval.runner import RunRecord
from app.eval.schema import EvalCase

# validator.py 가 내는 오류 문자열의 식별 조각(정확 문자열 결합도를 낮추려고 부분만 본다).
_CITATION_ERR = "존재하지 않는 인용"
_UNSUPPORTED_NUM_ERR = "재무성 숫자"

# 순위 기반 문서 검색 대상 vs 정확 행 조회 대상.
_DOC_SOURCE_TYPES = frozenset({"news_event", "research_report"})
_LOOKUP_SOURCE_TYPES = frozenset({"term", "financial", "structured_disclosure"})

_NEWS_DOC_ID_RE = re.compile(r"news_clusters\.id=(\d+)")
_REPORT_DOC_ID_RE = re.compile(r"research_reports\.id=([0-9a-fA-F-]{36})")
# gold note 규약: "news_clusters.id=<id> / <YYYY-MM-DD> / <감성> / 기사 N건 / ...".
_GOLD_PUBLISHED_DATE_RE = re.compile(r"/\s*(\d{4}-\d{2}-\d{2})\s*/")


def _normalize_doc_id(kind: str, raw: str) -> str:
    """부모 문서 ID 표기를 통일한다(ID 타입·문자열 형식 정규화).

    news_clusters.id 는 DB 상 정수이지만 라벨 note·locator.source_pk 양쪽에서
    문자열로 오갈 수 있다. research_reports.id(uuid) 는 대소문자 차이가 있을 수
    있다. 종류를 접두어로 붙여 뉴스/리포트 ID 공간이 절대 섞이지 않게 한다.
    """
    return f"{kind}:{str(raw).strip().lower()}"


def _gold_document_id(gs: Any) -> str | None:
    """정답 라벨(GoldSource)에서 부모 문서 ID를 뽑는다(청크 ID 아님).

    뉴스는 canonical_id 의 news_clusters.id 를 우선 사용한다. 기존 devset
    라벨과 리포트는 note 에 사람이 적어둔 원본 식별자를 읽는 호환 경로를
    유지한다. 어느 경우에도 재색인 산물인 chunk UUID를 문서 정답으로 쓰지 않는다.
    """
    if gs.source_type == "news_event":
        cluster_id = canonical_news_cluster_id(gs)
        if cluster_id:
            return _normalize_doc_id("news", cluster_id)

    note = gs.note or ""
    m = _NEWS_DOC_ID_RE.search(note)
    if m:
        return _normalize_doc_id("news", m.group(1))
    m = _REPORT_DOC_ID_RE.search(note)
    if m:
        return _normalize_doc_id("report", m.group(1))
    return None


def _source_document_id(source: dict) -> str | None:
    """Tool 이 반환한 출처 1건(dict)에서 부모 문서 ID를 뽑는다.

    news_event 는 locator.source_pk 가 news_clusters.id 와 동일 값이고,
    research_report 는 locator.report_id 가 research_reports.id 와 동일
    값이다(둘 다 이미 원본 테이블 PK를 그대로 넘겨받는 필드 — 별도 조인 없이
    신뢰 가능). 다른 source_type 은 문서 검색 대상이 아니므로 None.
    """
    loc = source.get("locator") or {}
    stype = source.get("source_type")
    if stype == "news_event":
        pk = loc.get("source_pk")
        return _normalize_doc_id("news", pk) if pk else None
    if stype == "research_report":
        rid = loc.get("report_id")
        return _normalize_doc_id("report", rid) if rid else None
    return None


def document_ranking(record: RunRecord) -> list[str]:
    """실행 기록에서 문서 검색 순위(부모 문서 ID, 중복 제거)를 뽑는다.

    record.sources 는 Tool 이 반환한 순서를 그대로 보존한다(실제 검색
    순위) — record.retrieved_ids 는 집합을 정렬한 값이라 청크 ID의
    알파벳순이 되어버려 순위 정보로 쓸 수 없다(Hit@1/MRR 계산에 그걸 쓰면
    실제 검색 결과와 무관한 순서로 채점된다). 같은 문서의 여러 청크가
    연달아 나오면 첫 등장 순위만 남기고 중복 제거한다.
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    for s in record.sources:
        doc_id = _source_document_id(s)
        if doc_id and doc_id not in seen_set:
            seen_set.add(doc_id)
            seen.append(doc_id)
    return seen


def _doc_miss_is_not_retriever_fault(case: EvalCase, record: RunRecord, grade: CaseGrade) -> bool:
    """이 문항의 문서 검색 실패를 Retriever 탓으로 볼 수 없는지 판정한다.

    §4 가 Retriever 실패에서 빼라고 지정한 경우:
      - Tool 은 정답 문서를 반환했는데 검증기가 답변을 삭제한 경우
      - 라벨이 한 청크만 허용했지만 같은 정답 '문서'의 다른 유효 청크를 반환한 경우
    단, 실제로 다른 종목·엉뚱한 문서를 반환한 경우는 계속 실패로 남긴다.

    주의: 이 함수는 '검색이 실패했을 때 그 실패를 Retriever 탓이 아니라고
    볼 것인가'를 판정하는 용도로만 쓴다. 문서를 실제로 맞힌 경우(완전 적중)
    에는 이 함수의 반환값과 무관하게 항상 적중으로 집계해야 한다 — 과거
    aggregate() 는 이 구분 없이 호출해 완전 적중 케이스까지 recall 집계에서
    빠지는 결함이 있었다(§1 참고). 새 aggregate() 는 document_recall_stats()
    를 통해 이 구분을 명시적으로 지킨다.
    """
    # 다른 종목이 섞였으면 명백한 검색 실패다.
    if grade.other_stock_sources:
        return False

    # 검증기가 답변 문장을 지운 경우 — 검색은 성공했는데 답이 사라진 것.
    if any("제거함" in e for e in record.validation_errors):
        return True

    # 같은 정답 문서의 다른 청크를 반환했는가 — 문서 ID 기준으로 비교한다.
    gold_doc = _gold_document_id_for_case(case)
    if gold_doc is None:
        return False
    return gold_doc in document_ranking(record)


def _gold_document_id_for_case(case: EvalCase) -> str | None:
    """이 문항의 뉴스/리포트 정답 문서 ID(있으면 정확히 1개)를 반환한다."""
    for gs in case.gold_sources:
        doc_id = _gold_document_id(gs)
        if doc_id is not None:
            return doc_id
    return None


def _gold_published_date(case: EvalCase) -> date | None:
    """gold note 에 사람이 적어둔 발행일(YYYY-MM-DD)을 뽑는다.

    devset·홀드아웃 자체는 수정하지 않는다 — note 는 이미 존재하는 라벨
    필드를 읽기만 한다.
    """
    for gs in case.gold_sources:
        note = gs.note or ""
        m = _GOLD_PUBLISHED_DATE_RE.search(note)
        if m:
            return date.fromisoformat(m.group(1))
    return None


def _relative_period_search_news_calls(record: RunRecord) -> list[dict]:
    """이 실행에서 실제로 relative_period 로 호출된 search_news 인자만 뽑는다.

    date_from/date_to 를 사용자가 절대 날짜로 지정한 호출은 상대 기간 계약과
    무관하므로 대상이 아니다.
    """
    out = []
    for c in record.tool_calls:
        if c.get("name") != "search_news":
            continue
        args = c.get("args") or {}
        if args.get("relative_period"):
            out.append(args)
    return out


def gold_out_of_relative_range(case: EvalCase, record: RunRecord) -> bool:
    """§4 stale_gold/evaluation_data_issue 판정: gold 발행일이 실제 실행 시각
    기준 relative_period 검색 범위 밖에 있었는지.

    실제 서비스는 "최근 3일"을 항상 Agent 실행 시각(evaluation_run_at) 기준으로
    계산한다(과거 라벨링 시점 기준으로 고정하지 않는다). devset 라벨링 당시에는
    gold 가 그 범위 안이었더라도, 평가를 재실행한 시각 기준으로는 범위 밖으로
    밀려날 수 있다 — 이건 Retriever 가 놓친 게 아니라 평가 데이터(라벨 유효기간)
    문제이므로 별도로 분류한다(Retriever 실패 집계에서 제외하지 않고, 원인 표시만
    덧붙인다 — 기존 strict 지표는 그대로 보존).
    """
    gold_date = _gold_published_date(case)
    if gold_date is None or not record.evaluation_run_at:
        return False
    run_at = datetime.fromisoformat(record.evaluation_run_at)
    for args in _relative_period_search_news_calls(record):
        try:
            start_s, end_s = resolve_relative_date_range(
                args["relative_period"], reference_date=run_at.date()
            )
        except ValueError:
            continue
        start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)
        if not (start <= gold_date <= end):
            return True
    return False


def preflight_check_relative_gold_validity(
    cases: list[EvalCase], *, planned_run_at: datetime
) -> dict:
    """§3 홀드아웃 정책: 실행 전에 상대 날짜 gold 가 유효한지만 미리 점검한다.

    실행 기록(RunRecord)이 아직 없는 시점(실행 전)에 쓰는 함수이므로,
    실제 search_news 호출은 아직 알 수 없으므로 질문의 명시적 상대 기간 표현이나
    expected_args.search_news.relative_period 를 사용한다. 상대 기간 조건이 없는
    문항은 오래된 특정 사건을 묻는 질문일 수 있으므로 날짜만으로 중단하지 않는다.

    이 함수는 실행을 멈추지 않는다 — 호출부(홀드아웃 실행 스크립트)가 반환된
    `should_abort`를 보고 직접 중단 여부를 결정한다. devset·holdout 파일 자체를
    열지 않고 이미 로드된 EvalCase 목록만 받는다(§6 '홀드아웃 열람·실행' 금지는
    이 함수 자체의 책임이 아니라 호출 시점의 책임이다).
    """
    from app.agent.time_context import RECENT_LOOKBACK_DAYS

    question_periods = (
        ("last_7_days", re.compile(r"(?:최근|지난)\s*(?:7\s*일|일주일|한\s*주)")),
        ("last_30_days", re.compile(r"(?:최근|지난)\s*(?:30\s*일|한\s*달|1\s*개월)")),
        ("this_week", re.compile(r"이번\s*주")),
        ("this_month", re.compile(r"이번\s*(?:달|개월)")),
        ("yesterday", re.compile(r"어제")),
        ("today", re.compile(r"오늘")),
        ("recent", re.compile(r"최근")),
    )

    def expected_relative_period(case: EvalCase) -> str | None:
        expected = case.expected_args.get("search_news", {}).get("relative_period")
        if expected:
            return str(expected)
        normalized_question = re.sub(r"\s+", " ", case.question)
        return next(
            (period for period, pattern in question_periods if pattern.search(normalized_question)),
            None,
        )

    stale: list[dict] = []
    checked = 0
    relative_cases = 0
    skipped_no_gold_date = 0
    for case in cases:
        relative_period = expected_relative_period(case)
        if relative_period is None:
            continue
        relative_cases += 1
        gold_date = _gold_published_date(case)
        if gold_date is None:
            skipped_no_gold_date += 1
            continue
        checked += 1
        try:
            start, end = resolve_relative_date_range(
                relative_period, reference_date=planned_run_at.date()
            )
        except ValueError:
            stale.append(
                {
                    "case_id": case.id,
                    "gold_published_date": gold_date.isoformat(),
                    "relative_period": relative_period,
                    "error": "unsupported_relative_period",
                }
            )
            continue
        start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
        if not (start_d <= gold_date <= end_d):
            stale.append(
                {
                    "case_id": case.id,
                    "gold_published_date": gold_date.isoformat(),
                    "relative_period": relative_period,
                    "relative_range": f"{start}~{end}",
                }
            )
    return {
        "planned_run_at": planned_run_at.isoformat(),
        "recent_lookback_days": RECENT_LOOKBACK_DAYS,
        "n_cases": len(cases),
        "n_checked": checked,
        "n_skipped_non_relative": len(cases) - relative_cases,
        "n_skipped_no_gold_date": skipped_no_gold_date,
        "n_stale": len(stale),
        "stale_cases": stale,
        # 호출부 판단용 신호일 뿐 강제 중단이 아니다 — 실제 중단은 호출부 책임.
        "should_abort": len(stale) > 0,
    }


def document_recall_stats(
    cases: list[EvalCase], records: list[RunRecord], grades: list[CaseGrade], doc_type: str
) -> dict:
    """뉴스 또는 리포트 문서 검색의 Recall@K/Hit@1/MRR을 문서 ID 기준으로 계산한다.

    prompt.md 감사 원칙:
      - 뉴스/리포트 별도 계산(doc_type 인자로 호출부에서 분리)
      - gold 문서가 있는 문항만 분모에 포함(그 외 문항은 아예 세지 않음)
      - 구조화 조회 질문은 대상이 아님(gold_document_id 가 애초에 None)
      - Validator/Generation 실패를 retrieval 실패로 중복 계산하지 않음
        (다른 종목 혼입만 실패로 유지, 답변 삭제·같은 문서 다른 청크는 적중 처리)
      - 청크 ID 대신 부모 문서 ID로 비교, 같은 문서의 중복 청크는 1건으로 축약
      - Recall@K·Hit@1·MRR 모두 동일한 분모(n_eval) 사용
    """
    kind = "news" if doc_type == "news_event" else "report"
    n_eval = 0
    recall_hit = 0
    hit1_hit = 0
    rr_sum = 0.0
    missed_ids: list[str] = []
    missed_ids_stale_gold: list[str] = []
    missed_ids_retriever: list[str] = []

    for case, rec, grade in zip(cases, records, grades, strict=True):
        gold_doc = _gold_document_id_for_case(case)
        if gold_doc is None or not gold_doc.startswith(f"{kind}:"):
            continue
        # 문서 검색 이외의 원인(다른 종목 혼입)이 아니면, 답변 삭제·청크 형식
        # 차이로 인한 '실패처럼 보임'은 적중으로 인정한다(§4 원칙).
        ranking = document_ranking(rec)
        hit = gold_doc in ranking
        if not hit and grade.other_stock_sources:
            # 다른 종목이 섞인 검색 실패 — 그대로 미스로 남긴다(이미 hit=False).
            pass

        n_eval += 1
        if hit:
            recall_hit += 1
            rank = ranking.index(gold_doc) + 1
            rr_sum += 1.0 / rank
            if rank == 1:
                hit1_hit += 1
        else:
            missed_ids.append(case.id)
            # strict recall_hit/recall_at_k 는 그대로 두고(§4 "기존 strict 결과는
            # 보존한다"), 미스 케이스만 원인별로 부가 분류한다 — Retriever 실패
            # 집계 자체를 바꾸지 않는다.
            if gold_out_of_relative_range(case, rec):
                missed_ids_stale_gold.append(case.id)
            else:
                missed_ids_retriever.append(case.id)

    def ratio(h: int, t: int) -> float | None:
        return round(h / t, 4) if t else None

    return {
        "n_eval": n_eval,
        "recall_hit": recall_hit,
        "recall_at_k": ratio(recall_hit, n_eval),
        "hit_at_1": ratio(hit1_hit, n_eval),
        "mrr": round(rr_sum / n_eval, 4) if n_eval else None,
        "missed_case_ids": missed_ids,
        # §4 evaluation data issue 분류(부가 정보, strict 지표는 그대로).
        "missed_case_ids_stale_gold": missed_ids_stale_gold,
        "missed_case_ids_retriever_failure": missed_ids_retriever,
    }


def event_equivalent_recall_stats(
    cases: list[EvalCase],
    records: list[RunRecord],
    grades: list[CaseGrade],
    doc_type: str,
    approvals: dict[str, list[str]],
) -> dict:
    """§4B event-equivalent Recall: strict gold 문서가 아니어도, 사람이 승인한
    동일 사건 클러스터 중 하나를 반환했으면 적중으로 센다.

    approvals 는 {case_id: [승인된 대체 문서ID(예: "news:7222"), ...]} 형태로,
    반드시 사람이 직접 검토해 작성한 매핑만 넘겨야 한다(자동 승인 금지 — 이
    함수는 매핑의 출처를 검증하지 않으므로 호출부가 책임진다). strict
    document_recall_stats() 와 완전히 같은 분모(gold 문서가 있는 문항)를 쓰되,
    hit 판정에만 승인된 대체 ID 를 추가로 인정한다.
    """
    kind = "news" if doc_type == "news_event" else "report"
    n_eval = 0
    recall_hit = 0
    missed_ids: list[str] = []

    for case, rec, grade in zip(cases, records, grades, strict=True):
        gold_doc = _gold_document_id_for_case(case)
        if gold_doc is None or not gold_doc.startswith(f"{kind}:"):
            continue
        n_eval += 1
        ranking = document_ranking(rec)
        accepted_ids = {gold_doc, *(approvals.get(case.id) or [])}
        hit = bool(accepted_ids & set(ranking))
        if hit and not grade.other_stock_sources:
            recall_hit += 1
        elif not hit:
            missed_ids.append(case.id)
        else:
            # 다른 종목 혼입이 함께 있으면 대체 문서 적중이라도 실패로 남긴다.
            missed_ids.append(case.id)

    def ratio(h: int, t: int) -> float | None:
        return round(h / t, 4) if t else None

    return {
        "n_eval": n_eval,
        "recall_hit": recall_hit,
        "recall_at_k": ratio(recall_hit, n_eval),
        "missed_case_ids": missed_ids,
    }


def product_failure_stats(
    cases: list[EvalCase],
    records: list[RunRecord],
    grades: list[CaseGrade],
    doc_type: str,
) -> dict:
    """§4C product failure rate: 실제 제품이 고쳐야 할 실패만 골라 센다.

    strict 미스 중에서도 다음은 "제품 실패"로 보지 않는다(§4D 로 넘어감):
      - stale_gold(평가 데이터 문제, gold_out_of_relative_range)
    반대로 다음은 반드시 제품 실패로 남긴다:
      - 필수 Tool 자체를 안 부름(Tool 미호출)
      - 종목·기간 필터가 틀려서 놓침(다른 종목 혼입)
      - 검색 가능한 gold 를 실제로 놓침(그 외 순수 검색 미스)
    """
    kind = "news" if doc_type == "news_event" else "report"
    required_tool = "search_news" if kind == "news" else "search_research_reports"
    n_eval = 0
    failures = 0
    failed_ids: list[str] = []

    for case, rec, grade in zip(cases, records, grades, strict=True):
        gold_doc = _gold_document_id_for_case(case)
        if gold_doc is None or not gold_doc.startswith(f"{kind}:"):
            continue
        n_eval += 1
        used = {c["name"] for c in rec.tool_calls}
        tool_missing = required_tool not in used
        hit = gold_doc in document_ranking(rec)
        if tool_missing or grade.other_stock_sources or not hit:
            if not tool_missing and not grade.other_stock_sources and not hit:
                # 순수 검색 미스는 stale_gold(평가 데이터 문제)면 제품 실패에서 뺀다.
                if gold_out_of_relative_range(case, rec):
                    continue
            failures += 1
            failed_ids.append(case.id)

    return {
        "n_eval": n_eval,
        "failures": failures,
        "failure_rate": round(failures / n_eval, 4) if n_eval else None,
        "failed_case_ids": failed_ids,
    }


def report_page_accuracy(cases: list[EvalCase], records: list[RunRecord]) -> dict:
    """리포트 근거 페이지 정확도(문서 검색 지표와 별도 계산, §1 요구사항).

    gold 라벨의 page 가 있는 리포트 문항만 대상. record.sources 중
    research_report 타입에서 같은 page 를 반환했는지만 본다(문서 자체를
    맞혔는지는 document_recall_stats 가 이미 별도로 잰다).
    """
    total = 0
    ok = 0
    for case, rec in zip(cases, records, strict=True):
        for gs in case.gold_sources:
            if gs.source_type != "research_report" or not gs.page:
                continue
            total += 1
            if any(
                s.get("source_type") == "research_report" and s.get("page") == gs.page
                for s in rec.sources
            ):
                ok += 1
    return {"n_eval": total, "hit": ok, "page_accuracy": round(ok / total, 4) if total else None}


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
    # 자연어 판정을 LLM judge 로 했는지, 키워드 채점으로 폴백했는지 구분한다.
    # judge_used=False 면 judge 미주입이거나 호출 실패(judge_error 에 사유).
    judge_used: bool = False
    judge_error: str | None = None
    judge_grounded: bool | None = None  # 참고 지표(통과 조건에 넣지 않는다)
    judge_reason: str = ""

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


def grade_case(
    case: EvalCase,
    record: RunRecord,
    facts: Any = None,
    *,
    judge: Any = None,
) -> CaseGrade:
    """케이스 1건을 채점한다.

    facts(FactsService)를 주면 expected_financial 정답을 DB 에서 조회해 함께 채점한다.

    judge 를 주면 자연어 의미 판단(제외 조건 준수·답변 불가 처리)을 키워드 부분
    문자열 검사 대신 LLM judge 결과로 채점한다. Tool 호출·문서 ID·숫자·기간처럼
    객관적으로 검증 가능한 지표는 judge 와 무관하게 항상 코드로 채점한다.
    judge 는 `(case, record) -> JudgeVerdict` 를 반환하는 호출 가능 객체이며,
    호출 실패(verdict.ok=False)면 기존 키워드 채점으로 폴백한다.
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
        # 뉴스·리포트는 아래 문서 ID 기반 전용 지표에서 채점한다. 재색인 때 바뀌는
        # chunk UUID를 여기서 exact match 하면 같은 문서/사건도 오답이 된다.
        if gs.source_type in _DOC_SOURCE_TYPES:
            continue
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

    # --- 제외 조건·과도한 단정·답변 불가 처리 (자연어 의미 판단) ---
    # 키워드 부분 문자열 검사는 "그 단어가 나왔는지"만 보므로, 금지 주제를 오히려
    # 거절한 문장("매수 추천은 드리지 않습니다")이나 다른 맥락의 동일 단어
    # (자기주식 공시의 "주관 증권사")까지 위반으로 잡는다. judge 가 있으면
    # 의미 기준으로 판정하고, 없거나 호출 실패면 기존 키워드 검사로 폴백한다.
    verdict = judge(case, record) if judge is not None else None
    judged = verdict is not None and getattr(verdict, "ok", False)
    g.judge_used = judged
    if verdict is not None:
        g.judge_error = None if judged else getattr(verdict, "error", None)
        g.judge_grounded = getattr(verdict, "grounded", None) if judged else None
        g.judge_reason = getattr(verdict, "reason", "") if judged else ""

    if judged and verdict.exclusion_respected is not None:
        # judge 는 위반 여부만 알려주므로, 어떤 금지어가 문제였는지는 표기하지
        # 않는다(사람 검토용 근거는 verdict.reason 에 남는다).
        g.exclusion_violations = [] if verdict.exclusion_respected else list(case.forbidden_claims)
        if not verdict.exclusion_respected:
            g.notes.append(f"judge 제외조건 위반 판정: {verdict.reason}")
    else:
        g.exclusion_violations = [
            c for c in case.forbidden_claims if _claim_asserted(record.answer, c)
        ]

    g.overclaim = has_overclaim(record.answer)

    if not case.is_answerable:
        if judged and verdict.handled_correctly is not None:
            g.unanswerable_handled = verdict.handled_correctly
            if not verdict.handled_correctly:
                g.notes.append(f"judge 답변불가 처리 실패 판정: {verdict.reason}")
        else:
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


def load_event_equivalent_approvals(path: Any, cases: list[EvalCase]) -> dict[str, list[str]]:
    """§4B 사람 승인 매핑 파일을 {case_id: [approved_equivalent_doc_id, ...]} 로 로드한다.

    파일이 없으면 빈 dict(= event-equivalent 계산에서 strict 와 동일하게 처리).
    devset.json/holdout.json 이 아니다 — 그 둘은 이 함수가 건드리지 않는다.
    문서 종류(news/report)는 승인 파일 자체가 아니라 해당 case 의 strict gold
    문서 ID 접두어를 그대로 따른다(같은 문항 안에서 뉴스·리포트가 섞이지 않는다).
    """
    import json
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text("utf-8"))
    by_id = {c.id: c for c in cases}
    out: dict[str, list[str]] = {}
    for item in data.get("approvals", []):
        case_id = item["case_id"]
        case = by_id.get(case_id)
        if case is None:
            continue
        gold_doc = _gold_document_id_for_case(case)
        if gold_doc is None:
            continue
        kind = gold_doc.split(":", 1)[0]
        ids = item.get("approved_equivalent_cluster_ids", [])
        out[case_id] = [_normalize_doc_id(kind, i) for i in ids]
    return out


def aggregate(
    cases: list[EvalCase],
    records: list[RunRecord],
    grades: list[CaseGrade],
    *,
    event_equivalent_approvals_path: Any = None,
) -> dict:
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

        # 검색: 문서 검색(뉴스·리포트, 문서 ID 기준)과 구조화 조회(정확 행 조회)를
        # 나눠 집계한다(성격이 다른 실패다). 문서 검색은 document_recall_stats() 로
        # 뉴스/리포트 전용 함수(아래)에서 별도 계산하므로 여기서는 lookup·부수
        # 지표(타 종목 혼입)만 채운다.
        lookup_gold = [
            gs.source_id
            for gs in case.gold_sources
            if gs.source_id and gs.source_type in _LOOKUP_SOURCE_TYPES
        ]
        hits = set(g.gold_source_hits)
        if lookup_gold:
            # 구조화 조회는 순위가 아니라 '정확한 행을 집었는가'다.
            retr.lookup_total += len(lookup_gold)
            retr.lookup_hit += len([x for x in lookup_gold if x in hits])
        if g.other_stock_sources:
            retr.other_stock_cases += 1

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

    # 문서 검색(뉴스/리포트 분리, 문서 ID 기준)은 케이스 단위 개별 채점이 아니라
    # 뉴스/리포트 각각의 분모로 한 번에 계산한다(§1 감사 원칙 — 두 유형을 같은
    # recall_total 에 합산하지 않는다).
    retr.news_stats = document_recall_stats(cases, records, grades, "news_event")
    retr.report_stats = document_recall_stats(cases, records, grades, "research_report")
    retr.page_stats = report_page_accuracy(cases, records)

    # §4A/B/C: strict Recall(위 news_stats/report_stats, 삭제·숨김 없이 그대로 보존)과
    # 별도로 event-equivalent Recall·product failure rate 를 추가 계산한다.
    approvals = (
        load_event_equivalent_approvals(event_equivalent_approvals_path, cases)
        if event_equivalent_approvals_path is not None
        else {}
    )
    retr.news_event_equivalent = event_equivalent_recall_stats(
        cases, records, grades, "news_event", approvals
    )
    retr.report_event_equivalent = event_equivalent_recall_stats(
        cases, records, grades, "research_report", approvals
    )
    retr.news_product_failure = product_failure_stats(cases, records, grades, "news_event")
    retr.report_product_failure = product_failure_stats(cases, records, grades, "research_report")

    return {
        "n": len(grades),
        "agent": agent.as_dict(),
        "retrieval": retr.as_dict(),
        "numbers": nums.as_dict(),
        "answer": ans.as_dict(),
        "ops": ops.as_dict(),
    }

"""숫자·용어·혼합 질문 QA (Phase 4, SPEC §9·§11·§12).

QueryPlan(규칙 기반)으로 질문을 해석해:
- 정확 숫자는 SQL(FactsService)에서 조회하고,
- 공시 설명은 RAG(HybridRetriever)로 검색하고,
- 용어는 rag_terms 에서 조회한 뒤,
한 번의 Solar 호출로 합성한다. 숫자 출처와 설명 출처를 분리해 반환한다.

숫자 조회와 문서 검색은 병렬 실행한다. 특정 종목/항목 하드코딩 없음.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.core.config import Settings
from app.ml.generation import SolarGenerator
from app.rag.prompting import SYSTEM_PROMPT, build_sources, build_user_prompt
from app.rag.query_plan import build_query_plan
from app.rag.retrieval import HybridRetriever
from app.services.facts import FactsService, NumericFact
from app.services.rag_qa import validate_citations

# 한국어 주격/보조사 접미사(일반 규칙, 특정 용어 하드코딩 아님).
_KO_PARTICLES = ("이", "가", "은", "는", "란", "이란", "라는", "라고", "가요", "이가")
_TERM_PATTERN = re.compile(
    r"([A-Za-z가-힣0-9]+)\s*(?:이|가|은|는|란|이란)?\s*(?:뭐|뜻|정의|무슨|무엇)"
)


def _term_candidates(question: str) -> list[str]:
    """질문에서 용어 후보를 뽑는다. 원형 + 조사 접미사 제거형을 함께 반환."""
    m = _TERM_PATTERN.search(question)
    base = m.group(1) if m else question.strip()
    cands = [base]
    for p in _KO_PARTICLES:
        if base.endswith(p) and len(base) > len(p):
            cands.append(base[: -len(p)])
    # 중복 제거(순서 보존)
    return list(dict.fromkeys(cands))


# 자주 묻는 재무 항목 신호어 → account_nm (일반 매핑, 특정 종목 아님)
_ACCOUNT_KEYWORDS = {
    "매출": "매출액",
    "영업이익": "영업이익",
    "순이익": "당기순이익",
    "당기순이익": "당기순이익",
    "자산": "자산총계",
    "부채": "부채총계",
    "자본": "자본총계",
    "현금흐름": "영업활동현금흐름",
}


@dataclass
class FactsQaResult:
    answer: str
    sources: list[dict] = field(default_factory=list)  # 설명(문서) 출처
    numeric_sources: list[dict] = field(default_factory=list)  # 숫자 출처(분리)
    term: dict | None = None
    invalid_citations: list[int] = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    latency_ms: dict = field(default_factory=dict)


class FactsQaService:
    def __init__(
        self,
        retriever: HybridRetriever,
        facts: FactsService,
        generator: SolarGenerator,
        cfg: Settings,
    ) -> None:
        self._retriever = retriever
        self._facts = facts
        self._generator = generator
        self._cfg = cfg

    def _wanted_accounts(self, question: str) -> list[str]:
        found = [acc for kw, acc in _ACCOUNT_KEYWORDS.items() if kw in question]
        # 중복 제거(순서 보존)
        return list(dict.fromkeys(found))

    def _fetch_numeric(self, question: str, stock_code: str | None) -> list[NumericFact]:
        if not stock_code:
            return []
        accounts = self._wanted_accounts(question) or None
        return self._facts.get_financials(stock_code, account_names=accounts, limit=12)

    def _fetch_term(self, question: str) -> dict | None:
        """'X가 뭐야' 패턴에서 용어 후보 X 를 뽑아 조회한다.

        한국어 조사가 토큰에 붙는 경우(예: 'ADR이')를 대비해 원형 + 조사 제거형을
        후보로 함께 넘긴다. lookup_term 이 '모든 후보 정확일치 → 별칭 → 유사' 순으로 처리해
        조사 붙은 원형이 유사검색에서 엉뚱한 항목을 먼저 잡는 것을 방지한다.
        """
        return self._facts.lookup_term(_term_candidates(question))

    def _prepare(
        self,
        question: str,
        *,
        stock_code: str | None,
        context_source_id: str | None,
        current_stock_code: str | None,
    ) -> tuple[list[NumericFact], list, dict | None, dict, float]:
        """QueryPlan 판정 후 숫자(SQL)·문서(RAG)·용어를 병렬 조회한다.

        answer() 와 stream() 이 공유하는 사전조회 단계(로직 복제 방지).
        반환: (facts, chunks, term, plan_dict, retrieve_ms).
        """
        plan = build_query_plan(
            question,
            stock_code=stock_code,
            current_document_id=context_source_id,
            current_stock_code=current_stock_code,
        )
        eff_stock = plan.stock_code

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=3) as ex:
            fut_facts = (
                ex.submit(self._fetch_numeric, question, eff_stock)
                if plan.need_financials
                else None
            )
            fut_docs = (
                ex.submit(
                    self._retriever.search,
                    question,
                    stock_code=eff_stock,
                    source_type="news_event",
                    context_source_id=context_source_id,
                )
                if plan.need_documents
                else None
            )
            fut_term = ex.submit(self._fetch_term, question) if plan.need_terms else None

            facts = fut_facts.result() if fut_facts else []
            chunks = fut_docs.result() if fut_docs else []
            term = fut_term.result() if fut_term else None
        retrieve_ms = (time.perf_counter() - t0) * 1000

        plan_dict = {
            "stock_code": plan.stock_code,
            "need_financials": plan.need_financials,
            "need_documents": plan.need_documents,
            "need_terms": plan.need_terms,
            "need_correction": plan.need_correction,
        }
        return facts, chunks, term, plan_dict, retrieve_ms

    @staticmethod
    def _numeric_sources(facts: list[NumericFact]) -> list[dict]:
        return [
            {
                "label": f.label,
                "value": f.value,
                "unit": f.unit,
                "period": f.period,
                "basis": f.basis,
                "value_kind": f.value_kind,
                "source_type": f.source_type,
                "source_key": f.source_key,
            }
            for f in facts
        ]

    def answer(
        self,
        question: str,
        *,
        stock_code: str | None = None,
        context_source_id: str | None = None,
        current_stock_code: str | None = None,
    ) -> FactsQaResult:
        facts, chunks, term, plan_dict, retrieve_ms = self._prepare(
            question,
            stock_code=stock_code,
            context_source_id=context_source_id,
            current_stock_code=current_stock_code,
        )

        sources = build_sources(chunks)
        user_prompt = build_user_prompt(question, chunks, facts=facts, term=term)

        t1 = time.perf_counter()
        answer = self._generator.generate(SYSTEM_PROMPT, user_prompt)
        gen_ms = (time.perf_counter() - t1) * 1000

        return FactsQaResult(
            answer=answer,
            sources=sources,
            numeric_sources=self._numeric_sources(facts),
            term=term,
            invalid_citations=validate_citations(answer, len(sources)),
            plan=plan_dict,
            latency_ms={"retrieve_and_fetch": round(retrieve_ms), "generate": round(gen_ms)},
        )

    def stream(
        self,
        question: str,
        *,
        stock_code: str | None = None,
        context_source_id: str | None = None,
        current_stock_code: str | None = None,
    ) -> tuple[list[dict], list[dict], dict | None, Iterator[str]]:
        """(문서 출처, 숫자 출처, 용어, 토큰 이터레이터)를 반환한다.

        answer() 와 동일한 사전조회를 재사용하고, 생성만 토큰 스트리밍한다.
        라우트가 SSE 로 포장한다.
        """
        facts, chunks, term, _plan_dict, _ms = self._prepare(
            question,
            stock_code=stock_code,
            context_source_id=context_source_id,
            current_stock_code=current_stock_code,
        )
        sources = build_sources(chunks)
        user_prompt = build_user_prompt(question, chunks, facts=facts, term=term)
        return (
            sources,
            self._numeric_sources(facts),
            term,
            self._generator.stream(SYSTEM_PROMPT, user_prompt),
        )

"""RAG QA 서비스: 검색 → 프롬프트 → Solar 답변 → 인용 검증 (Phase 2).

- 답변에 등장한 [n] 인용 번호 중 실제 출처 범위를 벗어난 것을 제거/경고한다.
- sources 배열을 함께 반환한다.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from app.core.config import Settings
from app.ml.generation import SolarGenerator
from app.rag.prompting import SYSTEM_PROMPT, build_sources, build_user_prompt
from app.rag.retrieval import HybridRetriever, RetrievedChunk, SemanticRetriever

_CITATION = re.compile(r"\[(\d+)\]")


@dataclass
class QaResult:
    answer: str
    sources: list[dict]
    retrieved_chunk_ids: list[str]
    invalid_citations: list[int] = field(default_factory=list)
    latency_ms: dict = field(default_factory=dict)


def validate_citations(answer: str, source_count: int) -> list[int]:
    """답변에서 참조한 번호 중 [1..source_count] 범위를 벗어난 것을 반환한다."""

    used = {int(m) for m in _CITATION.findall(answer)}
    return sorted(n for n in used if n < 1 or n > source_count)


class RagQaService:
    def __init__(
        self,
        retriever: SemanticRetriever | HybridRetriever,
        generator: SolarGenerator,
        cfg: Settings,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._cfg = cfg

    def _retrieve(
        self, question: str, stock_code: str | None, context_source_id: str | None
    ) -> tuple[list[RetrievedChunk], float]:
        t0 = time.perf_counter()
        chunks = self._retriever.search(
            question,
            stock_code=stock_code,
            source_type="news_event",
            context_source_id=context_source_id,
        )
        return chunks, (time.perf_counter() - t0) * 1000

    def answer(
        self,
        question: str,
        *,
        stock_code: str | None = None,
        context_source_id: str | None = None,
    ) -> QaResult:
        chunks, retrieve_ms = self._retrieve(question, stock_code, context_source_id)
        sources = build_sources(chunks)
        user_prompt = build_user_prompt(question, chunks)

        t0 = time.perf_counter()
        answer = self._generator.generate(SYSTEM_PROMPT, user_prompt)
        gen_ms = (time.perf_counter() - t0) * 1000

        return QaResult(
            answer=answer,
            sources=sources,
            retrieved_chunk_ids=[c.chunk_id for c in chunks],
            invalid_citations=validate_citations(answer, len(sources)),
            latency_ms={"retrieve": round(retrieve_ms), "generate": round(gen_ms)},
        )

    def stream(
        self,
        question: str,
        *,
        stock_code: str | None = None,
        context_source_id: str | None = None,
    ) -> tuple[list[dict], Iterator[str]]:
        """(sources, 토큰 이터레이터)를 반환한다. 라우트가 SSE 로 포장한다."""

        chunks, _ = self._retrieve(question, stock_code, context_source_id)
        sources = build_sources(chunks)
        user_prompt = build_user_prompt(question, chunks)
        return sources, self._generator.stream(SYSTEM_PROMPT, user_prompt)

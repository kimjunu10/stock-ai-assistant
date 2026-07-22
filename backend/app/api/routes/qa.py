"""RAG question-answering API routes (Phase 2)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from functools import lru_cache

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.db.client import get_supabase_client
from app.ml.embeddings import UpstageEmbedder
from app.ml.generation import SolarGenerator
from app.rag.retrieval import HybridRetriever
from app.schemas.qa import QaRequest, QaResponse
from app.services.rag_qa import RagQaService, validate_citations

router = APIRouter(prefix="/qa", tags=["qa"])


@lru_cache(maxsize=1)
def get_qa_service() -> RagQaService:
    client = get_supabase_client()
    embedder = UpstageEmbedder(settings)
    retriever = HybridRetriever(client, settings, embedder)
    generator = SolarGenerator(settings)
    return RagQaService(retriever, generator, settings)


def _sse(event: str, data: dict | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("", response_model=QaResponse)
def ask(req: QaRequest) -> QaResponse:
    """비스트리밍 QA. 스트리밍은 아래 /qa/stream 를 사용한다."""

    service = get_qa_service()
    result = service.answer(
        req.question,
        stock_code=req.stock_code,
        context_source_id=req.context_source_id,
    )
    return QaResponse(
        answer=result.answer,
        sources=result.sources,
        invalid_citations=result.invalid_citations,
        latency_ms=result.latency_ms,
    )


@router.post("/stream")
def ask_stream(req: QaRequest) -> StreamingResponse:
    """SSE 스트리밍 QA. 첫 이벤트로 sources, 이후 token, 마지막에 done."""

    service = get_qa_service()
    sources, token_iter = service.stream(
        req.question,
        stock_code=req.stock_code,
        context_source_id=req.context_source_id,
    )

    def gen() -> Iterator[str]:
        yield _sse("sources", {"sources": sources})
        buffer: list[str] = []
        for token in token_iter:
            buffer.append(token)
            yield _sse("token", {"text": token})
        answer = "".join(buffer)
        invalid = validate_citations(answer, len(sources))
        yield _sse("done", {"invalid_citations": invalid})

    return StreamingResponse(gen(), media_type="text/event-stream")

"""Phase 2 RAG 순수 로직 단위 테스트(외부 호출 없음)."""

from __future__ import annotations

from app.rag.chunking import chunk_news_event
from app.rag.normalization import build_search_text, normalize_content
from app.rag.prompting import build_sources, build_user_prompt
from app.rag.retrieval import RetrievedChunk
from app.services.rag_qa import validate_citations


def test_normalize_content_preserves_numbers_and_units():
    text = "영업이익 1,234억원 &amp; 3.5%   증가\n\n\n\n다음"
    out = normalize_content(text)
    assert "1,234억원" in out
    assert "&" in out and "3.5%" in out
    assert "\n\n\n" not in out


def test_build_search_text_lowercases_english():
    assert "hbm" in build_search_text("SK하이닉스", "000660", "HBM 공급")


def test_short_event_single_chunk():
    chunks = chunk_news_event(
        summary_title="제목", easy_explanation="쉬운 설명.", factual_body="본문."
    )
    assert len(chunks) == 1
    assert chunks[0].chunk_order == 0
    assert chunks[0].value_kind == "news_interpretation"


def test_long_event_splits_max_three():
    chunks = chunk_news_event(
        summary_title="T", easy_explanation="E", factual_body="문단.\n\n" * 400
    )
    assert 1 < len(chunks) <= 3
    assert all(len(c.content) <= 1200 for c in chunks)


def test_empty_event_no_chunks():
    assert chunk_news_event(summary_title=None, easy_explanation=None, factual_body=None) == []


def _chunk(i: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"c{i}",
        document_id=f"d{i}",
        content=f"내용{i}",
        value_kind="news_interpretation",
        stock_code="005930",
        source_type="news_event",
        published_at="2026-07-22",
        source_pk=str(i),
        title=f"제목{i}",
        publisher="언론사",
        source_url="http://x",
        similarity=0.9 - i * 0.1,
    )


def test_build_sources_numbering_from_one():
    sources = build_sources([_chunk(0), _chunk(1)])
    assert [s["citation"] for s in sources] == [1, 2]


def test_build_user_prompt_numbers_context():
    prompt = build_user_prompt("질문?", [_chunk(0), _chunk(1)])
    assert "[1]" in prompt and "[2]" in prompt and "[질문]" in prompt


def test_validate_citations_flags_out_of_range():
    assert validate_citations("결론 [1] 근거 [2][4]", 2) == [4]
    assert validate_citations("근거 없음", 3) == []

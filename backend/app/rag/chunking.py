"""청킹 규칙 (SPEC §8.2 뉴스).

뉴스 사건:
- 기본: 사건 1개 = 청크 1개 (summary_title + easy_explanation + factual_body 결합)
- 1,200자 이하면 분할하지 않음
- 1,200자 초과면 문단 경계로 500~900자 분할, overlap 최대 100자
- 한 사건에서 최대 3개 청크
- 대표 기사 본문은 기본 검색에서 제외 (SPEC §8.2)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.rag.normalization import normalize_content

NEWS_CHUNKING_VERSION = "news_event_v1"
_MAX_SINGLE = 1200
_TARGET_MIN = 500
_TARGET_MAX = 900
_OVERLAP = 100
_MAX_CHUNKS = 3


@dataclass
class Chunk:
    chunk_order: int
    content: str
    value_kind: str = "news_interpretation"
    metadata: dict = field(default_factory=dict)


def _split_long(text: str) -> list[str]:
    """긴 텍스트를 문단 경계 우선으로 500~900자 조각으로 나눈다(overlap 최대 100자)."""

    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        candidate = f"{buf}\n\n{para}".strip() if buf else para
        if len(candidate) <= _TARGET_MAX:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            # overlap: 이전 조각 끝 일부를 다음 버퍼 앞에 붙임
            tail = buf[-_OVERLAP:]
            buf = f"{tail}\n\n{para}".strip()
        else:
            # 단일 문단이 너무 길면 강제로 잘라낸다
            for i in range(0, len(para), _TARGET_MAX - _OVERLAP):
                chunks.append(para[i : i + _TARGET_MAX])
            buf = ""
    if buf:
        chunks.append(buf)
    # 너무 짧은 마지막 조각은 앞과 병합
    merged: list[str] = []
    for c in chunks:
        if merged and len(c) < _TARGET_MIN and len(merged[-1]) + len(c) <= _MAX_SINGLE:
            merged[-1] = f"{merged[-1]}\n\n{c}"
        else:
            merged.append(c)
    return merged[:_MAX_CHUNKS]


def chunk_news_event(
    *, summary_title: str | None, easy_explanation: str | None, factual_body: str | None
) -> list[Chunk]:
    """뉴스 사건 하나를 청크 리스트로 만든다."""

    parts = [
        normalize_content(summary_title),
        normalize_content(easy_explanation),
        normalize_content(factual_body),
    ]
    combined = "\n\n".join(p for p in parts if p).strip()
    if not combined:
        return []

    if len(combined) <= _MAX_SINGLE:
        return [Chunk(chunk_order=0, content=combined)]

    pieces = _split_long(combined)
    return [Chunk(chunk_order=i, content=p) for i, p in enumerate(pieces)]

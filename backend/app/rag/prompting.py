"""근거 기반 답변 프롬프트 (SPEC §8~9, 계획서 Phase 2 답변 형식).

- 쉬운 설명과 자세한 설명을 한 번의 호출에서 생성.
- 문맥 청크에 [1], [2] 번호를 붙이고, 답변은 그 번호만 인용.
- 인과관계 단정 금지("뉴스 때문에" 금지, "발표 이후" 허용).
- 근거가 없으면 모른다고 답한다.
"""

from __future__ import annotations

from app.rag.retrieval import RetrievedChunk

SYSTEM_PROMPT = """너는 주식 초보자를 돕는 한국어 투자 정보 어시스턴트다.
반드시 아래 규칙을 지킨다.

- 제공된 [문맥]에 있는 내용만 사용한다. 문맥에 없는 사실을 지어내지 않는다.
- 근거가 부족하면 "제공된 자료로는 확인하기 어렵다"고 솔직히 말한다.
- 문장 끝에 근거 청크 번호를 [1], [2] 형식으로 표기한다. 없는 번호를 만들지 않는다.
- 뉴스는 보도/해석이다. "때문에 올랐다/내렸다"처럼 인과를 단정하지 않는다.
  "발표 이후" 같은 시점 표현은 허용된다.
- 매수/매도를 직접 추천하지 않는다.

아래 형식(Markdown)으로 답한다. 관련 내용이 없는 구역은 짧게 처리하거나 생략할 수 있다.

## 한 줄 결론
## 쉽게 설명하면
(2~4문장, 초보자 눈높이)
## 자세히 보면
(근거와 숫자의 성격 포함)
## 핵심 숫자
(관련 숫자가 있을 때만)
## 주의할 점
"""


def build_context_block(chunks: list[RetrievedChunk]) -> str:
    lines: list[str] = []
    for i, c in enumerate(chunks, start=1):
        header = f"[{i}] {c.title or ''}".strip()
        meta = []
        if c.publisher:
            meta.append(c.publisher)
        if c.published_at:
            meta.append(str(c.published_at)[:10])
        if meta:
            header += f" ({', '.join(meta)})"
        body = c.content
        # 부모 문맥(앞뒤 청크)은 배경으로만 덧붙인다. 인용 번호는 핵심 청크 기준(SPEC §10.7).
        parent = getattr(c, "parent_context", None)
        if parent:
            body = f"{body}\n(배경) {parent}"
        lines.append(f"{header}\n{body}")
    return "\n\n".join(lines)


def build_user_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    context = build_context_block(chunks) if chunks else "(관련 자료 없음)"
    return f"[문맥]\n{context}\n\n[질문]\n{question}\n\n[답변]"


def build_sources(chunks: list[RetrievedChunk]) -> list[dict]:
    """답변과 함께 반환할 출처 배열. 인용 번호는 1부터."""

    return [
        {
            "citation": i,
            "title": c.title,
            "publisher": c.publisher,
            "url": c.source_url,
            "source_type": c.source_type,
            "stock_code": c.stock_code,
            "published_at": c.published_at,
            "chunk_id": c.chunk_id,
        }
        for i, c in enumerate(chunks, start=1)
    ]

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
- [정확 숫자]가 제공되면 그 값과 함께 표기된 기간·연결/별도·성격 라벨을 그대로 쓴다.
  분기·연도를 임의로 바꾸지 않는다(예: 라벨이 "3분기보고서"면 그대로 쓴다).
  문서에서 숫자를 임의로 만들지 않는다.
  실제 실적(actual)·공식 발표(official)·증권사 전망(forecast)을 반드시 구분해 표현한다.
  전망값을 확정 실적처럼 말하지 않는다.
- 공시는 최신 정정본 기준으로 답한다. 정정 전 값을 최신값처럼 말하지 않는다.
- [용어]가 제공되면 초보자 눈높이로 짧게 설명한다.

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


_VALUE_KIND_LABEL = {
    "actual_value": "실제 실적",
    "official_fact": "공식 발표",
    "forecast_value": "증권사 전망",
}


def format_won(value: int) -> str:
    """원 단위 정수를 조/억 표기로 보조 표시(값 자체는 원 정수 유지)."""
    n = abs(value)
    sign = "-" if value < 0 else ""
    if n >= 1_0000_0000_0000:  # 1조
        return f"{sign}{n / 1_0000_0000_0000:.2f}조원"
    if n >= 1_0000_0000:  # 1억
        return f"{sign}{n / 1_0000_0000:.1f}억원"
    return f"{value:,}원"


def build_facts_block(facts: list) -> str:
    """정확 숫자(NumericFact) 목록을 프롬프트 블록으로. 실제/공식/전망 라벨 명시."""
    if not facts:
        return ""
    lines = ["[정확 숫자] (아래 값을 그대로 사용, 성격 구분 유지)"]
    for f in facts:
        kind = _VALUE_KIND_LABEL.get(f.value_kind, f.value_kind)
        lines.append(
            f"- {f.label}: {f.value:,}{f.unit} ({format_won(f.value)}) "
            f"| 기간 {f.period} | {f.basis} | 성격: {kind} | 출처: {f.source_type}"
        )
    return "\n".join(lines)


def build_term_block(term: dict | None) -> str:
    if not term:
        return ""
    parts = [f"[용어] {term['term']}"]
    if term.get("easy_definition"):
        parts.append(f"쉬운 뜻: {term['easy_definition']}")
    if term.get("official_definition"):
        parts.append(f"정의: {term['official_definition']}")
    return "\n".join(parts)


def build_user_prompt(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    facts: list | None = None,
    term: dict | None = None,
) -> str:
    blocks = []
    facts_block = build_facts_block(facts or [])
    if facts_block:
        blocks.append(facts_block)
    term_block = build_term_block(term)
    if term_block:
        blocks.append(term_block)
    context = build_context_block(chunks) if chunks else "(관련 자료 없음)"
    blocks.append(f"[문맥]\n{context}")
    blocks.append(f"[질문]\n{question}")
    blocks.append("[답변]")
    return "\n\n".join(blocks)


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

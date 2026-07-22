"""공통 텍스트 정규화 (SPEC §8.1).

- content(원본 인용용): 의미를 바꾸지 않는 최소 정리만.
- search_text(검색용): content 를 소문자화 등 검색 친화적으로 추가 가공.
- 숫자 쉼표, %/조원/억원/원/주/날짜 단위, 종목 코드는 보존한다.
"""

from __future__ import annotations

import re
import unicodedata

_MULTI_SPACE = re.compile(r"[ \t ]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
_HTML_ENTITY = re.compile(r"&(amp|lt|gt|quot|#39|nbsp);")
_ENTITY_MAP = {
    "amp": "&",
    "lt": "<",
    "gt": ">",
    "quot": '"',
    "#39": "'",
    "nbsp": " ",
}


def _unescape_entities(text: str) -> str:
    return _HTML_ENTITY.sub(lambda m: _ENTITY_MAP[m.group(1)], text)


def normalize_content(text: str | None) -> str:
    """원본 인용용 정규화. 의미를 바꾸지 않는다."""

    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _unescape_entities(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 각 줄의 좌우 공백 정리 + 줄 내부 연속 공백 축소
    lines = [_MULTI_SPACE.sub(" ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


def build_search_text(*parts: str | None) -> str:
    """검색용 텍스트: 여러 조각을 합치고 소문자화(영문)한다.

    종목명/코드/제목/출처/본문/별칭 등을 이어 붙이는 용도(SPEC §8.1).
    한글은 소문자 개념이 없어 그대로 유지된다.
    """

    joined = " ".join(normalize_content(p) for p in parts if p)
    joined = _MULTI_SPACE.sub(" ", joined.replace("\n", " ")).strip()
    return joined.lower()

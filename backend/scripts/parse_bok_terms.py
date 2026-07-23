"""한국은행 「경제금융용어 800선」 PDF 파서 — PyMuPDF 좌표 + 목차 기준 (Phase 4).

특정 용어별 예외처리·화이트리스트 없이, 문서 구조로 파싱한다.

기준 데이터:
- 목차(leader dots 페이지)에서 전체 용어명 + 표시페이지를 추출한다.
- 표시페이지 → 실제 PDF 페이지 오프셋(PAGE_OFFSET)으로 source_page 검증.

본문 파싱:
- PyMuPDF words 를 컬럼(x 중앙 기준 좌/우) → y → x 순으로 읽기 순서 재구성.
- 용어 제목 = 제목 폰트(TITLE_FONT_HINT, 큰 size) span. 목차 용어명 집합과 대조해 확정.
- 다음 제목 전까지를 official_definition 으로 결합(여러 페이지 이어붙임).
- "연관검색어" 이후 내용은 aliases 로 분리.
- 머리말·상단 용어표시·초성 표식·페이지번호·하단 문서명은 폰트/위치로 제거.
- term/english_name 분리는 제목 괄호에 영문/약어가 있을 때만.
- easy_definition 은 생성하지 않고 NULL.

PyMuPDF 는 파싱 전용(오프라인 스크립트)이므로 런타임 의존성에 넣지 않는다.
실행: uv run --with pymupdf python scripts/parse_bok_terms.py ...
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

PDF_PATH = Path(__file__).resolve().parents[1] / "docs" / "rag" / "2026_경제금융용어 800선.pdf"
SOURCE_NAME = "한국은행 경제금융용어 800선(2026)"

PAGE_OFFSET = 18  # 목차 표시페이지 + 18 = 실제 PDF 페이지(0-based: 표시1 → index18)
TOC_PAGE_RANGE = range(3, 17)  # leader-dots 목차 페이지(0-based)
BODY_START_INDEX = 18  # 본문 시작(0-based, 표시 p1)

# 폰트 신호(조사로 확인).
TITLE_FONT_HINT = "ExtraBold"  # 용어 제목: SUIT-ExtraBold, size>12
TITLE_MIN_SIZE = 12.0
# 제목 줄의 영문 약어는 별도 폰트(DIN-Bold, 큰 size)로 제목 괄호 안에 위치.
TITLE_ENG_FONT_HINT = "DIN-Bold"
RELATED_FONT_HINT = "Dotum"  # 연관검색어 라벨/관련어: KoPubDotum*, size 9.0~9.5
# 연관검색어 라벨(9.0)/관련어(9.5)만 잡는 size 창(window).
# 하한(8.7)으로 그래프 축라벨·각주(size 5~8)를 배제, 상한(9.6)으로 본문(10.5)·「」를 배제.
RELATED_SIZE_MIN = 8.7
RELATED_SIZE_MAX = 9.6
HEADER_FONT_HINT = "NanumSquare"  # 상단 머리말/초성
PAGENUM_FONT_HINT = "Din"  # 페이지 번호(Dinlig). 주의: 제목 약어는 'DIN-Bold'로 구분됨

_TOC_DOT_RE = re.compile(r"^(.*?)[·.\s]{3,}(\d{1,4})$")
_CHOSUNG_RE = re.compile(r"^[ㄱ-ㅎ]$")
_ENG_IN_PAREN_RE = re.compile(r"\(([^()]*[A-Za-z][^()]*)\)")
_RELATED_LABEL = "연관검색어"


@dataclass
class Term:
    term: str
    english_name: str | None  # 완전한 영문명만(약어는 aliases). GPT 지침 §1
    official_definition: str  # 원문 보존(노이즈만 정규화). GPT 지침 §4
    aliases: list[str] = field(default_factory=list)  # 약어·완전영문명·슬래시 구성어
    related_terms: list[str] = field(default_factory=list)  # 연관검색어(동의어 아님). §3
    search_text: str = ""  # 검색·임베딩용 정규화 문자열. §4,§6
    # 출처 메타(§5)
    source_name: str = "한국은행"
    source_title: str = "경제금융용어 800선"
    source_edition: str = "2026"
    source_page: int | None = None  # 책에 인쇄된 페이지(목차 표시페이지)
    pdf_page: int | None = None  # PDF 파일상 실제 페이지(1-based)
    easy_definition: None = None  # 생성 금지


def extract_toc(doc) -> list[tuple[str, int]]:
    """목차에서 (용어명, 표시페이지) 목록을 추출한다.

    긴 용어명이 2줄로 줄바꿈되며 생기는 '이어진 줄'(예: 'Adjustment Mechanism, CBAM)')은
    용어 시작 형태가 아니므로 제외한다. 특정 용어 하드코딩 없이 형태로 판정.
    """
    toc: list[tuple[str, int]] = []
    for pno in TOC_PAGE_RANGE:
        for line in doc[pno].get_text().split("\n"):
            m = _TOC_DOT_RE.match(line.strip())
            if not m:
                continue
            name, pg = m.group(1).strip(), int(m.group(2))
            if not name or len(name) > 40:
                continue
            # 노이즈 제외: 닫는 괄호로 시작(줄바꿈 잔재), 소문자/기호로 시작하는 이어진 줄.
            if name.startswith((")", "(", ",")):
                continue
            # 정상 용어명은 한글 또는 대문자 영문으로 시작한다.
            if not (name[0].isalpha() and (("가" <= name[0] <= "힣") or name[0].isupper())):
                continue
            toc.append((name, pg))
    return toc


def _ordered_spans(page) -> list[dict]:
    """페이지 span 을 2단 컬럼 읽기순서(좌 컬럼 위→아래, 우 컬럼 위→아래)로 정렬.

    각 span: {text, font, size, x0, y0}. 머리말/페이지번호/초성은 폰트로 제거.
    """
    mid = page.rect.width / 2
    spans = []
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            for s in line["spans"]:
                txt = s["text"]
                if not txt.strip():
                    continue
                font = s["font"]
                size = s["size"]
                # 노이즈 폰트 제거: 머리말(NanumSquare), 페이지번호(Dinlig).
                # 단, 제목 영문 약어(DIN-Bold)는 유지해야 하므로 정확히 'Dinlig'만 제거.
                if HEADER_FONT_HINT in font or "Dinlig" in font:
                    continue
                if _CHOSUNG_RE.match(txt.strip()):
                    continue
                # 그래프 축라벨 등 매우 작은 글자(size<7.5)는 정의/관련어 아님 → 제외.
                # 각주(size≈8.8)와 연관검색어(9.0~9.5)는 유지된다.
                if size < 7.5:
                    continue
                x0, y0 = s["bbox"][0], s["bbox"][1]
                is_title_font = (
                    TITLE_FONT_HINT in font or TITLE_ENG_FONT_HINT in font
                ) and size >= TITLE_MIN_SIZE
                # 제목은 페이지 폭 전체에 걸쳐 조판되므로(닫는 괄호가 우측 컬럼에 올 수 있음)
                # 컬럼 분리를 적용하지 않고 항상 좌측 컬럼(0)으로 묶어 같은 y줄에 정렬한다.
                col = 0 if (is_title_font or x0 < mid) else 1
                spans.append(
                    {"text": txt, "font": font, "size": size, "x0": x0, "y0": y0, "col": col}
                )
    # 같은 줄(y가 근접)은 한 줄로 묶이도록 y를 정수 라운딩(2pt 버킷).
    spans.sort(key=lambda s: (s["col"], round(s["y0"] / 2), s["x0"]))
    return spans


def _is_title(span: dict) -> bool:
    """용어 제목 span: 제목 폰트(SUIT-ExtraBold) 또는 제목 줄의 영문 약어(DIN-Bold)."""
    if span["size"] < TITLE_MIN_SIZE:
        return False
    return TITLE_FONT_HINT in span["font"] or TITLE_ENG_FONT_HINT in span["font"]


def _is_related(span: dict) -> bool:
    """연관검색어 라벨/관련어: Dotum 계열, size 8.7~9.6.

    - 하한(8.7): 그래프 축라벨·각주(size 5~8)를 배제.
    - 상한(9.6): 본문(10.5)·「」 인용부호를 배제.
    """
    return (
        RELATED_FONT_HINT in span["font"] and RELATED_SIZE_MIN <= span["size"] <= RELATED_SIZE_MAX
    )


def _split_term_english(raw_term: str) -> tuple[str, str | None]:
    """제목에서 (한글 용어명, 괄호 안 영문) 분리. 영문 없으면 (원문, None)."""
    m = _ENG_IN_PAREN_RE.search(raw_term)
    if m:
        return (raw_term[: m.start()].strip() or raw_term, m.group(1).strip())
    return (raw_term, None)


def _is_abbrev(eng: str) -> bool:
    """영문 표현이 '약어'인지 판정(GPT §1). 대문자 위주·짧은 단일 토큰이면 약어.

    특정 용어 하드코딩 없이 형태로만 판정한다.
    - 공백 없이 한 토큰이고, 대문자 비율이 높으면 약어(HDRI, ICO, DSR, COFIX 등).
    - 여러 단어면 완전한 영문명으로 본다(Supervisory College 등).
    """
    e = eng.strip()
    if not e:
        return False
    if " " in e:  # 여러 단어 = 완전명
        return False
    letters = [c for c in e if c.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(c.isupper() for c in letters) / len(letters)
    return upper_ratio >= 0.6  # 대문자 위주 단일 토큰 = 약어


def _parse_paren_english(inner: str) -> tuple[str | None, list[str]]:
    """괄호 안 영문에서 (완전명, [약어들]) 분리(GPT §1).

    - "PDI; Personal Disposable Income" → ("Personal Disposable Income", ["PDI"])
    - "Virtual Asset" → ("Virtual Asset", [])
    - "HDRI" → (None, ["HDRI"])
    - 한글 포함이면 영문명으로 취급하지 않음.
    """
    s = inner.strip()
    if not s or any("가" <= c <= "힣" for c in s):
        return (None, [])
    full: str | None = None
    abbrevs: list[str] = []
    # 세미콜론/콜론으로 약어와 완전명이 병기되는 관례.
    parts = [p.strip() for p in re.split(r"[;:]", s) if p.strip()]
    for p in parts:
        if _is_abbrev(p):
            abbrevs.append(p)
        elif full is None:
            full = p
    if full is None and len(parts) == 1 and not _is_abbrev(parts[0]):
        full = parts[0]
    return (full, abbrevs)


def _find_full_english_in_def(term_ko: str, definition: str) -> tuple[str | None, list[str]]:
    """정의 앞부분의 '{용어명}({영문})' 병기에서 (완전명, [약어]) 추출(GPT §1).

    용어명이 정의 앞부분(정의 시작 또는 초반)에 반복되고 그 직후 괄호에
    영문이 병기될 때만 인정한다. 아무 괄호나 잡지 않는다.
    """
    base = term_ko.split("/")[0].strip()
    head = definition[:250]
    if not base:
        return (None, [])
    pos = head.find(base + "(")
    if pos < 0:
        return (None, [])
    rest = head[pos + len(base) :]
    m = _ENG_IN_PAREN_RE.match(rest)
    if not m:
        return (None, [])
    return _parse_paren_english(m.group(1))


def _slash_parts(term_ko: str) -> list[str]:
    """슬래시 복합 용어의 구성 용어(GPT §2). '간접금융/직접금융' → [간접금융, 직접금융]."""
    if "/" in term_ko:
        return [p.strip() for p in term_ko.split("/") if p.strip()]
    return []


def _build_search_text(term: str, english: str | None, aliases: list[str], definition: str) -> str:
    """검색·임베딩용 정규화 문자열(GPT §4,§6). related_terms 는 제외."""
    parts = [term]
    if english:
        parts.append(english)
    parts.extend(aliases)
    parts.append(definition)
    joined = " ".join(p for p in parts if p)
    # ①②③ → 1. 2. 3. (검색용만; official_definition 은 원형 보존)
    circ = {"①": "1.", "②": "2.", "③": "3.", "④": "4.", "⑤": "5.", "⑥": "6.", "⑦": "7."}
    for k, v in circ.items():
        joined = joined.replace(k, v)
    return " ".join(joined.split()).lower()


def parse_terms(max_index: int | None = None) -> tuple[list[Term], list[tuple[str, int]]]:
    doc = fitz.open(str(PDF_PATH))
    toc = extract_toc(doc)

    # 목차 표시페이지 매핑(용어명 → 인쇄 페이지).
    # 공백 차이·괄호 유무·슬래시 구성어까지 정규화 키로 대응한다(특정 용어 하드코딩 없음).
    def _norm_key(s: str) -> str:
        return re.sub(r"\s", "", _split_term_english(s)[0])

    toc_page_by_name: dict[str, int] = {}
    for name, pg in toc:
        toc_page_by_name.setdefault(_norm_key(name), pg)

    last = doc.page_count - 1
    if max_index is not None:
        last = min(last, BODY_START_INDEX + max_index - 1)

    terms: list[Term] = []
    cur: Term | None = None
    raw_title: str = ""
    def_parts: list[str] = []
    related_parts: list[str] = []  # 연관검색어(=related_terms), aliases 아님(§3)
    in_related = False

    def flush():
        nonlocal cur, raw_title, def_parts, related_parts, in_related
        if cur:
            definition = " ".join(" ".join(def_parts).split()).strip()
            name, paren_eng = _split_term_english(raw_title)
            aliases: list[str] = []
            english_name: str | None = None
            # §1 영문명/약어 결정: 제목 괄호 우선, 없으면 정의 앞부분 병기.
            if paren_eng:
                full, abbrevs = _parse_paren_english(paren_eng)
                english_name = full
                aliases.extend(abbrevs)
            if english_name is None:
                full2, abbrevs2 = _find_full_english_in_def(name, definition)
                english_name = full2
                aliases.extend(abbrevs2)
            # §2 슬래시 구성어 → aliases
            aliases.extend(_slash_parts(name))

            # 제어문자·불릿(‌, \x07 등) 및 앞뒤 기호 정리(일반 규칙).
            def _clean(x: str) -> str:
                x = re.sub("[\u0000-\u001f\u200b-\u200f\ufeff]", "", x)
                return x.strip(" \u00b7*\u2022\t")

            aliases = list(dict.fromkeys(c for a in aliases if (c := _clean(a))))
            related = list(dict.fromkeys(c for r in related_parts if (c := _clean(r))))
            cur.term = name
            cur.english_name = english_name
            cur.official_definition = definition
            cur.aliases = aliases
            cur.related_terms = related
            # 인쇄 페이지(source_page) 결정:
            #  ① 목차 정규화 키 매핑, ② 슬래시 구성어 매핑,
            #  ③ 목차 표기≠본문 제목이라 매핑 실패 시 pdf_page-PAGE_OFFSET 역산.
            # 검증 결과 매핑된 775건 전부 source_page == pdf_page-PAGE_OFFSET 로 일치하므로
            # 역산은 목차 매핑과 동일 규칙이다(특정 용어 하드코딩 아님).
            sp = toc_page_by_name.get(_norm_key(name))
            if sp is None:
                for part in _slash_parts(name):
                    sp = toc_page_by_name.get(_norm_key(part))
                    if sp is not None:
                        break
            if sp is None and cur.pdf_page is not None:
                sp = cur.pdf_page - PAGE_OFFSET
            cur.source_page = sp
            cur.search_text = _build_search_text(name, english_name, aliases, definition)
            if definition:
                terms.append(cur)
        cur, raw_title, def_parts, related_parts, in_related = None, "", [], [], False

    def open_title(text: str, page_index: int):
        nonlocal cur, raw_title
        cur = Term(term=text, english_name=None, official_definition="", pdf_page=page_index + 1)
        raw_title = text

    for pno in range(BODY_START_INDEX, last + 1):
        spans = _ordered_spans(doc[pno])
        idx = 0
        while idx < len(spans):
            sp = spans[idx]
            txt = sp["text"].strip()
            if _is_title(sp):
                # 같은 줄(y 근접)의 연속 제목 span(본체+영문약어)을 x0 순으로 이어붙임.
                group = [sp]
                j = idx + 1
                while j < len(spans) and _is_title(spans[j]) and abs(spans[j]["y0"] - sp["y0"]) < 5:
                    group.append(spans[j])
                    j += 1
                # x0 순으로 이어붙이되, 영문 약어 폰트(DIN-Bold) 조각 사이엔 공백을 넣어
                # 'Supervisory'+'College' → 'Supervisory College' 로 복원.
                title = ""
                for g in sorted(group, key=lambda g: g["x0"]):
                    piece = g["text"].strip()
                    if title and TITLE_ENG_FONT_HINT in g["font"] and title[-1].isalpha():
                        title += " "
                    title += piece
                flush()
                open_title(title, pno)
                idx = j
                continue
            # '연관검색어' 라벨을 실제로 만났을 때만 related 수집을 시작한다.
            # (라벨 이전의 Dotum 수식 변수·각주는 related 로 새지 않고 정의 본문으로 간다.)
            if _is_related(sp) and txt == _RELATED_LABEL:
                in_related = True
                idx += 1
                continue
            # 일반 텍스트: 라벨 이후면 related, 아니면 정의 본문.
            if cur is not None:
                if in_related and _is_related(sp):
                    related_parts.extend(a.strip() for a in txt.split(",") if a.strip())
                elif not in_related:
                    def_parts.append(txt)
                # in_related 인데 Dotum 이 아닌 조각(다음 블록 잔재)은 무시.
            idx += 1
    flush()
    return terms, toc


def _pick_spread(terms: list[Term], k: int) -> list[Term]:
    """앞·중간·뒤 균등 + GPT §검증 요구 유형을 고르게 포함해 k개 선정."""
    if len(terms) <= k:
        return terms

    n = len(terms)

    def has_law(t: Term) -> bool:
        return "「" in t.official_definition or "법" in t.official_definition

    def has_num(t: Term) -> bool:
        return any(c in t.official_definition for c in "①②③%")

    # 유형 태그
    def tags(i: int) -> set[str]:
        t = terms[i]
        s = set()
        if not t.english_name and t.aliases:
            s.add("abbrev_only")
        if t.english_name:
            s.add("full_english")
        if "/" in t.term:
            s.add("slash")
        if len(t.related_terms) >= 2:
            s.add("multi_related")
        if has_law(t):
            s.add("law")
        if has_num(t):
            s.add("number")
        if len(t.official_definition) > 700:
            s.add("long_def")  # 페이지 넘김 가능성 높음
        return s

    want = {"abbrev_only", "full_english", "slash", "multi_related", "law", "number", "long_def"}
    picked: list[int] = []
    covered: set[str] = set()

    # 1) 각 요구 유형을 앞/중/뒤 구간에서 하나씩 확보
    thirds = [(0, n // 3), (n // 3, 2 * n // 3), (2 * n // 3, n)]
    for tag in want:
        for lo, hi in thirds:
            hit = next((i for i in range(lo, hi) if i not in picked and tag in tags(i)), None)
            if hit is not None:
                picked.append(hit)
                covered.add(tag)
                break

    # 2) 남은 자리는 앞·중간·뒤 균등 인덱스로 채움
    even = [round(i * (n - 1) / (k - 1)) for i in range(k)]
    for i in even:
        if len(picked) >= k:
            break
        if i not in picked:
            picked.append(i)
    picked = sorted(set(picked))[:k]
    return [terms[i] for i in picked]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--max-index", type=int, default=None, help="본문 파싱 최대 페이지 수(디버그)")
    args = ap.parse_args()

    terms, toc = parse_terms(max_index=args.max_index)
    print(f"목차 용어 수: {len(toc)}")
    print(f"본문 파싱 용어 수: {len(terms)}")
    if args.count:
        return 0

    picked = _pick_spread(terms, args.limit)
    payload = [asdict(t) for t in picked]
    print(f"대표 {len(picked)}개 선정(앞·중간·뒤 고르게).")
    if args.out:
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"저장: {args.out}")
    else:
        print(json.dumps(payload[:2], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

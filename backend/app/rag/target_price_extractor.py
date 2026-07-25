"""증권사 리포트 '현재 목표주가' 추출기 (prompt.md §3).

데이터 소스 우선순위:
  1. research_report_tables (구조화 표: '투자의견 및 목표주가 변동추이' 등)
  2. research_report_pages.plain_text (페이지 텍스트)
  3. (호출부) 판정 애매·표 손실 시 원본 PDF fallback

핵심 안전 규칙(하드코딩 회사/질문 없음, 일반 규칙만):
  - report_date 와 일치하거나 가장 직접 연결된 현재 목표주가 행만 사용한다.
  - 변동추이표에 여러 날짜가 있으면 report_date 와 일치하는 행만 현재값 후보.
  - report_date 일치 행이 없으면 문서의 명시적 현재 목표주가 영역을 찾는다.
  - 복수 후보 충돌 → ambiguous. 과거 행을 현재값으로 쓰지 않는다.
  - 가장 큰 수/가장 최근처럼 보이는 수/범위를 임의 선택하지 않는다.
  - 영업이익·매출·EPS·주가·시총 등을 목표주가로 오인하지 않는다(라벨 근접 요구).
  - 목표주가 표기 자체가 없으면 not_stated.

결과는 TargetPriceExtraction(상태 + 값 + 근거). 이 모듈은 DB/Storage 를 직접
건드리지 않는다(순수 로직). 조회·적재는 backfill 스크립트가 담당한다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

EXTRACTOR_VERSION = "tp-extract-1"

# 목표주가 라벨(값이 이 라벨에 근접해야 목표주가로 인정 — 매출/영업이익 오인 방지).
TP_LABEL_RE = re.compile(r"(목표\s*주\s*가|목표\s*가격|목표가|target\s*price|TP)", re.I)
# 원화 목표주가 금액: 콤마 포함(74,000 / 320,000) 형식만. 콤마 없는 4자리는 연도(2026)와
# 충돌하므로 배제한다. 목표주가는 실무상 천단위 콤마 표기가 지배적이라 안전하다.
WON_RE = re.compile(r"(\d{1,3}(?:,\d{3})+)\s*원?")
# 한글 '만원' 단위(48만원, 56만 원). 콤마 표기가 아닌 리포트 대비.
MAN_WON_RE = re.compile(r"(\d{1,4})\s*만\s*원?")
# 이력표 신호
HISTORY_HINT_RE = re.compile(r"(변동\s*추이|제시\s*일자|괴리율)")
# 날짜 토큰: 2026.05.04 / 2026-05-04 / 2026/05/04
DATE_RE = re.compile(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})")
# 목표주가로 쓰면 안 되는 라벨(같은 줄에 있으면 금액을 목표주가로 보지 않음).
# '주가'는 '목표주가'의 부분문자열이라 제외하고, '현재주가/현재가'만 별도로 막는다.
NON_TP_LABEL_RE = re.compile(
    r"(매출|영업이익|순이익|EPS|BPS|시가총액|시총|현재\s*주?가|배당|PER|PBR|ROE)", re.I
)

# 목표주가로 받아들일 값 범위(원). 한국 주식 목표가 상식선. 이 밖은 오인으로 간주.
_MIN_TP = 1_000
_MAX_TP = 5_000_000


@dataclass
class TargetPriceExtraction:
    status: str  # stated / not_stated / parse_failed / ambiguous
    value: int | None = None
    currency: str = "KRW"
    effective_date: date | None = None
    source_page: int | None = None
    source_chunk_id: str | None = None
    evidence_text: str | None = None
    candidates: list[dict] = field(default_factory=list)  # 감사용(충돌 후보들)
    reason: str = ""


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def _to_won(raw: str) -> int | None:
    n = raw.replace(",", "").strip()
    if not n.isdigit():
        return None
    v = int(n)
    return v if _MIN_TP <= v <= _MAX_TP else None


def _find_won_near_label(text: str) -> tuple[int, str] | None:
    """라벨 '뒤' 텍스트(text)에서 현재 목표주가 금액을 찾는다.

    콤마형(560,000원) 또는 만원형(48만원) 중 라벨에 가장 가까운 첫 금액을 쓴다.
    라벨과 그 금액 '사이'에 매출/이익/현재가 등 방해 라벨이 끼면 목표주가로 보지 않는다
    (금액 '뒤'에 오는 현재주가 등은 무관 — 사이 구간만 검사).
    """
    cand: list[tuple[int, int]] = []  # (start, value)
    for m in WON_RE.finditer(text):
        v = _to_won(m.group(1))
        if v is not None:
            cand.append((m.start(), v))
    for m in MAN_WON_RE.finditer(text):
        v = int(m.group(1)) * 10_000
        if _MIN_TP <= v <= _MAX_TP:
            cand.append((m.start(), v))
    if not cand:
        return None
    cand.sort(key=lambda z: z[0])
    start, value = cand[0]
    # 라벨(=text 시작)과 첫 금액 사이에 방해 라벨이 있으면 목표주가 아님
    if NON_TP_LABEL_RE.search(text[:start]):
        return None
    return value, start


def _parse_date(y: str, m: str, d: str) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def extract_from_history_table(
    headers: list[str],
    rows: list[list[str]],
    report_date: date | None,
) -> TargetPriceExtraction | None:
    """'투자의견 및 목표주가 변동추이' 형태의 구조화 표에서 현재 목표주가를 뽑는다.

    표는 (제시일자, 투자의견, 목표주가, ...) 행들의 집합이라고 가정하지 않고,
    각 행에서 날짜 토큰과 목표주가 후보를 함께 찾는다. report_date 와 일치하는
    날짜 행의 금액만 현재값 후보로 본다. 일치 행 없으면 None(호출부가 다음 소스로).
    """
    flat_header = " ".join(_nfc(h) for h in (headers or []))
    if not TP_LABEL_RE.search(flat_header) and not HISTORY_HINT_RE.search(flat_header):
        # 목표주가/변동추이 표가 아니면 이 함수 대상 아님
        if not any(TP_LABEL_RE.search(_nfc(" ".join(map(str, r)))) for r in (rows or [])):
            return None

    dated: list[tuple[date, int, str]] = []
    for r in rows or []:
        line = _nfc(" ".join(str(c) for c in r))
        dm = DATE_RE.search(line)
        if not dm:
            continue
        rd = _parse_date(*dm.groups())
        if rd is None:
            continue
        # 이 행의 금액 후보(목표주가 열). 라벨 오인 방지: 매출/이익 라벨 있는 행 제외
        if NON_TP_LABEL_RE.search(line):
            continue
        for wm in WON_RE.finditer(line):
            v = _to_won(wm.group(1))
            if v is not None:
                dated.append((rd, v, line[:120]))
                break
    if not dated:
        return None

    if report_date is not None:
        exact = [t for t in dated if t[0] == report_date]
        if len(exact) == 1:
            rd, v, ev = exact[0]
            return TargetPriceExtraction(
                status="stated", value=v, effective_date=rd, evidence_text=ev,
                reason="history_table:report_date_match",
            )
        if len(exact) > 1 and len({t[1] for t in exact}) > 1:
            return TargetPriceExtraction(
                status="ambiguous",
                candidates=[{"date": str(t[0]), "value": t[1]} for t in exact],
                reason="history_table:multiple_values_same_date",
            )
        if len(exact) > 1:
            rd, v, ev = exact[0]
            return TargetPriceExtraction(
                status="stated", value=v, effective_date=rd, evidence_text=ev,
                reason="history_table:report_date_match_dedup",
            )
    # report_date 일치 행 없음 → 이 소스로는 현재값 확정 불가(호출부가 페이지 텍스트 시도)
    return None


def extract_from_page_text(
    pages: list[dict],
    report_date: date | None,
) -> TargetPriceExtraction:
    """페이지 텍스트에서 현재 목표주가를 찾는다.

    pages: [{"page_number": int, "plain_text": str}] (앞 페이지 우선 정렬 가정).
    현재 목표주가 표기 영역(라벨+금액 근접)을 우선한다. 이력표만 있고 현재값이
    라벨로 명시되지 않으면 ambiguous. 라벨 자체가 없으면 not_stated.
    """
    saw_label = False
    saw_history = False
    for p in pages or []:
        txt = _nfc(p.get("plain_text") or "")
        if not txt:
            continue
        if HISTORY_HINT_RE.search(txt):
            saw_history = True
        for lm in TP_LABEL_RE.finditer(txt):
            saw_label = True
            # 라벨 '뒤' 40자에서 목표주가 금액을 찾는다(라벨 자체는 제외).
            window = txt[lm.end() : lm.end() + 40]
            found = _find_won_near_label(window)
            if found:
                v, _ = found
                return TargetPriceExtraction(
                    status="stated", value=v, source_page=p.get("page_number"),
                    effective_date=report_date,
                    evidence_text=txt[lm.start() : lm.end() + 40],
                    reason="page_text:label_adjacent",
                )
    if saw_label and saw_history:
        return TargetPriceExtraction(
            status="ambiguous", reason="page_text:history_without_clear_current"
        )
    if saw_label:
        return TargetPriceExtraction(
            status="parse_failed", reason="page_text:label_without_value"
        )
    return TargetPriceExtraction(status="not_stated", reason="page_text:no_label")


def extract_target_price(
    tables: list[dict],
    pages: list[dict],
    report_date: date | None,
) -> TargetPriceExtraction:
    """소스 우선순위대로 현재 목표주가를 판정한다(순수 로직).

    tables: [{"headers": [...], "rows": [[...]], "page_number": int}]
    pages:  [{"page_number": int, "plain_text": str}]
    """
    # 1) 구조화 변동추이표
    for t in tables or []:
        res = extract_from_history_table(
            t.get("headers") or [], t.get("rows") or [], report_date
        )
        if res is not None:
            if res.source_page is None:
                res.source_page = t.get("page_number")
            return res
    # 2) 페이지 텍스트
    return extract_from_page_text(pages, report_date)

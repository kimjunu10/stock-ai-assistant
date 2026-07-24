"""증권사 리포트 PDF 파서 (Phase 5, SPEC §8.4).

read-only 로 PDF 를 구조화한다(본문 페이지·표·A/E/F value_kind). DB·Storage·임베딩은
호출하지 않는다(적재는 scripts/load_research_reports.py 담당).

Step 1~3 드라이런에서 확정한 일반 규칙:
  1. 표 셀 소수점·콤마 정규화 + 키움류 병합 셀 재정렬(_normalize_cell / _resplit_merged)
  2. 서술형 텍스트의 표 오인 강등(_is_narrative_table)
  3. 스캔·차트 페이지 판정(parse_status / chart page)
  4. 다중 페이지 표 연결(continued_from_prev)
  5. source_page 오프셋 탐지 + pdf_page fallback

특정 증권사·파일명 하드코딩 없음. 정규식·좌표·폰트 일반 규칙만 사용.
PyMuPDF(fitz)는 런타임 의존성이 아니므로 import 는 함수 안에서 지연 로딩한다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

AEF_TOKEN_RE = re.compile(r"(?:[1-4]Q)?(20\d{2})\.?\s*([AEFP])(?![A-Za-z가-힣])")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
QUARTER_RE = re.compile(r"\b([1-4]Q)\s?(?:20)?\d{2}\b|\b(20\d{2})\s?([1-4]Q)\b")
UNIT_RE = re.compile(r"(십억원|백만원|억원|천원|백만달러|백만USD|원|달러|USD|%|배|주|천주|천대)")
GUIDANCE_RE = re.compile(r"(가이던스|guidance|회사\s*가이드|사측\s*전망)", re.I)
NUM_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|[-+]?\d+(?:\.\d+)?%?")
FOOTER_HINT_RE = re.compile(
    r"(Page\s*\d+|^\s*\d+\s*$|Compliance|본\s*자료|투자등급|Disclaimer)", re.I
)
PAGE_NO_RE = re.compile(r"^\s*(\d{1,3})\s*$")
# 병합 셀: '숫자들 ... 콤마들' 이 이어지는 형태(키움류)
MERGED_NUMS_RE = re.compile(r"^((?:\d+\s+)+)((?:,\s*)+)(.*)$")
OPINION_RE = re.compile(r"(매수|매도|중립|보유|Buy|Hold|Sell|Trading Buy|Outperform)", re.I)

# A/E/F → 토큰 단위 value_kind. P(잠정/예상)는 estimate.
AEF_TO_KIND = {"A": "actual", "E": "estimate", "F": "forecast", "P": "estimate"}
# 표(열 집합) 단위 value_kind: DB CHECK 는 actual/forecast/mixed/unknown 만 허용.
TABLE_VALUE_KINDS = ("actual", "forecast", "mixed", "unknown")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


# ── 규칙 1: 셀 정규화 + 병합 셀 재정렬 ───────────────────────────────────────
def _resplit_merged(cell: str) -> str | None:
    """'25358 27134 29304 29597 , , , ,' → '25,358 27,134 29,304 29,597' + 나머지.

    숫자들이 먼저 나오고 콤마들이 몰려 나오는 병합 셀에 한정한 일반 규칙.
    각 숫자에 천단위 콤마를 부여해 원문 형태로 되돌린다. 값은 보존한다.
    """
    c = " ".join((cell or "").split())
    m = MERGED_NUMS_RE.match(c)
    if not m:
        return None
    nums = m.group(1).split()
    if len(nums) < 2:  # 병합이 아니면 건드리지 않음
        return None
    fixed = []
    for n in nums:
        try:
            fixed.append(f"{int(n):,}")
        except ValueError:
            fixed.append(n)
    rest = m.group(3).strip()
    return (" ".join(fixed) + (" " + rest if rest else "")).strip()


def normalize_cell(cell: str) -> str:
    """분리된 소수점/콤마를 재조립하고, 병합 셀은 천단위 콤마로 재정렬한다."""
    c = " ".join((cell or "").split())
    remerged = _resplit_merged(c)
    if remerged is not None:
        c = remerged
    c = re.sub(r"(\d)\s+([.,%])", r"\1\2", c)  # '55 .' → '55.'
    c = re.sub(r"([.,])\s+(\d)", r"\1\2", c)  # ', 333' → ',333'
    return c


# ── 규칙 2: 서술형 표 강등 ───────────────────────────────────────────────────
def is_narrative_table(rows: list[list[str]]) -> bool:
    cells = [c for r in rows for c in r if c]
    if not cells:
        return True
    numeric = sum(1 for c in cells if NUM_RE.search(c))
    numeric_ratio = numeric / len(cells)
    longest = max((len(c) for c in cells), default=0)
    return numeric_ratio < 0.15 or longest > 120


def _header_row(rows: list[list[str]]) -> tuple[int, list[str]]:
    best, idx = -1, 0
    for i, r in enumerate(rows[:3]):
        score = sum(1 for c in r if c and (AEF_TOKEN_RE.search(c) or YEAR_RE.search(c)))
        if score > best:
            best, idx = score, i
    return idx, (rows[idx] if rows else [])


def classify_columns(header_cells: list[str]) -> tuple[list[str], list[str]]:
    """헤더 셀 → (연도/분기 토큰, 열별 토큰 value_kind).

    value_kind: actual/estimate/forecast/guidance/unknown.
    """
    year_headers: list[str] = []
    kinds: list[str] = []
    for cell in header_cells:
        c = cell or ""
        m = AEF_TOKEN_RE.search(c)
        if m:
            year_headers.append(m.group(0))
            kinds.append(AEF_TO_KIND.get(m.group(2), "unknown"))
        elif GUIDANCE_RE.search(c):
            year_headers.append(c[:12])
            kinds.append("guidance")
        elif YEAR_RE.search(c) or QUARTER_RE.search(c):
            ym = YEAR_RE.search(c)
            year_headers.append(ym.group(0) if ym else c[:8])
            kinds.append("unknown")
        else:
            kinds.append("unknown")
    return year_headers, kinds


def table_value_kind(col_kinds: list[str]) -> str:
    """열별 토큰 kind 집합 → 표 단위 value_kind(DB CHECK: actual/forecast/mixed/unknown).

    estimate/guidance 는 forecast 계열로 묶고, 실제와 전망이 섞이면 mixed.
    """
    present = set(col_kinds)
    has_actual = "actual" in present
    has_future = bool(present & {"estimate", "forecast", "guidance"})
    if has_actual and has_future:
        return "mixed"
    if has_actual:
        return "actual"
    if has_future:
        return "forecast"
    return "unknown"


def token_value_kind(token: str) -> str:
    """A/E/F 토큰 하나 → value_kind(actual/estimate/forecast/unknown). guidance 는 문맥이라 제외."""
    m = AEF_TOKEN_RE.search(token)
    if not m:
        return "unknown"
    return AEF_TO_KIND.get(m.group(2), "unknown")


def _units(flat: str) -> list[str]:
    found: list[str] = []
    for m in UNIT_RE.finditer(flat):
        if m.group(0) not in found:
            found.append(m.group(0))
    return found[:8]


@dataclass
class ParsedTable:
    page_number: int
    table_order: int
    title: str | None
    unit: str | None
    headers: list[str]
    rows: list[list[str]]
    value_kind: str  # actual/forecast/mixed/unknown (DB)
    col_value_kinds: list[str]  # 열별 세부(actual/estimate/forecast/guidance/unknown)
    year_headers: list[str]
    continued_from_prev: bool
    numbers_sampled: int
    numbers_matched_in_text: int


@dataclass
class ParsedPage:
    page_number: int  # 1-indexed pdf page
    pdf_page: int  # 0-indexed
    source_page: int | None
    plain_text: str
    body_blocks: int
    is_chart_page: bool


@dataclass
class ParsedReport:
    parse_status: str  # success/partial/failed
    page_count: int
    encrypted: bool
    title_guess: str | None
    investment_opinion: str | None
    source_page_offset: int | None
    pages: list[ParsedPage] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    aef_value_total: int = 0
    aef_value_kind_counts: dict = field(default_factory=dict)  # 토큰 단위 합(6,063 계열)
    numbers_checked: int = 0
    number_mismatches: int = 0
    scan_pages: int = 0
    chart_pages: int = 0


def _ordered_body_blocks(page) -> list[str]:
    w, h = page.rect.width, page.rect.height
    kept: list[tuple[int, float, str]] = []
    for b in page.get_text("blocks"):
        x0, y0, x1, y1, txt = b[0], b[1], b[2], b[3], b[4]
        t = " ".join((txt or "").split())
        if not t:
            continue
        in_margin = y0 < h * 0.06 or y1 > h * 0.94
        if in_margin and (FOOTER_HINT_RE.search(t) or len(t) < 25 or t.isdigit()):
            continue
        toks = t.split()
        if len(t) <= 12 and all(NUM_RE.fullmatch(tok) for tok in toks if tok):
            continue
        col = 0 if (x0 + x1) / 2 < w / 2 else 1
        kept.append((col, round(y0, 1), t))
    kept.sort(key=lambda z: (z[0], z[1]))
    return [t for _, _, t in kept]


def _title_guess(page) -> str | None:
    spans = []
    for blk in page.get_text("dict")["blocks"]:
        for line in blk.get("lines", []):
            for sp in line.get("spans", []):
                t = sp["text"].strip()
                if t and not NUM_RE.fullmatch(t) and len(t) > 1:
                    spans.append((sp["size"], sp["bbox"][1], t))
    if not spans:
        return None
    spans.sort(key=lambda z: (-z[0], z[1]))
    return " ".join(t for _, _, t in spans[:3])[:120]


def _detect_source_page_offset(doc) -> int | None:
    offsets: dict[int, int] = {}
    for i in range(min(doc.page_count, 8)):
        page = doc[i]
        h = page.rect.height
        for b in page.get_text("blocks"):
            y1, txt = b[3], b[4]
            if y1 < h * 0.90:
                continue
            m = PAGE_NO_RE.match((txt or "").strip())
            if m:
                printed = int(m.group(1))
                if 1 <= printed <= doc.page_count + 5:
                    offsets[i - printed] = offsets.get(i - printed, 0) + 1
    if not offsets:
        return None
    best_off, cnt = max(offsets.items(), key=lambda kv: kv[1])
    return best_off if cnt >= 2 else None


def parse_report(pdf_path: str) -> ParsedReport:
    """리포트 PDF 하나를 구조화한다(read-only). fitz 는 지연 import."""
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    try:
        encrypted = bool(doc.needs_pass or doc.is_encrypted)
        offset = _detect_source_page_offset(doc)
        rep = ParsedReport(
            parse_status="failed",
            page_count=doc.page_count,
            encrypted=encrypted,
            title_guess=None,
            investment_opinion=None,
            source_page_offset=offset,
        )
        vk_counts: dict[str, int] = {}
        total_chars = 0
        text_pages = 0
        prev_cols: int | None = None
        prev_had_header = False

        for i, page in enumerate(doc):
            page_no = i + 1
            text = page.get_text("text") or ""
            if len(text.strip()) > 40:
                text_pages += 1
            body = _ordered_body_blocks(page)
            total_chars += sum(len(b) for b in body)
            n_images = len(page.get_images(full=True))
            is_chart = len(body) < 3 and n_images >= 3 and sum(len(b) for b in body) < 80
            if is_chart:
                rep.chart_pages += 1

            src_page = (i - offset) if offset is not None else None
            rep.pages.append(
                ParsedPage(
                    page_number=page_no,
                    pdf_page=i,
                    source_page=src_page,
                    plain_text=text,
                    body_blocks=len(body),
                    is_chart_page=is_chart,
                )
            )

            if page_no == 1:
                rep.title_guess = _title_guess(page)
                om = OPINION_RE.search(text)
                if om:
                    rep.investment_opinion = om.group(0)
            elif rep.investment_opinion is None:
                om = OPINION_RE.search(text)
                if om:
                    rep.investment_opinion = om.group(0)

            # 토큰 단위 A/E/F 합(6,063 계열): 본문+표 텍스트 전체
            for m in AEF_TOKEN_RE.finditer(text):
                rep.aef_value_total += 1
                k = AEF_TO_KIND.get(m.group(2), "unknown")
                vk_counts[k] = vk_counts.get(k, 0) + 1

            # 표
            try:
                raw_tables = [t.extract() for t in page.find_tables().tables]
            except Exception:  # noqa: BLE001
                raw_tables = []
            order = 0
            for raw in raw_tables:
                rows = [
                    [normalize_cell(str(c)) if c is not None else "" for c in row] for row in raw
                ]
                if not rows or is_narrative_table(rows):
                    prev_cols, prev_had_header = None, False
                    continue
                n_cols = max((len(r) for r in rows), default=0)
                hidx, header = _header_row(rows)
                year_headers, col_kinds = classify_columns(header)
                has_header = bool(year_headers)
                continued = prev_cols == n_cols and prev_had_header and not has_header and hidx == 0
                flat = " ".join(c for r in rows for c in r if c)
                units = _units(flat)

                # 원문 대조: 콤마·공백을 무시하고 숫자값이 원문에 존재하는지 확인한다.
                # (표/원문 모두 천단위 콤마 유무가 제각각이라 콤마를 제거해 값 자체를 비교)
                text_digits = re.sub(r"[,\s]", "", text)
                sampled = matched = 0
                for r in rows:
                    for c in r:
                        for num in NUM_RE.findall(c or ""):
                            core = num.replace(",", "").replace(" ", "").rstrip("%")
                            if len(core) < 2:
                                continue
                            sampled += 1
                            if core in text_digits:
                                matched += 1
                            if sampled >= 30:
                                break
                        if sampled >= 30:
                            break
                    if sampled >= 30:
                        break
                rep.numbers_checked += sampled
                rep.number_mismatches += sampled - matched

                rep.tables.append(
                    ParsedTable(
                        page_number=page_no,
                        table_order=order,
                        title=None,
                        unit=units[0] if units else None,
                        headers=header,
                        rows=rows,
                        value_kind=table_value_kind(col_kinds),
                        col_value_kinds=col_kinds,
                        year_headers=year_headers,
                        continued_from_prev=continued,
                        numbers_sampled=sampled,
                        numbers_matched_in_text=matched,
                    )
                )
                order += 1
                prev_cols, prev_had_header = n_cols, has_header

        rep.aef_value_kind_counts = dict(sorted(vk_counts.items()))
        rep.scan_pages = rep.page_count - text_pages
        avg = total_chars / max(1, rep.page_count)
        if avg < 80 or text_pages == 0:
            rep.parse_status = "failed" if text_pages == 0 else "partial"
        elif rep.scan_pages > rep.page_count * 0.5:
            rep.parse_status = "partial"
        else:
            rep.parse_status = "success"
        return rep
    finally:
        doc.close()

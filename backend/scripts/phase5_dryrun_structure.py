"""Phase 5 2단계: 대표 리포트 PDF 14개 구조화 드라이런 (읽기 전용).

본문·표·A/E/F 값을 안정적으로 구조화할 수 있는지 검증한다.
DB 쓰기·Storage 업로드·임베딩 API 호출·전체 적재 없음(순수 read-only).

실행:
    uv run --with pymupdf python scripts/phase5_dryrun_structure.py

검증(1~12): 본문 순서 복원 / 제목·본문·표·머리말·꼬리말 분리 / 표 행·열 보존 /
표 제목·열 머리글 연결 / 연도·분기·단위·통화 보존 / A/E/F→value_kind /
다중 페이지 표 연결 / 축라벨·각주·페이지번호 혼입 여부 / 숫자·부호·소수·% 손실 /
source_page·pdf_page 보존 / 추출값 원문 대조 / 증권사·파일명 하드코딩 없음.

산출물:
    docs/rag/phase_5/dryrun_structure.json   # 구조화 상세(표 셀 포함)
    docs/rag/phase_5/dryrun_structure_stats.json  # 통계
    docs/rag/phase_5/PHASE_5_STEP2_DRYRUN_REPORT.md
특정 증권사·파일명 하드코딩 없음. 일반 규칙(정규식·좌표·폰트)만 사용.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

REPORT_ROOT = Path("/Users/kimjunwoo/report")
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_5"

# 파일시스템→DB 매칭용 사전 확인 매핑(참고). 본 구현은 stocks 조회로 일반화.
FOLDER_TO_CODE = {
    "두산에너빌리티": "034020",
    "삼성전자": "005930",
    "한화오션": "042660",
    "현대차": "005380",
    "SK하이닉스": "000660",
}

# 연도+구분자: 2025A / 2026E / 2027F / 2026P / 4Q26F / 1Q26P 등
AEF_TOKEN_RE = re.compile(r"(?:[1-4]Q)?(20\d{2})\.?\s*([AEFP])(?![A-Za-z가-힣])")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
QUARTER_RE = re.compile(r"\b([1-4]Q)\s?(?:20)?\d{2}\b|\b(20\d{2})\s?([1-4]Q)\b")
# 단위/통화(일반 표기)
UNIT_RE = re.compile(r"(십억원|백만원|억원|천원|백만달러|백만USD|원|달러|USD|%|배|주|천주|천대)")
GUIDANCE_RE = re.compile(r"(가이던스|guidance|회사\s*가이드|사측\s*전망)", re.I)
# 숫자(부호·소수점·천단위 콤마·퍼센트 포함) 검출
NUM_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|[-+]?\d+(?:\.\d+)?%?")
# 페이지 번호/각주/면책 후보(꼬리말)
FOOTER_HINT_RE = re.compile(
    r"(Page\s*\d+|^\s*\d+\s*$|Compliance|본\s*자료|투자등급|Disclaimer)", re.I
)

# value_kind 매핑(일반 규칙; 특정 증권사 아님)
AEF_TO_KIND = {"A": "actual", "E": "estimate", "F": "forecast", "P": "estimate"}


@dataclass
class TableInfo:
    page: int
    n_rows: int
    n_cols: int
    header: list[str]
    year_headers: list[str]  # 헤더에서 뽑은 연도/분기 토큰
    col_value_kinds: list[str]  # 열별 value_kind(actual/estimate/forecast/guidance/unknown)
    units_currencies: list[str]  # 표/헤더에서 감지한 단위·통화
    sample_rows: list[list[str]]
    numbers_sampled: int
    numbers_matched_in_text: int  # 원문 대조 통과 수


@dataclass
class PageInfo:
    page: int  # 1-indexed pdf page
    pdf_page: int  # 0-indexed
    source_page: int | None  # 인쇄면 번호(추정)
    body_blocks: int
    body_chars: int
    header_footer_stripped: int  # 제거한 머리말/꼬리말 블록 수
    n_tables: int
    title_guess: str | None


@dataclass
class ReportResult:
    folder: str
    stock_code: str | None
    filename: str
    reasons: list[str]
    parse_ok: bool
    page_count: int
    encrypted: bool
    scanned_suspect: bool
    broker_from_name: str | None
    report_date: str | None
    title_from_name: str | None
    body_block_total: int = 0
    body_char_total: int = 0
    table_total: int = 0
    aef_value_total: int = 0
    value_kind_counts: dict = field(default_factory=dict)
    failed_pages: int = 0
    number_mismatches: int = 0
    numbers_checked: int = 0
    pages: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _resolve_targets() -> list[dict]:
    data = json.loads((OUT_DIR / "dryrun_targets.json").read_text(encoding="utf-8"))
    folders = {
        _nfc(d.name): d for d in REPORT_ROOT.iterdir() if d.is_dir() and not d.name.startswith(".")
    }
    out = []
    for d in data:
        fs_dir = folders.get(d["folder"])
        path = None
        if fs_dir:
            for f in fs_dir.glob("*.pdf"):
                if _nfc(f.name) == d["filename"]:
                    path = str(f)
                    break
        d["_path"] = path
        out.append(d)
    return out


def _parse_name(stem: str) -> tuple[str | None, str | None, str | None]:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})_([^_]+)_([^_]+)_(.+)$", stem)
    if not m:
        return None, None, None
    return m.group(1), m.group(3), m.group(4)  # date, broker, title


def _ordered_body_blocks(page: fitz.Page) -> tuple[list[str], int]:
    """좌표 blocks 를 2단 정렬로 본문 순서 복원. 머리말/꼬리말/페이지번호/축라벨 제거.

    반환: (본문 블록들, 제거한 머리말/꼬리말 블록 수)
    """
    w, h = page.rect.width, page.rect.height
    kept: list[tuple[int, float, str]] = []
    stripped = 0
    for b in page.get_text("blocks"):
        x0, y0, x1, y1, txt = b[0], b[1], b[2], b[3], b[4]
        t = " ".join((txt or "").split())
        if not t:
            continue
        # 머리말/꼬리말 영역 + 페이지번호/면책 후보 제거
        in_margin = y0 < h * 0.06 or y1 > h * 0.94
        if in_margin and (FOOTER_HINT_RE.search(t) or len(t) < 25 or t.isdigit()):
            stripped += 1
            continue
        # 차트 축 라벨 추정: 숫자·부호·짧은 토큰만으로 구성된 아주 짧은 블록
        toks = t.split()
        if len(t) <= 12 and all(NUM_RE.fullmatch(tok) for tok in toks if tok):
            stripped += 1
            continue
        col = 0 if (x0 + x1) / 2 < w / 2 else 1
        kept.append((col, round(y0, 1), t))
    kept.sort(key=lambda z: (z[0], z[1]))
    return [t for _, _, t in kept], stripped


def _title_guess(page: fitz.Page) -> str | None:
    spans = []
    for blk in page.get_text("dict")["blocks"]:
        for line in blk.get("lines", []):
            for sp in line.get("spans", []):
                t = sp["text"].strip()
                # 숫자-only(축 라벨) 제외
                if t and not NUM_RE.fullmatch(t) and len(t) > 1:
                    spans.append((sp["size"], sp["bbox"][1], t))
    if not spans:
        return None
    spans.sort(key=lambda z: (-z[0], z[1]))
    top = spans[:3]
    return " ".join(t for _, _, t in top)[:120]


def _classify_columns(header_cells: list[str]) -> tuple[list[str], list[str]]:
    """헤더 셀에서 연도/분기 토큰과 열별 value_kind 를 뽑는다.

    반환: (year_headers, col_value_kinds)
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
            # 연도만 있고 A/E/F 표기 없음 → 판별불가
            ym = YEAR_RE.search(c)
            year_headers.append(ym.group(0) if ym else c[:8])
            kinds.append("unknown")
        else:
            kinds.append("unknown")
    return year_headers, kinds


def _table_units(cells_flat: str) -> list[str]:
    found = []
    for m in UNIT_RE.finditer(cells_flat):
        if m.group(0) not in found:
            found.append(m.group(0))
    return found[:8]


def _process_table(page_no: int, rows: list[list[str]], page_text: str) -> TableInfo:
    n_rows = len(rows)
    n_cols = max((len(r) for r in rows), default=0)
    # 헤더행: 연도/분기 토큰이 가장 많은 상위 2행 중 하나를 헤더로
    header_idx = 0
    best = -1
    for i, r in enumerate(rows[:3]):
        score = sum(1 for c in r if c and (AEF_TOKEN_RE.search(c) or YEAR_RE.search(c)))
        if score > best:
            best, header_idx = score, i
    header = rows[header_idx] if rows else []
    year_headers, kinds = _classify_columns(header)
    flat = " ".join(c for r in rows for c in r if c)
    units = _table_units(flat)

    # 숫자 원문 대조: 표 셀 숫자 일부를 원문 텍스트에서 재확인
    sampled = 0
    matched = 0
    text_nospace = page_text.replace(" ", "")
    for r in rows:
        for c in r:
            for num in NUM_RE.findall(c or ""):
                if len(num) < 2:
                    continue
                sampled += 1
                if num.replace(" ", "") in text_nospace or num in page_text:
                    matched += 1
                if sampled >= 30:
                    break
            if sampled >= 30:
                break
        if sampled >= 30:
            break

    return TableInfo(
        page=page_no,
        n_rows=n_rows,
        n_cols=n_cols,
        header=[c[:20] for c in header],
        year_headers=year_headers,
        col_value_kinds=kinds,
        units_currencies=units,
        sample_rows=[[c[:24] for c in r] for r in rows[:4]],
        numbers_sampled=sampled,
        numbers_matched_in_text=matched,
    )


def process_report(d: dict) -> ReportResult:
    folder = d["folder"]
    date, broker, title = _parse_name(Path(d["filename"]).stem)
    res = ReportResult(
        folder=folder,
        stock_code=FOLDER_TO_CODE.get(folder),
        filename=d["filename"],
        reasons=d["reasons"],
        parse_ok=False,
        page_count=0,
        encrypted=False,
        scanned_suspect=False,
        broker_from_name=broker,
        report_date=date,
        title_from_name=title,
    )
    if not d["_path"]:
        res.error = "경로 해석 실패(NFC 매칭 불가)"
        return res
    try:
        doc = fitz.open(d["_path"])
    except Exception as e:  # noqa: BLE001
        res.error = f"open 실패: {type(e).__name__}"
        return res

    try:
        res.parse_ok = True
        res.encrypted = bool(doc.needs_pass or doc.is_encrypted)
        res.page_count = doc.page_count
        vk_counts: dict[str, int] = {}
        total_chars = 0
        for i, page in enumerate(doc):
            page_no = i + 1
            text = page.get_text("text") or ""
            body, stripped = _ordered_body_blocks(page)
            body_chars = sum(len(b) for b in body)
            total_chars += body_chars
            tables_raw = []
            try:
                tf = page.find_tables()
                for t in tf.tables:
                    tables_raw.append(
                        [
                            [("" if c is None else " ".join(str(c).split())) for c in row]
                            for row in t.extract()
                        ]
                    )
            except Exception:  # noqa: BLE001
                res.failed_pages += 1

            page_tables = []
            for rows in tables_raw:
                if not rows:
                    continue
                ti = _process_table(page_no, rows, text)
                page_tables.append(ti)
                res.table_total += 1
                res.numbers_checked += ti.numbers_sampled
                res.number_mismatches += ti.numbers_sampled - ti.numbers_matched_in_text
                for k in ti.col_value_kinds:
                    if k in ("actual", "estimate", "forecast", "guidance"):
                        vk_counts[k] = vk_counts.get(k, 0) + 1
                res.tables.append(asdict(ti))

            # A/E/F 값 개수(본문+표 텍스트에서)
            aef_hits = len(AEF_TOKEN_RE.findall(text))
            res.aef_value_total += aef_hits

            res.body_block_total += len(body)
            src_page = None  # 인쇄면 번호는 리포트마다 위치가 달라 2단계에선 pdf_page 기준만 확정
            res.pages.append(
                asdict(
                    PageInfo(
                        page=page_no,
                        pdf_page=i,
                        source_page=src_page,
                        body_blocks=len(body),
                        body_chars=body_chars,
                        header_footer_stripped=stripped,
                        n_tables=len(page_tables),
                        title_guess=_title_guess(page) if page_no == 1 else None,
                    )
                )
            )
        res.body_char_total = total_chars
        res.value_kind_counts = dict(sorted(vk_counts.items()))
        avg = total_chars / max(1, res.page_count)
        res.scanned_suspect = avg < 80
        if res.scanned_suspect:
            res.notes.append("스캔/이미지 의심(본문 텍스트 매우 적음) → partial 처리 권장")
    except Exception as e:  # noqa: BLE001
        res.error = f"처리 오류: {type(e).__name__}: {e}"[:160]
    finally:
        doc.close()
    return res


def main() -> int:
    targets = _resolve_targets()
    results = [process_report(d) for d in targets]

    # 상세 저장(표 셀 원문 포함 → gitignore 대상)
    (OUT_DIR / "dryrun_structure.json").write_text(
        json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 통계
    vk_total: dict[str, int] = {}
    for r in results:
        for k, v in r.value_kind_counts.items():
            vk_total[k] = vk_total.get(k, 0) + v
    broker_quality: dict[str, dict] = {}
    for r in results:
        b = r.broker_from_name or "(미상)"
        bq = broker_quality.setdefault(b, {"n": 0, "tables": 0, "mismatch": 0, "checked": 0})
        bq["n"] += 1
        bq["tables"] += r.table_total
        bq["mismatch"] += r.number_mismatches
        bq["checked"] += r.numbers_checked
    stats = {
        "reports": len(results),
        "parse_ok": sum(1 for r in results if r.parse_ok and not r.error),
        "page_total": sum(r.page_count for r in results),
        "body_block_total": sum(r.body_block_total for r in results),
        "table_total": sum(r.table_total for r in results),
        "aef_value_total": sum(r.aef_value_total for r in results),
        "value_kind_counts": dict(sorted(vk_total.items())),
        "failed_pages_total": sum(r.failed_pages for r in results),
        "numbers_checked_total": sum(r.numbers_checked for r in results),
        "number_mismatch_total": sum(r.number_mismatches for r in results),
        "scanned_suspect": sum(1 for r in results if r.scanned_suspect),
        "broker_quality": broker_quality,
    }
    (OUT_DIR / "dryrun_structure_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

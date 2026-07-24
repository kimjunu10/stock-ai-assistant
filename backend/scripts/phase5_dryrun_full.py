"""Phase 5 3단계 사전: DB 적재 전 전체 244개 리포트 PDF 드라이런 (읽기 전용).

Step 2 보고서의 5개 일반 규칙을 반영한다.
  1. 표 셀 소수점·콤마 정규화
  2. 서술형 텍스트의 표 오인 강등
  3. 스캔·차트 페이지 partial/제외 정책
  4. 다중 페이지 표 연결
  5. source_page 오프셋 탐지 및 pdf_page fallback

DB 쓰기·Storage 업로드·임베딩 API 호출·원본 수정 없음(순수 read-only).

실행:
    uv run --with pymupdf python scripts/phase5_dryrun_full.py

산출물:
    docs/rag/phase_5/full_dryrun_stats.json   # 집계(원문 텍스트 없음 → 추적)
    docs/rag/phase_5/full_dryrun_detail.json  # 파일별 상세(제목 등 소량 원문 → gitignore)
특정 증권사·파일명 하드코딩 없음. 정규식·좌표·폰트 일반 규칙만 사용.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

REPORT_ROOT = Path("/Users/kimjunwoo/report")
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_5"

FOLDER_TO_CODE = {
    "두산에너빌리티": "034020",
    "삼성전자": "005930",
    "한화오션": "042660",
    "현대차": "005380",
    "SK하이닉스": "000660",
}

AEF_TOKEN_RE = re.compile(r"(?:[1-4]Q)?(20\d{2})\.?\s*([AEFP])(?![A-Za-z가-힣])")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
QUARTER_RE = re.compile(r"\b([1-4]Q)\s?(?:20)?\d{2}\b|\b(20\d{2})\s?([1-4]Q)\b")
UNIT_RE = re.compile(r"(십억원|백만원|억원|천원|백만달러|백만USD|원|달러|USD|%|배|주|천주|천대)")
GUIDANCE_RE = re.compile(r"(가이던스|guidance|회사\s*가이드|사측\s*전망)", re.I)
NUM_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|[-+]?\d+(?:\.\d+)?%?")
FOOTER_HINT_RE = re.compile(
    r"(Page\s*\d+|^\s*\d+\s*$|Compliance|본\s*자료|투자등급|Disclaimer)", re.I
)
# source_page(인쇄면) 탐지용: 꼬리말 영역의 단독/짧은 페이지번호
PAGE_NO_RE = re.compile(r"^\s*(\d{1,3})\s*$")

AEF_TO_KIND = {"A": "actual", "E": "estimate", "F": "forecast", "P": "estimate"}


# ── 규칙 1: 표 셀 소수점·콤마 정규화 ────────────────────────────────────────
def _normalize_cell(cell: str) -> str:
    """PyMuPDF 표 추출에서 분리된 소수점/천단위 콤마를 원문 형태로 재조립한다.

    예) '55 .' → '55.', '333614 ,' → '333614,', '3.5 %' → '3.5%'
    숫자 뒤 공백 + (.,%) 를 붙이고, 콤마+공백+숫자를 붙여 원문 대조율을 높인다.
    """
    c = " ".join((cell or "").split())
    c = re.sub(r"(\d)\s+([.,%])", r"\1\2", c)  # 55 . -> 55.
    c = re.sub(r"([.,])\s+(\d)", r"\1\2", c)  # , 333 -> ,333
    return c


# ── 규칙 2: 서술형 텍스트의 표 오인 강등 ─────────────────────────────────────
def _is_narrative_table(rows: list[list[str]]) -> bool:
    """숫자 셀 비율이 낮거나 한 셀 길이가 매우 길면 서술형 → 표에서 강등."""
    cells = [c for r in rows for c in r if c]
    if not cells:
        return True
    numeric = sum(1 for c in cells if NUM_RE.search(c))
    numeric_ratio = numeric / len(cells)
    longest = max((len(c) for c in cells), default=0)
    return numeric_ratio < 0.15 or longest > 120


@dataclass
class ReportResult:
    folder: str
    stock_code: str | None
    filename: str
    file_hash: str
    parse_status: str  # success / partial / failed
    page_count: int
    encrypted: bool
    broker_from_name: str | None
    report_date: str | None
    title_from_name: str | None
    title_guess: str | None = None
    body_block_total: int = 0
    body_char_total: int = 0
    table_total: int = 0
    tables_with_units: int = 0
    narrative_demoted: int = 0  # 규칙 2
    merged_tables: int = 0  # 규칙 4
    chart_pages: int = 0  # 규칙 3
    scan_pages: int = 0  # 규칙 3
    aef_value_total: int = 0
    value_kind_counts: dict = field(default_factory=dict)
    failed_pages: int = 0
    numbers_checked: int = 0
    number_mismatches: int = 0
    source_page_detected: bool = False  # 규칙 5
    source_page_offset: int | None = None
    est_body_chunks: int = 0
    est_table_rows: int = 0
    dup_of: str | None = None
    error: str | None = None


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _file_hash(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_name(stem: str) -> tuple[str | None, str | None, str | None]:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})_([^_]+)_([^_]+)_(.+)$", stem)
    if not m:
        return None, None, None
    return m.group(1), m.group(3), m.group(4)


def _ordered_body_blocks(page: fitz.Page) -> tuple[list[str], int]:
    w, h = page.rect.width, page.rect.height
    kept: list[tuple[int, float, str]] = []
    stripped = 0
    for b in page.get_text("blocks"):
        x0, y0, x1, y1, txt = b[0], b[1], b[2], b[3], b[4]
        t = " ".join((txt or "").split())
        if not t:
            continue
        in_margin = y0 < h * 0.06 or y1 > h * 0.94
        if in_margin and (FOOTER_HINT_RE.search(t) or len(t) < 25 or t.isdigit()):
            stripped += 1
            continue
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
                if t and not NUM_RE.fullmatch(t) and len(t) > 1:
                    spans.append((sp["size"], sp["bbox"][1], t))
    if not spans:
        return None
    spans.sort(key=lambda z: (-z[0], z[1]))
    return " ".join(t for _, _, t in spans[:3])[:120]


def _classify_columns(header_cells: list[str]) -> tuple[list[str], list[str]]:
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


def _table_units(flat: str) -> list[str]:
    found: list[str] = []
    for m in UNIT_RE.finditer(flat):
        if m.group(0) not in found:
            found.append(m.group(0))
    return found[:8]


def _header_row(rows: list[list[str]]) -> tuple[int, list[str]]:
    best, idx = -1, 0
    for i, r in enumerate(rows[:3]):
        score = sum(1 for c in r if c and (AEF_TOKEN_RE.search(c) or YEAR_RE.search(c)))
        if score > best:
            best, idx = score, i
    return idx, (rows[idx] if rows else [])


def _detect_source_page_offset(doc: fitz.Document) -> int | None:
    """규칙 5: 꼬리말 영역의 페이지 번호로 pdf_page↔source_page 오프셋을 탐지.

    여러 페이지에서 (pdf_index - 인쇄면번호) 가 일관되면 그 오프셋을 채택.
    실패하면 None (호출부에서 pdf_page fallback).
    """
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
                    off = i - printed
                    offsets[off] = offsets.get(off, 0) + 1
    if not offsets:
        return None
    best_off, cnt = max(offsets.items(), key=lambda kv: kv[1])
    return best_off if cnt >= 2 else None


def process_report(path: Path, folder: str) -> ReportResult:
    date, broker, title = _parse_name(path.stem)
    res = ReportResult(
        folder=folder,
        stock_code=FOLDER_TO_CODE.get(folder),
        filename=_nfc(path.name),
        file_hash="",
        parse_status="failed",
        page_count=0,
        encrypted=False,
        broker_from_name=broker,
        report_date=date,
        title_from_name=title,
    )
    try:
        res.file_hash = _file_hash(path)
    except Exception as e:  # noqa: BLE001
        res.error = f"hash 실패: {type(e).__name__}"
        return res
    try:
        doc = fitz.open(path)
    except Exception as e:  # noqa: BLE001
        res.error = f"open 실패: {type(e).__name__}"
        return res

    try:
        res.encrypted = bool(doc.needs_pass or doc.is_encrypted)
        res.page_count = doc.page_count
        vk: dict[str, int] = {}
        total_chars = 0

        off = _detect_source_page_offset(doc)
        res.source_page_detected = off is not None
        res.source_page_offset = off

        prev_cols: int | None = None
        prev_had_header = False
        for i, page in enumerate(doc):
            page_no = i + 1
            text = page.get_text("text") or ""
            body, _stripped = _ordered_body_blocks(page)
            body_chars = sum(len(b) for b in body)
            total_chars += body_chars
            res.body_block_total += len(body)
            res.est_body_chunks += max(1, body_chars // 1000) if body_chars else 0

            # 규칙 3: 페이지 유형(스캔/차트) 판정
            n_images = len(page.get_images(full=True))
            if len(body) < 3 and n_images >= 3 and body_chars < 80:
                res.chart_pages += 1

            tables_raw = []
            try:
                for t in page.find_tables().tables:
                    tables_raw.append(
                        [
                            [_normalize_cell(str(c)) if c is not None else "" for c in row]
                            for row in t.extract()
                        ]
                    )
            except Exception:  # noqa: BLE001
                res.failed_pages += 1

            for rows in tables_raw:
                if not rows:
                    continue
                # 규칙 2: 서술형 표 강등
                if _is_narrative_table(rows):
                    res.narrative_demoted += 1
                    prev_cols, prev_had_header = None, False
                    continue
                n_cols = max((len(r) for r in rows), default=0)
                hidx, header = _header_row(rows)
                year_headers, kinds = _classify_columns(header)
                has_header = bool(year_headers)
                flat = " ".join(c for r in rows for c in r if c)
                if _table_units(flat):
                    res.tables_with_units += 1

                # 규칙 4: 다중 페이지 표 연결(직전 표와 컬럼 수 동일 + 이번 표 헤더 없음)
                continued = prev_cols == n_cols and prev_had_header and not has_header and hidx == 0
                if continued:
                    res.merged_tables += 1

                res.table_total += 1
                res.est_table_rows += len(rows)

                # 원문 대조(정규화 반영)
                sampled = matched = 0
                text_ns = text.replace(" ", "")
                for r in rows:
                    for c in r:
                        for num in NUM_RE.findall(c or ""):
                            if len(num) < 2:
                                continue
                            sampled += 1
                            if num.replace(" ", "") in text_ns or num in text:
                                matched += 1
                            if sampled >= 30:
                                break
                        if sampled >= 30:
                            break
                    if sampled >= 30:
                        break
                res.numbers_checked += sampled
                res.number_mismatches += sampled - matched

                for k in kinds:
                    if k in ("actual", "estimate", "forecast", "guidance"):
                        vk[k] = vk.get(k, 0) + 1

                prev_cols, prev_had_header = n_cols, has_header

            res.aef_value_total += len(AEF_TOKEN_RE.findall(text))
            if page_no == 1:
                res.title_guess = _title_guess(page)

        res.body_char_total = total_chars
        res.value_kind_counts = dict(sorted(vk.items()))

        # 규칙 3: 상태 판정
        avg = total_chars / max(1, res.page_count)
        text_pages = sum(
            1 for i in range(res.page_count) if len((doc[i].get_text("text") or "").strip()) > 40
        )
        res.scan_pages = res.page_count - text_pages
        if avg < 80 or text_pages == 0:
            res.parse_status = "failed" if text_pages == 0 else "partial"
        elif res.scan_pages > res.page_count * 0.5:
            res.parse_status = "partial"
        else:
            res.parse_status = "success"
    except Exception as e:  # noqa: BLE001
        res.error = f"처리 오류: {type(e).__name__}: {e}"[:160]
        res.parse_status = "failed"
    finally:
        doc.close()
    return res


def main() -> int:
    folders = sorted(
        [d for d in REPORT_ROOT.iterdir() if d.is_dir() and not d.name.startswith(".")]
    )
    results: list[ReportResult] = []
    for d in folders:
        for p in sorted(d.glob("*.pdf")):
            results.append(process_report(p, _nfc(d.name)))

    # file_hash 중복 탐지
    seen: dict[str, str] = {}
    for r in results:
        key = f"{r.folder}/{r.filename}"
        if r.file_hash and r.file_hash in seen:
            r.dup_of = seen[r.file_hash]
        elif r.file_hash:
            seen[r.file_hash] = key

    # 상세(제목 소량 원문 포함) → gitignore
    (OUT_DIR / "full_dryrun_detail.json").write_text(
        json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 집계(원문 없음) → 추적
    vk_total: dict[str, int] = {}
    for r in results:
        for k, v in r.value_kind_counts.items():
            vk_total[k] = vk_total.get(k, 0) + v
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.parse_status] = by_status.get(r.parse_status, 0) + 1
    broker_q: dict[str, dict] = {}
    for r in results:
        b = r.broker_from_name or "(미상)"
        q = broker_q.setdefault(b, {"n": 0, "tables": 0, "checked": 0, "mismatch": 0})
        q["n"] += 1
        q["tables"] += r.table_total
        q["checked"] += r.numbers_checked
        q["mismatch"] += r.number_mismatches
    exceptions = [
        {"file": f"{r.folder}/{r.filename}", "status": r.parse_status, "error": r.error}
        for r in results
        if r.parse_status != "success" or r.error
    ]
    dups = [{"file": f"{r.folder}/{r.filename}", "dup_of": r.dup_of} for r in results if r.dup_of]
    checked = sum(r.numbers_checked for r in results)
    mismatch = sum(r.number_mismatches for r in results)
    loadable = [r for r in results if r.parse_status in ("success", "partial") and not r.dup_of]
    stats = {
        "reports": len(results),
        "by_status": by_status,
        "page_total": sum(r.page_count for r in results),
        "body_block_total": sum(r.body_block_total for r in results),
        "table_total": sum(r.table_total for r in results),
        "tables_with_units_total": sum(r.tables_with_units for r in results),
        "narrative_demoted_total": sum(r.narrative_demoted for r in results),
        "merged_tables_total": sum(r.merged_tables for r in results),
        "aef_value_total": sum(r.aef_value_total for r in results),
        "value_kind_counts": dict(sorted(vk_total.items())),
        "failed_pages_total": sum(r.failed_pages for r in results),
        "numbers_checked_total": checked,
        "number_mismatch_total": mismatch,
        "number_match_rate": round((checked - mismatch) / max(1, checked), 4),
        "source_page_detected": sum(1 for r in results if r.source_page_detected),
        "source_page_detect_rate": round(
            sum(1 for r in results if r.source_page_detected) / max(1, len(results)), 4
        ),
        "chart_pages_total": sum(r.chart_pages for r in results),
        "scan_pages_total": sum(r.scan_pages for r in results),
        "encrypted": sum(1 for r in results if r.encrypted),
        "duplicates": len(dups),
        "duplicate_list": dups,
        "exceptions": exceptions,
        "broker_quality": broker_q,
        # 적재 추정
        "loadable_reports": len(loadable),
        "est_db_report_rows": len(loadable),
        "est_db_table_rows": sum(r.est_table_rows for r in loadable),
        "est_embed_chunks": sum(r.est_body_chunks for r in loadable),
    }
    (OUT_DIR / "full_dryrun_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 콘솔 요약(상세 리스트 제외)
    brief = {
        k: v
        for k, v in stats.items()
        if k not in ("exceptions", "duplicate_list", "broker_quality")
    }
    print(json.dumps(brief, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

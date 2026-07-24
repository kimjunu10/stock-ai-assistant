"""Phase 5 1단계: 증권사 리포트 PDF 읽기 전용 인벤토리 수집.

/Users/kimjunwoo/report/ 아래 종목 폴더의 모든 PDF를 조사한다.
DB 쓰기·Storage 업로드·임베딩·원본 수정은 절대 하지 않는다(순수 read-only).

PyMuPDF(fitz)는 런타임 의존성이 아니므로 다음처럼 격리 실행한다:
    uv run --with pymupdf python scripts/phase5_inventory.py

산출물(둘 다 stdout 요약 + JSON 파일):
    docs/rag/phase_5/inventory.json      # 파일별 상세
    docs/rag/phase_5/inventory_summary.json  # 분포 통계

특정 증권사·파일명 하드코딩 없음. 파일명 규칙은 일반화된 정규식으로만 분해한다.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

REPORT_ROOT = Path("/Users/kimjunwoo/report")
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_5"

# 폴더명 -> stock_code (DB stocks 테이블에서 사전 확인한 값. 조사용 참고 매핑일 뿐
# 본 구현에서는 stocks 테이블 조회로 일반화한다.)
FOLDER_TO_CODE = {
    "두산에너빌리티": "034020",
    "삼성전자": "005930",
    "한화오션": "042660",
    "현대차": "005380",
    "SK하이닉스": "000660",
}

# 파일명 규칙: "YYYY-MM-DD_종목_증권사_제목.pdf"
# 종목/증권사에 공백이 없다는 가정 대신, 앞의 3필드만 '_'로 분해하고 나머지는 제목으로.
FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_([^_]+)_([^_]+)_(.+)$")

# 실제값/추정값/전망값 표기 탐지용 (일반적 표기; 특정 증권사 하드코딩 아님)
AEF_RE = re.compile(r"(?<![A-Za-z])([AEFP])\)")  # 2025A) 2026E) 2027F) 형태
AEF_YEAR_RE = re.compile(r"(20\d{2})\s*([AEFP])(?![A-Za-z])")  # 2025E, 2026F


@dataclass
class PdfInfo:
    folder: str
    stock_code: str | None
    filename: str
    file_size: int
    file_hash: str
    # 파일명 파싱
    fn_date: str | None
    fn_stock: str | None
    fn_broker: str | None
    fn_title: str | None
    fn_parse_ok: bool
    # PDF 구조
    open_ok: bool
    encrypted: bool
    corrupt: bool
    page_count: int
    total_chars: int
    text_pages: int  # 텍스트가 추출된 페이지 수
    scanned_suspect: bool  # 텍스트 거의 없음 -> 스캔 의심
    image_count: int
    drawing_count: int  # 벡터 그래픽(차트) 개수 추정
    table_pages: int  # find_tables 로 표가 감지된 페이지 수
    table_count: int  # 감지된 표 총 개수
    aef_hits: int  # A/E/F 표기 등장 횟수
    header_footer_note: str
    error: str | None = None
    dup_of: str | None = field(default=None)


def _file_hash(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_filename(stem: str) -> tuple[str | None, str | None, str | None, str | None, bool]:
    m = FILENAME_RE.match(stem)
    if not m:
        return None, None, None, None, False
    return m.group(1), m.group(2), m.group(3), m.group(4), True


def _header_footer_note(doc: fitz.Document) -> str:
    """첫 3페이지의 상단/하단 라인 반복 여부를 대략 관찰한다(구조 파악용)."""
    tops: list[str] = []
    bots: list[str] = []
    for i in range(min(3, doc.page_count)):
        page = doc[i]
        h = page.rect.height
        lines_top, lines_bot = [], []
        for b in page.get_text("blocks"):
            y0, y1, txt = b[1], b[3], b[4]
            t = " ".join(txt.split())
            if not t:
                continue
            if y0 < h * 0.10:
                lines_top.append(t[:40])
            elif y1 > h * 0.90:
                lines_bot.append(t[:40])
        tops.append(" | ".join(lines_top))
        bots.append(" | ".join(lines_bot))
    note = []
    if any(tops):
        note.append(f"top~={tops[0][:60]!r}")
    if any(bots):
        note.append(f"bot~={bots[0][:60]!r}")
    return "; ".join(note)


def inspect(p: Path, folder: str) -> PdfInfo:
    stem = p.stem
    fn_date, fn_stock, fn_broker, fn_title, fn_ok = _parse_filename(stem)
    info = PdfInfo(
        folder=folder,
        stock_code=FOLDER_TO_CODE.get(folder),
        filename=p.name,
        file_size=p.stat().st_size,
        file_hash=_file_hash(p),
        fn_date=fn_date,
        fn_stock=fn_stock,
        fn_broker=fn_broker,
        fn_title=fn_title,
        fn_parse_ok=fn_ok,
        open_ok=False,
        encrypted=False,
        corrupt=False,
        page_count=0,
        total_chars=0,
        text_pages=0,
        scanned_suspect=False,
        image_count=0,
        drawing_count=0,
        table_pages=0,
        table_count=0,
        aef_hits=0,
        header_footer_note="",
    )
    try:
        doc = fitz.open(p)
    except Exception as e:  # noqa: BLE001
        info.corrupt = True
        info.error = f"open: {type(e).__name__}: {e}"[:200]
        return info
    try:
        info.open_ok = True
        info.encrypted = bool(doc.needs_pass or doc.is_encrypted)
        info.page_count = doc.page_count
        total_chars = 0
        text_pages = 0
        image_count = 0
        drawing_count = 0
        table_pages = 0
        table_count = 0
        aef_hits = 0
        for page in doc:
            txt = page.get_text("text") or ""
            n = len(txt.strip())
            total_chars += n
            if n > 40:
                text_pages += 1
            image_count += len(page.get_images(full=True))
            try:
                drawing_count += len(page.get_drawings())
            except Exception:  # noqa: BLE001
                pass
            aef_hits += len(AEF_RE.findall(txt)) + len(AEF_YEAR_RE.findall(txt))
            try:
                tf = page.find_tables()
                tbls = list(tf.tables)
                if tbls:
                    table_pages += 1
                    table_count += len(tbls)
            except Exception:  # noqa: BLE001
                pass
        info.total_chars = total_chars
        info.text_pages = text_pages
        info.image_count = image_count
        info.drawing_count = drawing_count
        info.table_pages = table_pages
        info.table_count = table_count
        info.aef_hits = aef_hits
        # 스캔 의심: 페이지당 평균 글자수가 매우 적으면 이미지 기반으로 추정
        avg = total_chars / max(1, info.page_count)
        info.scanned_suspect = avg < 80
        info.header_footer_note = _header_footer_note(doc)
    except Exception as e:  # noqa: BLE001
        info.error = f"inspect: {type(e).__name__}: {e}"[:200]
    finally:
        doc.close()
    return info


def main() -> int:
    if not REPORT_ROOT.exists():
        print(f"[error] {REPORT_ROOT} 없음", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    folders = sorted(
        [d for d in REPORT_ROOT.iterdir() if d.is_dir() and not d.name.startswith(".")]
    )
    items: list[PdfInfo] = []
    for d in folders:
        pdfs = sorted(d.glob("*.pdf"))
        print(f"[{d.name}] {len(pdfs)} PDFs", file=sys.stderr)
        for p in pdfs:
            items.append(inspect(p, d.name))

    # 중복 탐지 (file_hash 기준)
    seen: dict[str, str] = {}
    for it in items:
        if it.file_hash in seen:
            it.dup_of = seen[it.file_hash]
        else:
            seen[it.file_hash] = f"{it.folder}/{it.filename}"

    # 상세 저장
    (OUT_DIR / "inventory.json").write_text(
        json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 분포 요약
    total = len(items)
    brokers: dict[str, int] = {}
    for it in items:
        b = it.fn_broker or "(파싱실패)"
        brokers[b] = brokers.get(b, 0) + 1
    summary = {
        "total": total,
        "folders": {d.name: len(list(d.glob("*.pdf"))) for d in folders},
        "stock_code_mapped": sum(1 for i in items if i.stock_code),
        "filename_parse_ok": sum(1 for i in items if i.fn_parse_ok),
        "filename_parse_fail": sum(1 for i in items if not i.fn_parse_ok),
        "brokers": dict(sorted(brokers.items(), key=lambda x: -x[1])),
        "broker_count": len([b for b in brokers if b != "(파싱실패)"]),
        "encrypted": sum(1 for i in items if i.encrypted),
        "corrupt": sum(1 for i in items if i.corrupt),
        "scanned_suspect": sum(1 for i in items if i.scanned_suspect),
        "with_tables": sum(1 for i in items if i.table_count > 0),
        "with_aef": sum(1 for i in items if i.aef_hits > 0),
        "duplicates": sum(1 for i in items if i.dup_of),
        "page_count": {
            "min": min((i.page_count for i in items), default=0),
            "max": max((i.page_count for i in items), default=0),
            "avg": round(sum(i.page_count for i in items) / max(1, total), 1),
        },
        "table_count": {
            "min": min((i.table_count for i in items), default=0),
            "max": max((i.table_count for i in items), default=0),
            "avg": round(sum(i.table_count for i in items) / max(1, total), 1),
        },
    }
    (OUT_DIR / "inventory_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

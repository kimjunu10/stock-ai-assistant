"""Phase 5 1단계: 대표 리포트 PDF 읽기 전용 시험 파싱.

dryrun_targets.json 의 14개 대표 PDF에 대해 여러 추출 방식을 비교한다.
DB 쓰기·Storage·임베딩·원본 수정 없음(순수 read-only).

실행:
    uv run --with pymupdf python scripts/phase5_dryrun_parse.py

비교 항목:
  1) 기본 텍스트 추출(get_text "text")
  2) 좌표 기반 단락 복원(blocks 정렬)
  3) 페이지별 제목/본문/표 분리
  4) 표 행·열 유지(find_tables -> extract)
  5) 실제값(A)/추정값(E)/전망값(F) 구분 가능성
  6) 페이지 출처 보존(모든 청크에 page_no)

산출물:
    docs/rag/phase_5/dryrun_parse.json    # 구조화 결과(표 셀·A/E/F 샘플 포함)
    docs/rag/phase_5/dryrun_parse.md      # 사람이 읽는 요약
특정 증권사·파일명 하드코딩 없음.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import fitz  # PyMuPDF

REPORT_ROOT = Path("/Users/kimjunwoo/report")
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_5"

# A/E/F 표기: 연도+구분자(2025A, 2026E, 2027F, 2026P) 또는 헤더셀 "2026E)" 형태
AEF_YEAR_RE = re.compile(r"(20\d{2})\s*\.?\s*([AEFP])(?![A-Za-z가-힣])")
# 목표주가/투자의견 등 핵심 숫자 라벨(일반적 표현; 특정 증권사 하드코딩 아님)
OPINION_RE = re.compile(r"(매수|매도|중립|보유|Buy|Hold|Sell|Trading Buy|Outperform)", re.I)
TARGET_RE = re.compile(r"목표\s*주?가")


def _find_targets() -> list[dict]:
    data = json.loads((OUT_DIR / "dryrun_targets.json").read_text(encoding="utf-8"))
    # 파일시스템은 NFD 이므로, 후보 이름을 정규화해 실제 파일과 매칭한다.
    resolved = []
    for d in data:
        folder_nfc = d["folder"]
        # 실제 폴더(자모분리형)를 NFC 비교로 찾는다.
        fs_folder = None
        for cand in REPORT_ROOT.iterdir():
            if cand.is_dir() and unicodedata.normalize("NFC", cand.name) == folder_nfc:
                fs_folder = cand
                break
        if fs_folder is None:
            d["_path"] = None
            resolved.append(d)
            continue
        fs_file = None
        for cand in fs_folder.glob("*.pdf"):
            if unicodedata.normalize("NFC", cand.name) == d["filename"]:
                fs_file = cand
                break
        d["_path"] = str(fs_file) if fs_file else None
        resolved.append(d)
    return resolved


def _blocks_paragraphs(page: fitz.Page) -> list[str]:
    """좌표 기반: blocks 를 (컬럼, y) 순으로 정렬해 단락을 복원한다.

    2단 레이아웃 대응: 페이지 폭 절반을 기준으로 좌/우 컬럼을 나눈다.
    """
    w = page.rect.width
    blocks = []
    for b in page.get_text("blocks"):
        x0, y0, x1, txt = b[0], b[1], b[2], b[4]
        t = " ".join((txt or "").split())
        if not t:
            continue
        col = 0 if (x0 + x1) / 2 < w / 2 else 1
        blocks.append((col, round(y0, 1), t))
    blocks.sort(key=lambda z: (z[0], z[1]))
    return [t for _, _, t in blocks]


def _tables(page: fitz.Page) -> list[list[list[str]]]:
    out = []
    try:
        tf = page.find_tables()
        for t in tf.tables:
            rows = t.extract()
            clean = [[("" if c is None else " ".join(str(c).split())) for c in r] for r in rows]
            out.append(clean)
    except Exception:  # noqa: BLE001
        pass
    return out


def _aef_samples(text: str, limit: int = 6) -> list[str]:
    hits = []
    for m in AEF_YEAR_RE.finditer(text):
        s = max(0, m.start() - 15)
        e = min(len(text), m.end() + 5)
        hits.append(" ".join(text[s:e].split()))
        if len(hits) >= limit:
            break
    return hits


def parse_one(path: Path) -> dict:
    doc = fitz.open(path)
    result = {
        "page_count": doc.page_count,
        "first_page_title_guess": "",
        "opinion_found": None,
        "target_price_line": None,
        "aef_sample": [],
        "table_page_example": None,
        "basic_vs_block_diff": None,
        "pages": [],
    }
    try:
        full_text = ""
        first_basic = doc[0].get_text("text") if doc.page_count else ""
        first_block = " \n".join(_blocks_paragraphs(doc[0])) if doc.page_count else ""
        result["basic_vs_block_diff"] = {
            "basic_chars": len(first_basic),
            "block_chars": len(first_block),
            "basic_head": " ".join(first_basic.split())[:180],
            "block_head": first_block[:180],
        }
        # 1페이지 제목 추정: 가장 큰 폰트 span
        if doc.page_count:
            spans = []
            for blk in doc[0].get_text("dict")["blocks"]:
                for line in blk.get("lines", []):
                    for sp in line.get("spans", []):
                        t = sp["text"].strip()
                        if t:
                            spans.append((sp["size"], t))
            if spans:
                spans.sort(key=lambda z: -z[0])
                result["first_page_title_guess"] = " ".join(t for _, t in spans[:3] if len(t) > 1)[
                    :120
                ]

        for pno, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            full_text += text + "\n"
            tables = _tables(page)
            if result["opinion_found"] is None:
                m = OPINION_RE.search(text)
                if m:
                    result["opinion_found"] = {"page": pno, "match": m.group(0)}
            if result["target_price_line"] is None and TARGET_RE.search(text):
                for line in text.splitlines():
                    if TARGET_RE.search(line):
                        result["target_price_line"] = {"page": pno, "line": line.strip()[:80]}
                        break
            if result["table_page_example"] is None and tables:
                # 첫 표의 상위 4행만 샘플로
                sample = tables[0][:4]
                result["table_page_example"] = {
                    "page": pno,
                    "n_tables": len(tables),
                    "rows_cols": [len(tables[0]), max((len(r) for r in tables[0]), default=0)],
                    "sample_rows": sample,
                }
            result["pages"].append(
                {
                    "page": pno,
                    "chars": len(text.strip()),
                    "n_tables": len(tables),
                    "para_count": len(_blocks_paragraphs(page)),
                }
            )
        result["aef_sample"] = _aef_samples(full_text)
    finally:
        doc.close()
    return result


def main() -> int:
    targets = _find_targets()
    report = []
    for d in targets:
        entry = {
            "folder": d["folder"],
            "filename": d["filename"],
            "reasons": d["reasons"],
            "resolved": bool(d["_path"]),
        }
        if not d["_path"]:
            entry["error"] = "파일 경로 해석 실패(NFC 매칭 불가)"
        else:
            entry["parse"] = parse_one(Path(d["_path"]))
        report.append(entry)
        print(f"[done] {d['folder']} / {d['filename'][:50]}")

    (OUT_DIR / "dryrun_parse.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 사람이 읽는 요약
    lines = ["# Phase 5 대표 PDF 시험 파싱 결과", ""]
    for e in report:
        lines.append(f"## [{e['folder']}] {e['filename']}")
        lines.append(f"- 선정 사유: {', '.join(e['reasons'])}")
        if not e.get("resolved"):
            lines.append(f"- ❌ {e.get('error')}")
            lines.append("")
            continue
        p = e["parse"]
        lines.append(f"- 페이지: {p['page_count']}")
        lines.append(f"- 1p 제목 추정: {p['first_page_title_guess']!r}")
        lines.append(f"- 투자의견: {p['opinion_found']}")
        lines.append(f"- 목표주가 라인: {p['target_price_line']}")
        lines.append(
            f"- 텍스트 vs 좌표단락 글자수: {p['basic_vs_block_diff']['basic_chars']} vs "
            f"{p['basic_vs_block_diff']['block_chars']}"
        )
        if p["table_page_example"]:
            te = p["table_page_example"]
            lines.append(
                f"- 표 예시(p{te['page']}, {te['n_tables']}개 중 첫 표 "
                f"{te['rows_cols'][0]}행x{te['rows_cols'][1]}열):"
            )
            for r in te["sample_rows"]:
                lines.append(f"    | {' | '.join(r)} |")
        lines.append(f"- A/E/F 샘플: {p['aef_sample']}")
        lines.append("")
    (OUT_DIR / "dryrun_parse.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{len(report)}개 파싱 완료 -> dryrun_parse.json / dryrun_parse.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

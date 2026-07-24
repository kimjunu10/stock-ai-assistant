"""Phase 5: 증권사 리포트 244개 적재(Storage 업로드 + DB + 본문 임베딩).

파이프라인(리포트 1개당, file_hash 기준 멱등·재시작 가능):
  1. parse_report(read-only 구조화)
  2. Storage 업로드(research-reports-private / <stock_code>/<file_hash>.pdf)
  3. research_reports upsert(file_hash unique) + pages + tables 교체
  4. 본문 청크 임베딩 → rag_documents/rag_chunks(source_type=research_report)
     content_hash 동일 시 재임베딩 skip.

QA 연결·Agentic·MCP 없음. 특정 증권사·파일명 하드코딩 없음.
PyMuPDF 필요:  uv run --with pymupdf python scripts/load_research_reports.py --apply
    --dry-run  : 파싱·비용추정만(기본), DB/Storage/임베딩 없음
    --apply    : 실제 적재
    --limit N  : 앞 N개만
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.ml.embeddings import UpstageEmbedder, content_hash  # noqa: E402
from app.rag.report_parser import ParsedReport, nfc, parse_report  # noqa: E402
from app.repositories.rag import RagRepository  # noqa: E402

REPORT_ROOT = Path("/Users/kimjunwoo/report")
BUCKET = "research-reports-private"
PARSER_NAME = "research_report"
PARSER_VERSION = "v1"
CHUNKING_VERSION = "report-v1"
SOURCE_TYPE = "research_report"
MAX_CHUNK_CHARS = 1000


def _parse_name(stem: str) -> tuple[str | None, str | None, str | None]:
    import re

    m = re.match(r"^(\d{4}-\d{2}-\d{2})_([^_]+)_([^_]+)_(.+)$", stem)
    if not m:
        return None, None, None
    return m.group(1), m.group(3), m.group(4)  # date, broker, title


def _stock_code_map(client) -> dict[str, str]:
    rows = client.table("stocks").select("code,name").execute().data or []
    return {r["name"]: r["code"] for r in rows}


def _body_chunks(rep: ParsedReport) -> list[tuple[int, str]]:
    """본문(차트/스캔 페이지 제외)을 페이지별로 ~1000자 청크로 나눈다."""
    chunks: list[tuple[int, str]] = []
    for pg in rep.pages:
        if pg.is_chart_page:
            continue
        text = " ".join((pg.plain_text or "").split())
        if len(text) < 40:
            continue
        for i in range(0, len(text), MAX_CHUNK_CHARS):
            piece = text[i : i + MAX_CHUNK_CHARS]
            if piece.strip():
                chunks.append((pg.page_number, piece))
    return chunks


def _upload_pdf(client, stock_code: str, file_hash: str, path: Path) -> str:
    key = f"{stock_code}/{file_hash}.pdf"
    data = path.read_bytes()
    try:
        client.storage.from_(BUCKET).upload(
            key, data, {"content-type": "application/pdf", "upsert": "true"}
        )
    except Exception as e:  # noqa: BLE001 - 이미 있으면 멱등 성공으로 간주
        if "exists" not in str(e).lower() and "duplicate" not in str(e).lower():
            raise
    return key


def process(
    path: Path,
    folder: str,
    *,
    apply: bool,
    client,
    repo: RagRepository | None,
    embedder: UpstageEmbedder | None,
    code_map: dict[str, str],
) -> dict:
    date, broker, title = _parse_name(path.stem)
    stock_code = code_map.get(folder)
    rep = parse_report(str(path))
    file_hash = content_hash(path.read_bytes().hex())
    body_chunks = _body_chunks(rep)
    info = {
        "file": f"{folder}/{nfc(path.name)}",
        "stock_code": stock_code,
        "broker": broker,
        "status": rep.parse_status,
        "pages": rep.page_count,
        "tables": len(rep.tables),
        "chunks": len(body_chunks),
        "aef": rep.aef_value_total,
        "loaded": False,
        "skipped": False,
        "error": None,
    }
    if not stock_code:
        info["error"] = "stock_code 매핑 실패"
        return info
    if not apply:
        return info

    try:
        # 2. Storage 업로드
        storage_path = _upload_pdf(client, stock_code, file_hash, path)

        # 3. research_reports upsert
        report_row = repo.upsert_report(
            {
                "stock_code": stock_code,
                "broker": broker or "미상",
                "title": (title or rep.title_guess or path.stem)[:300],
                "report_date": date,
                "investment_opinion": rep.investment_opinion,
                "page_count": rep.page_count,
                "storage_bucket": BUCKET,
                "storage_path": storage_path,
                "file_hash": file_hash,
                "parse_status": rep.parse_status,
                "parser_name": PARSER_NAME,
                "parser_version": PARSER_VERSION,
                "metadata": {
                    "source_page_offset": rep.source_page_offset,
                    "chart_pages": rep.chart_pages,
                    "scan_pages": rep.scan_pages,
                    "aef_value_kind_counts": rep.aef_value_kind_counts,
                },
            }
        )
        report_id = report_row["id"]

        # pages
        repo.replace_report_pages(
            report_id,
            [
                {
                    "page_number": pg.page_number,
                    "plain_text": pg.plain_text,
                    "elements": {
                        "pdf_page": pg.pdf_page,
                        "source_page": pg.source_page,
                        "is_chart_page": pg.is_chart_page,
                        "body_blocks": pg.body_blocks,
                    },
                    "page_hash": content_hash(pg.plain_text or ""),
                }
                for pg in rep.pages
            ],
        )
        # tables
        repo.replace_report_tables(
            report_id,
            [
                {
                    "page_number": t.page_number,
                    "table_order": t.table_order,
                    "title": t.title,
                    "unit": t.unit,
                    "headers": t.headers,
                    "rows": t.rows,
                    "value_kind": t.value_kind,
                    "source_bbox": None,
                    "parse_confidence": (
                        round(t.numbers_matched_in_text / t.numbers_sampled, 3)
                        if t.numbers_sampled
                        else None
                    ),
                }
                for t in rep.tables
            ],
        )

        # 4. 본문 임베딩 (content_hash 재실행 skip)
        if body_chunks:
            doc_hash = content_hash("\n---\n".join(c for _, c in body_chunks))
            current = repo.find_current_document(SOURCE_TYPE, file_hash)
            if current and current.get("content_hash") == doc_hash:
                info["skipped"] = True
                info["loaded"] = True
                return info
            doc = repo.upsert_document(
                {
                    "source_type": SOURCE_TYPE,
                    "source_pk": file_hash,
                    "stock_code": stock_code,
                    "title": (title or rep.title_guess or path.stem)[:300],
                    "published_at": date,
                    "content_hash": doc_hash,
                    "parser_name": PARSER_NAME,
                    "parser_version": PARSER_VERSION,
                    "chunking_version": CHUNKING_VERSION,
                    "metadata": {"report_id": report_id, "broker": broker},
                }
            )
            document_id = doc["id"]
            vectors = embedder.embed_passages([c for _, c in body_chunks])
            rows = []
            for order, ((page_no, text), vec) in enumerate(zip(body_chunks, vectors, strict=True)):
                rows.append(
                    {
                        "chunk_order": order,
                        "content": text,
                        "search_text": text,
                        "content_hash": content_hash(text),
                        "embedding": vec,
                        "value_kind": None,
                        "token_estimate": len(text) // 2,
                        "source_locator": {"report_id": report_id, "page_number": page_no},
                        "stock_code": stock_code,
                        "source_type": SOURCE_TYPE,
                        "published_at": date,
                        "is_active": True,
                    }
                )
            repo.replace_chunks(document_id, rows)
            info["embedded"] = len(rows)
        info["loaded"] = True
    except Exception as e:  # noqa: BLE001 - 파일 단위 실패 격리(재시작 가능)
        info["error"] = f"{type(e).__name__}: {e}"[:200]
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    client = get_supabase_client()
    repo = RagRepository(client, settings) if apply else None
    embedder = UpstageEmbedder(settings) if apply else None
    code_map = _stock_code_map(client)

    pdfs: list[tuple[Path, str]] = []
    for d in sorted(REPORT_ROOT.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            for p in sorted(d.glob("*.pdf")):
                pdfs.append((p, nfc(d.name)))
    if args.limit:
        pdfs = pdfs[: args.limit]

    run_id = None
    if apply:
        run_id = repo.start_ingestion_run(SOURCE_TYPE, {"count": len(pdfs)})

    results = []
    for i, (p, folder) in enumerate(pdfs, 1):
        r = process(
            p, folder, apply=apply, client=client, repo=repo, embedder=embedder, code_map=code_map
        )
        results.append(r)
        tag = "SKIP" if r["skipped"] else ("OK" if r["loaded"] else ("DRY" if not apply else "ERR"))
        print(
            f"[{i}/{len(pdfs)}] {tag} {r['file'][:50]} status={r['status']} "
            f"표{r['tables']} 청크{r['chunks']}" + (f" err={r['error']}" if r["error"] else "")
        )

    loaded = sum(1 for r in results if r["loaded"] and not r["skipped"])
    skipped = sum(1 for r in results if r["skipped"])
    errors = [r for r in results if r["error"]]
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    total_chunks = sum(r["chunks"] for r in results)
    est_cost = total_chunks * 500 / 1_000_000 * 0.10  # ~500 tok/chunk

    if apply and run_id:
        repo.finish_ingestion_run(
            run_id,
            status="success" if not errors else "partial",
            processed_count=len(pdfs),
            success_count=loaded + skipped,
            failure_count=len(errors),
            actual_cost=round(est_cost, 4),
        )

    print("\n=== 요약 ===")
    print(f"대상 {len(pdfs)} | status {by_status}")
    print(f"적재 {loaded} | skip {skipped} | 오류 {len(errors)}")
    print(f"본문 청크 총 {total_chunks} | 임베딩 예상비용 ~${est_cost:.4f}")
    for e in errors[:20]:
        print(f"  ERR {e['file'][:50]}: {e['error']}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

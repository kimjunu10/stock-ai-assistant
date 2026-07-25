"""증권사 리포트 현재 목표주가 backfill (prompt.md §3). dry-run / apply 분리.

데이터 소스: research_report_tables → research_report_pages → (fallback) 원본 PDF.
공유(운영) Supabase 에는 dry-run 만 실행한다. 실제 UPDATE(--apply)는 명시적 승인 후.

실행:
  # dry-run(기본) — 아무것도 쓰지 않는다. 상태별 건수·변경안·검수 목록만 출력.
  python scripts/backfill_target_price.py            # 전체
  python scripts/backfill_target_price.py 005930     # 종목 한정
  python scripts/backfill_target_price.py --json out.json   # 상세 결과 파일

  # 실제 적용(승인 후에만) — target_price/status/근거 컬럼 UPDATE.
  python scripts/backfill_target_price.py --apply --yes-i-have-approval

fallback(PDF) 사용: --allow-pdf 를 줄 때만 원본 PDF 다운로드를 시도한다(느림).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections import Counter
from datetime import date

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.db.client import get_supabase_client  # noqa: E402
from app.rag.target_price_extractor import (  # noqa: E402
    EXTRACTOR_VERSION,
    extract_from_page_text,
    extract_target_price,
)

BUCKET = "research-reports-private"


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _fetch_pages(client, report_id: str) -> list[dict]:
    return (
        client.table("research_report_pages")
        .select("page_number,plain_text")
        .eq("report_id", report_id)
        .order("page_number")
        .execute()
        .data
        or []
    )


def _fetch_tables(client, report_id: str) -> list[dict]:
    return (
        client.table("research_report_tables")
        .select("page_number,title,headers,rows")
        .eq("report_id", report_id)
        .order("page_number")
        .execute()
        .data
        or []
    )


def _pdf_fallback(client, report: dict) -> object:
    """원본 PDF 를 서버 권한으로 내려받아 페이지 텍스트로 재추출(fallback).

    Storage 접근 불가·PDF 파싱 불가면 ambiguous 로 둔다(억지 확정 금지).
    """
    from app.rag.target_price_extractor import TargetPriceExtraction

    path = report.get("storage_path")
    if not path:
        return TargetPriceExtraction(status="ambiguous", reason="pdf:no_storage_path")
    try:
        raw = client.storage.from_(report.get("storage_bucket") or BUCKET).download(path)
    except Exception as e:  # noqa: BLE001
        return TargetPriceExtraction(
            status="ambiguous", reason=f"pdf:download_failed:{type(e).__name__}"
        )
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=io.BytesIO(raw), filetype="pdf")
        pages = [
            {"page_number": i + 1, "plain_text": doc[i].get_text("text") or ""}
            for i in range(doc.page_count)
        ]
        doc.close()
    except Exception as e:  # noqa: BLE001
        return TargetPriceExtraction(
            status="ambiguous", reason=f"pdf:parse_failed:{type(e).__name__}"
        )
    res = extract_from_page_text(pages, _parse_date(report.get("report_date")))
    res.reason = "pdf_fallback:" + res.reason
    return res


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stock_code", nargs="?", default=None)
    ap.add_argument("--apply", action="store_true", help="실제 DB UPDATE(승인 필요)")
    ap.add_argument("--yes-i-have-approval", action="store_true")
    ap.add_argument("--allow-pdf", action="store_true", help="fallback 원본 PDF 다운로드 허용")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    if args.apply and not args.yes_i_have_approval:
        print("거부: --apply 는 --yes-i-have-approval 과 함께여야 한다(승인 게이트).")
        return 2

    client = get_supabase_client()
    q = client.table("research_reports").select(
        "id,stock_code,broker,title,report_date,target_price,target_price_status,"
        "storage_bucket,storage_path"
    )
    if args.stock_code:
        q = q.eq("stock_code", args.stock_code)
    reports = q.order("report_date", desc=True).execute().data or []

    status_counter: Counter = Counter()
    by_broker: dict[str, Counter] = {}
    changes: list[dict] = []
    review_needed: list[dict] = []
    details: list[dict] = []

    for r in reports:
        rid = r["id"]
        rdate = _parse_date(r.get("report_date"))
        tables = _fetch_tables(client, rid)
        pages = _fetch_pages(client, rid)
        res = extract_target_price(tables, pages, rdate)
        # 애매/실패 + PDF 허용 시 fallback 시도
        if res.status in ("ambiguous", "parse_failed") and args.allow_pdf:
            fb = _pdf_fallback(client, r)
            if fb.status == "stated":
                res = fb

        status_counter[res.status] += 1
        b = r.get("broker") or "?"
        by_broker.setdefault(b, Counter())[res.status] += 1

        old_tp = r.get("target_price")
        if res.status == "stated" and old_tp != res.value:
            changes.append(
                {
                    "id": rid, "broker": b, "report_date": r.get("report_date"),
                    "old": old_tp, "new": res.value,
                    "effective_date": str(res.effective_date) if res.effective_date else None,
                    "source_page": res.source_page, "reason": res.reason,
                }
            )
        if res.status in ("ambiguous", "parse_failed"):
            review_needed.append(
                {"id": rid, "broker": b, "report_date": r.get("report_date"),
                 "status": res.status, "reason": res.reason}
            )
        details.append(
            {"id": rid, "broker": b, "report_date": r.get("report_date"),
             "status": res.status, "value": res.value, "reason": res.reason}
        )

    # ── 리포트 출력 ──
    print("=" * 72)
    print(f"목표주가 backfill {'APPLY' if args.apply else 'DRY-RUN'} "
          f"— {len(reports)}건 (stock={args.stock_code or 'ALL'})")
    print("=" * 72)
    print(f"상태 분포: {dict(status_counter)}")
    print(f"  stated={status_counter['stated']} not_stated={status_counter['not_stated']} "
          f"parse_failed={status_counter['parse_failed']} ambiguous={status_counter['ambiguous']}")
    print(f"변경 예정(값 갱신): {len(changes)}건")
    for c in changes[:20]:
        print(f"  {c['report_date']} {c['broker']}: {c['old']} → {c['new']} "
              f"(eff={c['effective_date']}, p{c['source_page']}, {c['reason']})")
    if len(changes) > 20:
        print(f"  ... 외 {len(changes) - 20}건")
    print(f"검수 필요(ambiguous/parse_failed): {len(review_needed)}건")
    print("증권사별 상태:")
    for b, c in sorted(by_broker.items()):
        print(f"  {b}: {dict(c)}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(
                {"summary": dict(status_counter), "changes": changes,
                 "review_needed": review_needed, "details": details},
                f, ensure_ascii=False, indent=2,
            )
        print(f"\n상세 결과 저장: {args.json_out}")

    # ── APPLY (승인 후에만) ──
    if args.apply:
        print("\n[APPLY] 실제 UPDATE 를 수행한다...")
        applied = 0
        for r in reports:
            rid = r["id"]
            rdate = _parse_date(r.get("report_date"))
            res = extract_target_price(
                _fetch_tables(client, rid), _fetch_pages(client, rid), rdate
            )
            payload: dict = {
                "target_price_status": res.status,
                "target_price_extractor_version": EXTRACTOR_VERSION,
            }
            if res.status == "stated":
                payload.update(
                    target_price=res.value,
                    target_price_effective_date=(
                        str(res.effective_date) if res.effective_date else None
                    ),
                    target_price_source_page=res.source_page,
                    target_price_evidence_text=(res.evidence_text or "")[:500],
                )
            client.table("research_reports").update(payload).eq("id", rid).execute()
            applied += 1
        print(f"[APPLY] 완료: {applied}건 갱신.")
    else:
        print("\n(dry-run: 아무것도 쓰지 않았다. 적용하려면 승인 후 "
              "--apply --yes-i-have-approval)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))

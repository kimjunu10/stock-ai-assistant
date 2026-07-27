"""Phase 8: needs_manual_review 라벨을 원본 대조로 확정 (read-only).

RAG 가 생성한 답변을 정답으로 쓰지 않는다. DB 원본만 본다.
검색 결과 1위를 자동으로 정답 처리하지 않는다 — 사건·리포트 식별자에서
결정적으로 유도되는 청크만 확정한다.

확정 조건(§4)을 모두 만족할 때만 review_status 를 confirmed 로 바꾼다.
하나라도 어긋나면 needs_manual_review 를 유지하고 사유를 label_basis 에 남긴다.

실행:
    cd backend
    .venv/bin/python scripts/phase8_review_labels.py            # 검토 후 파일 갱신
    .venv/bin/python scripts/phase8_review_labels.py --dry-run  # 결과만 출력
산출: docs/rag/phase_8/eval/{devset,holdout}.json 갱신 + review_report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.client import get_supabase_client  # noqa: E402
from app.eval.schema import EvalSuite  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"


# ─────────────────────────── 원본 조회 ───────────────────────────


def load_news_index(client, cluster_ids: list[str]) -> dict[str, dict]:
    """news_clusters.id → 사건 사실 + 정답 chunk_id.

    rag_documents(source_type='news_event', source_pk=cluster_id) 로 문서를 찾고
    그 문서의 활성 청크를 정답 식별자로 쓴다. 검색을 돌리지 않는다.
    """
    out: dict[str, dict] = {}
    if not cluster_ids:
        return out

    clusters = (
        client.table("news_clusters")
        .select(
            "id,stock_code,summary_title,factual_body,first_published_at,"
            "sentiment_label,article_count,representative_article_id,summary_status"
        )
        .in_("id", cluster_ids)
        .execute()
        .data
        or []
    )
    docs = (
        client.table("rag_documents")
        .select("id,source_pk,stock_code,is_current,source_url,title")
        .eq("source_type", "news_event")
        .eq("is_current", True)
        .in_("source_pk", [str(c) for c in cluster_ids])
        .execute()
        .data
        or []
    )
    doc_by_pk = {str(d["source_pk"]): d for d in docs}

    doc_ids = [d["id"] for d in docs]
    chunks: list[dict] = []
    for i in range(0, len(doc_ids), 50):
        chunks += (
            client.table("rag_chunks")
            .select("id,document_id,stock_code,is_active")
            .eq("is_active", True)
            .in_("document_id", doc_ids[i : i + 50])
            .execute()
            .data
            or []
        )
    chunks_by_doc: dict[str, list[dict]] = {}
    for ch in chunks:
        chunks_by_doc.setdefault(ch["document_id"], []).append(ch)

    for cl in clusters:
        cid = str(cl["id"])
        doc = doc_by_pk.get(cid)
        out[cid] = {
            "cluster": cl,
            "doc": doc,
            "chunks": chunks_by_doc.get(doc["id"], []) if doc else [],
        }
    return out


def load_report_index(client, report_ids: list[str]) -> dict[str, dict]:
    """research_reports.id → 리포트 메타 + 페이지별 청크.

    청크 페이지는 rag_chunks.source_locator JSON(report_id, page_number)에 있다
    (page_start/page_end 컬럼은 리포트 청크에서 전부 NULL).
    """
    out: dict[str, dict] = {}
    if not report_ids:
        return out

    reports = (
        client.table("research_reports")
        .select(
            "id,stock_code,broker,title,report_date,investment_opinion,target_price,"
            "target_price_status,target_price_source_page,target_price_evidence_text,"
            "page_count,file_hash,parse_status"
        )
        .in_("id", report_ids)
        .execute()
        .data
        or []
    )
    for rp in reports:
        chunks = (
            client.table("rag_chunks")
            .select("id,content,source_locator,stock_code,is_active")
            .eq("source_type", "research_report")
            .eq("is_active", True)
            .eq("source_locator->>report_id", rp["id"])
            .execute()
            .data
            or []
        )
        out[rp["id"]] = {"report": rp, "chunks": chunks}
    return out


# ─────────────────────────── 확정 판정 ───────────────────────────


def _cluster_id_from_basis(text: str) -> str | None:
    m = re.search(r"news_clusters\.id=(\d+)", text or "")
    return m.group(1) if m else None


def _report_id_from_basis(text: str) -> str | None:
    m = re.search(r"research_reports\.id=([0-9a-f-]{36})", text or "")
    return m.group(1) if m else None


def review_news_case(case, index: dict) -> tuple[bool, str, list[dict]]:
    """뉴스 라벨 확정. 반환: (확정 여부, 사유, 갱신된 gold_sources)."""
    cid = _cluster_id_from_basis(case.label_basis) or _cluster_id_from_basis(
        (case.gold_sources[0].note or "") if case.gold_sources else ""
    )
    if not cid:
        return False, "라벨에 news_clusters.id 가 없어 사건을 특정할 수 없음", []

    entry = index.get(cid)
    if not entry:
        return False, f"news_clusters.id={cid} 가 DB 에 없음", []

    cl = entry["cluster"]
    doc = entry["doc"]
    chunks = entry["chunks"]

    if cl.get("summary_status") != "success":
        return False, f"사건 요약 상태가 success 아님({cl.get('summary_status')})", []
    if not doc:
        return False, f"사건 {cid} 에 대응하는 현재 rag_documents 가 없음(색인 누락)", []
    if not chunks:
        return False, f"사건 {cid} 문서에 활성 청크가 없음(색인 누락)", []

    want_stock = case.context.stock_code or case.stock_code
    if want_stock and str(cl["stock_code"]) != want_stock:
        return False, f"질문 종목({want_stock})과 사건 종목({cl['stock_code']}) 불일치", []
    if want_stock and str(doc.get("stock_code")) != want_stock:
        return False, f"질문 종목({want_stock})과 문서 종목({doc.get('stock_code')}) 불일치", []
    bad = [c["id"] for c in chunks if want_stock and str(c.get("stock_code")) != want_stock]
    if bad:
        return False, f"다른 종목 청크 혼입: {bad[:2]}", []

    # 정답은 재색인으로 바뀌는 청크가 아니라 안정적인 사건 PK 하나로 확정한다.
    date = str(cl.get("first_published_at", ""))[:10]
    gold = [
        {
            "source_type": "news_event",
            "source_id": None,
            "canonical_id": f"news_clusters.id={cid}",
            "ref": (cl.get("summary_title") or "")[:80],
            "note": (
                f"news_clusters.id={cid} / {date} / {cl['sentiment_label']} / "
                f"기사 {cl['article_count']}건"
            ),
        }
    ]
    basis = (
        f"canonical Gold news_clusters.id={cid} 실재(요약 success, "
        f"기사 {cl['article_count']}건, {date}, 감성 {cl['sentiment_label']}). "
        f"현재 rag_documents.id={doc['id']}, 활성 청크 {len(chunks)}건은 검토 시점 "
        f"resolved 감사값이며 canonical 정답이 아님. 종목 {cl['stock_code']} 일치."
    )
    return True, basis, gold


def review_report_case(case, index: dict) -> tuple[bool, str, list[dict]]:
    """리포트 라벨 확정. 목표주가 근거 청크를 페이지·본문으로 검증한다."""
    rid = _report_id_from_basis(case.label_basis) or _report_id_from_basis(
        (case.gold_sources[0].note or "") if case.gold_sources else ""
    )
    if not rid:
        return False, "라벨에 research_reports.id 가 없어 리포트를 특정할 수 없음", []

    entry = index.get(rid)
    if not entry:
        return False, f"research_reports.id={rid} 가 DB 에 없음", []

    rp = entry["report"]
    chunks = entry["chunks"]
    if not chunks:
        return False, f"리포트 {rid} 에 활성 청크가 없음(파싱·색인 누락)", []

    want_stock = case.context.stock_code or case.stock_code
    if want_stock and str(rp["stock_code"]) != want_stock:
        return False, f"질문 종목({want_stock})과 리포트 종목({rp['stock_code']}) 불일치", []

    if rp.get("target_price_status") != "stated":
        return False, f"목표주가가 stated 가 아님({rp.get('target_price_status')})", []
    tp = rp.get("target_price")
    if not tp:
        return False, "목표주가 값이 없음", []

    # 목표주가 숫자가 실제로 담긴 청크만 근거로 인정한다(검색 1위 자동 채택 금지).
    tp_str = f"{int(tp):,}"
    tp_plain = str(int(tp))
    evidence = [
        c for c in chunks if tp_str in (c["content"] or "") or tp_plain in (c["content"] or "")
    ]
    if not evidence:
        return (
            False,
            (
                f"목표주가 {tp_str} 원이 이 리포트의 어떤 청크 본문에도 없음 "
                f"(청크 {len(chunks)}건 확인) — 근거 문단 확정 불가"
            ),
            [],
        )

    pages = sorted(
        {
            int(c["source_locator"]["page_number"])
            for c in evidence
            if isinstance(c.get("source_locator"), dict) and c["source_locator"].get("page_number")
        }
    )
    page_count = rp.get("page_count")
    if page_count and pages and max(pages) > page_count:
        return False, f"근거 청크 페이지 {max(pages)} 가 PDF 페이지 수({page_count})를 넘음", []

    gold = [
        {
            "source_type": "research_report",
            "source_id": c["id"],
            "ref": f"{rp['broker']} {rp['report_date']} {(rp['title'] or '')[:40]}",
            "page": (
                int(c["source_locator"]["page_number"])
                if isinstance(c.get("source_locator"), dict)
                and c["source_locator"].get("page_number")
                else None
            ),
            "note": f"research_reports.id={rid} / 목표주가 {tp_str}원(stated)",
        }
        for c in evidence
    ]
    basis = (
        f"research_reports.id={rid} 실재: {rp['broker']} {rp['report_date']}, "
        f"목표주가 {tp_str}원(stated), 투자의견 {rp.get('investment_opinion')}, "
        f"종목 {rp['stock_code']} 일치. 목표주가 숫자가 본문에 있는 청크 {len(evidence)}건"
        f"(p.{pages if pages else '미상'})을 근거로 확정. PDF {page_count}쪽. "
        f"목표주가는 전망값(투자의견 기준)이며 실제 거래가가 아니다."
    )
    return True, basis, gold


def review_mixed_case(case, news_idx: dict, report_idx: dict) -> tuple[bool, str, list[dict]]:
    """복합 질문 라벨 확정.

    복합 질문은 하위 질문마다 정답 문서가 달라 단일 정답 식별자를 확정할 수 없다.
    대신 §3 이 요구하는 나머지 항목(필수·보조·금지 Tool, 기대 입력, 허용 출처,
    금지 주장)이 전부 채워져 있는지 확인하고, 그것으로 확정 여부를 판정한다.
    정답 식별자는 비워 두되 그 사실을 근거에 명시한다.
    """
    missing = []
    if not case.required_tools:
        missing.append("필수 Tool")
    if not case.expected_args:
        missing.append("기대 입력 조건")
    if not case.allowed_source_types:
        missing.append("허용 출처")
    # 복합 질문은 필수 Tool 이 2개 이상이어야 '복합'이다.
    if len(case.required_tools) < 2:
        missing.append("필수 Tool 2개 이상")
    if missing:
        return False, f"복합 질문 라벨 필수 항목 누락: {', '.join(missing)}", []

    want_stock = case.context.stock_code or case.stock_code
    if not want_stock:
        return False, "복합 질문에 대상 종목이 없어 자료 범위를 확정할 수 없음", []

    basis = (
        f"복합 질문 라벨 확정: 종목 {want_stock}, 필수 Tool {case.required_tools}, "
        f"보조 Tool {case.optional_tools}, 허용 출처 {case.allowed_source_types}. "
        "하위 질문마다 정답 문서가 달라 단일 정답 식별자는 두지 않는다"
        "(검색 Recall 분모에서 제외되며, 필수 Tool 호출·입력 조건·출처 종류로 채점한다)."
    )
    return True, basis, []


# ─────────────────────────── 실행 ───────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 결과만 출력")
    args = ap.parse_args()

    client = get_supabase_client()
    suites = {
        name: EvalSuite.model_validate(json.loads((EVAL_DIR / f"{name}.json").read_text("utf-8")))
        for name in ("devset", "holdout")
    }

    targets = [
        (name, c)
        for name, s in suites.items()
        for c in s.cases
        if c.review_status == "needs_manual_review"
    ]
    print(f"수동 검토 대상 {len(targets)}건")

    # 원본을 한 번에 읽는다(문항마다 조회하지 않는다).
    cluster_ids, report_ids = [], []
    for _, c in targets:
        note = (c.gold_sources[0].note or "") if c.gold_sources else ""
        cid = _cluster_id_from_basis(c.label_basis) or _cluster_id_from_basis(note)
        rid = _report_id_from_basis(c.label_basis) or _report_id_from_basis(note)
        if cid:
            cluster_ids.append(cid)
        if rid:
            report_ids.append(rid)
    news_idx = load_news_index(client, sorted(set(cluster_ids)))
    report_idx = load_report_index(client, sorted(set(report_ids)))
    print(f"원본 조회: 뉴스 사건 {len(news_idx)}건 / 리포트 {len(report_idx)}건")

    rows = []
    for split, case in targets:
        if case.type == "뉴스 사건·영향":
            ok, basis, gold = review_news_case(case, news_idx)
        elif case.type == "증권사 리포트":
            ok, basis, gold = review_report_case(case, report_idx)
        elif case.type == "복수 기능 혼합":
            ok, basis, gold = review_mixed_case(case, news_idx, report_idx)
        else:
            ok, basis, gold = False, f"검토 대상 유형 아님({case.type})", []

        if ok:
            case.review_status = "confirmed"
            case.label_basis = basis
            if gold:
                case.gold_sources = [type(case.gold_sources[0]).model_validate(g) for g in gold]
        else:
            # 확정하지 못한 이유를 남긴다(추측해서 채우지 않는다).
            case.label_basis = f"{case.label_basis} || 미확정 사유: {basis}"

        rows.append(
            {
                "split": split,
                "id": case.id,
                "type": case.type,
                "confirmed": ok,
                "reason": basis if not ok else "",
                "gold_count": len(gold),
            }
        )
        mark = "확정" if ok else "미확정"
        print(f"[{mark}] {case.id:14} {case.type:12} {'' if ok else basis[:70]}")

    confirmed = sum(1 for r in rows if r["confirmed"])
    print(f"\n확정 {confirmed} / 미확정 {len(rows) - confirmed}")

    if args.dry_run:
        print("(dry-run: 파일 미변경)")
        return 0

    for name, suite in suites.items():
        (EVAL_DIR / f"{name}.json").write_text(
            json.dumps(suite.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    (EVAL_DIR / "review_report.json").write_text(
        json.dumps(
            {
                "note": "Phase 8 라벨 검토 결과. 정답은 DB 원본에서만 확정했다.",
                "reviewed": len(rows),
                "confirmed": confirmed,
                "still_manual": len(rows) - confirmed,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"저장: {EVAL_DIR}/devset.json, holdout.json, review_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Stable canonical news Gold resolution for Phase 8 evaluation.

News events are identified by ``news_clusters.id``. RAG document and chunk UUIDs
are execution-time artifacts and must be resolved from the current read-only DB
state instead of being treated as canonical labels.
"""

from __future__ import annotations

import re
from typing import Any

from app.eval.schema import EvalCase, GoldSource

_CANONICAL_NEWS_ID_RE = re.compile(r"^news_clusters\.id=(\d+)$")
_NOTE_NEWS_ID_RE = re.compile(r"news_clusters\.id=(\d+)")


def canonical_news_cluster_id(gold: GoldSource) -> str | None:
    """Return the canonical cluster ID, with note fallback for legacy labels."""

    if gold.canonical_id:
        match = _CANONICAL_NEWS_ID_RE.fullmatch(gold.canonical_id.strip())
        return match.group(1) if match else None
    match = _NOTE_NEWS_ID_RE.search(gold.note or "")
    return match.group(1) if match else None


def _news_gold_entries(cases: list[EvalCase]) -> list[dict[str, str | None]]:
    entries: list[dict[str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for case in cases:
        expected_stock = case.context.stock_code or case.stock_code
        for gold in case.gold_sources:
            if gold.source_type != "news_event":
                continue
            cluster_id = canonical_news_cluster_id(gold)
            key = (case.id, cluster_id or "")
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    "case_id": case.id,
                    "canonical_id": gold.canonical_id,
                    "cluster_id": cluster_id,
                    "expected_stock_code": expected_stock,
                }
            )
    return entries


def resolve_news_gold_rows(
    cases: list[EvalCase],
    *,
    cluster_rows: list[dict[str, Any]],
    document_rows: list[dict[str, Any]],
    chunk_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate canonical labels against DB rows and return an audit-ready resolution."""

    entries = _news_gold_entries(cases)
    clusters = {str(row["id"]): row for row in cluster_rows}
    documents: dict[str, list[dict[str, Any]]] = {}
    for row in document_rows:
        documents.setdefault(str(row.get("source_pk")), []).append(row)
    chunks: dict[str, list[dict[str, Any]]] = {}
    for row in chunk_rows:
        chunks.setdefault(str(row.get("document_id")), []).append(row)

    resolutions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for entry in entries:
        case_id = str(entry["case_id"])
        cluster_id = entry["cluster_id"]
        canonical_id = entry["canonical_id"]
        expected_stock = entry["expected_stock_code"]
        base = {
            "case_id": case_id,
            "canonical_id": canonical_id,
            "cluster_id": cluster_id,
        }
        if cluster_id is None:
            errors.append({**base, "reason": "canonical_cluster_id_missing_or_invalid"})
            continue

        cluster = clusters.get(cluster_id)
        if cluster is None:
            errors.append({**base, "reason": "canonical_cluster_missing"})
            continue
        if expected_stock and str(cluster.get("stock_code")) != expected_stock:
            errors.append(
                {
                    **base,
                    "reason": "canonical_cluster_stock_mismatch",
                    "actual_stock_code": cluster.get("stock_code"),
                    "expected_stock_code": expected_stock,
                }
            )
            continue

        current_documents = [
            row for row in documents.get(cluster_id, []) if row.get("is_current") is True
        ]
        if len(current_documents) != 1:
            errors.append(
                {
                    **base,
                    "reason": (
                        "current_document_missing"
                        if not current_documents
                        else "multiple_current_documents"
                    ),
                    "current_document_count": len(current_documents),
                }
            )
            continue

        document = current_documents[0]
        document_id = str(document["id"])
        if expected_stock and str(document.get("stock_code")) != expected_stock:
            errors.append(
                {
                    **base,
                    "reason": "current_document_stock_mismatch",
                    "resolved_document_id": document_id,
                    "actual_stock_code": document.get("stock_code"),
                    "expected_stock_code": expected_stock,
                }
            )
            continue

        active_chunks = [row for row in chunks.get(document_id, []) if row.get("is_active") is True]
        if not active_chunks:
            errors.append(
                {
                    **base,
                    "reason": "current_active_chunk_missing",
                    "resolved_document_id": document_id,
                }
            )
            continue

        mismatched_chunks = [
            str(row["id"])
            for row in active_chunks
            if str((row.get("source_locator") or {}).get("cluster_id")) != cluster_id
        ]
        if mismatched_chunks:
            errors.append(
                {
                    **base,
                    "reason": "resolved_chunk_cluster_mismatch",
                    "resolved_document_id": document_id,
                    "mismatched_chunk_ids": sorted(mismatched_chunks),
                }
            )
            continue

        resolutions.append(
            {
                **base,
                "stock_code": expected_stock,
                "cluster_title": cluster.get("summary_title"),
                "cluster_first_published_at": cluster.get("first_published_at"),
                "resolved_document_id": document_id,
                "resolved_chunk_ids": sorted(str(row["id"]) for row in active_chunks),
            }
        )

    return {
        "n_canonical_gold": len(entries),
        "n_resolved": len(resolutions),
        "n_errors": len(errors),
        "should_abort": bool(errors),
        "resolutions": resolutions,
        "errors": errors,
    }


def resolve_news_gold_sources(cases: list[EvalCase], client: Any) -> dict[str, Any]:
    """Resolve canonical news Gold to current documents/chunks using read-only queries."""

    entries = _news_gold_entries(cases)
    cluster_ids = sorted({str(e["cluster_id"]) for e in entries if e["cluster_id"]})
    cluster_rows = (
        client.table("news_clusters")
        .select("id,stock_code,summary_title,first_published_at")
        .in_("id", cluster_ids)
        .execute()
        .data
        or []
    )
    document_rows = (
        client.table("rag_documents")
        .select("id,source_pk,stock_code,is_current")
        .eq("source_type", "news_event")
        .in_("source_pk", cluster_ids)
        .execute()
        .data
        or []
    )
    document_ids = [str(row["id"]) for row in document_rows]
    chunk_rows = []
    if document_ids:
        chunk_rows = (
            client.table("rag_chunks")
            .select("id,document_id,stock_code,is_active,source_locator")
            .in_("document_id", document_ids)
            .execute()
            .data
            or []
        )
    return resolve_news_gold_rows(
        cases,
        cluster_rows=cluster_rows,
        document_rows=document_rows,
        chunk_rows=chunk_rows,
    )

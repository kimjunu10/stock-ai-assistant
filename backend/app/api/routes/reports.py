"""Broker research-report listing and private PDF download routes."""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from supabase import Client

from app.db.client import get_supabase_client
from app.schemas.reports import ResearchReportItem, ResearchReportList
from app.sources.prices import SUPPORTED_STOCK_CODES

router = APIRouter(prefix="/stocks", tags=["reports"])
SIGNED_URL_TTL_SECONDS = 300


def _nfc(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip()


def _download_filename(row: dict[str, Any]) -> str:
    parts = [
        _nfc(row.get("report_date")),
        _nfc(row.get("broker")),
        _nfc(row.get("title")),
    ]
    stem = "_".join(part for part in parts if part)
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", stem).strip(" ._")
    return f"{stem[:180] or 'research-report'}.pdf"


def _validate_stock_code(stock_code: str) -> None:
    if stock_code not in SUPPORTED_STOCK_CODES:
        raise HTTPException(status_code=404, detail="현재는 지정된 5개 종목만 제공하고 있어요.")


@router.get("/{stock_code}/reports", response_model=ResearchReportList)
def get_reports(
    stock_code: str,
    client: Annotated[Client, Depends(get_supabase_client)],
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ResearchReportList:
    """Return report metadata without exposing private Storage paths."""

    _validate_stock_code(stock_code)
    response = (
        client.table("research_reports")
        .select(
            "id,stock_code,broker,title,report_date,investment_opinion,page_count",
            count="exact",
        )
        .eq("stock_code", stock_code)
        .in_("parse_status", ["success", "partial"])
        .order("report_date", desc=True)
        .order("id")
        .range(offset, offset + limit - 1)
        .execute()
    )
    items = [
        ResearchReportItem(
            id=str(row["id"]),
            stockCode=str(row["stock_code"]),
            broker=_nfc(row.get("broker")) or "증권사",
            title=_nfc(row.get("title")) or "제목 없는 리포트",
            date=str(row.get("report_date") or ""),
            opinion=_nfc(row.get("investment_opinion")) or None,
            pageCount=int(row["page_count"]) if row.get("page_count") is not None else None,
            downloadUrl=f"/api/stocks/{stock_code}/reports/{row['id']}/download",
        )
        for row in response.data or []
    ]
    total = int(response.count or 0)
    return ResearchReportList(
        stockCode=stock_code,
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        hasMore=offset + len(items) < total,
    )


@router.get("/{stock_code}/reports/{report_id}/download")
def download_report(
    stock_code: str,
    report_id: str,
    client: Annotated[Client, Depends(get_supabase_client)],
) -> RedirectResponse:
    """Redirect to a short-lived signed URL for one private report PDF."""

    _validate_stock_code(stock_code)
    response = (
        client.table("research_reports")
        .select("id,stock_code,broker,title,report_date,storage_bucket,storage_path")
        .eq("id", report_id)
        .eq("stock_code", stock_code)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="해당 증권사 리포트를 찾지 못했어요.")

    row = rows[0]
    try:
        signed = client.storage.from_(str(row["storage_bucket"])).create_signed_url(
            str(row["storage_path"]),
            SIGNED_URL_TTL_SECONDS,
            {"download": _download_filename(row)},
        )
    except Exception as exc:  # noqa: BLE001 - Storage SDK 오류를 API 경계에서 변환
        raise HTTPException(
            status_code=502,
            detail="리포트 다운로드 링크를 만들지 못했어요.",
        ) from exc
    signed_url = signed.get("signedURL") or signed.get("signedUrl")
    if not signed_url:
        raise HTTPException(status_code=502, detail="리포트 다운로드 링크를 만들지 못했어요.")
    return RedirectResponse(url=str(signed_url), status_code=307)


@router.get("/{stock_code}/reports/{report_id}/view")
def view_report(
    stock_code: str,
    report_id: str,
    client: Annotated[Client, Depends(get_supabase_client)],
) -> RedirectResponse:
    """Redirect to an inline short-lived signed URL for PDF preview."""

    _validate_stock_code(stock_code)
    response = (
        client.table("research_reports")
        .select("id,stock_code,storage_bucket,storage_path")
        .eq("id", report_id)
        .eq("stock_code", stock_code)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="해당 증권사 리포트를 찾지 못했어요.")

    row = rows[0]
    try:
        signed = client.storage.from_(str(row["storage_bucket"])).create_signed_url(
            str(row["storage_path"]),
            SIGNED_URL_TTL_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 - Storage SDK 오류를 API 경계에서 변환
        raise HTTPException(
            status_code=502,
            detail="리포트 미리보기 링크를 만들지 못했어요.",
        ) from exc
    signed_url = signed.get("signedURL") or signed.get("signedUrl")
    if not signed_url:
        raise HTTPException(status_code=502, detail="리포트 미리보기 링크를 만들지 못했어요.")
    return RedirectResponse(url=str(signed_url), status_code=307)

"""DART disclosure API routes."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from app.db.client import get_supabase_client
from app.schemas.fundamentals import DisclosureSummary, DisclosureSummaryItem
from app.sources.prices import SUPPORTED_STOCK_CODES

router = APIRouter(prefix="/stocks", tags=["disclosures"])


@router.get("/{stock_code}/disclosures", response_model=DisclosureSummary)
def get_disclosures(
    stock_code: str,
    client: Annotated[Client, Depends(get_supabase_client)],
    limit: Annotated[int, Query(ge=1, le=20)] = 3,
) -> DisclosureSummary:
    """Return the latest disclosures already collected from Open DART."""

    if stock_code not in SUPPORTED_STOCK_CODES:
        raise HTTPException(status_code=404, detail="현재는 지정된 5개 종목만 제공하고 있어요.")

    response = (
        client.table("disclosures")
        .select("id,title,disclosed_at,disclosure_type,viewer_url")
        .eq("stock_code", stock_code)
        .order("disclosed_at", desc=True)
        .order("id")
        .limit(limit)
        .execute()
    )
    items = []
    for row in response.data or []:
        disclosed_at = datetime.fromisoformat(str(row["disclosed_at"]).replace("Z", "+00:00"))
        items.append(
            DisclosureSummaryItem(
                id=int(row["id"]),
                stockCode=stock_code,
                type=str(row.get("disclosure_type") or "공시"),
                title=str(row["title"]),
                date=disclosed_at.date().isoformat().replace("-", "."),
                viewerUrl=str(row["viewer_url"]),
            )
        )
    return DisclosureSummary(stockCode=stock_code, items=items)

"""News-cluster API routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from app.core.config import settings
from app.db.client import get_supabase_client
from app.schemas.clusters import (
    NewsClusterItem,
    NewsClusterList,
    NewsClusterSource,
    SelectionExplanationRequest,
    SelectionExplanationResponse,
)
from app.sources.prices import SUPPORTED_STOCK_CODES
from experiments.exp_b_factual_summaries.summarize import call_solar_easy_explain

router = APIRouter(prefix="/clusters", tags=["clusters"])


def _source_from_assignment(row: dict[str, Any]) -> NewsClusterSource | None:
    article = row.get("articles") or {}
    url = article.get("final_url") or article.get("original_url")
    if not url:
        return None
    return NewsClusterSource(
        articleId=int(row["article_id"]),
        title=str(article.get("title") or "원문 기사"),
        press=str(article.get("press") or "언론사 미상"),
        url=str(url),
        publishedAt=str(article.get("published_at") or ""),
        description=str(article.get("description") or ""),
        imageUrl=article.get("image_url") or None,
    )


@router.get("", response_model=NewsClusterList)
def get_clusters(
    client: Annotated[Client, Depends(get_supabase_client)],
    stock_code: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> NewsClusterList:
    """Return factual summaries and original sources for completed clusters."""

    if stock_code is not None and stock_code not in SUPPORTED_STOCK_CODES:
        raise HTTPException(status_code=404, detail="현재는 지정된 5개 종목만 제공하고 있어요.")

    query = (
        client.table("news_clusters")
        .select(
            "id,stock_code,kind,summary_title,easy_explanation,factual_body,"
            "article_count,last_active_at"
        )
        .eq("summary_status", "success")
        .order("last_active_at", desc=True)
        .limit(limit)
    )
    if stock_code is not None:
        query = query.eq("stock_code", stock_code)
    clusters = list(query.execute().data or [])
    if not clusters:
        return NewsClusterList(items=[])

    cluster_ids = [int(row["id"]) for row in clusters]
    assignment_response = (
        client.table("news_cluster_assignments")
        .select(
            "cluster_id,article_id,articles!inner("
            "title,description,press,final_url,original_url,published_at,image_url)"
        )
        .in_("cluster_id", cluster_ids)
        .in_("status", ["assigned_new", "assigned_existing"])
        .execute()
    )
    sources_by_cluster: dict[int, list[NewsClusterSource]] = {}
    for assignment in assignment_response.data or []:
        source = _source_from_assignment(assignment)
        if source is not None:
            sources_by_cluster.setdefault(int(assignment["cluster_id"]), []).append(source)

    items = []
    for row in clusters:
        cluster_id = int(row["id"])
        sources = sorted(
            sources_by_cluster.get(cluster_id, []),
            key=lambda source: source.publishedAt,
            reverse=True,
        )
        items.append(
            NewsClusterItem(
                id=cluster_id,
                stockCode=str(row["stock_code"]),
                kind=str(row["kind"]),
                title=str(row.get("summary_title") or ""),
                easyExplanation=str(row.get("easy_explanation") or ""),
                factualBody=str(row.get("factual_body") or ""),
                articleCount=int(row.get("article_count") or len(sources)),
                publishedAt=str(row["last_active_at"]),
                sources=sources,
            )
        )
    return NewsClusterList(items=items)


@router.post("/explain-selection", response_model=SelectionExplanationResponse)
def explain_selection(
    payload: SelectionExplanationRequest,
    client: Annotated[Client, Depends(get_supabase_client)],
) -> SelectionExplanationResponse:
    """Explain selected cluster text in beginner-friendly Korean using Solar."""

    selected_text = " ".join(payload.text.split()).strip()
    if not 2 <= len(selected_text) <= 500:
        raise HTTPException(
            status_code=422,
            detail="설명할 문구는 2자 이상 500자 이하로 선택해 주세요.",
        )
    response = (
        client.table("news_clusters")
        .select("summary_title,easy_explanation,factual_body")
        .eq("id", payload.clusterId)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="뉴스 사건 정리를 찾지 못했어요.")
    row = rows[0]
    context = "\n".join(
        str(row.get(field) or "")
        for field in ("summary_title", "easy_explanation", "factual_body")
    )
    parsed, meta = call_solar_easy_explain(settings.upstage_api_key, selected_text, context)
    if not meta.get("ok") or not meta.get("parse_success"):
        raise HTTPException(
            status_code=502,
            detail="AI가 문구를 설명하지 못했어요. 잠시 후 다시 시도해 주세요.",
        )
    return SelectionExplanationResponse(
        selectedText=selected_text,
        explanation=parsed["explanation"],
    )

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
    RelatedArticle,
    RelatedArticleList,
    SelectionExplanationRequest,
    SelectionExplanationResponse,
)
from app.sources.prices import SUPPORTED_STOCK_CODES
from experiments.exp_b_factual_summaries.summarize import call_solar_easy_explain

router = APIRouter(prefix="/clusters", tags=["clusters"])


def _active_version(client: Client) -> str | None:
    """API 가 읽을 활성 clustering_version. 없으면 None(모든 버전 = 하위호환)."""
    try:
        resp = client.table("news_pipeline_state").select("active_version").eq("id", 1).execute()
    except Exception:  # noqa: BLE001 - 상태 테이블이 없던 구버전 호환
        return None
    rows = resp.data or []
    return rows[0]["active_version"] if rows else None


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
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NewsClusterList:
    """Return factual summaries and original sources for completed clusters."""

    if stock_code is not None and stock_code not in SUPPORTED_STOCK_CODES:
        raise HTTPException(status_code=404, detail="현재는 지정된 5개 종목만 제공하고 있어요.")

    query = (
        client.table("news_clusters")
        .select(
            "id,stock_code,kind,summary_title,easy_explanation,factual_body,"
            "article_count,last_active_at",
            count="exact",
        )
        .eq("summary_status", "success")
        .order("last_active_at", desc=True)
    )
    active_version = _active_version(client)
    if active_version:
        # 활성 버전(v1 또는 v2)만 event_clusters 로 노출해 버전 혼합을 막는다.
        query = query.eq("clustering_version", active_version)
    if stock_code is not None:
        query = query.eq("stock_code", stock_code)
    cluster_response = query.range(offset, offset + limit - 1).execute()
    clusters = list(cluster_response.data or [])
    total = int(cluster_response.count or 0)
    if not clusters:
        return NewsClusterList(items=[], total=total, offset=offset, limit=limit, hasMore=False)

    cluster_ids = [int(row["id"]) for row in clusters]
    assignments: list[dict[str, Any]] = []
    assignment_offset = 0
    assignment_page_size = 1000
    while True:
        assignment_response = (
            client.table("news_cluster_assignments")
            .select(
                "cluster_id,article_id,articles!inner("
                "title,description,press,final_url,original_url,published_at,image_url)"
            )
            .in_("cluster_id", cluster_ids)
            .in_("status", ["assigned_new", "assigned_existing"])
            .range(assignment_offset, assignment_offset + assignment_page_size - 1)
            .execute()
        )
        page = list(assignment_response.data or [])
        assignments.extend(page)
        if len(page) < assignment_page_size:
            break
        assignment_offset += assignment_page_size

    sources_by_cluster: dict[int, list[NewsClusterSource]] = {}
    for assignment in assignments:
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
    return NewsClusterList(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        hasMore=offset + len(items) < total,
    )


@router.get("/related", response_model=RelatedArticleList)
def get_related_articles(
    client: Annotated[Client, Depends(get_supabase_client)],
    stock_code: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RelatedArticleList:
    """사건 클러스터에 넣지 않은 개별 관련 뉴스(v2 역할분류에서 event_eligible=false).

    칼럼·시장 종합·주가 반응·전망/해설·단순 언급 등. 웹사이트에서 뉴스가 사라지지 않도록
    개별 기사로 반환한다. (역할 분류 미완료 환경에서는 빈 목록을 반환한다.)
    """

    if stock_code is not None and stock_code not in SUPPORTED_STOCK_CODES:
        raise HTTPException(status_code=404, detail="현재는 지정된 5개 종목만 제공하고 있어요.")

    query = (
        client.table("article_stocks")
        .select(
            "article_id,stock_code,article_role,"
            "articles!inner(title,description,press,final_url,original_url,"
            "published_at,image_url)",
            count="exact",
        )
        .eq("relevance", "relevant")
        .eq("event_eligible", False)
        .order("published_at", desc=True, foreign_table="articles")
    )
    if stock_code is not None:
        query = query.eq("stock_code", stock_code)
    response = query.range(offset, offset + limit - 1).execute()
    rows = list(response.data or [])
    total = int(response.count or 0)

    items = []
    for row in rows:
        article = row.get("articles") or {}
        url = article.get("final_url") or article.get("original_url")
        if not url:
            continue
        items.append(
            RelatedArticle(
                articleId=int(row["article_id"]),
                stockCode=str(row["stock_code"]),
                articleRole=str(row.get("article_role") or ""),
                title=str(article.get("title") or "원문 기사"),
                press=str(article.get("press") or "언론사 미상"),
                url=str(url),
                publishedAt=str(article.get("published_at") or ""),
                description=str(article.get("description") or ""),
                imageUrl=article.get("image_url") or None,
            )
        )
    return RelatedArticleList(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        hasMore=offset + len(items) < total,
    )


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
        str(row.get(field) or "") for field in ("summary_title", "easy_explanation", "factual_body")
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

"""Public response models for summarized news clusters."""

from pydantic import BaseModel


class NewsClusterSource(BaseModel):
    articleId: int
    title: str
    press: str
    url: str
    publishedAt: str
    description: str = ""
    imageUrl: str | None = None


class NewsClusterItem(BaseModel):
    id: int
    stockCode: str
    kind: str
    title: str
    easyExplanation: str
    factualBody: str
    articleCount: int
    publishedAt: str
    sources: list[NewsClusterSource]


class NewsClusterList(BaseModel):
    items: list[NewsClusterItem]
    total: int
    offset: int
    limit: int
    hasMore: bool


class RelatedArticle(BaseModel):
    """사건 클러스터에 넣지 않는 개별 관련 뉴스(칼럼·시장·주가·해설·단순언급 등)."""

    articleId: int
    stockCode: str
    articleRole: str
    title: str
    press: str
    url: str
    publishedAt: str
    description: str = ""
    imageUrl: str | None = None


class RelatedArticleList(BaseModel):
    items: list[RelatedArticle]
    total: int
    offset: int
    limit: int
    hasMore: bool


class SelectionExplanationRequest(BaseModel):
    clusterId: int
    text: str


class SelectionExplanationResponse(BaseModel):
    selectedText: str
    explanation: str

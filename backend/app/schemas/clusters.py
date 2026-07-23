"""Public response models for summarized news clusters."""

from pydantic import BaseModel, Field


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
    sentimentLabel: str | None = None
    sentimentScore: float | None = None
    sentimentPositiveScore: float | None = None
    sentimentNeutralScore: float | None = None
    sentimentNegativeScore: float | None = None


class StockIssueBriefItem(BaseModel):
    text: str
    clusterIds: list[int] = Field(default_factory=list)


class StockIssueBrief(BaseModel):
    stockCode: str
    positiveItems: list[StockIssueBriefItem] = Field(default_factory=list)
    negativeItems: list[StockIssueBriefItem] = Field(default_factory=list)
    generatedAt: str


class NewsClusterList(BaseModel):
    items: list[NewsClusterItem]
    total: int
    offset: int
    limit: int
    hasMore: bool
    issueBrief: StockIssueBrief | None = None


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

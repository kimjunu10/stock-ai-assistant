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


class SelectionExplanationRequest(BaseModel):
    clusterId: int
    text: str


class SelectionExplanationResponse(BaseModel):
    selectedText: str
    explanation: str

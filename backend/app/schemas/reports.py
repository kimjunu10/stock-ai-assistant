"""Research-report API schemas."""

from pydantic import BaseModel


class ResearchReportItem(BaseModel):
    id: str
    stockCode: str
    broker: str
    title: str
    date: str
    opinion: str | None = None
    pageCount: int | None = None
    downloadUrl: str


class ResearchReportList(BaseModel):
    stockCode: str
    items: list[ResearchReportItem]
    total: int
    offset: int
    limit: int
    hasMore: bool

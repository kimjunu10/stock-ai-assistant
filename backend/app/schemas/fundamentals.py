"""Public response models for DART-backed stock fundamentals."""

from pydantic import BaseModel


class FinancialSummaryItem(BaseModel):
    account: str
    display: str
    yoyPct: float | None
    note: str


class FinancialSummary(BaseModel):
    stockCode: str
    source: str = "DART"
    items: list[FinancialSummaryItem]


class DisclosureSummaryItem(BaseModel):
    id: int
    stockCode: str
    type: str
    title: str
    date: str
    source: str = "DART"
    viewerUrl: str


class DisclosureSummary(BaseModel):
    stockCode: str
    source: str = "DART"
    items: list[DisclosureSummaryItem]

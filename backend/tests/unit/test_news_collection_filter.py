from app.jobs.news import collect_search_results
from app.schemas.news import NewsSearchItem, NewsSearchResult


def _item(url: str) -> NewsSearchItem:
    return NewsSearchItem(
        title="기사",
        original_url=url,
        naver_url="",
        description="설명",
        published_at="2026-07-22T00:00:00+00:00",
    )


class FakeNaver:
    def search_latest(self, query: str, max_results: int) -> NewsSearchResult:
        return NewsSearchResult(
            query=query,
            items=[
                _item(f"https://yna.co.kr/{query}"),
                _item(f"https://example.com/{query}"),
            ],
            pages_requested=1,
            raw_items_received=2,
            api_total=2,
        )


class RecordingRepo:
    def __init__(self) -> None:
        self.urls_by_stock: dict[str, list[str]] = {}

    def upsert_search_items(self, *, stock_code: str, query: str, items) -> dict[str, int]:
        del query
        self.urls_by_stock[stock_code] = [item.original_url for item in items]
        return {"received": len(items), "unique": len(items), "linked": len(items)}


def test_collect_search_results_filters_before_persistence() -> None:
    repo = RecordingRepo()

    completed, errors = collect_search_results(
        repo=repo,
        naver=FakeNaver(),
        max_per_stock=100,
        stock_rounds=1,
    )

    assert errors == {}
    assert set(repo.urls_by_stock) == set(completed)
    assert all(len(urls) == 1 for urls in repo.urls_by_stock.values())
    assert all(urls[0].startswith("https://yna.co.kr/") for urls in repo.urls_by_stock.values())
    assert all(summary["filtered_out"] == 1 for summary in completed.values())

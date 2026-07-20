from datetime import UTC, datetime
from email.utils import format_datetime

from app.core.config import Settings
from app.sources.naver_news import NaverNewsClient


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200
        self.text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls: list[dict] = []

    def get(self, _url: str, **kwargs) -> FakeResponse:
        self.calls.append(kwargs["params"])
        start = kwargs["params"]["start"]
        display = kwargs["params"]["display"]
        items = [
            {
                "title": f"<b>기사</b> {index}",
                "originallink": f"https://example.com/{index}",
                "link": f"https://n.news.naver.com/{index}",
                "description": "설명",
                "pubDate": format_datetime(datetime(2026, 7, 20, tzinfo=UTC)),
            }
            for index in range(start, start + display)
        ]
        return FakeResponse({"total": 1000, "items": items})

    def close(self) -> None:
        return None


def test_search_latest_paginates_until_requested_limit() -> None:
    session = FakeSession()
    client = NaverNewsClient(
        Settings(naver_client_id="id", naver_client_secret="secret"),
        session=session,
    )

    result = client.search_latest("삼성전자", max_results=250)

    assert len(result.items) == 250
    assert result.raw_items_received == 250
    assert [call["start"] for call in session.calls] == [1, 101, 201]
    assert [call["display"] for call in session.calls] == [100, 100, 50]

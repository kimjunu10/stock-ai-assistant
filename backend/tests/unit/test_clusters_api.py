from datetime import date

from app.api.routes.clusters import get_clusters
from experiments.exp_b_factual_summaries.summarize import _parse_easy_explanation


class FakeQuery:
    def __init__(self, rows):
        self.data = [dict(row) for row in rows]
        self.count = len(self.data)

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self.data = [row for row in self.data if row.get(field) == value]
        return self

    def in_(self, field, values):
        self.data = [row for row in self.data if row.get(field) in values]
        return self

    def gte(self, field, value):
        self.data = [row for row in self.data if row.get(field, "") >= value]
        return self

    def lte(self, field, value):
        self.data = [row for row in self.data if row.get(field, "") <= value]
        return self

    def order(self, field, desc=False):
        self.data.sort(key=lambda row: row.get(field, ""), reverse=desc)
        return self

    def limit(self, value):
        self.data = self.data[:value]
        return self

    def range(self, start, end):
        self.count = len(self.data)
        self.data = self.data[start : end + 1]
        return self

    def execute(self):
        return self


class FakeClient:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeQuery(self.tables[name])


def test_clusters_api_maps_summary_and_original_sources() -> None:
    client = FakeClient(
        {
            "news_clusters": [
                {
                    "id": 9,
                    "stock_code": "042660",
                    "kind": "company",
                    "summary_title": "한화오션, 함정 건조 계약",
                    "easy_explanation": "쉽게 말해 회사가 새 일감을 확보했다는 내용이에요.",
                    "factual_body": "한화오션이 함정 건조 계약을 체결했습니다.",
                    "article_count": 2,
                    "last_active_at": "2026-07-20T03:00:00+00:00",
                    "summary_status": "success",
                    "sentiment_label": "positive",
                    "sentiment_score": 0.91,
                    "sentiment_positive_score": 0.91,
                    "sentiment_neutral_score": 0.07,
                    "sentiment_negative_score": 0.02,
                }
            ],
            "news_cluster_assignments": [
                {
                    "cluster_id": 9,
                    "article_id": 31,
                    "status": "assigned_new",
                    "articles": {
                        "title": "한화오션 계약 체결",
                        "description": "새 일감을 확보했다는 내용입니다.",
                        "press": "연합뉴스",
                        "final_url": "https://example.com/final",
                        "original_url": "https://example.com/original",
                        "published_at": "2026-07-20T02:00:00+00:00",
                        "image_url": "https://example.com/article.jpg",
                    },
                }
            ],
        }
    )

    response = get_clusters(client, "042660", 20)

    assert response.items[0].title == "한화오션, 함정 건조 계약"
    assert response.items[0].easyExplanation.startswith("쉽게 말해")
    assert response.items[0].factualBody.startswith("한화오션")
    assert response.items[0].sources[0].press == "연합뉴스"
    assert response.items[0].sources[0].url == "https://example.com/final"
    assert response.items[0].sources[0].description.startswith("새 일감")
    assert response.items[0].sources[0].imageUrl == "https://example.com/article.jpg"
    assert response.items[0].sentimentLabel == "positive"
    assert response.items[0].sentimentScore == 0.91
    assert response.items[0].sentimentPositiveScore == 0.91
    assert response.items[0].sentimentNeutralScore == 0.07
    assert response.items[0].sentimentNegativeScore == 0.02
    assert response.total == 1
    assert response.hasMore is False


def test_clusters_api_filters_by_korean_published_date() -> None:
    client = FakeClient(
        {
            "news_clusters": [
                {
                    "id": 1,
                    "stock_code": "005930",
                    "kind": "company",
                    "summary_title": "오늘 뉴스",
                    "easy_explanation": "오늘 설명",
                    "factual_body": "오늘 본문",
                    "article_count": 1,
                    "last_active_at": "2026-07-22T15:30:00+00:00",
                    "summary_status": "success",
                },
                {
                    "id": 2,
                    "stock_code": "005930",
                    "kind": "company",
                    "summary_title": "어제 뉴스",
                    "easy_explanation": "어제 설명",
                    "factual_body": "어제 본문",
                    "article_count": 1,
                    "last_active_at": "2026-07-22T14:59:00+00:00",
                    "summary_status": "success",
                },
            ],
            "news_cluster_assignments": [],
        }
    )

    response = get_clusters(client, "005930", 20, 0, date(2026, 7, 23))

    assert [item.id for item in response.items] == [1]
    assert response.total == 1


def test_easy_explanation_parser_accepts_json_and_rejects_empty_text() -> None:
    parsed, ok = _parse_easy_explanation(
        '{"explanation":"유상증자는 새 주식을 발행하는 일이에요."}'
    )
    assert ok is True
    assert parsed["explanation"].startswith("유상증자는")
    assert _parse_easy_explanation('{"explanation":""}')[1] is False

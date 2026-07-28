"""Phase 7 공개 UI payload는 검증된 ToolResult만 사용한다."""

from app.services.agent_qa import _build_ui_payload


def test_price_payload_uses_tool_values_and_sources_without_recalculation():
    sources, visualizations, warnings = _build_ui_payload(
        [
            {
                "_tool_name": "get_stock_prices",
                "status": "ok",
                "data": {
                    "quote": {"price": 100_000, "currency": "KRW", "trading_day": "2026-07-24"},
                    "period": {"return_pct": 2.5},
                    "daily": [
                        {"trading_day": "2026-07-23", "close": 98_000},
                        {"trading_day": "2026-07-24", "close": 100_000},
                    ],
                },
                "sources": [
                    {
                        "source_id": "price:005930:2026-07-24",
                        "source_type": "price",
                        "title": "005930 주가",
                        "locator": {"provider": "toss"},
                    }
                ],
                "warnings": [],
            }
        ]
    )
    assert sources[0]["source_id"] == "price:005930:2026-07-24"
    assert visualizations == [
        {
            "type": "price_line",
            "title": "2026-07-23 ~ 2026-07-24 주가",
            "data": {
                "points": [
                    {"trading_day": "2026-07-23", "close": 98_000},
                    {"trading_day": "2026-07-24", "close": 100_000},
                ],
                "quote": {
                    "price": 100_000,
                    "currency": "KRW",
                    "trading_day": "2026-07-24",
                },
                "period": {"return_pct": 2.5},
                "sampled": False,
            },
            "source_ids": ["price:005930:2026-07-24"],
        }
    ]
    assert warnings == []


def test_visualization_is_not_created_without_source():
    sources, visualizations, _ = _build_ui_payload(
        [
            {
                "_tool_name": "get_financial_facts",
                "status": "ok",
                "data": {"facts": [{"label": "영업이익", "value_won": 1}]},
                "sources": [],
            }
        ]
    )
    assert sources == []
    assert visualizations == []


def test_news_tool_creates_cards_with_the_server_date_window():
    _, visualizations, _ = _build_ui_payload(
        [
            {
                "_tool_name": "search_news",
                "status": "ok",
                "data": {
                    "news": [
                        {
                            "source_id": "news-1",
                            "title": "반도체 공급 확대",
                            "published_at": "2026-07-25T09:00:00+09:00",
                            "publisher": "테스트뉴스",
                            "url": "https://example.com/news-1",
                        }
                    ],
                    "applied_filters": {
                        "date_from": "2026-07-23",
                        "date_to": "2026-07-25",
                    },
                },
                "sources": [
                    {
                        "source_id": "news-1",
                        "source_type": "news_event",
                        "title": "반도체 공급 확대",
                        "locator": {},
                    }
                ],
                "warnings": [],
            }
        ]
    )
    assert visualizations == [
        {
            "type": "news_cards",
            "title": "해당 기간 뉴스",
            "data": {
                "items": [
                    {
                        "source_id": "news-1",
                        "title": "반도체 공급 확대",
                        "published_at": "2026-07-25T09:00:00+09:00",
                        "publisher": "테스트뉴스",
                        "url": "https://example.com/news-1",
                    }
                ],
                "date_from": "2026-07-23",
                "date_to": "2026-07-25",
            },
            "source_ids": ["news-1"],
        }
    ]


def test_price_line_prefers_full_daily_over_summary():
    """UI 선그래프는 요약(daily)이 아니라 거래일별 전체(daily_full)를 우선 사용한다."""
    full = [{"trading_day": f"2026-07-{d:02d}", "close": 100 + d} for d in range(1, 21)]
    _, visualizations, _ = _build_ui_payload(
        [
            {
                "_tool_name": "get_stock_prices",
                "status": "ok",
                "data": {
                    "quote": {"price": 1},
                    "period": None,
                    "daily": full[:3] + full[-3:],  # 6점 요약
                    "daily_full": full,  # 20점 UI용
                },
                "sources": [{"source_id": "price:x", "source_type": "price", "locator": {}}],
                "warnings": [],
            }
        ]
    )
    assert visualizations[0]["type"] == "price_line"
    assert visualizations[0]["data"]["points"] == full  # 전체 20점


def test_event_timeline_only_when_news_and_disclosures_both_present():
    news = {
        "_tool_name": "search_news",
        "status": "ok",
        "data": {
            "news": [
                {
                    "source_id": "n1",
                    "title": "뉴스A",
                    "published_at": "2026-07-25T09:00:00+09:00",
                    "publisher": "언론",
                }
            ]
        },
        "sources": [{"source_id": "n1", "source_type": "news_event", "locator": {}}],
        "warnings": [],
    }
    disc = {
        "_tool_name": "search_disclosures",
        "status": "ok",
        "data": {
            "disclosures": [
                {"rcept_no": "R1", "title": "공시A", "disclosed_at": "2026-07-21T09:00:00+09:00"}
            ]
        },
        "sources": [{"source_id": "R1", "source_type": "dart_document", "locator": {}}],
        "warnings": [],
    }
    # 둘 다 있으면 타임라인 생성 + 최신순
    _, viz_both, _ = _build_ui_payload([news, disc])
    timelines = [v for v in viz_both if v["type"] == "event_timeline"]
    assert len(timelines) == 1
    events = timelines[0]["data"]["events"]
    assert {e["kind"] for e in events} == {"news", "disclosure"}
    assert events[0]["at"] >= events[-1]["at"]  # 최신순
    # 뉴스만 있으면 타임라인 없음
    _, viz_news_only, _ = _build_ui_payload([news])
    assert not any(v["type"] == "event_timeline" for v in viz_news_only)


def test_news_cards_carry_sentiment_and_stock_code_when_present():
    _, visualizations, _ = _build_ui_payload(
        [
            {
                "_tool_name": "search_news",
                "status": "ok",
                "data": {
                    "news": [
                        {
                            "source_id": "n1",
                            "title": "악재",
                            "published_at": "2026-07-24T09:00:00+09:00",
                            "sentiment": "negative",
                            "stock_code": "005930",
                        }
                    ]
                },
                "sources": [{"source_id": "n1", "source_type": "news_event", "locator": {}}],
                "warnings": [],
            }
        ]
    )
    item = visualizations[0]["data"]["items"][0]
    assert item["sentiment"] == "negative"
    assert item["stock_code"] == "005930"


def test_price_driver_news_cards_describe_the_filtered_direction():
    _, visualizations, _ = _build_ui_payload(
        [
            {
                "_tool_name": "search_news",
                "status": "ok",
                "data": {
                    "news": [
                        {
                            "source_id": "n1",
                            "title": "주가 하락 관련 악재",
                            "published_at": "2026-07-28T09:00:00+09:00",
                            "sentiment": "negative",
                            "stock_code": "005930",
                        }
                    ],
                    "applied_filters": {
                        "date_from": "2026-07-28",
                        "date_to": "2026-07-28",
                        "sentiment": "negative",
                        "purpose": "price_driver_down",
                    },
                },
                "sources": [{"source_id": "n1", "source_type": "news_event", "locator": {}}],
                "warnings": [],
            }
        ]
    )

    assert visualizations[0]["title"] == "하락 관련 뉴스"


def test_no_data_and_error_remain_distinct_and_do_not_make_empty_charts():
    _, visualizations, warnings = _build_ui_payload(
        [
            {
                "_tool_name": "get_stock_prices",
                "status": "no_data",
                "data": {},
                "sources": [],
                "warnings": ["확인 가능한 자료가 없습니다."],
            },
            {
                "_tool_name": "search_news",
                "status": "error",
                "data": {},
                "sources": [],
                "warnings": ["내부 조회 오류(DatabaseError)가 발생했습니다."],
            },
        ]
    )
    assert visualizations == []
    assert warnings == [
        "확인 가능한 자료가 없습니다.",
        "데이터를 불러오는 중 문제가 발생했습니다.",
    ]

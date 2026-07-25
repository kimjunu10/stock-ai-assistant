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
            "title": "실제 주가 흐름",
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

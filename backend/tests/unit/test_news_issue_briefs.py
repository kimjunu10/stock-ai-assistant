from app.services.news_issue_briefs import (
    _parse_issue_briefs,
    prepare_issue_brief_inputs,
    refresh_stock_issue_briefs,
)


def _rows():
    return [
        {
            "id": 11,
            "stock_code": "005930",
            "easy_explanation": "삼성전자가 AI 기기 신제품을 공개했어요. 판매는 다음 달 시작해요.",
            "article_count": 8,
            "last_active_at": "2026-07-23T10:00:00+00:00",
            "sentiment_label": "positive",
            "sentiment_score": 0.91,
        },
        {
            "id": 12,
            "stock_code": "005930",
            "easy_explanation": "레버리지 ETF 규제가 강화됐어요.",
            "article_count": 4,
            "last_active_at": "2026-07-23T10:10:00+00:00",
            "sentiment_label": "negative",
            "sentiment_score": 0.82,
        },
        {
            "id": 13,
            "stock_code": "005930",
            "easy_explanation": "확신도가 낮아 제외돼야 해요.",
            "article_count": 10,
            "last_active_at": "2026-07-23T10:20:00+00:00",
            "sentiment_label": "negative",
            "sentiment_score": 0.55,
        },
    ]


def test_prepare_issue_brief_inputs_uses_first_sentence_and_confident_labels():
    prepared = prepare_issue_brief_inputs(_rows(), {"005930": "삼성전자"})

    assert prepared["005930"]["positive"][0]["text"] == "삼성전자가 AI 기기 신제품을 공개했어요."
    assert [item["cluster_id"] for item in prepared["005930"]["negative"]] == [12]
    assert len(prepared["005930"]["source_hash"]) == 64


def test_issue_brief_parser_keeps_only_allowed_cluster_ids():
    inputs = prepare_issue_brief_inputs(_rows(), {"005930": "삼성전자"})
    raw = """
    {"stocks":{"005930":{
      "positive":[{"text":"AI 기기 신제품 공개","cluster_ids":[11,999]}],
      "negative":[{"text":"레버리지 ETF 규제 강화","cluster_ids":[12]}]
    }}}
    """

    parsed, ok = _parse_issue_briefs(raw, inputs)

    assert ok is True
    assert parsed["005930"]["positive"][0]["clusterIds"] == [11]
    assert parsed["005930"]["negative"][0]["text"] == "레버리지 ETF 규제 강화"


def test_refresh_calls_solar_once_for_all_changed_stocks_and_then_skips():
    class Repo:
        def __init__(self):
            self.states = {}
            self.saved = []

        def get_today_issue_brief_candidates(self):
            return _rows()

        def get_stock_names(self):
            return {"005930": "삼성전자", "000660": "SK하이닉스"}

        def get_issue_brief_states(self, _stock_codes):
            return self.states

        def save_issue_brief(self, **values):
            self.saved.append(values)
            self.states[values["stock_code"]] = {"source_hash": values["source_hash"]}

    calls = []

    def fake_call(api_key, inputs):
        calls.append((api_key, sorted(inputs)))
        return (
            {
                "005930": {
                    "positive": [{"text": "AI 기기 신제품 공개", "clusterIds": [11]}],
                    "negative": [{"text": "레버리지 ETF 규제 강화", "clusterIds": [12]}],
                }
            },
            {"ok": True, "parse_success": True},
        )

    repo = Repo()
    first = refresh_stock_issue_briefs(repo, "test-key", call_fn=fake_call)
    second = refresh_stock_issue_briefs(repo, "test-key", call_fn=fake_call)

    assert calls == [("test-key", ["005930"])]
    assert first["issue_brief_calls"] == 1
    assert first["issue_briefs"] == 2  # 빈 SK하이닉스 상태도 저장해 전날 결과를 지운다.
    assert second["issue_brief_calls"] == 0
    assert second["issue_brief_skipped"] == 2

from __future__ import annotations

import json

from app.services.stock_reference_classifier import StockReferenceClassifier


class _FakeStructuredModel:
    def __init__(self, result):
        self.result = result
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return self.result


def test_classifier_sends_selected_context_and_parses_structured_result():
    model = _FakeStructuredModel({"relation": "none", "company_names": []})
    classifier = StockReferenceClassifier.__new__(StockReferenceClassifier)
    classifier._model = model

    result = classifier.classify(
        "가장 최근 공시는 뭐야?",
        selected_stock_code="005930",
        selected_stock_name="삼성전자",
        supported_stock_names=["삼성전자", "현대차"],
    )

    assert result.relation == "none"
    assert result.company_names == []
    assert "가장 최근 공시" in model.messages[0].content
    payload = json.loads(model.messages[1].content)
    assert payload["selected_stock_code"] == "005930"
    assert payload["selected_stock_name"] == "삼성전자"


def test_classifier_preserves_other_company_name_from_structured_result():
    model = _FakeStructuredModel({"relation": "other", "company_names": ["애플"]})
    classifier = StockReferenceClassifier.__new__(StockReferenceClassifier)
    classifier._model = model

    result = classifier.classify(
        "애플 실적 알려줘",
        selected_stock_code="005930",
        selected_stock_name="삼성전자",
        supported_stock_names=["삼성전자"],
    )

    assert result.relation == "other"
    assert result.company_names == ["애플"]

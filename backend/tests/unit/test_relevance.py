import pytest

from app.services.relevance import classify_stock_relevance


@pytest.mark.parametrize(
    ("stock_code", "field", "text"),
    [
        ("005930", "title", "삼성전자, 신제품을 공개했다"),
        ("005930", "body", "SAMSUNG ELECTRONICS posted quarterly results."),
        ("000660", "description", "하이닉스의 HBM 공급 소식"),
        ("034020", "body", "두산중공업에서 사명을 변경한 회사다."),
        ("042660", "title", "Hanwha-Ocean wins a new order"),
        ("005380", "description", "현대자동차가 북미 판매량을 발표했다."),
    ],
)
def test_safe_term_in_any_article_field_is_relevant(
    stock_code: str,
    field: str,
    text: str,
) -> None:
    fields = {"title": "", "body": "", "description": ""}
    fields[field] = text

    decision = classify_stock_relevance(stock_code=stock_code, **fields)

    assert decision.relevance == "relevant"
    assert decision.mention_count == 1
    assert field in decision.reason


def test_broad_group_name_is_not_a_safe_alias() -> None:
    decision = classify_stock_relevance(
        stock_code="005930",
        title="삼성, 취약계층 지원 확대",
        body="삼성 계열사가 공동으로 참여한다.",
        description="삼성이 신규 사업을 발표했다.",
    )

    assert decision.relevance == "irrelevant"
    assert decision.mention_count == 0


def test_overlapping_aliases_count_one_mention() -> None:
    decision = classify_stock_relevance(
        stock_code="000660",
        title="SK하이닉스 실적 발표",
        body="",
        description="",
    )

    assert decision.relevance == "relevant"
    assert decision.mention_count == 1


def test_stock_code_requires_numeric_boundaries() -> None:
    decision = classify_stock_relevance(
        stock_code="005930",
        title="주문번호 10059301 처리 완료",
        body="",
        description="",
    )

    assert decision.relevance == "irrelevant"


def test_unknown_stock_code_is_rejected() -> None:
    with pytest.raises(ValueError, match="No relevance rule configured"):
        classify_stock_relevance(
            stock_code="999999",
            title="",
            body="",
            description="",
        )

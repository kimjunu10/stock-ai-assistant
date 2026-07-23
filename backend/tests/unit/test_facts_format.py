"""재무 숫자 표기(format_won) + facts 프롬프트 블록 단위 테스트."""

from __future__ import annotations

from app.rag.prompting import build_facts_block, format_won
from app.services.facts import NumericFact


def test_format_won_trillion():
    # 133,873,444,000,000 원 ≈ 133.87조원
    assert "조원" in format_won(133_873_444_000_000)


def test_format_won_billion():
    assert "억원" in format_won(322_755_945_000)


def test_format_won_small_and_negative():
    assert format_won(5000) == "5,000원"
    assert format_won(-1_0000_0000_0000).startswith("-")


def test_facts_block_labels_value_kind():
    facts = [
        NumericFact(
            label="영업이익",
            value=57_232_797_000_000,
            unit="원",
            period="2026년 3분기보고서 누적",
            basis="연결",
            value_kind="actual_value",
            source_type="financials",
            source_key="k",
        )
    ]
    block = build_facts_block(facts)
    assert "영업이익" in block
    assert "실제 실적" in block  # value_kind 라벨
    assert "연결" in block


def test_facts_block_empty():
    assert build_facts_block([]) == ""

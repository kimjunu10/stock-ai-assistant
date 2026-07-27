"""Phase 8 라벨 검토 판정 단위 테스트 (DB·LLM 호출 없음).

확정 조건(§4)을 만족하지 않으면 needs_manual_review 를 유지해야 한다.
추측으로 정답을 채우지 않는지, 검색 1위를 자동 채택하지 않는지 검증한다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.eval.schema import EvalCase

_SPEC = importlib.util.spec_from_file_location(
    "phase8_review_labels",
    Path(__file__).resolve().parents[2] / "scripts" / "phase8_review_labels.py",
)
review = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(review)


def _news_case(basis: str, stock="005930") -> EvalCase:
    return EvalCase(
        id="news-x",
        type="뉴스 사건·영향",
        question="삼성전자 무슨 일 있었어?",
        stock_code=stock,
        required_tools=["search_news"],
        gold_sources=[{"source_type": "news_event", "ref": "제목"}],
        review_status="needs_manual_review",
        label_basis=basis,
    )


def _report_case(basis: str, stock="005930") -> EvalCase:
    return EvalCase(
        id="report-x",
        type="증권사 리포트",
        question="목표주가 얼마야?",
        stock_code=stock,
        required_tools=["search_research_reports"],
        gold_sources=[{"source_type": "research_report", "ref": "리포트"}],
        review_status="needs_manual_review",
        label_basis=basis,
    )


# ─────────────────── 뉴스 ───────────────────


def _news_index(**over):
    base = {
        "cluster": {
            "id": 7134,
            "stock_code": "005930",
            "summary_title": "이재용 엔비디아 회동",
            "first_published_at": "2026-07-24T09:00:00+09:00",
            "sentiment_label": "neutral",
            "article_count": 32,
            "summary_status": "success",
        },
        "doc": {"id": "doc-1", "source_pk": "7134", "stock_code": "005930", "is_current": True},
        "chunks": [{"id": "chunk-1", "stock_code": "005930", "is_active": True}],
    }
    base.update(over)
    return {"7134": base}


def test_news_confirmed_when_all_conditions_met():
    ok, basis, gold = review.review_news_case(
        _news_case("news_clusters.id=7134 실재"), _news_index()
    )
    assert ok is True
    assert gold == [
        {
            "source_type": "news_event",
            "source_id": None,
            "canonical_id": "news_clusters.id=7134",
            "ref": "이재용 엔비디아 회동",
            "note": "news_clusters.id=7134 / 2026-07-24 / neutral / 기사 32건",
        }
    ]
    # 사람이 다시 추적할 수 있게 원본 식별자가 근거에 남아야 한다
    assert "news_clusters.id=7134" in basis
    assert "rag_documents.id=doc-1" in basis


def test_news_rejected_when_cluster_missing_from_db():
    ok, basis, _ = review.review_news_case(_news_case("news_clusters.id=9999"), _news_index())
    assert ok is False and "DB 에 없음" in basis


def test_news_rejected_when_no_indexed_chunk():
    """색인이 안 된 사건은 정답 식별자를 만들 수 없다 — 추측 금지."""
    ok, basis, gold = review.review_news_case(
        _news_case("news_clusters.id=7134"), _news_index(chunks=[])
    )
    assert ok is False and "활성 청크가 없음" in basis and gold == []


def test_news_rejected_on_stock_mismatch():
    """질문 종목과 사건 종목이 다르면 확정하지 않는다."""
    ok, basis, _ = review.review_news_case(
        _news_case("news_clusters.id=7134", stock="000660"), _news_index()
    )
    assert ok is False and "불일치" in basis


def test_news_rejected_when_summary_not_success():
    idx = _news_index()
    idx["7134"]["cluster"]["summary_status"] = "pending"
    ok, basis, _ = review.review_news_case(_news_case("news_clusters.id=7134"), idx)
    assert ok is False and "success 아님" in basis


def test_news_rejected_without_cluster_id_in_label():
    ok, basis, _ = review.review_news_case(_news_case("근거 없음"), _news_index())
    assert ok is False and "특정할 수 없음" in basis


def test_news_uses_one_canonical_cluster_when_event_has_multiple_chunks():
    """여러 청크는 하나의 canonical 사건 Gold로 수렴하며 UUID를 정답으로 고정하지 않는다."""
    idx = _news_index(
        chunks=[
            {"id": "c1", "stock_code": "005930", "is_active": True},
            {"id": "c2", "stock_code": "005930", "is_active": True},
        ]
    )
    ok, basis, gold = review.review_news_case(_news_case("news_clusters.id=7134"), idx)
    assert ok is True
    assert len(gold) == 1
    assert gold[0]["canonical_id"] == "news_clusters.id=7134"
    assert gold[0]["source_id"] is None
    assert "활성 청크 2건" in basis


# ─────────────────── 리포트 ───────────────────

_RID = "9fad15ea-6cf1-4f0c-9a93-9a8978b4c345"


def _report_index(**over):
    base = {
        "report": {
            "id": _RID,
            "stock_code": "005930",
            "broker": "대신증권",
            "title": "체급의 위력",
            "report_date": "2026-07-08",
            "investment_opinion": "BUY",
            "target_price": 560000,
            "target_price_status": "stated",
            "page_count": 4,
        },
        "chunks": [
            {
                "id": "rc-1",
                "content": "투자의견 Buy 목표주가 560,000원",
                "source_locator": {"report_id": _RID, "page_number": 1},
                "stock_code": "005930",
            },
            {
                "id": "rc-2",
                "content": "관련 없는 표 내용",
                "source_locator": {"report_id": _RID, "page_number": 3},
                "stock_code": "005930",
            },
        ],
    }
    base.update(over)
    return {_RID: base}


def test_report_confirmed_only_with_target_price_in_content():
    """목표주가 숫자가 실제로 있는 청크만 근거로 삼는다(1위 자동 채택 금지)."""
    ok, basis, gold = review.review_report_case(
        _report_case(f"research_reports.id={_RID}"), _report_index()
    )
    assert ok is True
    assert [g["source_id"] for g in gold] == ["rc-1"]  # rc-2 는 숫자가 없어 제외
    assert gold[0]["page"] == 1
    assert "전망값" in basis  # 실제값·전망값 구분 명시


def test_report_rejected_when_target_price_absent_from_all_chunks():
    idx = _report_index(
        chunks=[
            {
                "id": "rc-9",
                "content": "숫자 없는 본문",
                "source_locator": {"report_id": _RID, "page_number": 1},
                "stock_code": "005930",
            }
        ]
    )
    ok, basis, gold = review.review_report_case(_report_case(f"research_reports.id={_RID}"), idx)
    assert ok is False and "본문에도 없음" in basis and gold == []


def test_report_rejected_when_target_price_not_stated():
    idx = _report_index()
    idx[_RID]["report"]["target_price_status"] = "inferred"
    ok, basis, _ = review.review_report_case(_report_case(f"research_reports.id={_RID}"), idx)
    assert ok is False and "stated 가 아님" in basis


def test_report_rejected_on_stock_mismatch():
    ok, basis, _ = review.review_report_case(
        _report_case(f"research_reports.id={_RID}", stock="000660"), _report_index()
    )
    assert ok is False and "불일치" in basis


def test_report_rejected_when_page_exceeds_pdf():
    idx = _report_index()
    idx[_RID]["chunks"][0]["source_locator"]["page_number"] = 99
    ok, basis, _ = review.review_report_case(_report_case(f"research_reports.id={_RID}"), idx)
    assert ok is False and "넘음" in basis


# ─────────────────── 복합 ───────────────────


def _mixed_case(**over) -> EvalCase:
    kw = {
        "id": "mix-x",
        "type": "복수 기능 혼합",
        "question": "실적이랑 뉴스 알려줘",
        "stock_code": "005930",
        "required_tools": ["get_financial_facts", "search_news"],
        "expected_args": {"get_financial_facts": {"stock_code": "005930"}},
        "allowed_source_types": ["financial", "news_event"],
        "review_status": "needs_manual_review",
        "label_basis": "복합",
    }
    kw.update(over)
    return EvalCase(**kw)


def test_mixed_confirmed_when_label_complete():
    ok, basis, gold = review.review_mixed_case(_mixed_case(), {}, {})
    assert ok is True
    # 정답 식별자를 억지로 만들지 않고 그 사실을 근거에 남긴다
    assert gold == []
    assert "단일 정답 식별자는 두지 않는다" in basis


def test_mixed_rejected_when_single_required_tool():
    """필수 Tool 이 1개면 복합 질문 라벨로 성립하지 않는다."""
    ok, basis, _ = review.review_mixed_case(_mixed_case(required_tools=["search_news"]), {}, {})
    assert ok is False and "2개 이상" in basis


def test_mixed_rejected_when_allowed_sources_missing():
    ok, basis, _ = review.review_mixed_case(_mixed_case(allowed_source_types=[]), {}, {})
    assert ok is False and "허용 출처" in basis

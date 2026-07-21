from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime

from app.core.config import Settings
from app.jobs.dart_corrections import extract_first_submission_date
from app.jobs.dart_structured import build_normalized
from app.jobs.disclosures import collect_disclosure_texts
from app.sources.dart import DartArchive
from app.sources.dart_documents import document_priority, needs_document
from app.sources.dart_events import build_event_row


def test_document_selection_excludes_low_value_holdings_and_keeps_important():
    base = {
        "disclosed_at": datetime.now(UTC).isoformat(),
        "raw_text": None,
        "raw_text_truncated": False,
    }
    low = {**base, "title": "임원ㆍ주요주주특정증권등소유상황보고서"}
    important = {**base, "title": "단일판매ㆍ공급계약체결"}
    assert document_priority(low) == "low"
    assert not needs_document(low)
    assert document_priority(important) == "important"
    assert needs_document(important)


def test_full_document_is_saved_without_50000_character_truncation(tmp_path):
    text = "가" * 60000
    xml = f"<DOCUMENT><P>{text}</P></DOCUMENT>".encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("20260101000001.xml", xml)

    class Client:
        def get_zip_archive(self, endpoint, params):
            assert endpoint == "document.xml"
            return DartArchive(content=buffer.getvalue(), members={"20260101000001.xml": xml})

    class Repo:
        updated = None

        def list_disclosures_for_documents(self, stock_code):
            return [
                {
                    "stock_code": stock_code,
                    "rcept_no": "20260101000001",
                    "title": "사업보고서 (2025.12)",
                    "disclosed_at": datetime.now(UTC).isoformat(),
                    "raw_text": "기존",
                    "raw_text_truncated": True,
                    "raw_document_path": None,
                    "content_hash": None,
                    "raw_text_length": None,
                    "parse_status": "pending",
                }
            ]

        def update_disclosure_document(self, rcept_no, **values):
            self.updated = {"rcept_no": rcept_no, **values}

        def mark_disclosure_parse_failed(self, rcept_no, error):
            raise AssertionError(error)

    repo = Repo()
    cfg = Settings(dart_raw_document_dir=str(tmp_path))
    result = collect_disclosure_texts(Client(), repo, cfg, "005930")
    assert result["success"] == 1
    assert len(repo.updated["raw_text"]) == 60000
    assert repo.updated["raw_text_length"] == 60000
    assert (tmp_path / repo.updated["raw_document_path"]).exists()


def test_correction_first_submission_date_is_explicitly_parsed():
    text = "2. 정정대상 공시서류의 최초제출일 : 2026년 3월 11일"
    assert extract_first_submission_date(text).isoformat() == "2026-03-11"
    assert (
        extract_first_submission_date("2. 정정대상 공시서류의 최초제출일 : 2026.03.19").isoformat()
        == "2026-03-19"
    )


def test_generic_normalization_fills_overseas_listing_fields():
    normalized = build_normalized(
        "ovLst",
        {
            "rcept_no": "20260713000324",
            "cfd": "2026년 07월 10일",
            "lstex_nt": "미국 나스닥 증권거래소",
            "lststk_ostk_cnt": "17,790,000",
            "lstd": "2026년 07월 10일",
        },
    )
    assert normalized["cfd"] == "2026-07-10"
    assert normalized["lststk_ostk_cnt"] == 17790000
    assert normalized["lstex_nt"] == "미국 나스닥 증권거래소"


def test_event_parser_uses_explicit_date_time_and_location():
    event = build_event_row(
        {
            "stock_code": "005930",
            "rcept_no": "1",
            "title": "주주총회소집결의",
            "disclosed_at": "2026-02-01T00:00:00+00:00",
            "viewer_url": "https://dart.example/1",
            "raw_text": (
                "주주총회 예정일 : 2026년 3월 18일\n개최시간 : 09시 00분\n개최장소 : 본사 대강당"
            ),
            "supersedes_rcept_no": None,
        }
    )
    assert event["event_date"] == "2026-03-18"
    assert event["start_time"] == "09:00:00"
    assert event["location"] == "본사 대강당"

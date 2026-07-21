"""DART 공시 원본 선택·로컬 보존.

RAG 가치가 높은 공시만 증분 수집하고, 임원/주요주주 보유변동처럼 대량·저우선순위
문서는 기본 대상에서 제외한다. document.xml 응답 ZIP은 변형하지 않고 저장한다.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.config import BACKEND_DIR, Settings

LOW_PRIORITY_PATTERNS = (
    "임원ㆍ주요주주특정증권등소유상황보고서",
    "임원·주요주주특정증권등소유상황보고서",
    "주식등의대량보유상황보고서",
)

IMPORTANT_PATTERNS = (
    "사업보고서",
    "반기보고서",
    "분기보고서",
    "주요사항보고서",
    "잠정)실적",
    "잠정실적",
    "단일판매ㆍ공급계약",
    "단일판매·공급계약",
    "현금ㆍ현물배당",
    "현금·현물배당",
    "유상증자",
    "무상증자",
    "감자",
    "전환사채",
    "신주인수권부사채",
    "교환사채",
    "자기주식취득",
    "자기주식처분",
    "자기주식 취득",
    "자기주식 처분",
    "합병",
    "분할",
    "자산양수",
    "자산 양수",
    "자산양도",
    "자산 양도",
    "영업양수",
    "영업 양수",
    "영업양도",
    "영업 양도",
    "주주총회",
    "기업설명회(IR)",
    "주주명부폐쇄",
    "기준일",
)


def document_priority(row: dict[str, Any], *, now: datetime | None = None) -> str:
    """공시 원문 우선순위: required | important | low | skip."""

    title = str(row.get("title") or "")
    if any(pattern in title for pattern in LOW_PRIORITY_PATTERNS):
        return "low"
    if bool(row.get("raw_text_truncated")):
        return "required"
    if any(
        pattern in title for pattern in ("사업보고서", "반기보고서", "분기보고서", "주요사항보고서")
    ):
        return "required"

    disclosed = _as_datetime(row.get("disclosed_at"))
    cutoff = (now or datetime.now(UTC)) - timedelta(days=365)
    if disclosed and disclosed < cutoff:
        return "skip"
    if any(pattern in title for pattern in IMPORTANT_PATTERNS) or bool(row.get("is_correction")):
        return "important"
    return "skip"


def needs_document(row: dict[str, Any]) -> bool:
    """정상 보존된 원문은 건너뛰고 누락/잘림/메타데이터 미완료만 선택한다."""

    if row.get("parse_status") == "unavailable":
        return False
    if document_priority(row) not in {"required", "important"}:
        return False
    if row.get("raw_text_truncated"):
        return True
    if not str(row.get("raw_text") or "").strip():
        return True
    return not (
        row.get("raw_document_path")
        and row.get("content_hash")
        and row.get("raw_text_length") is not None
        and row.get("parse_status") == "success"
    )


@dataclass(frozen=True)
class StoredDocument:
    relative_path: str
    content_hash: str
    byte_length: int


class RawDocumentStore:
    """설정된 루트에 DART ZIP 원본을 원자적으로 저장한다."""

    def __init__(self, cfg: Settings) -> None:
        configured = Path(cfg.dart_raw_document_dir).expanduser()
        self.root = configured if configured.is_absolute() else BACKEND_DIR / configured

    def save(self, stock_code: str, rcept_no: str, content: bytes) -> StoredDocument:
        digest = hashlib.sha256(content).hexdigest()
        relative = Path(stock_code) / f"{rcept_no}.zip"
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_suffix(".zip.tmp")
        tmp.write_bytes(content)
        os.replace(tmp, destination)
        return StoredDocument(str(relative), digest, len(content))


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
        if not match:
            return None
        return datetime(*(int(x) for x in match.groups()), tzinfo=UTC)

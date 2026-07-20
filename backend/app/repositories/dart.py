"""DART 수집 결과의 멱등 Supabase 저장 (SPEC §4-5).

upsert 기준:
- disclosures: rcept_no
- financials: (stock_code, bsns_year, reprt_code, fs_div, account_nm, amount_type)
- structured_disclosures: (stock_code, source_api, record_key)
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, TypeVar

from supabase import Client

from app.core.config import Settings

T = TypeVar("T")


def _batched(items: list[T], size: int) -> Iterable[list[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class DartRepository:
    """DART 초기 백필용 idempotent 저장소."""

    def __init__(self, client: Client, cfg: Settings) -> None:
        self._db = client
        self._cfg = cfg

    # -- stocks.dart_corp_code -------------------------------------------
    def get_target_stocks(self) -> list[dict[str, Any]]:
        resp = self._db.table("stocks").select("code,name,dart_corp_code").order("code").execute()
        return resp.data or []

    def set_corp_code(self, stock_code: str, corp_code: str) -> None:
        self._db.table("stocks").update({"dart_corp_code": corp_code}).eq(
            "code", stock_code
        ).execute()

    # -- disclosures ------------------------------------------------------
    def upsert_disclosures(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        total = 0
        for batch in _batched(rows, self._cfg.supabase_batch_size):
            self._db.table("disclosures").upsert(batch, on_conflict="rcept_no").execute()
            total += len(batch)
        return total

    def disclosures_needing_text(
        self, stock_code: str, report_name_patterns: list[str]
    ) -> list[dict[str, Any]]:
        """원문 추출 대상(raw_text is null)인 공시 목록을 종목별로 조회.

        report_name_patterns 중 하나라도 title에 포함되는 행만 (사업/반기/분기/주요사항).
        """

        resp = (
            self._db.table("disclosures")
            .select("rcept_no,title")
            .eq("stock_code", stock_code)
            .is_("raw_text", "null")
            .execute()
        )
        out = []
        for row in resp.data or []:
            title = row.get("title") or ""
            if any(p in title for p in report_name_patterns):
                out.append(row)
        return out

    def update_disclosure_text(self, rcept_no: str, raw_text: str, truncated: bool) -> None:
        self._db.table("disclosures").update(
            {"raw_text": raw_text, "raw_text_truncated": truncated}
        ).eq("rcept_no", rcept_no).execute()

    # -- financials -------------------------------------------------------
    def upsert_financials(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        total = 0
        conflict = "stock_code,bsns_year,reprt_code,fs_div,account_nm,amount_type"
        for batch in _batched(rows, self._cfg.supabase_batch_size):
            self._db.table("financials").upsert(batch, on_conflict=conflict).execute()
            total += len(batch)
        return total

    # -- structured_disclosures ------------------------------------------
    def upsert_structured(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        total = 0
        conflict = "stock_code,source_api,record_key"
        for batch in _batched(rows, self._cfg.supabase_batch_size):
            self._db.table("structured_disclosures").upsert(batch, on_conflict=conflict).execute()
            total += len(batch)
        return total

    # -- 검증용 카운트 ----------------------------------------------------
    def count(self, table: str, stock_code: str, **filters: str) -> int:
        q = self._db.table(table).select("id", count="exact").eq("stock_code", stock_code)
        for key, value in filters.items():
            q = q.eq(key, value)
        resp = q.execute()
        return resp.count or 0

    def latest_disclosed_at(self, stock_code: str) -> str | None:
        resp = (
            self._db.table("disclosures")
            .select("disclosed_at")
            .eq("stock_code", stock_code)
            .order("disclosed_at", desc=True)
            .limit(1)
            .execute()
        )
        data = resp.data or []
        return data[0]["disclosed_at"] if data else None

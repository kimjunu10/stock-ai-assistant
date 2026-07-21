"""DART 수집 결과의 멱등 Supabase 저장 (SPEC §4-5).

upsert 기준:
- disclosures: rcept_no
- financials: (stock_code, bsns_year, reprt_code, fs_div, account_nm, amount_type)
- structured_disclosures: (stock_code, source_api, record_key)
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
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

    def _fetch_all(self, build_query: Callable[[int, int], Any]) -> list[dict[str, Any]]:
        """Supabase 기본 1,000행 제한을 넘겨 전 행을 안정적으로 읽는다."""

        page_size = 1000
        rows: list[dict[str, Any]] = []
        for start in range(0, 1_000_000, page_size):
            batch = build_query(start, start + page_size - 1).execute().data or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
        return rows

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

        rows = self._fetch_all(
            lambda start, end: (
                self._db.table("disclosures")
                .select("rcept_no,title")
                .eq("stock_code", stock_code)
                .is_("raw_text", "null")
                .order("rcept_no")
                .range(start, end)
            )
        )
        out = []
        for row in rows:
            title = row.get("title") or ""
            if any(p in title for p in report_name_patterns):
                out.append(row)
        return out

    def list_disclosures_for_documents(self, stock_code: str) -> list[dict[str, Any]]:
        """원문 증분 선택에 필요한 공시 메타데이터 전체."""

        fields = (
            "rcept_no,stock_code,title,disclosed_at,is_correction,viewer_url,raw_text,"
            "raw_text_truncated,raw_document_path,raw_text_length,content_hash,parse_status"
        )
        return self._fetch_all(
            lambda start, end: (
                self._db.table("disclosures")
                .select(fields)
                .eq("stock_code", stock_code)
                .order("disclosed_at")
                .order("rcept_no")
                .range(start, end)
            )
        )

    def update_disclosure_text(self, rcept_no: str, raw_text: str, truncated: bool) -> None:
        self._db.table("disclosures").update(
            {"raw_text": raw_text, "raw_text_truncated": truncated}
        ).eq("rcept_no", rcept_no).execute()

    def update_disclosure_document(
        self,
        rcept_no: str,
        *,
        raw_text: str,
        raw_document_path: str,
        raw_text_length: int,
        content_hash: str,
    ) -> None:
        self._db.table("disclosures").update(
            {
                "raw_text": raw_text,
                "raw_text_truncated": False,
                "raw_document_path": raw_document_path,
                "raw_text_length": raw_text_length,
                "content_hash": content_hash,
                "parse_status": "success",
                "parse_error": None,
            }
        ).eq("rcept_no", rcept_no).execute()

    def mark_disclosure_parse_failed(self, rcept_no: str, error: str) -> None:
        self._db.table("disclosures").update(
            {"parse_status": "failed", "parse_error": error[:2000]}
        ).eq("rcept_no", rcept_no).execute()

    def mark_disclosure_unavailable(self, rcept_no: str, reason: str) -> None:
        self._db.table("disclosures").update(
            {
                "parse_status": "unavailable",
                "parse_error": reason[:2000],
                "raw_text_truncated": False,
            }
        ).eq("rcept_no", rcept_no).execute()

    def list_disclosures_for_corrections(self, stock_code: str) -> list[dict[str, Any]]:
        return self._fetch_all(
            lambda start, end: (
                self._db.table("disclosures")
                .select(
                    "rcept_no,stock_code,title,disclosed_at,is_correction,raw_text,"
                    "original_rcept_no,supersedes_rcept_no,is_latest,correction_status"
                )
                .eq("stock_code", stock_code)
                .order("disclosed_at")
                .order("rcept_no")
                .range(start, end)
            )
        )

    def update_disclosure_version(self, rcept_no: str, values: dict[str, Any]) -> None:
        self._db.table("disclosures").update(values).eq("rcept_no", rcept_no).execute()

    def list_event_candidate_disclosures(self, stock_code: str) -> list[dict[str, Any]]:
        return self._fetch_all(
            lambda start, end: (
                self._db.table("disclosures")
                .select(
                    "rcept_no,stock_code,title,disclosed_at,viewer_url,raw_text,"
                    "supersedes_rcept_no,correction_status"
                )
                .eq("stock_code", stock_code)
                .not_.is_("raw_text", "null")
                .order("disclosed_at")
                .order("rcept_no")
                .range(start, end)
            )
        )

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

    # -- 기업개황 / 기업일정 ---------------------------------------------
    def upsert_company_profile(self, row: dict[str, Any]) -> int:
        self._db.table("company_profiles").upsert(row, on_conflict="stock_code").execute()
        return 1

    def company_profile_exists(self, stock_code: str) -> bool:
        resp = (
            self._db.table("company_profiles")
            .select("stock_code")
            .eq("stock_code", stock_code)
            .limit(1)
            .execute()
        )
        return bool(resp.data)

    def upsert_corporate_events(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        conflict = "stock_code,event_type,rcept_no"
        for batch in _batched(rows, self._cfg.supabase_batch_size):
            self._db.table("corporate_events").upsert(batch, on_conflict=conflict).execute()
        return len(rows)

    # -- 실행/호출 감사 --------------------------------------------------
    def start_run(self, run_key: str, mode: str) -> int:
        resp = (
            self._db.table("dart_collection_runs")
            .upsert(
                {"run_key": run_key, "mode": mode, "status": "running", "error": None},
                on_conflict="run_key",
            )
            .execute()
        )
        data = resp.data or []
        if data:
            return int(data[0]["id"])
        lookup = (
            self._db.table("dart_collection_runs")
            .select("id")
            .eq("run_key", run_key)
            .single()
            .execute()
        )
        return int(lookup.data["id"])

    def finish_run(
        self, run_id: int, status: str, stats: dict[str, Any], error: str | None = None
    ) -> None:
        self._db.table("dart_collection_runs").update(
            {
                "status": status,
                "stats": stats,
                "error": error,
                "finished_at": datetime.now().isoformat(),
            }
        ).eq("id", run_id).execute()

    def record_api_result(
        self,
        run_id: int,
        stock_code: str,
        data_group: str,
        source_api: str,
        request_key: str,
        result_status: str,
        *,
        dart_status: str | None = None,
        row_count: int = 0,
        error: str | None = None,
    ) -> None:
        self._db.table("dart_collection_api_results").upsert(
            {
                "run_id": run_id,
                "stock_code": stock_code,
                "data_group": data_group,
                "source_api": source_api,
                "request_key": request_key,
                "result_status": result_status,
                "dart_status": dart_status,
                "row_count": row_count,
                "error": error,
                "requested_at": datetime.now().isoformat(),
            },
            on_conflict="run_id,stock_code,data_group,source_api,request_key",
        ).execute()

    def api_request_completed(
        self,
        run_id: int,
        stock_code: str,
        data_group: str,
        source_api: str,
        request_key: str,
    ) -> bool:
        resp = (
            self._db.table("dart_collection_api_results")
            .select("id")
            .eq("run_id", run_id)
            .eq("stock_code", stock_code)
            .eq("data_group", data_group)
            .eq("source_api", source_api)
            .eq("request_key", request_key)
            .in_("result_status", ["success", "no_data"])
            .limit(1)
            .execute()
        )
        return bool(resp.data)

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

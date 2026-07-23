"""정확한 값 조회 어댑터 (SPEC §11) — 전부 읽기 전용.

기존 DART·재무 테이블을 SELECT 만 한다(수정/삭제 없음).
- 재무 숫자: financials (원 단위 정수, 연결 CFS, reprt_code/amount_type로 기간 구분)
- 구조화 공시 값: structured_disclosures (normalized_data jsonb)
- 정정공시: disclosures 에서 is_latest=true 최신본 우선
- 금융 용어: rag_terms (정확일치 → 별칭 → 유사)

숫자는 LLM이 추측/계산하지 않고 여기서 그대로 가져와 structured fact 로 전달한다.
특정 종목/항목/공시번호 하드코딩 없음(전부 파라미터).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from supabase import Client

# DART 표준 보고서 코드(특정 종목/항목이 아닌 공용 코드 매핑).
REPRT_LABEL = {
    "11011": "1분기보고서",
    "11012": "반기보고서",
    "11013": "3분기보고서",
    "11014": "사업보고서(연간)",
}
FS_DIV_LABEL = {"CFS": "연결", "OFS": "별도"}
AMOUNT_TYPE_LABEL = {
    "quarter": "당기(3개월)",
    "cumulative": "누적",
    "point_in_time": "시점값",
}


@dataclass
class NumericFact:
    """정확 숫자 1건. value_kind 로 실제/공식/전망을 구분한다."""

    label: str  # 예: 매출액
    value: int
    unit: str  # 원
    period: str  # 예: 2025년 3분기보고서 누적
    basis: str  # 예: 연결
    value_kind: str  # actual_value / official_fact / forecast_value
    source_type: str  # financials / structured_disclosure / corporate_event
    source_key: str  # 출처 식별(rcept_no 또는 조회키)
    extra: dict = field(default_factory=dict)


class FactsService:
    def __init__(self, client: Client) -> None:
        self._db = client

    # -- 재무 숫자 -------------------------------------------------------
    def get_financials(
        self,
        stock_code: str,
        *,
        account_names: list[str] | None = None,
        bsns_year: str | None = None,
        reprt_code: str | None = None,
        amount_type: str | None = None,
        limit: int = 50,
    ) -> list[NumericFact]:
        """financials 에서 실제 재무 수치를 조회한다. 연도/분기 미지정 시 최신 우선."""

        q = self._db.table("financials").select("*").eq("stock_code", stock_code)
        if account_names:
            q = q.in_("account_nm", account_names)
        if bsns_year:
            q = q.eq("bsns_year", bsns_year)
        if reprt_code:
            q = q.eq("reprt_code", reprt_code)
        if amount_type:
            q = q.eq("amount_type", amount_type)
        rows = (
            q.order("bsns_year", desc=True)
            .order("reprt_code", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
        facts: list[NumericFact] = []
        for r in rows:
            if r.get("thstrm_amount") is None:
                continue
            period = f"{r['bsns_year']}년 {REPRT_LABEL.get(r['reprt_code'], r['reprt_code'])}"
            period += f" {AMOUNT_TYPE_LABEL.get(r['amount_type'], r['amount_type'])}"
            facts.append(
                NumericFact(
                    label=r["account_nm"],
                    value=int(r["thstrm_amount"]),
                    unit="원",
                    period=period,
                    basis=FS_DIV_LABEL.get(r["fs_div"], r["fs_div"]),
                    value_kind="actual_value",
                    source_type="financials",
                    source_key=(
                        f"{r['stock_code']}/{r['bsns_year']}/{r['reprt_code']}/"
                        f"{r['fs_div']}/{r['account_nm']}/{r['amount_type']}"
                    ),
                    extra={"frmtrm_amount": r.get("frmtrm_amount")},
                )
            )
        return facts

    # -- 구조화 공시 값 --------------------------------------------------
    def get_structured_values(
        self,
        stock_code: str,
        *,
        event_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """structured_disclosures 최신순 조회(요약 + normalized_data)."""

        q = (
            self._db.table("structured_disclosures")
            .select("rcept_no,data_group,event_type,announced_at,summary_text,normalized_data")
            .eq("stock_code", stock_code)
        )
        if event_types:
            q = q.in_("event_type", event_types)
        return q.order("announced_at", desc=True).limit(limit).execute().data or []

    # -- 정정공시 최신본 -------------------------------------------------
    def get_latest_disclosures(
        self,
        stock_code: str,
        *,
        only_corrections: bool = False,
        with_text: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """disclosures 에서 is_latest=true 최신본을 조회한다(정정 전 배제)."""

        q = (
            self._db.table("disclosures")
            .select(
                "rcept_no,title,disclosed_at,correction_status,is_latest,"
                "original_rcept_no,supersedes_rcept_no,parse_status,raw_text"
            )
            .eq("stock_code", stock_code)
            .eq("is_latest", True)
        )
        if only_corrections:
            q = q.neq("correction_status", "original")
        if with_text:
            q = q.eq("parse_status", "success")
        return q.order("disclosed_at", desc=True).limit(limit).execute().data or []

    def get_correction_pair(self, rcept_no: str) -> dict[str, Any] | None:
        """정정본 rcept_no 로 정정 전(직전본)과 최신본을 함께 반환한다."""

        latest = (
            self._db.table("disclosures")
            .select("*")
            .eq("rcept_no", rcept_no)
            .limit(1)
            .execute()
            .data
        )
        if not latest:
            return None
        cur = latest[0]
        prev_no = cur.get("supersedes_rcept_no")
        prev = None
        if prev_no:
            prev_rows = (
                self._db.table("disclosures")
                .select("*")
                .eq("rcept_no", prev_no)
                .limit(1)
                .execute()
                .data
            )
            prev = prev_rows[0] if prev_rows else None
        return {"latest": cur, "previous": prev}

    # -- 금융 용어 -------------------------------------------------------
    def lookup_term(self, term_query: str | list[str]) -> dict[str, Any] | None:
        """용어를 찾는다. 단일 문자열 또는 후보 리스트를 받는다(GPT §6 우선순위).

        후보 여러 개일 때: **모든 후보의 정확일치 → 모든 후보의 별칭 → 그다음 유사**.
        (조사 붙은 원형이 유사검색에서 엉뚱한 항목을 먼저 잡는 것을 방지.)
        """
        cands = [term_query] if isinstance(term_query, str) else list(term_query)
        cands = [c.strip() for c in cands if c and c.strip()]
        if not cands:
            return None

        # 1) 정확일치(term) — 모든 후보
        for c in cands:
            exact = (
                self._db.table("rag_terms")
                .select("*")
                .eq("is_active", True)
                .ilike("term", c)
                .limit(1)
                .execute()
                .data
            )
            if exact:
                return exact[0]
        # 2) 별칭 포함 — 모든 후보
        for c in cands:
            alias = (
                self._db.table("rag_terms")
                .select("*")
                .eq("is_active", True)
                .contains("aliases", [c])
                .limit(1)
                .execute()
                .data
            )
            if alias:
                return alias[0]
        # 3) 유사(search_text 부분일치) — 최후. 가장 긴(정보량 많은) 후보 우선.
        for c in sorted(cands, key=len, reverse=True):
            fuzzy = (
                self._db.table("rag_terms")
                .select("*")
                .eq("is_active", True)
                .ilike("search_text", f"%{c.lower()}%")
                .limit(1)
                .execute()
                .data
            )
            if fuzzy:
                return fuzzy[0]
        return None

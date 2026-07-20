"""구조화 공시(주요사항 36종 + 정기보고서 4종) 공통 저장 헬퍼 (SPEC §4-3, §4-4)."""

from __future__ import annotations

import logging
from typing import Any

from app.sources.dart_parsing import (
    TREASURY_NORMALIZE,
    build_summary_text,
    has_business_content,
    make_record_key,
    normalize_treasury,
    parse_amount,
    parse_dart_date,
)

logger = logging.getLogger(__name__)

# normalized_data 표준 키로 뽑아낼 후보 필드 (있으면 숫자/날짜로 정규화).
_NORMALIZE_NUMERIC = (
    "nstk_ostk_cnt",
    "nstk_estk_cnt",
    "isu_dcrs_qy",
    "aqpln_stk_ostk",
    "aqpln_stk_estk",
    "dpstk_ostk",
    "dpstk_estk",
    "bsis_qy",
    "change_qy_acqs",
    "change_qy_dsps",
    "change_qy_incnr",
    "trmend_qy",
    "isu_stock_totqy",
    "istc_totqy",
    "tesstk_co",
    "distb_stock_co",
    "thstrm",
    "frmtrm",
    "lwfr",
    "cr_rt",
    "fv_ps",
)
_NORMALIZE_DATE = (
    "aqexpd_bgd",
    "aqexpd_edd",
    "isu_dcrs_de",
    "stlm_dt",
    "bddd",
    "ftc_stt_de",
)


def _iso(dt: Any) -> str | None:
    return dt.isoformat() if dt else None


def build_normalized(source_api: str, row: dict[str, Any]) -> dict[str, Any]:
    """원본 행에서 핵심 숫자/날짜를 표준 키로 정규화 (LLM 미사용, 원본 파싱).

    자기주식 취득/처분은 전용 매핑(normalize_treasury)으로 표준 키를 채운다.
    누락된 필수 필드는 로그로 남긴다(SPEC §4-3: 원본에 없으면 억지로 만들지 않음).
    """

    if source_api in TREASURY_NORMALIZE:
        normalized, missing = normalize_treasury(source_api, row)
        if missing:
            logger.info(
                "자기주식 normalized 필수 누락 api=%s rcept=%s 누락=%s (원본에 값 없음)",
                source_api,
                row.get("rcept_no"),
                ",".join(missing),
            )
        return normalized

    out: dict[str, Any] = {}
    for key in _NORMALIZE_NUMERIC:
        if key in row:
            amt = parse_amount(row.get(key))
            if amt is not None:
                out[key] = amt
    for key in _NORMALIZE_DATE:
        if key in row:
            dt = parse_dart_date(row.get(key))
            if dt is not None:
                out[key] = dt.date().isoformat()
    return out


def build_structured_rows(
    *,
    stock_code: str,
    data_group: str,
    source_api: str,
    event_type: str,
    name_ko: str,
    api_rows: list[dict[str, Any]],
    distinguishing_fields: list[str] | None = None,
    bsns_year: str | None = None,
    reprt_code: str | None = None,
    skip_empty: bool = False,
) -> list[dict[str, Any]]:
    """API 원본 행들 → structured_disclosures upsert 행 리스트.

    skip_empty=True이면 메타·결산일을 제외한 업무 필드가 전부 비어 있는 행을
    저장하지 않는다(정기보고서에서 이력 없음을 빈 행으로 반환하는 경우 대응).
    """

    out: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in api_rows:
        if skip_empty and not has_business_content(row):
            continue
        rcept_no = row.get("rcept_no") or None
        corp_name = row.get("corp_name") or ""
        announced = parse_dart_date(row.get("rcept_dt") or row.get("bddd"))
        record_key = make_record_key(source_api, rcept_no, row, distinguishing_fields)
        # 같은 배치 안에서 record_key가 겹치면 첫 행만 남긴다 — upsert 충돌 방지.
        if record_key in seen_keys:
            continue
        seen_keys.add(record_key)
        out.append(
            {
                "stock_code": stock_code,
                "rcept_no": rcept_no,
                "data_group": data_group,
                "source_api": source_api,
                "event_type": event_type,
                "announced_at": _iso(announced),
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
                "record_key": record_key,
                "normalized_data": build_normalized(source_api, row),
                "raw_data": row,
                "summary_text": build_summary_text(name_ko, corp_name, rcept_no, row),
            }
        )
    return out

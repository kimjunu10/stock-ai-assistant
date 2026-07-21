"""재무 수집 잡: fnlttSinglAcntAll (SPEC §4-2).

종목별 최근 2개 사업연도 × 4개 보고서(11013/11012/11014/11011).
각 (종목·연도·보고서)마다 CFS 먼저, 없으면 OFS 폴백.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.config import Settings
from app.repositories.dart import DartRepository
from app.sources.dart import DartAuthError, DartClient
from app.sources.dart_financials import extract_financial_rows

logger = logging.getLogger(__name__)

REPRT_CODES = ("11013", "11012", "11014", "11011")


def _recent_business_years(cfg: Settings) -> list[str]:
    """최근 N개 사업연도. 전년도부터 역순 (당해년도 사업보고서는 아직 미제출 가능)."""

    this_year = datetime.now(UTC).year
    return [str(this_year - offset) for offset in range(cfg.dart_financial_years)]


def collect_financials(
    client: DartClient, repo: DartRepository, cfg: Settings, stock_code: str, corp_code: str
) -> dict[str, int]:
    """종목 하나의 재무를 수집·저장. CFS 우선, 없으면 OFS 폴백."""

    saved = 0
    cfs_hits = 0
    ofs_fallbacks = 0
    for bsns_year in _recent_business_years(cfg):
        for reprt_code in REPRT_CODES:
            try:
                rows, used_div = _fetch_one(client, corp_code, bsns_year, reprt_code)
            except DartAuthError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("재무 조회 실패 stock=%s %s/%s", stock_code, bsns_year, reprt_code)
                continue
            if not rows:
                continue
            fin_rows = extract_financial_rows(rows, stock_code, bsns_year, reprt_code, used_div)
            saved += repo.upsert_financials(fin_rows)
            if used_div == "CFS":
                cfs_hits += 1
            else:
                ofs_fallbacks += 1

    logger.info(
        "재무 저장 stock=%s saved=%d cfs=%d ofs_fallback=%d",
        stock_code,
        saved,
        cfs_hits,
        ofs_fallbacks,
    )
    return {"saved": saved, "cfs_hits": cfs_hits, "ofs_fallbacks": ofs_fallbacks}


def _fetch_one(
    client: DartClient, corp_code: str, bsns_year: str, reprt_code: str
) -> tuple[list[dict], str]:
    """CFS 먼저 조회, 데이터 없으면 OFS. (rows, 사용한 fs_div) 반환."""

    for fs_div in ("CFS", "OFS"):
        result = client.get_json(
            "fnlttSinglAcntAll",
            {
                "corp_code": corp_code,
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
                "fs_div": fs_div,
            },
        )
        if result.ok and result.rows:
            return result.rows, fs_div
        # no_data(013) 이거나 빈 응답이면 다음 fs_div로 폴백
    return [], "CFS"

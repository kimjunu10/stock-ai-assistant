"""정기보고서 핵심정보 4종 수집 잡 (SPEC §4-4).

종목별 최근 2개 사업연도 × 4개 보고서 코드 × 4개 API. 미제출은 status=013 정상 처리.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.config import Settings
from app.jobs.dart_structured import build_structured_rows
from app.repositories.dart import DartRepository
from app.sources.dart import DartClient
from app.sources.dart_parsing import REGULAR_DISTINGUISHING
from app.sources.dart_regular_facts import REGULAR_FACT_SPECS, REPRT_CODES

logger = logging.getLogger(__name__)


def _recent_business_years(cfg: Settings) -> list[str]:
    this_year = datetime.now(UTC).year
    return [str(this_year - 1 - offset) for offset in range(cfg.dart_financial_years)]


def collect_regular_facts(
    client: DartClient, repo: DartRepository, cfg: Settings, stock_code: str, corp_code: str
) -> dict[str, int]:
    """정기보고서 4종을 최근 2개 사업연도 × 4개 보고서로 조회·저장."""

    called = 0
    apis_with_data = 0
    saved_rows = 0

    for bsns_year in _recent_business_years(cfg):
        for reprt_code in REPRT_CODES:
            for spec in REGULAR_FACT_SPECS:
                called += 1
                try:
                    result = client.get_json(
                        spec.source_api,
                        {
                            "corp_code": corp_code,
                            "bsns_year": bsns_year,
                            "reprt_code": reprt_code,
                        },
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "정기보고서 조회 실패 stock=%s api=%s %s/%s",
                        stock_code,
                        spec.source_api,
                        bsns_year,
                        reprt_code,
                    )
                    continue

                if result.no_data or not result.rows:
                    continue
                if not result.ok:
                    logger.warning(
                        "정기보고서 비정상 stock=%s api=%s status=%s",
                        stock_code,
                        spec.source_api,
                        result.status,
                    )
                    continue

                apis_with_data += 1
                rows = build_structured_rows(
                    stock_code=stock_code,
                    data_group="regular_report",
                    source_api=spec.source_api,
                    event_type=spec.event_type,
                    name_ko=spec.name_ko,
                    api_rows=result.rows,
                    distinguishing_fields=REGULAR_DISTINGUISHING.get(spec.source_api),
                    bsns_year=bsns_year,
                    reprt_code=reprt_code,
                    skip_empty=True,  # 이력 없어 필드가 전부 '-'인 빈 행 저장 안 함
                )
                saved_rows += repo.upsert_structured(rows)

    logger.info(
        "정기보고서 4종 stock=%s called=%d with_data=%d saved=%d",
        stock_code,
        called,
        apis_with_data,
        saved_rows,
    )
    return {"called": called, "apis_with_data": apis_with_data, "saved_rows": saved_rows}

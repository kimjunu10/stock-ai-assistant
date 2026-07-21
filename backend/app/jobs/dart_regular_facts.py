"""정기보고서 핵심정보 4종 수집 잡 (SPEC §4-4).

종목별 최근 2개 사업연도 × 4개 보고서 코드 × 4개 API. 미제출은 status=013 정상 처리.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from app.core.config import Settings
from app.jobs.dart_structured import build_structured_rows
from app.repositories.dart import DartRepository
from app.sources.dart import DartAuthError, DartClient
from app.sources.dart_parsing import REGULAR_DISTINGUISHING
from app.sources.dart_regular_facts import REGULAR_FACT_SPECS, REPRT_CODES

logger = logging.getLogger(__name__)


def _recent_business_years(cfg: Settings) -> list[str]:
    this_year = datetime.now(UTC).year
    return [str(this_year - offset) for offset in range(cfg.dart_financial_years)]


def collect_regular_facts(
    client: DartClient,
    repo: DartRepository,
    cfg: Settings,
    stock_code: str,
    corp_code: str,
    *,
    on_result: Callable[[dict], None] | None = None,
    should_call: Callable[[str, str], bool] | None = None,
) -> dict[str, int]:
    """정기보고서 4종을 최근 2개 사업연도 × 4개 보고서로 조회·저장."""

    called = 0
    apis_with_data = 0
    saved_rows = 0
    skipped = 0

    for bsns_year in _recent_business_years(cfg):
        for reprt_code in REPRT_CODES:
            for spec in REGULAR_FACT_SPECS:
                request_key = f"{bsns_year}:{reprt_code}"
                if should_call and not should_call(spec.source_api, request_key):
                    skipped += 1
                    continue
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
                except DartAuthError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    if on_result:
                        on_result(
                            {
                                "data_group": "regular_report",
                                "source_api": spec.source_api,
                                "request_key": request_key,
                                "result_status": "failed",
                                "dart_status": None,
                                "row_count": 0,
                                "error": str(exc),
                            }
                        )
                    logger.exception(
                        "정기보고서 조회 실패 stock=%s api=%s %s/%s",
                        stock_code,
                        spec.source_api,
                        bsns_year,
                        reprt_code,
                    )
                    continue

                if result.no_data or not result.rows:
                    if on_result:
                        on_result(
                            {
                                "data_group": "regular_report",
                                "source_api": spec.source_api,
                                "request_key": request_key,
                                "result_status": "no_data",
                                "dart_status": result.status,
                                "row_count": 0,
                                "error": None,
                            }
                        )
                    continue
                if not result.ok:
                    if on_result:
                        on_result(
                            {
                                "data_group": "regular_report",
                                "source_api": spec.source_api,
                                "request_key": request_key,
                                "result_status": "failed",
                                "dart_status": result.status,
                                "row_count": 0,
                                "error": result.message,
                            }
                        )
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
                if on_result:
                    on_result(
                        {
                            "data_group": "regular_report",
                            "source_api": spec.source_api,
                            "request_key": request_key,
                            "result_status": "success",
                            "dart_status": result.status,
                            "row_count": len(rows),
                            "error": None,
                        }
                    )

    logger.info(
        "정기보고서 4종 stock=%s called=%d with_data=%d saved=%d",
        stock_code,
        called,
        apis_with_data,
        saved_rows,
    )
    return {
        "called": called,
        "skipped_completed": skipped,
        "apis_with_data": apis_with_data,
        "saved_rows": saved_rows,
    }

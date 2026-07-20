"""주요사항보고서 구조화 API 36종 수집 잡 (SPEC §4-3).

종목별로 36종 전부를 bgn_de=오늘-1년, end_de=오늘 범위로 조회한다.
status=013은 데이터 없음으로 저장하지 않고, 한 API 실패가 다른 API를 막지 않는다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.jobs.dart_structured import build_structured_rows
from app.repositories.dart import DartRepository
from app.sources.dart import DartClient
from app.sources.dart_major_events import MAJOR_EVENT_SPECS

logger = logging.getLogger(__name__)


def _yyyymmdd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def collect_major_events(
    client: DartClient, repo: DartRepository, cfg: Settings, stock_code: str, corp_code: str
) -> dict[str, int]:
    """36종 전부 조회하고 응답 있는 모든 행을 structured_disclosures에 저장."""

    end = datetime.now(UTC)
    begin = end - timedelta(days=cfg.dart_disclosure_lookback_days)
    params_range = {"bgn_de": _yyyymmdd(begin), "end_de": _yyyymmdd(end)}

    called = 0
    apis_with_data = 0
    saved_rows = 0

    for spec in MAJOR_EVENT_SPECS:
        called += 1
        try:
            result = client.get_json(spec.source_api, {"corp_code": corp_code, **params_range})
        except Exception:  # noqa: BLE001 - 한 API 실패가 전체를 막지 않게 (SPEC §4-5)
            logger.exception("주요사항 조회 실패 stock=%s api=%s", stock_code, spec.source_api)
            continue

        if result.no_data or not result.rows:
            continue
        if not result.ok:
            logger.warning(
                "주요사항 비정상 응답 stock=%s api=%s status=%s msg=%s",
                stock_code,
                spec.source_api,
                result.status,
                result.message,
            )
            continue

        apis_with_data += 1
        rows = build_structured_rows(
            stock_code=stock_code,
            data_group="major_event",
            source_api=spec.source_api,
            event_type=spec.event_type,
            name_ko=spec.name_ko,
            api_rows=result.rows,
        )
        saved_rows += repo.upsert_structured(rows)

    logger.info(
        "주요사항 36종 stock=%s called=%d with_data=%d saved=%d",
        stock_code,
        called,
        apis_with_data,
        saved_rows,
    )
    return {"called": called, "apis_with_data": apis_with_data, "saved_rows": saved_rows}

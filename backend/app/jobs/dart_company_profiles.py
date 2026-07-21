"""대상 종목의 OpenDART 기업개황을 멱등 upsert."""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.repositories.dart import DartRepository
from app.sources.dart import DartAuthError, DartClient
from app.sources.dart_company import build_company_profile

logger = logging.getLogger(__name__)


def collect_company_profile(
    client: DartClient,
    repo: DartRepository,
    stock_code: str,
    corp_code: str,
    *,
    on_failure: Callable[[dict], None] | None = None,
) -> dict[str, int | str]:
    try:
        result = client.get_json("company", {"corp_code": corp_code})
        if result.no_data:
            return {"status": "no_data", "saved": 0}
        if not result.ok:
            raise RuntimeError(f"company status={result.status} message={result.message}")
        repo.upsert_company_profile(build_company_profile(stock_code, result.raw))
        return {"status": "success", "saved": 1}
    except DartAuthError:
        raise
    except Exception as exc:  # noqa: BLE001
        if on_failure:
            on_failure(
                {
                    "stage": "company_profile",
                    "stock_code": stock_code,
                    "source_api": "company",
                    "error": str(exc),
                }
            )
        logger.exception("기업개황 수집 실패 stock=%s", stock_code)
        return {"status": "failed", "saved": 0, "error": str(exc)}

"""DART RAG 원본·메타데이터 증분 보완.

기존 정상 데이터는 건너뛰고 원문 누락/잘림/중요 공시, 최신 재무·구조화 API,
기업개황, 일정, 정정 연결만 멱등 보완한다. 임베딩·청킹은 실행하지 않는다.

사용:
    python -m scripts.complete_dart_collection --dry-run
    python -m scripts.complete_dart_collection --run-key dart-rag-source-20260721
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db.client import get_supabase_client
from app.jobs.dart_company_profiles import collect_company_profile
from app.jobs.dart_corporate_events import collect_corporate_events
from app.jobs.dart_corrections import link_corrections
from app.jobs.dart_major_events import collect_major_events
from app.jobs.dart_regular_facts import collect_regular_facts
from app.jobs.disclosures import collect_disclosure_list, collect_disclosure_texts, sync_corp_codes
from app.jobs.financials import collect_financials
from app.repositories.dart import DartRepository
from app.sources.dart import DartAuthError, DartClient

logger = logging.getLogger("complete_dart_collection")
TARGET_STOCKS = {"005930", "000660", "034020", "042660", "005380"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="외부 호출·DB 변경 없이 대상만 계산")
    parser.add_argument("--run-key", default="dart-rag-source-20260721", help="중단·재개 실행 키")
    parser.add_argument("--only", choices=sorted(TARGET_STOCKS), help="특정 종목만 실행")
    parser.add_argument(
        "--failure-log", default="dart_collection_failures.jsonl", help="실패 JSONL 경로"
    )
    return parser.parse_args()


class FailureWriter:
    def __init__(self, path: str, *, dry_run: bool) -> None:
        self.path = Path(path)
        self.dry_run = dry_run
        # 같은 run-key로 재개할 때 이전 실패 기록을 지우지 않는다.
        if not dry_run and not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def __call__(self, payload: dict[str, Any]) -> None:
        event = {"timestamp": datetime.now(UTC).isoformat(), **payload}
        if not self.dry_run:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def table_counts(repo: DartRepository, stocks: list[str]) -> dict[str, int]:
    return {
        table: sum(repo.count(table, stock_code) for stock_code in stocks)
        for table in ("disclosures", "financials", "structured_disclosures", "corporate_events")
    }


def finish_run_safely(
    repo: DartRepository,
    run_id: int,
    status: str,
    stats: dict[str, Any],
    error: str | None = None,
) -> None:
    """네트워크 단절이 원래 실패 원인과 로컬 실패 로그를 가리지 않게 한다."""

    try:
        repo.finish_run(run_id, status, stats, error)
    except Exception:  # noqa: BLE001
        logger.exception("DART 실행 상태 저장 실패 run_id=%s status=%s", run_id, status)


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    settings.validate_dart_collection()
    repo = DartRepository(get_supabase_client(), settings)
    failure = FailureWriter(args.failure_log, dry_run=args.dry_run)

    stock_rows = [
        row
        for row in repo.get_target_stocks()
        if row["code"] in TARGET_STOCKS and (not args.only or row["code"] == args.only)
    ]
    stocks = [row["code"] for row in stock_rows]

    if args.dry_run:
        summary = {
            "mode": "dry_run",
            "stocks": {},
            "expected_major_api_calls": len(stocks) * 36,
            "expected_regular_api_calls": len(stocks) * settings.dart_financial_years * 4 * 4,
        }
        for row in stock_rows:
            summary["stocks"][row["code"]] = {
                "corp_code": row.get("dart_corp_code"),
                "documents": collect_disclosure_texts(
                    None,
                    repo,
                    settings,
                    row["code"],
                    dry_run=True,  # type: ignore[arg-type]
                ),
            }
        print("DART_COMPLETION_SUMMARY=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0

    run_id = repo.start_run(args.run_key, "incremental_completion")
    before = table_counts(repo, stocks)
    summary: dict[str, Any] = {
        "mode": "actual",
        "run_key": args.run_key,
        "before": before,
        "stocks": {},
    }
    client = DartClient(settings)
    try:
        corp_map = sync_corp_codes(client, repo)
        corp_map = {code: corp for code, corp in corp_map.items() if code in stocks}
        for stock_code, corp_code in corp_map.items():
            stock_report: dict[str, Any] = {}
            summary["stocks"][stock_code] = stock_report
            logger.info("=== DART 증분 보완 stock=%s ===", stock_code)

            stock_report["disclosure_list"] = collect_disclosure_list(
                client, repo, settings, stock_code, corp_code
            )
            stock_report["documents"] = collect_disclosure_texts(
                client, repo, settings, stock_code, on_failure=failure
            )

            if repo.company_profile_exists(stock_code):
                stock_report["company_profile"] = {"status": "skipped_existing", "saved": 0}
            else:
                stock_report["company_profile"] = collect_company_profile(
                    client, repo, stock_code, corp_code, on_failure=failure
                )

            stock_report["financials"] = collect_financials(
                client, repo, settings, stock_code, corp_code
            )

            def on_api_result(payload: dict[str, Any]) -> None:
                repo.record_api_result(run_id, stock_code, **payload)
                if payload["result_status"] == "failed":
                    failure({"stage": "structured_api", "stock_code": stock_code, **payload})

            def should_call_major(source_api: str, request_key: str) -> bool:
                return not repo.api_request_completed(
                    run_id, stock_code, "major_event", source_api, request_key
                )

            def should_call_regular(source_api: str, request_key: str) -> bool:
                return not repo.api_request_completed(
                    run_id, stock_code, "regular_report", source_api, request_key
                )

            stock_report["major_events"] = collect_major_events(
                client,
                repo,
                settings,
                stock_code,
                corp_code,
                on_result=on_api_result,
                should_call=should_call_major,
            )
            stock_report["regular_facts"] = collect_regular_facts(
                client,
                repo,
                settings,
                stock_code,
                corp_code,
                on_result=on_api_result,
                should_call=should_call_regular,
            )
            stock_report["corrections"] = link_corrections(repo, stock_code)
            stock_report["corporate_events"] = collect_corporate_events(repo, stock_code)

        summary["after"] = table_counts(repo, stocks)
        summary["row_delta"] = {table: summary["after"][table] - before[table] for table in before}
        finish_run_safely(repo, run_id, "success", summary)
    except DartAuthError as exc:
        summary["fatal_error"] = str(exc)
        failure({"stage": "authentication", "error": str(exc)})
        finish_run_safely(repo, run_id, "failed", summary, str(exc))
        logger.error("DART 인증 오류로 즉시 중단: %s", exc)
        return 2
    except Exception as exc:  # noqa: BLE001
        summary["fatal_error"] = str(exc)
        failure({"stage": "orchestrator", "error": str(exc)})
        finish_run_safely(repo, run_id, "failed", summary, str(exc))
        logger.exception("DART 보완 실행 실패")
        return 1
    finally:
        client.close()

    print("DART_COMPLETION_SUMMARY=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

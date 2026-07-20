"""OpenDART 초기 데이터 백필 (SPEC §4).

종목별로 corp_code → 공시목록 → 원문 → 재무 → 주요사항 36종 → 정기 4종을
독립 try/except로 실행하고, 종목별 통계를 JSON으로 출력한다. 멱등 upsert이므로
여러 번 재실행해도 중복 행이 생기지 않는다.

사용:
    python -m scripts.backfill_dart                 # 5종목 전체
    python -m scripts.backfill_dart --only 005930   # 스모크(1종목)
    python -m scripts.backfill_dart --skip-text     # 원문 추출 제외
"""

from __future__ import annotations

import argparse
import json
import logging

from app.core.config import settings
from app.db.client import get_supabase_client
from app.jobs.dart_major_events import collect_major_events
from app.jobs.dart_regular_facts import collect_regular_facts
from app.jobs.disclosures import (
    collect_disclosure_list,
    collect_disclosure_texts,
    sync_corp_codes,
)
from app.jobs.financials import collect_financials
from app.repositories.dart import DartRepository
from app.sources.dart import DartAuthError, DartClient

logger = logging.getLogger("backfill_dart")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--only", help="특정 종목코드 하나만 (스모크 테스트용)")
    p.add_argument("--skip-text", action="store_true", help="원문 추출 단계 건너뛰기")
    return p.parse_args()


def run_stock(client, repo, cfg, stock_code, corp_code, *, skip_text: bool) -> dict:
    """종목 하나에 대한 전체 수집. 단계별 독립 try/except."""

    report: dict = {"corp_code": corp_code}

    def step(name: str, fn):
        try:
            report[name] = fn()
        except DartAuthError:
            raise  # 인증 오류는 전체 중단
        except Exception as exc:  # noqa: BLE001
            logger.exception("[%s] %s 단계 실패", stock_code, name)
            report[name] = {"error": str(exc)}

    step(
        "disclosure_list",
        lambda: collect_disclosure_list(client, repo, cfg, stock_code, corp_code),
    )
    if not skip_text:
        step("disclosure_text", lambda: collect_disclosure_texts(client, repo, cfg, stock_code))
    step("financials", lambda: collect_financials(client, repo, cfg, stock_code, corp_code))
    step("major_events", lambda: collect_major_events(client, repo, cfg, stock_code, corp_code))
    step("regular_facts", lambda: collect_regular_facts(client, repo, cfg, stock_code, corp_code))

    report["latest_disclosed_at"] = repo.latest_disclosed_at(stock_code)
    return report


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
    client = DartClient(settings)

    summary: dict[str, dict] = {}
    try:
        corp_map = sync_corp_codes(client, repo)
        if args.only:
            corp_map = {args.only: corp_map[args.only]} if args.only in corp_map else {}
            if not corp_map:
                logger.error("--only %s 의 corp_code를 찾지 못함", args.only)
                return 1
        for stock_code, corp_code in corp_map.items():
            logger.info("=== 종목 %s (corp_code=%s) 수집 시작 ===", stock_code, corp_code)
            summary[stock_code] = run_stock(
                client, repo, settings, stock_code, corp_code, skip_text=args.skip_text
            )
    except DartAuthError as exc:
        logger.error("인증 오류로 중단: %s", exc)
        print("BACKFILL_SUMMARY=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 2
    finally:
        client.close()

    print("BACKFILL_SUMMARY=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

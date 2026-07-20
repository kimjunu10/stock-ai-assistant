"""공시 수집 잡: corp_code 매핑 + 공시목록 + 원문 (SPEC §4-1)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.repositories.dart import DartRepository
from app.sources.dart import DartClient
from app.sources.dart_parsing import (
    extract_document_text,
    parse_corp_code_map,
    parse_dart_date,
)

logger = logging.getLogger(__name__)

# 원문 추출 대상 보고서(SPEC §4-1): 사업/반기/분기/주요사항보고서.
RAW_TEXT_TARGET_PATTERNS = ["사업보고서", "반기보고서", "분기보고서", "주요사항보고서"]


def _today_utc() -> datetime:
    return datetime.now(UTC)


def _yyyymmdd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def sync_corp_codes(client: DartClient, repo: DartRepository) -> dict[str, str]:
    """corpCode.xml → 대상 5개 종목의 dart_corp_code를 stocks에 저장.

    반환: {stock_code: corp_code} (대상 종목 한정).
    """

    members = client.get_zip_members("corpCode.xml", {})
    full_map = parse_corp_code_map(members)
    logger.info("corpCode.xml 파싱 완료: 상장사 %d개", len(full_map))

    result: dict[str, str] = {}
    for stock in repo.get_target_stocks():
        code = stock["code"]
        corp_code = full_map.get(code)
        if not corp_code:
            logger.error("종목 %s 의 corp_code를 corpCode.xml에서 찾지 못함", code)
            continue
        if stock.get("dart_corp_code") != corp_code:
            repo.set_corp_code(code, corp_code)
        result[code] = corp_code
        logger.info("corp_code 매핑 %s → %s", code, corp_code)
    return result


def collect_disclosure_list(
    client: DartClient, repo: DartRepository, cfg: Settings, stock_code: str, corp_code: str
) -> dict[str, int]:
    """종목별 최근 1년 모든 공시 목록을 페이지네이션해 disclosures에 upsert."""

    end = _today_utc()
    begin = end - timedelta(days=cfg.dart_disclosure_lookback_days)
    page_no = 1
    saved = 0
    total_page = 1

    while page_no <= total_page:
        result = client.get_json(
            "list",
            {
                "corp_code": corp_code,
                "bgn_de": _yyyymmdd(begin),
                "end_de": _yyyymmdd(end),
                "page_no": page_no,
                "page_count": 100,
            },
        )
        if result.no_data:
            break
        if not result.ok:
            logger.warning(
                "공시목록 조회 실패 stock=%s status=%s msg=%s",
                stock_code,
                result.status,
                result.message,
            )
            break
        total_page = result.total_page or 1
        rows = []
        for item in result.rows:
            rcept_no = item.get("rcept_no")
            if not rcept_no:
                continue
            rm = item.get("rm") or ""
            report_nm = item.get("report_nm") or ""
            is_correction = ("정" in rm) or ("철" in rm) or report_nm.startswith("[")
            rows.append(
                {
                    "stock_code": stock_code,
                    "rcept_no": rcept_no,
                    "title": report_nm,
                    "disclosed_at": _iso_or_none(parse_dart_date(item.get("rcept_dt"))),
                    "disclosure_type": report_nm,
                    "is_correction": is_correction,
                    "viewer_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                }
            )
        saved += repo.upsert_disclosures(rows)
        page_no += 1

    logger.info("공시목록 저장 stock=%s saved=%d", stock_code, saved)
    return {"saved": saved}


def collect_disclosure_texts(
    client: DartClient, repo: DartRepository, cfg: Settings, stock_code: str
) -> dict[str, int]:
    """대상 공시 원문을 document.xml로 추출해 앞 50,000자까지 저장."""

    targets = repo.disclosures_needing_text(stock_code, RAW_TEXT_TARGET_PATTERNS)
    success = 0
    failed = 0
    limit = cfg.dart_raw_text_limit
    for row in targets:
        rcept_no = row["rcept_no"]
        try:
            members = client.get_zip_members("document.xml", {"rcept_no": rcept_no})
            if not members:
                failed += 1
                logger.warning("원문 없음 stock=%s rcept=%s", stock_code, rcept_no)
                continue
            text = extract_document_text(members, rcept_no)
            if not text:
                failed += 1
                logger.warning("원문 텍스트 추출 실패 stock=%s rcept=%s", stock_code, rcept_no)
                continue
            truncated = len(text) > limit
            repo.update_disclosure_text(rcept_no, text[:limit], truncated)
            success += 1
        except Exception:  # noqa: BLE001 - 한 건 실패가 전체를 막지 않게
            failed += 1
            logger.exception("원문 처리 실패 stock=%s rcept=%s", stock_code, rcept_no)
    logger.info("원문 저장 stock=%s success=%d failed=%d", stock_code, success, failed)
    return {"success": success, "failed": failed}


def _iso_or_none(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None

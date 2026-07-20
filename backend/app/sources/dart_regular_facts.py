"""정기보고서 핵심정보 4종 레지스트리 (SPEC §4-4).

엔드포인트명은 OpenDART 공식 개발가이드와 대조하고 실제 API 호출로 status=000 응답을
확인했다. 최근 2개 사업연도 × 4개 보고서 코드로 조회한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegularFactSpec:
    event_type: str
    source_api: str
    name_ko: str


REGULAR_FACT_SPECS: tuple[RegularFactSpec, ...] = (
    RegularFactSpec("stock_total_status", "stockTotqySttus", "주식의 총수 현황"),
    RegularFactSpec("treasury_stock_status", "tesstkAcqsDspsSttus", "자기주식 취득 및 처분 현황"),
    RegularFactSpec("dividend_matter", "alotMatter", "배당에 관한 사항"),
    RegularFactSpec("capital_change_status", "irdsSttus", "증자(감자) 현황"),
)

# reprt_code: 11013=1분기, 11012=반기, 11014=3분기, 11011=사업보고서
REPRT_CODES: tuple[str, ...] = ("11013", "11012", "11014", "11011")

assert len(REGULAR_FACT_SPECS) == 4

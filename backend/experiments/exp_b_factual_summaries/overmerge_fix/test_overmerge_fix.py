"""over-merge 보호(실험 A: 시장 뉴스 브리지 차단) 자동 테스트.

prompt.md 9절 요구 5종:
 1. 동일 기업 발표를 여러 언론사가 보도하면 하나로 유지된다.
 2. 서로 다른 거래일의 시황 기사는 시장 단어가 유사해도 계속 연결되지 않는다.
 3. 시장 뉴스가 서로 다른 종목 사건을 잇는 징검다리 역할을 하지 못한다.
 4. 날짜가 달라도 동일한 기업 사건이면 유지될 수 있다.
 5. 보호 기능을 끄면 기존 방식과 동일하게 작동한다.

임베딩은 규칙/클러스터링 로직만 검증하면 되므로 소형 합성 벡터를 직접 만든다
(실제 BGE-M3 를 부르지 않아 빠르고 결정적). market_wide 판별은 실제 market_rules 사용.

실행: pytest test_overmerge_fix.py -q  (또는 python test_overmerge_fix.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
EXP_B = BASE.parent
EXP_A = EXP_B.parent / "exp_a_clustering"
for p in (EXP_A, EXP_B, BASE):
    sys.path.insert(0, str(p))

import market_rules as MR  # noqa: E402
from cluster_variants import VariantConfig, cluster_all_variant  # noqa: E402

STOCKS = ["005930", "000660"]


def _norm(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-12)


def _mk_rows_and_vecs(specs: list[dict]) -> tuple[list[dict], np.ndarray]:
    """specs: [{title, stock, at, vec}] → rows, l2정규화 vecs."""
    rows = []
    vlist = []
    for k, s in enumerate(specs):
        rows.append(
            {
                "article_stock_id": f"{k}:{s['stock']}",
                "article_id": k,
                "stock_code": s["stock"],
                "title": s["title"],
                "description": s.get("desc", ""),
                "published_at": s["at"],
            }
        )
        vlist.append(_norm(np.asarray(s["vec"], dtype=np.float32)))
    return rows, np.vstack(vlist)


def _labels(assign: dict, rows: list) -> dict[str, int]:
    return {rows[i]["article_stock_id"]: a["cluster_id"] for i, a in assign.items()}


# 사건별 고유 방향 벡터(3차원이면 충분). 같은 사건은 같은 방향 + 작은 노이즈.
E_COMPANY_A = np.array([1.0, 0.0, 0.0])  # 기업 사건 A
E_MARKET = np.array([0.0, 1.0, 0.0])  # 시황 공통 방향
E_COMPANY_B = np.array([0.0, 0.0, 1.0])  # 기업 사건 B


def _jit(base: np.ndarray, seed: int) -> np.ndarray:
    # 인덱스 기반 결정적 소음(테스트 재현성; Math.random 없이).
    d = np.array([(seed * 7) % 5, (seed * 3) % 5, (seed * 11) % 5], dtype=np.float32)
    return base + 0.02 * d


def test_1_same_event_many_press_stays_one():
    """동일 기업 발표를 12개 언론사가 보도 → 하나의 클러스터."""
    specs = [
        {
            "title": f"삼성전자, 신형 반도체 공급 계약 체결 - 언론{k}",
            "stock": "005930",
            "at": f"2026-07-10T09:{k:02d}:00+09:00",
            "vec": _jit(E_COMPANY_A, k),
        }
        for k in range(12)
    ]
    rows, vecs = _mk_rows_and_vecs(specs)
    assign, _ = cluster_all_variant(rows, vecs, STOCKS, VariantConfig(block_market_bridge=True))
    labels = set(_labels(assign, rows).values())
    assert len(labels) == 1, f"동일 사건인데 {len(labels)}개로 쪼개짐"


def test_2_different_day_market_news_not_merged():
    """서로 다른 거래일의 시황 기사는 유사해도 연결되지 않는다."""
    specs = [
        {
            "title": "코스피, 외국인 순매도에 급락 마감…사이드카 발동",
            "stock": "005930",
            "at": "2026-07-10T15:30:00+09:00",
            "vec": _jit(E_MARKET, 1),
        },
        {
            "title": "코스피, 기관 매수에 급등 마감…증시 반등",
            "stock": "005930",
            "at": "2026-07-15T15:30:00+09:00",  # 5일 뒤 다른 거래일
            "vec": _jit(E_MARKET, 2),
        },
    ]
    rows, vecs = _mk_rows_and_vecs(specs)
    # 둘 다 market_wide 로 판별돼야 함
    assert MR.is_market_wide(specs[0]["title"])
    assert MR.is_market_wide(specs[1]["title"])
    assign, _ = cluster_all_variant(rows, vecs, STOCKS, VariantConfig(block_market_bridge=True))
    labels = _labels(assign, rows)
    assert len(set(labels.values())) == 2, "다른 거래일 시황이 하나로 붙음"


def test_3_market_news_no_bridge_between_events():
    """시황 기사가 서로 다른 기업 사건(A, B)을 잇는 다리가 되지 않는다.

    시간순: 기업A 기사 → 시황 기사(둘 다에 약한 유사) → 기업B 기사.
    보호 켜면 시황은 별도 클러스터라 A/B 를 잇지 못하고, A 와 B 는 분리 유지.
    """
    specs = [
        {
            "title": "삼성전자, 신형 반도체 공급 계약 체결",
            "stock": "005930",
            "at": "2026-07-10T09:00:00+09:00",
            "vec": E_COMPANY_A,
        },
        {
            "title": "코스피, 급락 마감…외국인 순매도 사이드카",
            "stock": "005930",
            "at": "2026-07-10T10:00:00+09:00",
            "vec": _norm(E_COMPANY_A + E_MARKET + E_COMPANY_B),  # 셋 다에 유사(브리지 후보)
        },
        {
            "title": "삼성전자, 미국 신공장 착공 발표",
            "stock": "005930",
            "at": "2026-07-10T11:00:00+09:00",
            "vec": E_COMPANY_B,
        },
    ]
    rows, vecs = _mk_rows_and_vecs(specs)
    assign, _ = cluster_all_variant(rows, vecs, STOCKS, VariantConfig(block_market_bridge=True))
    labels = _labels(assign, rows)
    ca = labels["0:005930"]
    cb = labels["2:005930"]
    assert ca != cb, "시황 브리지를 타고 기업A 와 기업B 가 한 클러스터가 됨"


def test_4_same_event_across_days_kept():
    """날짜가 달라도(활성창 내) 동일 기업 사건이면 유지될 수 있다."""
    specs = [
        {
            "title": "현대차 노조, 임단협 부분 파업 돌입",
            "stock": "005930",
            "at": "2026-07-10T09:00:00+09:00",
            "vec": _jit(E_COMPANY_A, 1),
        },
        {
            "title": "현대차 노조, 파업 이틀째 이어가",
            "stock": "005930",
            "at": "2026-07-11T09:00:00+09:00",  # 다음 날, 현재 활성창 24h 경계
            "vec": _jit(E_COMPANY_A, 2),
        },
    ]
    rows, vecs = _mk_rows_and_vecs(specs)
    assign, _ = cluster_all_variant(rows, vecs, STOCKS, VariantConfig(block_market_bridge=True))
    assert len(set(_labels(assign, rows).values())) == 1, "같은 기업 사건이 날짜 때문에 쪼개짐"


def test_7_info_not_bridging_company_events():
    """비사건형 투자정보(info)가 서로 다른 기업 사건을 잇는 다리가 되지 않는다.

    기업A 사건 → 투자정보(순위/추천/시세) → 기업B 사건 순서. info 는 별도 유형이라
    company A/B 를 잇지 못하고 A 와 B 는 분리 유지.
    """
    specs = [
        {
            "title": "두산에너빌리티, 발전기 모니터링 시스템 사업 확대",
            "stock": "005930",
            "at": "2026-07-10T09:00:00+09:00",
            "vec": E_COMPANY_A,
        },
        {
            "title": "두산에너빌리티 주가, 7월 10일 장중 78,900원 7.79% 상승",
            "stock": "005930",
            "at": "2026-07-10T10:00:00+09:00",
            "vec": _norm(E_COMPANY_A + E_MARKET + E_COMPANY_B),  # 브리지 후보
        },
        {
            "title": "두산에너빌리티, 해외 원전 조기 감지 시스템 공급 계약",
            "stock": "005930",
            "at": "2026-07-10T11:00:00+09:00",
            "vec": E_COMPANY_B,
        },
    ]
    rows, vecs = _mk_rows_and_vecs(specs)
    cfg = VariantConfig(block_market_bridge=True, separate_info=True)
    labels = _labels(cluster_all_variant(rows, vecs, STOCKS, cfg)[0], rows)
    assert labels["0:005930"] != labels["2:005930"], "info 브리지로 기업A·B가 한 클러스터"
    # 시세 기사는 info 로 분류돼야 함
    assert MR.classify_kind(specs[1]["title"]) == "info"


def test_8_event_articles_stay_company():
    """구체 기업 사건(계약·수주·착공·파업·지분)은 company 로 유지되어 info 로 새지 않는다."""
    events = [
        "한화오션, 신안우이 해상풍력 착공…390MW 발전단지 조성",
        "현대차 노조, 부분 파업 2배로 이어간다",
        "현대차그룹, 보스턴다이내믹스 지분 100% 확보",
        "한화 필리조선소, 미국 미사일시험 계측선 수주",
        "현대차, 전북대 피지컬 AI 계약학과 추진",
    ]
    for t in events:
        assert MR.classify_kind(t) == "company", f"사건형인데 info/market 로 분류됨: {t}"


def test_6_market_rules_copy_matches_service():
    """실험 폴더 복사본 market_rules.py 가 서비스 정본(exp_b/market_rules.py)과 동일.

    두 곳에 두는 대신 자동으로 동기 여부를 검증한다(갈라지면 실패).
    정본: exp_b/market_rules.py (pipeline 이 참조). 복사본: overmerge_fix/market_rules.py.
    """
    svc = (EXP_B / "market_rules.py").read_text(encoding="utf-8")
    cpy = (BASE / "market_rules.py").read_text(encoding="utf-8")
    assert svc == cpy, "market_rules 정본과 실험 복사본이 다름 — cp 로 재동기화 필요"


def test_5_protection_off_equals_baseline():
    """보호 기능을 끄면 기존 방식과 완전히 동일한 라벨을 낸다."""
    rng_specs = []
    for k in range(30):
        base = [E_COMPANY_A, E_MARKET, E_COMPANY_B][k % 3]
        rng_specs.append(
            {
                "title": f"코스피 급락 마감 기사 {k}" if k % 3 == 1 else f"삼성전자 계약 기사 {k}",
                "stock": STOCKS[k % 2],
                "at": f"2026-07-{10 + (k % 5):02d}T09:{k:02d}:00+09:00",
                "vec": _jit(base, k),
            }
        )
    rows, vecs = _mk_rows_and_vecs(rng_specs)
    off = _labels(
        cluster_all_variant(rows, vecs, STOCKS, VariantConfig(block_market_bridge=False))[0], rows
    )
    base = _labels(cluster_all_variant(rows, vecs, STOCKS, VariantConfig())[0], rows)
    assert off == base, "보호 OFF 가 baseline 과 다름"


def _run_all():
    tests = [
        test_1_same_event_many_press_stays_one,
        test_2_different_day_market_news_not_merged,
        test_3_market_news_no_bridge_between_events,
        test_4_same_event_across_days_kept,
        test_5_protection_off_equals_baseline,
        test_6_market_rules_copy_matches_service,
        test_7_info_not_bridging_company_events,
        test_8_event_articles_stay_company,
    ]
    ok = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            ok += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{ok}/{len(tests)} passed")
    return ok == len(tests)


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)

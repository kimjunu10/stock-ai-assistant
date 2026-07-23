"""금융 용어 소량 시드 (rag_terms 적재).

특정 종목/재무항목이 아니라 일반 금융 용어 사전 데이터다.
용어는 코드가 아닌 DB(rag_terms)에 저장되며, 정확일치/별칭/유사 검색에 쓰인다.
Phase 4 검증용 소량 시드이며, 이후 한국은행 경제금융용어 등으로 확장 가능(SPEC).

usage: uv run python scripts/seed_rag_terms.py [--apply]  (기본 dry-run)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.rag.normalization import build_search_text  # noqa: E402
from app.repositories.rag import RagRepository  # noqa: E402

# 초보 투자자 대상 소량 금융 용어(일반 사전). 종목/재무항목 하드코딩 아님.
SEED_TERMS = [
    {
        "term": "ADR",
        "aliases": ["미국주식예탁증서", "주식예탁증서", "American Depositary Receipt"],
        "english_name": "American Depositary Receipt",
        "official_definition": (
            "미국 시장에서 외국 기업의 주식을 대신해 거래되도록 발행한 예탁증서. "
            "미국 예탁기관이 원주를 보관하고 그에 대응하는 증서를 미국 거래소에 상장한다."
        ),
        "easy_definition": (
            "외국 회사 주식을 미국에서 사고팔 수 있게 만든 '주식 교환권' 같은 거예요."
        ),
    },
    {
        "term": "영업이익",
        "aliases": ["operating profit", "operating income"],
        "english_name": "Operating Profit",
        "official_definition": (
            "매출액에서 매출원가와 판매비·관리비를 뺀 이익으로, 기업의 본업에서 번 이익을 나타낸다."
        ),
        "easy_definition": (
            "회사가 본업으로 벌어들인 이익이에요. 매출에서 만들고 파는 비용을 뺀 값이에요."
        ),
    },
    {
        "term": "당기순이익",
        "aliases": ["net income", "순이익"],
        "english_name": "Net Income",
        "official_definition": (
            "일정 기간 동안 모든 수익에서 모든 비용과 법인세까지 뺀 뒤 최종적으로 남은 이익."
        ),
        "easy_definition": "세금까지 다 내고 회사에 최종적으로 남은 돈이에요.",
    },
    {
        "term": "유상증자",
        "aliases": ["paid-in capital increase", "증자"],
        "english_name": "Paid-in Capital Increase",
        "official_definition": (
            "기업이 새 주식을 발행하고 그 대금을 받아 자본금을 늘리는 것. "
            "자금 조달 목적으로 시행한다."
        ),
        "easy_definition": ("회사가 새 주식을 팔아서 돈을 더 모으는 거예요. 주식 수가 늘어나요."),
    },
    {
        "term": "자기주식",
        "aliases": ["treasury stock", "자사주"],
        "english_name": "Treasury Stock",
        "official_definition": (
            "회사가 이미 발행한 자기 회사 주식을 다시 사들여 보유하는 것. "
            "소각·성과급 지급 등에 쓰인다."
        ),
        "easy_definition": ("회사가 자기 회사 주식을 도로 사서 갖고 있는 거예요."),
    },
    {
        "term": "정정공시",
        "aliases": ["correction disclosure", "기재정정"],
        "english_name": "Correction Disclosure",
        "official_definition": (
            "이미 제출한 공시의 내용을 고쳐 다시 제출하는 공시. 최신 정정본이 유효한 내용이다."
        ),
        "easy_definition": "먼저 낸 공시를 고쳐서 다시 낸 거예요. 가장 최근 것이 맞는 내용이에요.",
    },
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 upsert. 없으면 dry-run.")
    args = ap.parse_args()

    rows = []
    for t in SEED_TERMS:
        rows.append(
            {
                **t,
                "search_text": build_search_text(
                    t["term"],
                    " ".join(t["aliases"]),
                    t.get("english_name"),
                    t["official_definition"],
                    t.get("easy_definition"),
                ),
                "is_active": True,
            }
        )

    if not args.apply:
        print(f"[dry-run] 시드 예정 용어 {len(rows)}개: {[r['term'] for r in rows]}")
        return 0

    repo = RagRepository(get_supabase_client(), settings)
    n = repo.upsert_terms(rows)
    print(f"용어 {n}개 upsert 완료: {[r['term'] for r in rows]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 8 §10: 평가셋 정적 검증 (모델 호출 없음).

검사 항목:
1. 평가 스키마 검증(pydantic)
2. 160개 질문 개수·유형 분포
3. 필수 필드 누락
4. 정답 출처 식별자 유효성(DB 실재 확인)
5. 숫자·단위·기간 형식
6. 개발셋·홀드아웃 중복

실행:
    cd backend
    .venv/bin/python scripts/phase8_validate_dataset.py          # DB 확인 포함
    .venv/bin/python scripts/phase8_validate_dataset.py --offline # 스키마·형식만
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.eval.schema import TYPE_QUOTA, EvalCase, EvalSuite  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"

_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, passed, detail))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def load(name: str) -> EvalSuite:
    return EvalSuite.model_validate(json.loads((EVAL_DIR / f"{name}.json").read_text("utf-8")))


def check_distribution(cases: list[EvalCase]) -> None:
    counts = Counter(c.type for c in cases)
    check("총 160문항", len(cases) == 160, f"{len(cases)}문항")
    bad = {
        t: (counts.get(t, 0), want) for t, want in TYPE_QUOTA.items() if counts.get(t, 0) != want
    }
    check(
        "유형별 분포 일치",
        not bad,
        "불일치 " + json.dumps(bad, ensure_ascii=False) if bad else "9개 유형 모두 일치",
    )


def check_required_fields(cases: list[EvalCase]) -> None:
    missing_basis = [c.id for c in cases if c.review_status == "confirmed" and not c.label_basis]
    check("확정 라벨의 근거 존재", not missing_basis, f"누락 {missing_basis[:5]}")

    no_tools = [
        c.id for c in cases if c.is_answerable and not (c.required_tools or c.required_tools_any)
    ]
    check("답변 가능 질문의 필수 기능 지정", not no_tools, f"누락 {no_tools[:5]}")

    no_expect = [c.id for c in cases if not c.is_answerable and not c.no_data_expectation]
    check("답변 불가 질문의 기대 행동 지정", not no_expect, f"누락 {no_expect[:5]}")

    empty_q = [c.id for c in cases if not c.question.strip()]
    check("질문 문자열 비어있지 않음", not empty_q, f"빈 질문 {empty_q[:5]}")


def check_formats(cases: list[EvalCase]) -> None:
    """숫자·단위·기간 형식 검사."""
    bad_unit = [
        f"{c.id}:{n.label}" for c in cases for n in c.expected_numbers if not n.unit.strip()
    ]
    check("기대 숫자에 단위 존재", not bad_unit, f"누락 {bad_unit[:5]}")

    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    bad_date = [
        f"{c.id}:{d}"
        for c in cases
        if c.expected_period
        for d in (
            c.expected_period.start_trading_day,
            c.expected_period.end_trading_day,
            c.expected_period.event_date,
        )
        if d and not date_re.match(d)
    ]
    check("거래일 YYYY-MM-DD 형식", not bad_date, f"형식 오류 {bad_date[:5]}")

    year_re = re.compile(r"^\d{4}$")
    bad_year = [
        f"{c.id}:{c.expected_period.business_year}"
        for c in cases
        if c.expected_period
        and c.expected_period.business_year
        and not year_re.match(c.expected_period.business_year)
    ]
    check("사업연도 4자리 형식", not bad_year, f"형식 오류 {bad_year[:5]}")

    bad_code = [c.id for c in cases if c.stock_code and not re.match(r"^\d{6}$", c.stock_code)]
    check("종목코드 6자리 형식", not bad_code, f"형식 오류 {bad_code[:5]}")


def check_overlap(dev: list[EvalCase], hold: list[EvalCase]) -> None:
    dev_ids = {c.id for c in dev}
    hold_ids = {c.id for c in hold}
    check(
        "개발·홀드아웃 id 중복 없음",
        not (dev_ids & hold_ids),
        f"중복 {sorted(dev_ids & hold_ids)[:5]}",
    )

    dev_q = Counter(c.question for c in dev)
    hold_q = Counter(c.question for c in hold)
    shared = sorted(set(dev_q) & set(hold_q))
    check("개발·홀드아웃 질문 중복 없음", not shared, f"중복 질문 {shared[:3]}")

    dupe_in_all = [q for q, n in (dev_q + hold_q).items() if n > 1]
    check("전체 질문 중복 없음", not dupe_in_all, f"중복 {dupe_in_all[:3]}")

    check("개발셋 120문항", len(dev) == 120, f"{len(dev)}문항")
    check("홀드아웃 40문항", len(hold) == 40, f"{len(hold)}문항")


def check_gold_sources(cases: list[EvalCase], client) -> None:
    """정답 출처 식별자가 실제 DB 에 있는지 확인한다."""
    fin_ids: list[str] = []
    disc_ids: list[str] = []
    term_ids: list[str] = []
    for c in cases:
        for gs in c.gold_sources:
            if not gs.source_id:
                continue
            if gs.source_type == "financial":
                fin_ids.append(gs.source_id)
            elif gs.source_type == "structured_disclosure":
                disc_ids.append(gs.source_id)
            elif gs.source_type == "term":
                term_ids.append(gs.source_id)

    # 재무: "code/year/reprt/fs_div/account/amount_label"
    missing_fin = []
    for sid in fin_ids:
        parts = sid.split("/")
        if len(parts) != 6:
            missing_fin.append(sid)
            continue
        code, year, reprt, fs_div, acct, amount_type = parts
        rows = (
            client.table("financials")
            .select("id")
            .eq("stock_code", code)
            .eq("bsns_year", year)
            .eq("reprt_code", reprt)
            .eq("fs_div", fs_div)
            .eq("account_nm", acct)
            .eq("amount_type", amount_type)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            missing_fin.append(sid)
    check(
        "재무 정답 식별자 DB 실재",
        not missing_fin,
        f"{len(fin_ids) - len(missing_fin)}/{len(fin_ids)} 확인, 누락 {missing_fin[:3]}",
    )

    # 공시: rcept_no
    missing_disc = []
    for sid in disc_ids:
        rows = (
            client.table("structured_disclosures")
            .select("id")
            .eq("rcept_no", sid)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            missing_disc.append(sid)
    check(
        "공시 정답 접수번호 DB 실재",
        not missing_disc,
        f"{len(disc_ids) - len(missing_disc)}/{len(disc_ids)} 확인, 누락 {missing_disc[:3]}",
    )

    # 용어: "term:{표제어}"
    missing_term = []
    for sid in term_ids:
        term = sid.split(":", 1)[1] if ":" in sid else sid
        rows = (
            client.table("rag_terms")
            .select("id")
            .eq("term", term)
            .eq("is_active", True)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            missing_term.append(sid)
    check(
        "용어 정답 표제어 DB 실재",
        not missing_term,
        f"{len(term_ids) - len(missing_term)}/{len(term_ids)} 확인, 누락 {missing_term[:3]}",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="DB 확인 없이 스키마·형식만 검사")
    args = ap.parse_args()

    try:
        dev_suite = load("devset")
        hold_suite = load("holdout")
        check("평가 스키마 검증(pydantic)", True, "devset·holdout 모두 통과")
    except Exception as e:  # noqa: BLE001
        check("평가 스키마 검증(pydantic)", False, str(e)[:300])
        return 1

    dev, hold = dev_suite.cases, hold_suite.cases
    allc = dev + hold

    check_distribution(allc)
    check_required_fields(allc)
    check_formats(allc)
    check_overlap(dev, hold)

    if not args.offline:
        from app.db.client import get_supabase_client

        check_gold_sources(allc, get_supabase_client())

    need = [c.id for c in allc if c.review_status == "needs_manual_review"]
    print(f"\n수동 검토 필요 라벨: {len(need)}건")

    failed = [n for n, ok, _ in _RESULTS if not ok]
    print(f"\n{len(_RESULTS) - len(failed)}/{len(_RESULTS)} 통과")
    if failed:
        print("실패: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

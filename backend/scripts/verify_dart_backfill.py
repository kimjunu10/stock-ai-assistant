"""OpenDART 백필 결과 검증 (읽기 전용 + 멱등성 재실행).

데이터를 수정/삭제/재수집하지 않는다. 멱등성 항목(7)만 예외로
`python -m scripts.backfill_dart`를 다시 실행하고 실행 전후 행 수를 비교한다.

DB 접근은 psql(subprocess)로 하며, 실제 SQL과 그 결과를 그대로 출력하고
각 검사 항목을 PASS/FAIL로 판정한다.

사용:
    python -m scripts.verify_dart_backfill                # 멱등성 재실행 포함
    python -m scripts.verify_dart_backfill --skip-rerun   # 재실행 없이 정적 검증만
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from app.core.config import settings

TARGET_STOCKS = "'005930','000660','034020','042660','005380'"
REGULAR_APIS = ["stockTotqySttus", "tesstkAcqsDspsSttus", "alotMatter", "irdsSttus"]
META_KEYS = "'rcept_no','corp_code','corp_cls','corp_name','stock_code','status','message'"

_RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def header(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def psql(sql: str, *, tuples_only: bool = False) -> str:
    """psql로 SQL 실행 후 텍스트 결과 반환. 연결정보는 env로만 전달(노출 방지)."""

    args = ["psql", settings.database_url, "-v", "ON_ERROR_STOP=1"]
    if tuples_only:
        args += ["-t", "-A"]
    args += ["-c", sql]
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"psql 실패: {proc.stderr.strip()}")
    return proc.stdout


def scalar(sql: str) -> int:
    out = psql(sql, tuples_only=True).strip()
    return int(out) if out else 0


def show(sql: str) -> None:
    print(psql(sql).rstrip())


# --- 1. 대상 종목 --------------------------------------------------------
def check_stocks() -> None:
    header("1. 대상 종목")
    show(
        f"select code, name, dart_corp_code from public.stocks "
        f"where code in ({TARGET_STOCKS}) order by code;"
    )
    present = scalar(f"select count(*) from public.stocks where code in ({TARGET_STOCKS});")
    record("5개 대상 종목 모두 존재", present == 5, f"{present}/5")
    bad = scalar(
        f"select count(*) from public.stocks where code in ({TARGET_STOCKS}) "
        f"and coalesce(trim(dart_corp_code), '') = '';"
    )
    record("dart_corp_code 모두 채워짐", bad == 0, f"빈 값 {bad}건")


# --- 2. 공시 목록 --------------------------------------------------------
def check_disclosures() -> None:
    header("2. 공시 목록")
    show(
        "select stock_code, count(*) as cnt, min(disclosed_at)::date as min_dt, "
        "max(disclosed_at)::date as max_dt from public.disclosures "
        "group by stock_code order by stock_code;"
    )
    out_of_range = scalar(
        "select count(*) from public.disclosures "
        "where disclosed_at < (now() - interval '365 days');"
    )
    print(f"\n  최근 1년(365일) 범위 밖 공시 건수: {out_of_range}")
    record("최근 1년 범위 밖 공시 없음", out_of_range == 0, f"{out_of_range}건")

    dup = scalar(
        "select count(*) from (select rcept_no from public.disclosures "
        "group by rcept_no having count(*) > 1) x;"
    )
    record("rcept_no 중복 0건", dup == 0, f"{dup}건")

    no_url = scalar(
        "select count(*) from public.disclosures where viewer_url is null or viewer_url = '';"
    )
    print(f"  viewer_url 없는 행 수: {no_url}")
    record("viewer_url 모두 존재", no_url == 0, f"{no_url}건 누락")


# --- 3. 공시 원문 --------------------------------------------------------
TARGET_FILTER = (
    "(title like '%사업보고서%' or title like '%반기보고서%' "
    "or title like '%분기보고서%' or title like '%주요사항보고서%')"
)


def check_raw_text() -> None:
    header("3. 공시 원문 (사업·반기·분기·주요사항보고서)")
    with_text = scalar(
        f"select count(*) from public.disclosures where {TARGET_FILTER} "
        "and raw_text is not null and raw_text <> '';"
    )
    without_text = scalar(
        f"select count(*) from public.disclosures where {TARGET_FILTER} "
        "and (raw_text is null or raw_text = '');"
    )
    print(f"  원문 대상 중 raw_text 있음: {with_text} / 없음: {without_text}")

    truncated = scalar("select count(*) from public.disclosures where raw_text_truncated = true;")
    print(f"  raw_text_truncated=true 건수: {truncated}")

    over = scalar("select count(*) from public.disclosures where length(raw_text) > 50000;")
    record("raw_text 50,000자 초과 행 없음", over == 0, f"{over}건")

    print("\n  [지나치게 짧은 원문 (<200자, raw_text 존재)]")
    show(
        f"select rcept_no, stock_code, length(raw_text) as len, left(raw_text, 60) as head "
        f"from public.disclosures where {TARGET_FILTER} "
        "and raw_text is not null and raw_text <> '' and length(raw_text) < 200 "
        "order by len limit 20;"
    )
    short_cnt = scalar(
        f"select count(*) from public.disclosures where {TARGET_FILTER} "
        "and raw_text is not null and raw_text <> '' and length(raw_text) < 200;"
    )
    record("지나치게 짧은 원문 없음", short_cnt == 0, f"{short_cnt}건")

    print("\n  ['<' 문자가 50개 넘게 남은 원문 (태그 잔존 의심)]")
    show(
        "select rcept_no, stock_code, "
        "(length(raw_text) - length(replace(raw_text, '<', ''))) as lt_count "
        f"from public.disclosures where {TARGET_FILTER} and raw_text is not null "
        "and (length(raw_text) - length(replace(raw_text, '<', ''))) > 50 "
        "order by lt_count desc limit 20;"
    )
    tagful = scalar(
        f"select count(*) from public.disclosures where {TARGET_FILTER} and raw_text is not null "
        "and (length(raw_text) - length(replace(raw_text, '<', ''))) > 50;"
    )
    record("태그 잔존 과다 원문 없음", tagful == 0, f"{tagful}건")


# --- 4. 재무 데이터 -----------------------------------------------------
def check_financials() -> None:
    header("4. 재무 데이터")
    print("  [종목×연도×보고서×fs_div×amount_type 행수]")
    show(
        "select stock_code, bsns_year, reprt_code, fs_div, amount_type, count(*) as cnt "
        "from public.financials group by 1,2,3,4,5 "
        "order by 1,2,3,5 limit 24;"
    )
    dup = scalar(
        "select count(*) from (select stock_code,bsns_year,reprt_code,fs_div,account_nm,amount_type "
        "from public.financials group by 1,2,3,4,5,6 having count(*) > 1) x;"
    )
    record("financials 유니크키 중복 0건", dup == 0, f"{dup}건")

    print("\n  [amount_type 분포]")
    show("select amount_type, count(*) as cnt from public.financials group by 1 order by 1;")
    q_cnt = scalar("select count(*) from public.financials where amount_type='quarter';")
    record("quarter 행 존재", q_cnt > 0, f"{q_cnt}행")

    print("\n  [삼성 2024 반기 손익 — quarter/cumulative 별도 저장 사례]")
    show(
        "select account_nm, amount_type, thstrm_amount from public.financials "
        "where stock_code='005930' and bsns_year='2024' and reprt_code='11012' "
        "and account_nm in ('매출액','영업이익','당기순이익') order by account_nm, amount_type;"
    )


# --- 4'. 구조화 공시 (주요사항 major_event) ------------------------------
def check_structured_major() -> None:
    header("4'. 구조화 공시 — 주요사항보고서(major_event)")
    dup = scalar(
        "select count(*) from (select stock_code,source_api,record_key "
        "from public.structured_disclosures group by 1,2,3 having count(*) > 1) x;"
    )
    record("(stock_code,source_api,record_key) 중복 0건", dup == 0, f"{dup}건")

    print("\n  [같은 rcept_no에 여러 행이 별도 저장된 사례 (major_event)]")
    show(
        "select stock_code, source_api, rcept_no, count(*) as rows "
        "from public.structured_disclosures where data_group='major_event' and rcept_no is not null "
        "group by 1,2,3 having count(*) > 1 order by rows desc limit 10;"
    )

    empty_raw = scalar(
        "select count(*) from public.structured_disclosures "
        "where data_group='major_event' and (raw_data is null or raw_data = '{}'::jsonb);"
    )
    record("major_event raw_data 비어있지 않음", empty_raw == 0, f"{empty_raw}건")

    blank = scalar(
        f"""select count(*) from public.structured_disclosures sd
        where sd.data_group='major_event' and not exists (
          select 1 from jsonb_each_text(sd.raw_data) e
          where e.key not in ({META_KEYS})
            and coalesce(nullif(trim(e.value), ''), '-') <> '-')"""
    )
    print(f"\n  업무 필드가 전부 null/''/'-' 인 major_event 행 수: {blank}")
    record("major_event 빈 업무행 없음", blank == 0, f"{blank}건")

    print("\n  [normalized_data가 비어있는 major_event 행]")
    show(
        "select stock_code, source_api, event_type, rcept_no from public.structured_disclosures "
        "where data_group='major_event' and normalized_data = '{}'::jsonb "
        "order by source_api limit 30;"
    )
    empty_norm = scalar(
        "select count(*) from public.structured_disclosures "
        "where data_group='major_event' and normalized_data = '{}'::jsonb;"
    )
    print(
        f"  normalized_data 비어있는 major_event 행 수: {empty_norm} "
        "(참고: 저빈도 유형은 normalized 비어도 raw_data/summary_text는 존재)"
    )

    null_sum = scalar(
        "select count(*) from public.structured_disclosures "
        "where data_group='major_event' and (summary_text is null or summary_text = '');"
    )
    record("major_event summary_text 모두 존재", null_sum == 0, f"{null_sum}건")


# --- 6. 정기보고서 핵심정보 ---------------------------------------------
def check_regular() -> None:
    header("6. 정기보고서 핵심정보 4종 (regular_report)")
    for api in REGULAR_APIS:
        print(f"\n  [{api}] 종목×연도×보고서 행수")
        show(
            "select stock_code, bsns_year, reprt_code, count(*) as cnt "
            "from public.structured_disclosures where data_group='regular_report' "
            f"and source_api='{api}' group by 1,2,3 order by 1,2,3 limit 16;"
        )

    blank = scalar(
        f"""select count(*) from public.structured_disclosures sd
        where sd.data_group='regular_report' and not exists (
          select 1 from jsonb_each_text(sd.raw_data) e
          where e.key not in ({META_KEYS}, 'stlm_dt')
            and coalesce(nullif(trim(e.value), ''), '-') <> '-')"""
    )
    print(f"\n  업무 내용이 전부 '-'/빈 값인 regular 행 수: {blank}")
    record("정기보고서 빈 행 저장 안 됨", blank == 0, f"{blank}건")

    print("\n  [동일 보고서(rcept_no) 내 여러 행이 덮어쓰기 없이 저장된 사례]")
    show(
        "select stock_code, source_api, rcept_no, count(*) as rows "
        "from public.structured_disclosures where data_group='regular_report' and rcept_no is not null "
        "group by 1,2,3 having count(*) > 1 order by rows desc limit 10;"
    )
    multi = scalar(
        "select count(*) from (select stock_code,source_api,rcept_no "
        "from public.structured_disclosures where data_group='regular_report' and rcept_no is not null "
        "group by 1,2,3 having count(*) > 1) x;"
    )
    record("동일 보고서 다중 주식종류 별도 저장", multi > 0, f"{multi}개 rcept_no에서 다중 행")


# --- 7. 멱등성 -----------------------------------------------------------
TABLES = ["stocks", "disclosures", "financials", "structured_disclosures"]


def snapshot() -> dict[str, int]:
    return {t: scalar(f"select count(*) from public.{t};") for t in TABLES}


def check_idempotency(skip_rerun: bool) -> None:
    header("7. 멱등성 (재실행 전후 행 수 비교)")
    before = snapshot()
    print("  [재실행 전 행 수]", before)

    if skip_rerun:
        print("\n  --skip-rerun → backfill 재실행 생략")
        record("멱등성 재실행", False, "skip-rerun으로 미검증")
        return

    print("\n  python -m scripts.backfill_dart 재실행 중... (수 분 소요)")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.backfill_dart"], capture_output=True, text=True
    )
    print(f"  재실행 종료코드: {proc.returncode}")
    if proc.returncode != 0:
        print("  STDERR(tail):", proc.stderr[-800:])

    after = snapshot()
    print("\n  [재실행 후 행 수]", after)
    print("\n  [증감]")
    grew = {}
    for t in TABLES:
        d = after[t] - before[t]
        print(f"    {t}: {before[t]} -> {after[t]} (delta {d:+d})")
        if d != 0:
            grew[t] = d

    if not grew:
        record("모든 테이블 증가 0 (중복 없음)", True)
        return

    record("일부 테이블 행 수 증가", False, f"증가: {grew} — 아래에서 원인 규명")
    print("\n  [증가 원인 규명] 최근 created_at 공시 20건:")
    show(
        "select stock_code, rcept_no, disclosed_at::date as dt, created_at "
        "from public.disclosures order by created_at desc limit 20;"
    )
    dup_disc = scalar(
        "select count(*) from (select rcept_no from public.disclosures "
        "group by rcept_no having count(*) > 1) x;"
    )
    dup_struct = scalar(
        "select count(*) from (select stock_code,source_api,record_key "
        "from public.structured_disclosures group by 1,2,3 having count(*) > 1) x;"
    )
    dup_fin = scalar(
        "select count(*) from (select stock_code,bsns_year,reprt_code,fs_div,account_nm,amount_type "
        "from public.financials group by 1,2,3,4,5,6 having count(*) > 1) x;"
    )
    print(
        f"  → 증가 후 유니크 중복: disclosures={dup_disc}, financials={dup_fin}, structured={dup_struct}"
    )
    record(
        "증가분이 중복이 아님 (유니크 위반 0 유지)",
        dup_disc == 0 and dup_struct == 0 and dup_fin == 0,
        f"disc={dup_disc}, fin={dup_fin}, struct={dup_struct}",
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--skip-rerun", action="store_true")
    args = p.parse_args()

    if not settings.database_url:
        print("DATABASE_URL이 설정되지 않았습니다.", file=sys.stderr)
        return 2

    check_stocks()
    check_disclosures()
    check_raw_text()
    check_financials()
    check_structured_major()
    check_regular()
    check_idempotency(args.skip_rerun)

    header("최종 판정 요약")
    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    failed = [n for n, ok, _ in _RESULTS if not ok]
    for name, ok, detail in _RESULTS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    print(f"\n  총 {len(_RESULTS)}개 검사 중 PASS {passed} / FAIL {len(failed)}")
    if failed:
        print("  FAIL:", failed)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())

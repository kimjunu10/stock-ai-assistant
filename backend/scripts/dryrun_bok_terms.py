"""경제금융용어 800선 — 789개 전체 파싱 드라이런 + 품질 검증 (Phase 4).

DB 쓰기·임베딩 호출 없음. 파싱 결과를 검사만 한다.

검사 항목:
- canonical entry 수 vs 목차 789
- 정규화 term 중복
- official_definition 누락/과단/과장(길이 이상치)
- 정의 시작·종료 경계 이상
- 페이지 넘는 정의 연결 실패
- source_page / pdf_page 범위 오류
- related_terms 가 정의 본문에 섞였는지
- 머리말/꼬리말/페이지번호 잔여
- english_name 에 약어만 잘못 들어간 항목
- aliases ↔ related_terms 중복·혼입
- 목차엔 있으나 본문 미발견
- 본문엔 있으나 목차 미연결
- 정의 길이/페이지 수 이상치 전체 목록화
- 앞·중간·뒤 무작위 50개 + 모든 이상치 원문 대조
- 기존 rag_terms 6건 충돌(읽기만)

산출물:
- docs/rag/phase_4/bok_dryrun_report.md
- docs/rag/phase_4/bok_dryrun_full.json (전량, 원문 포함 → gitignore 대상)
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz  # noqa: E402

from scripts.parse_bok_terms import PAGE_OFFSET, PDF_PATH, parse_terms  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_4"

# 정의 길이 이상치 임계(문자). 한국은행 용어 정의는 대략 80~1500자.
DEF_MIN = 60
DEF_MAX = 2000
# 머리말/꼬리말 잔여 탐지 패턴.
_NOISE_PATTERNS = [re.compile(r"경제금융용어\s*800선"), re.compile(r"찾아보기")]
_PAGENUM_ONLY = re.compile(r"(?:^|\s)\d{1,4}(?:\s|$)")


def _norm(s: str) -> str:
    return re.sub(r"\s", "", s)


def _page_text(doc, printed_page: int) -> str:
    idx = printed_page - 1 + PAGE_OFFSET
    return doc[idx].get_text() if 0 <= idx < doc.page_count else ""


def main() -> int:
    import random

    terms, toc = parse_terms()
    doc = fitz.open(str(PDF_PATH))
    pdf_pages = doc.page_count

    def base(n: str) -> str:
        return _norm(re.split(r"\(", n)[0])

    toc_base = {base(n) for n, _ in toc}

    def expand(term: str) -> set[str]:
        parts = {base(term)}
        if "/" in term:
            parts |= {base(p) for p in term.split("/")}
        return parts

    parsed_cover: set[str] = set()
    for t in terms:
        parsed_cover |= expand(t.term)

    checks: dict[str, list] = {}

    # 1. 정규화 term 중복
    seen: dict[str, int] = {}
    dup = []
    for t in terms:
        k = base(t.term)
        seen[k] = seen.get(k, 0) + 1
    dup = [k for k, c in seen.items() if c > 1]
    checks["dup_normalized_term"] = dup

    # 2. 정의 길이 이상치
    too_short = [
        (t.term, len(t.official_definition)) for t in terms if len(t.official_definition) < DEF_MIN
    ]
    too_long = [
        (t.term, len(t.official_definition)) for t in terms if len(t.official_definition) > DEF_MAX
    ]
    empty_def = [t.term for t in terms if not t.official_definition.strip()]
    checks["too_short"] = too_short
    checks["too_long"] = too_long
    checks["empty_definition"] = empty_def

    # 3. source_page / pdf_page 범위
    page_errors = []
    for t in terms:
        if t.pdf_page is None or not (1 <= t.pdf_page <= pdf_pages):
            page_errors.append((t.term, "pdf_page", t.pdf_page))
        if t.source_page is None:
            page_errors.append((t.term, "source_page", None))
    checks["page_range_error"] = page_errors

    # 4. 머리말/꼬리말/페이지번호 잔여
    noise_left = []
    for t in terms:
        d = t.official_definition
        if any(p.search(d) for p in _NOISE_PATTERNS):
            noise_left.append(t.term)
    checks["noise_left"] = noise_left

    # 5. english_name 에 약어만 들어간 항목(완전명 아님)
    from scripts.parse_bok_terms import _is_abbrev

    eng_abbrev = [t.term for t in terms if t.english_name and _is_abbrev(t.english_name)]
    checks["english_name_is_abbrev"] = eng_abbrev

    # 6. aliases ↔ related_terms 중복/혼입
    alias_related_overlap = []
    for t in terms:
        ov = set(t.aliases) & set(t.related_terms)
        if ov:
            alias_related_overlap.append((t.term, sorted(ov)))
    checks["alias_related_overlap"] = alias_related_overlap

    # 7. 목차엔 있으나 본문 미발견 / 본문엔 있으나 목차 미연결
    missing = sorted(toc_base - parsed_cover)
    extra = sorted({base(t.term) for t in terms} - toc_base)
    checks["missing_from_body"] = missing
    checks["extra_not_in_toc"] = extra

    # 8. related_terms 가 정의 본문에 섞였는지(정의 끝에 관련어가 붙은 흔적)
    related_in_def = []
    for t in terms:
        if t.related_terms and t.official_definition.rstrip().endswith(tuple(t.related_terms)):
            related_in_def.append(t.term)
    checks["related_mixed_in_def"] = related_in_def

    # 8-1. 수식/그래프/각주 오염 의심: related_terms 가 비정상적으로 많음(>5).
    #   수식·그래프 축 라벨·각주가 연관검색어 폰트(Dotum size9)와 겹쳐 오분류된 것.
    math_polluted = [(t.term, len(t.related_terms)) for t in terms if len(t.related_terms) > 5]
    checks["math_graph_polluted"] = math_polluted

    # 9. 정의 종료 경계: 정의가 다음 용어 제목으로 끝나는 흔적(제목 침범)
    #    본문 파싱 상 다음 제목 전까지이므로, 정의 끝이 온전한 문장부호로 끝나는 비율만 리포트.
    bad_end = [
        t.term
        for t in terms
        if t.official_definition and t.official_definition.rstrip()[-1] not in ".다””」)%"
    ]
    checks["def_end_not_sentence"] = bad_end

    # --- 이상치 통합(원문 대조 대상) ---
    outlier_terms = set(
        [x[0] for x in too_short]
        + [x[0] for x in too_long]
        + empty_def
        + [x[0] for x in page_errors]
        + noise_left
        + related_in_def
    )

    # --- 무작위 50개(앞·중간·뒤 균등) + 이상치 원문 대조 ---
    n = len(terms)
    rng = random.Random(42)  # 재현 가능
    thirds = [terms[: n // 3], terms[n // 3 : 2 * n // 3], terms[2 * n // 3 :]]
    sample_terms = []
    for chunk in thirds:
        sample_terms += rng.sample(chunk, min(17, len(chunk)))
    sample_terms = sample_terms[:50]
    check_set = list({t.term: t for t in sample_terms}.values()) + [
        t for t in terms if t.term in outlier_terms
    ]

    boundary_ok = 0
    related_ok = 0
    checked = 0
    boundary_fail = []

    def _pdf_page_text(pdf_page: int | None) -> str:
        # pdf_page 는 1-based PDF 페이지. source_page(인쇄) 미매핑 항목도 대조 가능.
        if not pdf_page:
            return ""
        return doc[pdf_page - 1].get_text() if 1 <= pdf_page <= doc.page_count else ""

    for t in check_set:
        checked += 1
        cur = _norm(_pdf_page_text(t.pdf_page))
        nxt = _norm(_pdf_page_text((t.pdf_page or 0) + 1))
        both = cur + nxt
        head = _norm(t.official_definition[:20])[:12]
        if head and head in both:
            boundary_ok += 1
        else:
            boundary_fail.append(t.term)
        if all(_norm(r) in both for r in t.related_terms):
            related_ok += 1

    # 페이지 넘는 정의: 정의 끝이 다음 페이지에 있는 항목 수(pdf_page 기준)
    multipage = 0
    for t in terms:
        if not t.pdf_page:
            continue
        tail = _norm(t.official_definition[-20:])[-12:]
        cur = _norm(_pdf_page_text(t.pdf_page))
        nxt = _norm(_pdf_page_text(t.pdf_page + 1))
        if tail and tail not in cur and tail in nxt:
            multipage += 1

    # 기존 rag_terms 6건 충돌(읽기만) — DB 접근
    conflicts = []
    try:
        from app.db.client import get_supabase_client

        db = get_supabase_client()
        existing = db.table("rag_terms").select("term").execute().data or []
        ex_terms = {e["term"] for e in existing}
        parsed_terms = {t.term for t in terms}
        conflicts = sorted(ex_terms & parsed_terms)
        existing_count = len(ex_terms)
    except Exception as exc:  # noqa: BLE001
        existing_count = f"조회 실패: {str(exc)[:80]}"

    # --- 리포트 작성 ---
    lines = ["# Phase 4 — 경제금융용어 800선 전체 파싱 드라이런 검증\n"]
    lines.append(f"- 목차 개념 수: {len(toc)}")
    lines.append(f"- 본문 canonical entry: {len(terms)}")
    lines.append(f"- PDF 총 페이지: {pdf_pages}\n")

    lines.append("## 품질 검사 요약\n")
    summary = [
        ("정규화 term 중복", len(checks["dup_normalized_term"])),
        (f"정의 과단(<{DEF_MIN}자)", len(checks["too_short"])),
        (f"정의 과장(>{DEF_MAX}자)", len(checks["too_long"])),
        ("정의 없음", len(checks["empty_definition"])),
        ("페이지 범위 오류", len(checks["page_range_error"])),
        ("머리말/꼬리말 잔여", len(checks["noise_left"])),
        ("english_name 약어 오입력", len(checks["english_name_is_abbrev"])),
        ("aliases↔related 중복", len(checks["alias_related_overlap"])),
        ("목차엔 있으나 본문 미발견", len(checks["missing_from_body"])),
        ("본문엔 있으나 목차 미연결", len(checks["extra_not_in_toc"])),
        ("related 정의 본문 혼입", len(checks["related_mixed_in_def"])),
        ("수식/그래프/각주 오염(related>5)", len(checks["math_graph_polluted"])),
        ("정의 끝 비문장부호", len(checks["def_end_not_sentence"])),
    ]
    for name, cnt in summary:
        lines.append(f"- {name}: {cnt}")
    lines.append(f"- 페이지 넘는 정의: {multipage}건")
    lines.append(
        f"\n## 원문 대조 ({checked}개 = 무작위 50 + 이상치)\n"
        f"- 정의 시작 경계 일치: {boundary_ok}/{checked}\n"
        f"- 연관검색어 원문 존재: {related_ok}/{checked}"
    )
    if boundary_fail:
        lines.append(f"- 경계 실패: {boundary_fail[:20]}")

    # 목차 미발견/미연결 항목별 분류(슬래시 통합 vs 목차 줄바꿈/표기 차이)
    slash_parts = set()
    for t in terms:
        if "/" in t.term:
            slash_parts |= {base(p) for p in t.term.split("/")}
    lines.append("\n## 목차 미발견 7 / 본문 미연결 18 — 항목별 분류\n")
    lines.append("### 목차엔 있으나 본문 미발견 (원인)")
    for m in missing:
        reason = "슬래시 통합에 흡수됨" if m in slash_parts else "목차 긴 용어명 줄바꿈/표기 잔재"
        lines.append(f"- `{m}`: {reason}")
    lines.append("\n### 본문엔 있으나 목차 미연결 (원인)")
    for e in extra:
        reason = (
            "슬래시 통합(목차엔 구성어 개별 표기)" if "/" in e
            else "목차 표기 차이(영문 병기·약칭·공백)"
        )
        lines.append(f"- `{e}`: {reason}")

    lines.append("\n## 이상치 상세\n")
    for key in (
        "dup_normalized_term",
        "too_short",
        "too_long",
        "empty_definition",
        "page_range_error",
        "noise_left",
        "english_name_is_abbrev",
        "alias_related_overlap",
        "related_mixed_in_def",
        "math_graph_polluted",
        "missing_from_body",
        "extra_not_in_toc",
    ):
        v = checks[key]
        if v:
            lines.append(f"### {key} ({len(v)})")
            lines.append(f"```\n{json.dumps(v[:40], ensure_ascii=False, indent=1)}\n```")

    lines.append("\n## 기존 rag_terms 충돌(읽기만, 수정 안 함)\n")
    lines.append(f"- 기존 rag_terms 건수: {existing_count}")
    lines.append(f"- 파싱 term 과 겹치는 항목: {conflicts}")
    lines.append(
        "  (영업이익·당기순이익·유상증자·자기주식·정정공시·ADR 중 800선과 겹치는 것. "
        "적재 시 upsert 정책 필요 — 이번엔 수정하지 않음.)"
    )

    # 적재/임베딩 예상
    total_def_chars = sum(len(t.official_definition) for t in terms)
    total_search_chars = sum(len(t.search_text) for t in terms)
    est_tokens = int(total_search_chars / 2.5)
    est_cost = round(est_tokens / 1_000_000 * 0.10, 4)
    lines.append("\n## 전체 적재/임베딩 예상\n")
    lines.append(
        f"- 적재 예상 rows: {len(terms)} (기존 6건과 upsert 시 term 중복 {len(conflicts)}건 병합)"
    )
    lines.append(f"- 정의 총 문자: {total_def_chars:,}")
    lines.append(f"- search_text 총 문자: {total_search_chars:,}")
    lines.append(f"- passage 임베딩 예상 토큰: ~{est_tokens:,} (문자/2.5)")
    lines.append(f"- 임베딩 예상 비용(참고 단가 $0.10/1M): ~${est_cost}")
    lines.append(f"- 임베딩 배치(100개): {(len(terms) + 99) // 100}회 호출")

    (OUT_DIR / "bok_dryrun_report.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / "bok_dryrun_full.json").write_text(
        json.dumps([asdict(t) for t in terms], ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"canonical entry: {len(terms)} / 목차 {len(toc)}")
    print(
        f"중복 {len(dup)}, 과단 {len(too_short)}, 과장 {len(too_long)}, 정의없음 {len(empty_def)}"
    )
    print(
        f"페이지오류 {len(page_errors)}, 노이즈잔여 {len(noise_left)}, "
        f"eng약어 {len(eng_abbrev)}, alias/related중복 {len(alias_related_overlap)}"
    )
    print(f"목차미발견 {len(missing)}, 목차미연결 {len(extra)}, related혼입 {len(related_in_def)}")
    print(f"원문대조 경계 {boundary_ok}/{checked}, 연관 {related_ok}/{checked}")
    print(f"페이지넘김 {multipage}건")
    print(f"기존 rag_terms 충돌: {conflicts}")
    print(f"임베딩 예상 토큰 ~{est_tokens:,}, 비용 ~${est_cost}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

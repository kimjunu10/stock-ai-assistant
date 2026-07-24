"""Phase 5 파서 회귀 검증 (read-only).

키움 병합셀 재정렬 규칙 + 토큰 단위 value_kind 합계 일치 + 값 손실 0 을 검증한다.
키움 파일 + 다른 증권사 일부만 대상. DB·Storage·임베딩 없음.

실행:
    uv run --with pymupdf python scripts/phase5_verify_parser.py
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.report_parser import normalize_cell, parse_report  # noqa: E402

REPORT_ROOT = Path("/Users/kimjunwoo/report")


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _pick(broker_hint: str, limit: int) -> list[Path]:
    out: list[Path] = []
    for d in sorted(REPORT_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        for f in sorted(d.glob("*.pdf")):
            if broker_hint in _nfc(f.name):
                out.append(f)
                if len(out) >= limit:
                    return out
    return out


def main() -> int:
    # 키움 3개 + 다른 증권사(대신·IBK·교보) 각 1개
    targets = (
        _pick("키움증권", 3) + _pick("대신증권", 1) + _pick("IBK투자증권", 1) + _pick("교보증권", 1)
    )
    print(f"검증 대상 {len(targets)}개\n")

    total_aef = 0
    total_vk_sum = 0
    total_checked = 0
    total_mismatch = 0
    value_loss = 0  # 재정렬로 값이 사라지거나 바뀐 셀 수

    for p in targets:
        rep = parse_report(str(p))
        vk_sum = sum(rep.aef_value_kind_counts.values())
        # (1) 토큰 단위 value_kind 합계 == aef_value_total
        aef_ok = vk_sum == rep.aef_value_total
        total_aef += rep.aef_value_total
        total_vk_sum += vk_sum
        total_checked += rep.numbers_checked
        total_mismatch += rep.number_mismatches
        rate = (rep.numbers_checked - rep.number_mismatches) / max(1, rep.numbers_checked)
        broker = _nfc(p.name).split("_")[2] if len(_nfc(p.name).split("_")) > 2 else "?"
        print(
            f"[{broker}] {_nfc(p.name)[:44]}\n"
            f"    status={rep.parse_status} 표{len(rep.tables)} "
            f"A/E/F={rep.aef_value_total} vk합={vk_sum} 합일치={aef_ok} "
            f"원문대조={rate:.1%} vk={rep.aef_value_kind_counts}"
        )

    # (2) 값 손실 0 확인: 재정렬 전후 셀에서 숫자(콤마 제거) 다중집합이 보존되는지
    #     normalize_cell 이 값을 바꾸지 않는지 병합셀 표본으로 직접 확인
    import re

    def digits_multiset(s: str) -> list[str]:
        # 콤마·공백 제거 후 숫자 토큰만 추출(값 보존 판정용)
        return sorted(re.findall(r"\d+", s.replace(",", "")))

    sample_cells = [
        "25358 27134 29304 29597 , , , ,",
        "19020 ,",
        "333614 ,",
        "55 .",
        "매출액 영업이익",  # 숫자 없음
    ]
    for c in sample_cells:
        before = digits_multiset(c)
        after = digits_multiset(normalize_cell(c))
        if before != after:
            value_loss += 1
            print(f"  [값손실!] '{c}' -> '{normalize_cell(c)}' ({before} != {after})")

    print("\n=== 합계 ===")
    print(
        f"A/E/F 총합: {total_aef}, value_kind 토큰합: {total_vk_sum}, "
        f"일치: {total_aef == total_vk_sum}"
    )
    print(
        f"원문 대조: {total_checked - total_mismatch}/{total_checked} "
        f"({(total_checked - total_mismatch) / max(1, total_checked):.1%})"
    )
    print(f"값 손실 셀 수: {value_loss} (0 이어야 통과)")
    ok = total_aef == total_vk_sum and value_loss == 0
    print(f"\n결과: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

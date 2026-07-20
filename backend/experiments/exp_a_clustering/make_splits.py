"""실험 A [2] group-aware stock-balanced split.

AI-reviewed reference set을 split_unit_id 단위로 development/validation/test(60/20/20)로
나눈다. 같은 split_unit_id(= 같은 gold_event_id / 공유 article_id 묶음)는 반드시 같은
split에 들어가므로 article_id·gold_event_id 누출이 원천 차단된다.

- 단일 날짜 cutoff 미적용. 종목별로 unit을 배분해 종목별 시점 분포/행수를 균형 있게.
- 고정 seed=42. 결정적.
- 멀티종목 unit(공유 article_id)은 unit 무결성 우선 — 한 split에만 배정.

산출:
  splits/{development,validation,test}.csv
  splits/split_manifest.csv
  reports/split_report.md
"""

from __future__ import annotations

import csv
import random
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
REF_CSV = BASE / "labels" / "cluster_reference_ai_reviewed_final.csv"
SPLITS_DIR = BASE / "splits"
REPORTS_DIR = BASE / "reports"

SEED = 42
RATIOS = {"development": 0.60, "validation": 0.20, "test": 0.20}
STOCKS = ["005930", "000660", "034020", "042660", "005380"]


def load_rows() -> list[dict]:
    with REF_CSV.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build_units(rows: list[dict]) -> dict[str, dict]:
    """split_unit_id → {rows, row_count, primary_stock, stocks, dates}."""

    units: dict[str, dict] = defaultdict(
        lambda: {"rows": [], "stock_counter": Counter(), "dates": []}
    )
    for r in rows:
        u = units[r["split_unit_id"]]
        u["rows"].append(r)
        u["stock_counter"][r["stock_code"]] += 1
        u["dates"].append(r["published_at"])
    for _, u in units.items():
        u["row_count"] = len(u["rows"])
        # 주 종목 = 행이 가장 많은 종목(동률이면 종목코드 사전순으로 결정적)
        u["primary_stock"] = min(u["stock_counter"].most_common(), key=lambda kv: (-kv[1], kv[0]))[
            0
        ]
        u["stocks"] = set(u["stock_counter"])
    return units


def assign_splits(units: dict[str, dict]) -> dict[str, str]:
    """unit_id → split. 종목별 60/20/20 근사, 멀티종목 unit은 한 번만 배정."""

    stock_units: dict[str, list[str]] = defaultdict(list)
    for uid, u in units.items():
        stock_units[u["primary_stock"]].append(uid)

    assignment: dict[str, str] = {}
    for stock in STOCKS:
        uids = stock_units.get(stock, [])
        local = random.Random(f"{SEED}-{stock}")
        local.shuffle(uids)
        total_rows = sum(units[u]["row_count"] for u in uids)
        target = {s: total_rows * r for s, r in RATIOS.items()}
        acc = {s: 0 for s in RATIOS}
        # 큰 unit 먼저 배치해 경계 넘침 최소화
        uids.sort(key=lambda u: (-units[u]["row_count"],))
        for uid in uids:
            if uid in assignment:  # 멀티종목 unit이 이미 배정됨
                continue
            rc = units[uid]["row_count"]
            # 목표 대비 절대 부족분이 큰 split에 배정. 동률이면 dev>val>test.
            order = {"development": 0, "validation": 1, "test": 2}
            best = max(RATIOS, key=lambda s: (target[s] - acc[s], -order[s]))
            assignment[uid] = best
            acc[best] += rc

    for uid in units:
        assignment.setdefault(uid, "development")
    return assignment


def write_splits(rows: list[dict], units: dict, assignment: dict[str, str]) -> dict:
    SPLITS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    fieldnames = list(rows[0].keys())
    split_rows: dict[str, list[dict]] = {s: [] for s in RATIOS}
    for r in rows:
        split_rows[assignment[r["split_unit_id"]]].append(r)

    for s, rws in split_rows.items():
        with (SPLITS_DIR / f"{s}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rws)

    with (SPLITS_DIR / "split_manifest.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["split_unit_id", "split", "row_count", "primary_stock", "stocks"])
        for uid, u in sorted(units.items()):
            w.writerow(
                [
                    uid,
                    assignment[uid],
                    u["row_count"],
                    u["primary_stock"],
                    "|".join(sorted(u["stocks"])),
                ]
            )
    return split_rows


def verify_and_report(rows, units, assignment, split_rows) -> None:
    lines = ["# 데이터 분할 리포트 (group-aware stock-balanced split)\n"]
    lines.append("> reference set: AI-reviewed reference set (human gold set 아님)\n")
    lines.append(f"> seed={SEED}, 목표 development 60% / validation 20% / test 20%\n")

    def leak(field: str) -> int:
        seen: dict[str, str] = {}
        bad = 0
        for r in rows:
            key = r[field]
            s = assignment[r["split_unit_id"]]
            if key in seen and seen[key] != s:
                bad += 1
            seen.setdefault(key, s)
        return bad

    art_leak, gold_leak, unit_leak = (
        leak("article_id"),
        leak("gold_event_id"),
        leak("split_unit_id"),
    )
    lines.append("\n## 누출 검사 (0이어야 함)\n")
    lines.append(f"- article_id split 중복: **{art_leak}**\n")
    lines.append(f"- gold_event_id split 중복: **{gold_leak}**\n")
    lines.append(f"- split_unit_id split 중복: **{unit_leak}**\n")

    total = len(rows)
    lines.append("\n## split별 행수/비율\n")
    lines.append("| split | 행수 | 비율 | eligible행 |\n|---|---:|---:|---:|\n")
    for s in RATIOS:
        rws = split_rows[s]
        elig = sum(1 for r in rws if r["evaluation_eligible"] == "true")
        lines.append(f"| {s} | {len(rws)} | {len(rws) / total * 100:.1f}% | {elig} |\n")

    lines.append("\n## 종목별 split 행수\n")
    lines.append("| 종목 | development | validation | test |\n|---|---:|---:|---:|\n")
    by = defaultdict(Counter)
    for r in rows:
        by[r["stock_code"]][assignment[r["split_unit_id"]]] += 1
    for st in STOCKS:
        c = by[st]
        lines.append(f"| {st} | {c['development']} | {c['validation']} | {c['test']} |\n")

    lines.append("\n## split별 사건/단독사건/날짜범위\n")
    lines.append("| split | 사건수 | 단독사건 | 날짜 min | 날짜 max |\n|---|---:|---:|---|---|\n")
    for s in RATIOS:
        rws = split_rows[s]
        ev = Counter(r["gold_event_id"] for r in rws)
        singles = sum(1 for _, n in ev.items() if n == 1)
        dates = [r["published_at"] for r in rws]
        lines.append(f"| {s} | {len(ev)} | {singles} | {min(dates)[:10]} | {max(dates)[:10]} |\n")

    (REPORTS_DIR / "split_report.md").write_text("".join(lines), encoding="utf-8")

    print("\n=== 누출 검사 (0이어야 함) ===")
    print(f"  article_id={art_leak}  gold_event_id={gold_leak}  split_unit_id={unit_leak}")
    print("=== split별 행수 ===")
    for s in RATIOS:
        print(f"  {s}: {len(split_rows[s])} ({len(split_rows[s]) / total * 100:.1f}%)")
    print("=== 종목별 split 행수 ===")
    for st in STOCKS:
        c = by[st]
        print(f"  {st}: dev={c['development']} val={c['validation']} test={c['test']}")
    assert art_leak == 0 and gold_leak == 0 and unit_leak == 0, "누출 발생!"
    print("리포트: reports/split_report.md")


def main() -> int:
    rows = load_rows()
    units = build_units(rows)
    assignment = assign_splits(units)
    split_rows = write_splits(rows, units, assignment)
    verify_and_report(rows, units, assignment, split_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

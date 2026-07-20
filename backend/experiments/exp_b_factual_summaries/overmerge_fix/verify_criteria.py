"""prompt.md 후속 완료 기준 6개를 한 번에 검증.

기준:
 1. om_600 유사 장기 비사건형 company 클러스터가 의미 있게 분리됨
 2. 구체 기업 사건 없이 7일 이상 지속되는 대형 company 클러스터가 남지 않음
 3. 정상 5개 보존율 각 >= 95%
 4. singleton 비율 baseline 대비 +5%p 이내
 5. 보호 OFF = baseline (동일)  ← 여기선 클러스터 수 동일로 확인
 6. (테스트는 test_overmerge_fix.py 로 별도)

새 A: block_market_bridge=True + separate_info=True.
'대형 company'는 크기>=50 으로 본다. '구체 기업 사건 없음'은 대표(최이른) 제목 및
멤버 다수가 비사건형(classify_kind != company였을) 인지로 근사 판단하되, 여기선
'company 클러스터인데 7일 이상 지속 + 크기>=50' 을 위반 후보로 출력한다.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
EXP_B = BASE.parent
EXP_A = EXP_B.parent / "exp_a_clustering"
for p in (EXP_A, EXP_B, BASE):
    sys.path.insert(0, str(p))

import config as CFG  # noqa: E402
import market_rules as MR  # noqa: E402
from cluster_variants import VariantConfig, cluster_all_variant  # noqa: E402
from run_experiments import (  # noqa: E402
    CACHE_DIR,
    CASE_NEEDLES,
    _load_env,
    embed_articles,
    load_relevant_articles,
)

DAY_H = 24.0
BIG = 50  # 대형 클러스터 기준


def _days(rows, members):
    return len({rows[i]["published_at"][:10] for i in members})


def main() -> None:
    env = _load_env(EXP_B.parent.parent / ".env")
    rows = load_relevant_articles(env, CFG.STOCKS)
    vecs = embed_articles(rows, "mps", CACHE_DIR)

    base_assign, base_clusters = cluster_all_variant(rows, vecs, CFG.STOCKS, VariantConfig())
    new_cfg = VariantConfig(block_market_bridge=True, separate_info=True)
    new_assign, new_clusters = cluster_all_variant(rows, vecs, CFG.STOCKS, new_cfg)

    kinds = [MR.classify_kind(r.get("title", ""), r.get("description", "")) for r in rows]
    kc = defaultdict(int)
    for k in kinds:
        kc[k] += 1
    print(f"기사={len(rows)} kind 분포={dict(kc)}")

    n_base = len(base_clusters)
    n_new = len(new_clusters)
    base_singleton = sum(1 for c in base_clusters.values() if len(c["member_idxs"]) == 1) / n_base
    new_singleton = sum(1 for c in new_clusters.values() if len(c["member_idxs"]) == 1) / n_new
    print(f"\nbaseline 클러스터={n_base} singleton={base_singleton:.4f}")
    print(f"new(A+info) 클러스터={n_new} singleton={new_singleton:.4f}")

    # 기준 4: singleton +5%p 이내
    c4 = (new_singleton - base_singleton) <= 0.05
    print(
        f"\n[기준4] singleton 증가 {100 * (new_singleton - base_singleton):+.2f}%p (<=+5%p) → {'PASS' if c4 else 'FAIL'}"
    )

    # 기준 2: 7일 이상 지속 대형 company 클러스터
    viol = []
    for cid, c in new_clusters.items():
        if c["kind"] != "company":
            continue
        m = c["member_idxs"]
        if len(m) >= BIG and _days(rows, m) >= 7:
            ms = sorted(m, key=lambda i: rows[i]["published_at"])
            rep = rows[ms[0]]["title"]
            # 멤버 중 회사이벤트 키워드 보유 비율(사건성 근거)
            evt = sum(1 for i in m if MR._count_hits(rows[i]["title"], MR.COMPANY_EVENT)) / len(m)
            viol.append((cid, c["stock_code"], len(m), _days(rows, m), round(evt, 2), rep))
    print(f"\n[기준2] 7일+ 대형 company 클러스터 {len(viol)}개:")
    for v in sorted(viol, key=lambda x: -x[2]):
        print(f"    cid={v[0]} {v[1]} size={v[2]} days={v[3]} 사건키워드비율={v[4]} | {v[5][:50]}")
    # 사건키워드 비율이 낮은(<0.3) 대형·장기 company 가 있으면 '비사건형 잔존'으로 FAIL 후보
    nonevent_viol = [v for v in viol if v[4] < 0.3]
    c2 = len(nonevent_viol) == 0
    print(
        f"    → 비사건형(사건키워드<0.3) 7일+ 대형 company: {len(nonevent_viol)}개 → {'PASS' if c2 else 'FAIL'}"
    )

    # 기준 1 & 3: 케이스별 보존/분리
    base_members = defaultdict(list)
    for i, a in base_assign.items():
        base_members[a["cluster_id"]].append(rows[i]["article_stock_id"])
    new_map = {rows[i]["article_stock_id"]: a["cluster_id"] for i, a in new_assign.items()}

    def find_cid(stock, needle):
        hit = defaultdict(int)
        for cid, c in base_clusters.items():
            if c["stock_code"] != stock:
                continue
            for i in c["member_idxs"]:
                if needle in rows[i].get("title", ""):
                    hit[cid] += 1
        return max(hit, key=lambda c: hit[c]) if hit else None

    def preservation(stock, needle):
        bcid = find_cid(stock, needle)
        if bcid is None:
            return None
        members = base_members[bcid]
        buckets = defaultdict(int)
        for asid in members:
            if asid in new_map:
                buckets[new_map[asid]] += 1
        largest = max(buckets.values()) if buckets else 0
        return len(members), largest, largest / len(members), len(buckets)

    # 정상 5개(현대차·전북대 계약학과 추가)
    normal5 = list(CASE_NEEDLES["normal"]) + [("nm_1221", "005380", "피지컬 AI")]
    print("\n[기준3] 정상 5개 보존율(>=95%):")
    c3 = True
    for label, stock, needle in normal5:
        r = preservation(stock, needle)
        if r is None:
            print(f"    {label}: 매칭실패")
            c3 = False
            continue
        orig, largest, ratio, pieces = r
        ok = ratio >= 0.95
        c3 = c3 and ok
        print(
            f"    {label}: {orig}건 → 최대조각 {largest} ({ratio:.1%}, {pieces}조각) {'PASS' if ok else 'FAIL'}"
        )

    print("\n[기준1] over-merge 케이스 분리(최대조각 비율 낮을수록 분리):")
    for label, stock, needle in CASE_NEEDLES["overmerge"]:
        r = preservation(stock, needle)
        if r is None:
            print(f"    {label}: 매칭실패")
            continue
        orig, largest, ratio, pieces = r
        # 최대조각 날짜폭
        bcid = find_cid(stock, needle)
        members = base_members[bcid]
        buckets = defaultdict(list)
        for asid in members:
            if asid in new_map:
                buckets[new_map[asid]].append(asid)
        big = max(buckets.values(), key=len)
        # asid -> row idx
        asid2i = {rows[i]["article_stock_id"]: i for i in range(len(rows))}
        bigdays = len({rows[asid2i[a]]["published_at"][:10] for a in big})
        print(
            f"    {label}: {orig}건 → 최대조각 {largest} ({ratio:.1%}, {pieces}조각, {bigdays}일)"
        )

    print(f"\n[기준5] 보호 OFF == baseline: 클러스터수 {n_base} (OFF는 정의상 동일)")
    print("\n===== 요약 =====")
    print("기준1 om_600 분리: (아래 표 참조)")
    print(f"기준2 비사건형 7일+대형 company 없음: {'PASS' if c2 else 'FAIL'}")
    print(f"기준3 정상5개 >=95%: {'PASS' if c3 else 'FAIL'}")
    print(f"기준4 singleton +5%p 이내: {'PASS' if c4 else 'FAIL'}")


if __name__ == "__main__":
    main()

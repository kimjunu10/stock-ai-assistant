"""실제 Solar Pro3 로 동일사건 판정 소규모 검증.

로컬 검증 케이스(실제 기사 제목 기반)로 Solar 가 다음을 맞히는지 확인:
 - 동일 발표 후속 → existing
 - 군함 수주 vs 방산 협력 → new(분리)
 - 주체·행동·대상 다름 → new
그리고 호출 수·토큰 사용량을 실측한다. Supabase/스케줄러 미연결.

usage: python verify_solar_assign.py   (backend/.env 의 UPSTAGE_API_KEY 사용)
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
EXP_B = BASE.parent
BACKEND = EXP_B.parent.parent
sys.path.insert(0, str(BACKEND))

from experiments.exp_b_factual_summaries import assign_llm as A  # noqa: E402


def _load_env(p: Path) -> dict:
    env = {}
    with p.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                env[k] = v.strip().strip('"').strip("'")
    return env


# 후보(대표 기사) — 두 개의 서로 다른 사건
CANDIDATES = [
    {
        "cluster_id": 101,
        "title": "한화오션, 미국 군함 설계·정보 요청 대응…'군함 10척' 수주 기대",
        "description": "미국이 한국 조선사에 전투함·급유함 설계 정보를 첫 요청했다.",
    },
    {
        "cluster_id": 202,
        "title": "한화오션, 신안우이 해상풍력 착공…390MW 발전단지 조성",
        "description": "국민성장펀드 1호 투자 사업으로 2029년 상업운전 목표.",
    },
]

# 새 기사 케이스: (설명, 새기사, 기대 decision, 기대 matched)
CASES = [
    (
        "동일 발표 후속(군함 수주)",
        {
            "title": "한화 필리조선소, 美 미사일시험 계측선 수주…'골든돔' 참여",
            "description": "미국 군함 관련 한화오션 미사일시험선 첫 수주.",
        },
        "existing",
        101,
    ),
    (
        "주체·대상 다름(해상풍력과 무관한 실적)",
        {
            "title": "한화오션, 2분기 영업이익 시장 기대 상회 예상",
            "description": "고부가 선박 효과로 실적 개선 전망.",
        },
        "new",
        None,
    ),
    (
        "주제만 비슷(다른 회사 방산 협력)",
        {
            "title": "HD현대, 미국과 방산 조선 협력 협약 체결",
            "description": "HD현대가 별도로 미국과 방산 협력에 나섰다.",
        },
        "new",
        None,
    ),
    (
        "동일 사건(해상풍력 착공 후속)",
        {
            "title": "신안우이 해상풍력 착공식 개최…390MW 규모 본격화",
            "description": "한화오션 주도 신안우이 해상풍력 착공.",
        },
        "existing",
        202,
    ),
]


def main() -> None:
    env = _load_env(BACKEND / ".env")
    api_key = env.get("UPSTAGE_API_KEY", "")
    if not api_key:
        print("UPSTAGE_API_KEY 없음 — 중단")
        sys.exit(2)

    total_prompt = total_completion = calls = 0
    correct = 0
    print(f"후보: {[c['cluster_id'] for c in CANDIDATES]}\n")
    for desc, art, exp_dec, exp_mid in CASES:
        prompt = A.build_user_prompt(art, CANDIDATES)
        parsed, meta = A.call_solar_assign(api_key, prompt)
        calls += 1
        if meta.get("usage"):
            total_prompt += meta["usage"].get("prompt_tokens", 0)
            total_completion += meta["usage"].get("completion_tokens", 0)
        dec = parsed.get("decision")
        mid = parsed.get("matched_cluster_id")
        ok_parse = meta.get("parse_success")
        # 판정 일치: decision 일치 + existing 이면 matched 도 일치
        hit = ok_parse and dec == exp_dec and (exp_dec == "new" or int(mid) == exp_mid)
        correct += bool(hit)
        mark = "✓" if hit else "✗"
        print(f"[{mark}] {desc}")
        print(
            f"    기대={exp_dec}/{exp_mid}  실제={dec}/{mid}  (parse={ok_parse}, {meta.get('latency_ms')}ms)"
        )

    print(f"\n판정 정확: {correct}/{len(CASES)}")
    print(f"총 호출: {calls}회 (기사당 1회)")
    print(
        f"토큰 실측: prompt={total_prompt} completion={total_completion} "
        f"(평균 prompt={total_prompt // max(calls, 1)}/호출)"
    )
    # 운영 추정: company 기사 중 후보 있는 비율만 호출. 예시로 6018 company 가정.
    avg_p = total_prompt / max(calls, 1)
    avg_c = total_completion / max(calls, 1)
    print("\n[추정] company 기사당 후보가 있으면 1회 호출. 후보 있는 기사 N건이면")
    print(f"       prompt≈{avg_p:.0f}·N, completion≈{avg_c:.0f}·N 토큰.")


if __name__ == "__main__":
    main()

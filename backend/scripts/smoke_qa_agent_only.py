"""Phase 5.5-G QA smoke — legacy 제거 후 단일 Agent 경로 검증(운영 동일 조건).

AGENT_ENABLED=true + 실제 DB + OpenAI 자격증명으로 FastAPI TestClient 를 태워
/api/qa · /api/qa/stream 을 실제로 호출한다. 운영 배포(금지) 대신 운영과 동일한
설정으로 로컬에서 검증한다.

검증 항목(지시 §8):
  1 금융용어  2 재무숫자  3 뉴스제외조건  4 증권사리포트  5 복합질문
  6 no_data  7 타 종목 혼입  8 SSE 이벤트 순서

실행:
  AGENT_ENABLED=true python scripts/smoke_qa_agent_only.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

# Agent 경로를 강제(운영 동일). 자격증명은 환경(.env)에서 로드된다.
os.environ.setdefault("AGENT_ENABLED", "true")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _post(question: str, stock_code: str | None = None) -> dict:
    body: dict = {"question": question}
    if stock_code:
        body["stock_code"] = stock_code
    r = client.post("/api/qa", json=body)
    return {"status": r.status_code, "json": (r.json() if r.status_code == 200 else r.text)}


def _summary(res: dict) -> str:
    if res["status"] != 200:
        return f"HTTP {res['status']}: {str(res['json'])[:120]}"
    j = res["json"]
    ex = j.get("execution") or {}
    ops = j.get("broker_opinions") or []
    tools = [t.get("name") for t in ex.get("tool_calls", [])]
    ans = (j.get("answer") or "").replace("\n", " ")
    return (
        f"agent={ex.get('agent')} stop={ex.get('stop_reason')} tools={tools} "
        f"broker_opinions={len(ops)}\n    answer: {ans[:160]}"
    )


def main() -> int:
    fails: list[str] = []
    print("=" * 70)
    print("Phase 5.5-G QA smoke (단일 Agent 경로, legacy 제거 후)")
    print("=" * 70)

    cases = [
        ("1 금융용어", "PER이 무슨 뜻이야?", None),
        ("2 재무숫자", "삼성전자 2025년 영업이익 얼마야?", "005930"),
        ("3 뉴스제외조건", "삼성전자 관련 뉴스 알려줘. 단 실적 관련은 빼줘", "005930"),
        ("4 증권사리포트", "삼성전자 최근 증권사 목표주가 알려줘", "005930"),
        ("5 복합질문", "삼성전자 실적이랑 증권사 목표주가 같이 알려줘", "005930"),
        ("6 no_data", "네이버 최근 증권사 목표주가 알려줘", "035420"),
        ("7 타종목혼입", "SK하이닉스 최근 증권사 목표주가 알려줘", "000660"),
    ]

    results: dict[str, dict] = {}
    for label, q, sc in cases:
        print(f"\n◆ {label}: {q}")
        res = _post(q, sc)
        results[label] = res
        print("   ", _summary(res))
        # 공통: 200 이어야 하고 agent=True 여야 한다(legacy 로 안 빠졌는지)
        if res["status"] != 200:
            fails.append(f"{label}: HTTP {res['status']}")
            continue
        ex = res["json"].get("execution") or {}
        if not ex.get("agent"):
            fails.append(f"{label}: agent 경로 아님(execution.agent={ex.get('agent')})")

    # §7 타 종목 혼입 0건: SK하이닉스 답변에 삼성전자 목표가(48만~58만원대) 없어야
    r7 = results.get("7 타종목혼입", {})
    if r7.get("status") == 200:
        ops7 = r7["json"].get("broker_opinions") or []
        # SK하이닉스 목표가는 수백만원대. 삼성 값(48만~58만)이 섞이면 실패.
        bad = [o for o in ops7 if o.get("target_price") and o["target_price"] < 1_000_000]
        if bad:
            fails.append(f"§7 타 종목 혼입 의심: {[(o['broker'], o['target_price']) for o in bad]}")

    # §8 SSE 이벤트 순서
    print("\n◆ 8 SSE 이벤트 순서: /api/qa/stream")
    with client.stream(
        "POST",
        "/api/qa/stream",
        json={"question": "삼성전자 최근 목표주가", "stock_code": "005930"},
    ) as resp:
        text = "".join(chunk for chunk in resp.iter_text())
    order = ["agent_start", "tool_start", "tool_end", "sources", "delta", "done"]
    present = [ev for ev in order if f"event: {ev}" in text]
    idxs = [text.index(f"event: {ev}") for ev in present]
    print(f"    등장 이벤트: {present}")
    if idxs != sorted(idxs):
        fails.append(f"§8 SSE 순서 위반: {present}")
    for must in ("agent_start", "delta", "done"):
        if must not in present:
            fails.append(f"§8 필수 이벤트 누락: {must}")

    print("\n" + "=" * 70)
    if fails:
        print("❌ 실패:")
        for f in fails:
            print("  -", f)
        return 1
    print("✅ 전체 통과: 단일 Agent 경로 / 타 종목 혼입 0 / SSE 순서 정상")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

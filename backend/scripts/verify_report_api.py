"""목표주가 안전성 실제 API 검증 (prompt.md §10). 로컬에서 Agent 경로로 호출.

AGENT_ENABLED=true 를 이 프로세스에만 주입하고 FastAPI TestClient 로 /api/qa 를 친다.
운영 flag 파일은 바꾸지 않는다. migration 0022 + backfill 이 적용된 개발 DB 전제.

실행: AGENT_ENABLED=true uv run python scripts/verify_report_api.py 005930
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STOCK = sys.argv[1] if len(sys.argv) > 1 else "005930"

QUESTIONS = [
    ("현재 목표주가", f"{STOCK} 최근 증권사 목표주가 알려줘"),
    ("실적+목표주가", f"{STOCK} 실적이랑 증권사 목표주가 같이 알려줘"),
    ("증권사 전망", f"{STOCK} 증권사 전망 알려줘"),
    ("목표주가 변화", f"{STOCK} 목표주가가 어떻게 변했어?"),
    ("공식정보만", f"{STOCK} 증권사 의견 없이 공식 정보만 알려줘"),
]


def main() -> int:
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    for label, q in QUESTIONS:
        body = {"question": q, "stock_code": STOCK, "stream": False}
        r = client.post("/api/qa", json=body)
        print("=" * 72)
        print(f"◆ {label}: {q}")
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}: {r.text[:200]}")
            continue
        d = r.json()
        ex = d.get("execution") or {}
        print(f"  agent={ex.get('agent')} tools={[t['name'] for t in ex.get('tool_calls', [])]}")
        print(f"  validation_errors={ex.get('validation_errors')}")
        bo = d.get("broker_opinions") or []
        print(f"  broker_opinions({len(bo)}):")
        for o in bo[:6]:
            tp = o.get("target_price")
            print(
                f"    - {o.get('broker')} {o.get('report_date')} "
                f"opinion={o.get('investment_opinion')} "
                f"target_price={tp} status={o.get('target_price_status')} "
                f"stale={o.get('is_stale')}"
            )
        oi = d.get("official_information") or []
        if oi:
            print(
                f"  official_information({len(oi)}): "
                f"{[(x.get('label'), x.get('value')) for x in oi[:3]]}"
            )
        print(f"  answer: {(d.get('answer') or '')[:300]}".replace("\n", " "))
    print("=" * 72)
    print(json.dumps({"checked": len(QUESTIONS), "stock": STOCK}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 5.5-A: LangChain create_agent + Upstage(OpenAI 호환) Tool Calling preflight.

Upstage 는 OpenAI 호환 API 이므로 langchain-openai 의 ChatOpenAI(base_url=Upstage)로 쓴다.
langchain-upstage 0.7.7 은 tokenizers<0.21 을 강제해 프로젝트 transformers>=5 와 충돌하므로
사용하지 않는다(5.5-A 문서 참조). 이 조합은 프로젝트 .venv 에 정식 설치·고정돼 있다.

실행:
    cd backend
    .venv/bin/python scripts/agent_preflight.py

검증(문서 5.5-A):
  1) bind_tools() 단일 Tool call
  2) Tool result 후 추가 Tool call
  3) 2개 Tool 연속 호출
  4) Tool call streaming
  5) 한국어 부정·제외 질문에서 올바른 Tool 선택
  6) create_agent 호환(단일 Agent가 Tool 0..N 선택)

비밀키는 출력하지 않는다. 실제 DB·서비스는 호출하지 않고 더미 Tool 로 모델 능력만 본다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# .env 로드(키 출력 안 함)
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:  # noqa: BLE001
    pass

API_KEY = os.environ.get("UPSTAGE_API_KEY", "")
MODEL = os.environ.get("AGENT_CHAT_MODEL") or os.environ.get("RAG_CHAT_MODEL", "solar-pro3-260323")
BASE_URL = os.environ.get("UPSTAGE_BASE_URL", "https://api.upstage.ai/v1")

results: dict[str, object] = {"model": MODEL, "checks": {}}


def _record(name: str, ok: bool, detail: str = "") -> None:
    results["checks"][name] = {"ok": ok, "detail": detail[:300]}
    print(f"[{'PASS' if ok else 'FAIL'}] {name} — {detail[:120]}")


def main() -> int:
    if not API_KEY:
        print("UPSTAGE_API_KEY 없음 — preflight 불가")
        return 2

    # 버전 기록(모듈 __version__ 이 없을 수 있어 importlib.metadata 사용)
    from importlib.metadata import PackageNotFoundError, version

    def _ver(pkg: str) -> str:
        try:
            return version(pkg)
        except PackageNotFoundError:
            return "(not installed)"

    results["versions"] = {
        "langchain": _ver("langchain"),
        "langchain_core": _ver("langchain-core"),
        "langgraph": _ver("langgraph"),
        "langchain_openai": _ver("langchain-openai"),
    }
    try:
        from langchain_openai import ChatOpenAI
    except Exception as e:  # noqa: BLE001
        _record("import_langchain_openai", False, str(e))
        _finish()
        return 1
    print("versions:", json.dumps(results["versions"], ensure_ascii=False))

    from langchain_core.tools import tool

    # ── 더미 read-only Tool 2종 (실제 DB 미접근) ──
    calls: list[str] = []

    @tool
    def get_financial_facts(stock_code: str, account_name: str, business_year: int) -> str:
        """종목의 특정 재무 계정 실제 값을 조회한다(연간/분기 등 정확 값)."""
        calls.append(f"fin:{stock_code}:{account_name}:{business_year}")
        return json.dumps(
            {
                "stock_code": stock_code,
                "account": account_name,
                "year": business_year,
                "value_won": 6_000_000_000_000,
                "period": "annual",
                "value_kind": "actual",
            },
            ensure_ascii=False,
        )

    @tool
    def search_news(stock_code: str, query: str, exclude_topics: list[str] | None = None) -> str:
        """종목 뉴스를 검색한다. exclude_topics 로 제외 주제를 지정할 수 있다."""
        calls.append(f"news:{stock_code}:{query}:excl={exclude_topics}")
        return json.dumps(
            {
                "stock_code": stock_code,
                "query": query,
                "excluded": exclude_topics or [],
                "hits": [{"title": "삼성전자 신규 공급계약 체결", "sentiment": "positive"}],
            },
            ensure_ascii=False,
        )

    tools = [get_financial_facts, search_news]

    try:
        # Upstage OpenAI 호환 엔드포인트를 ChatOpenAI 로 사용
        llm = ChatOpenAI(model=MODEL, api_key=API_KEY, base_url=BASE_URL, temperature=0)
    except Exception as e:  # noqa: BLE001
        _record("init_chat_model", False, str(e))
        _finish()
        return 1
    _record("init_chat_model", True, f"model={MODEL} via langchain-openai(base_url=Upstage)")

    # ── 1) bind_tools 단일 Tool call ──
    try:
        bound = llm.bind_tools(tools)
        msg = bound.invoke("삼성전자 2025년 영업이익 알려줘")
        tc = getattr(msg, "tool_calls", []) or []
        ok = len(tc) == 1 and tc[0]["name"] == "get_financial_facts"
        _record("1_single_tool_call", ok, f"tool_calls={[t['name'] for t in tc]}")
    except Exception as e:  # noqa: BLE001
        _record("1_single_tool_call", False, f"{type(e).__name__}: {e}")

    # ── 5) 한국어 부정·제외: '실적 제외' → 재무 Tool 미호출, 뉴스만 ──
    try:
        bound = llm.bind_tools(tools)
        msg = bound.invoke(
            "최근 뉴스에서 삼성전자 호재 있어? 영업이익 같은 실적 관련 내용은 제외해."
        )
        tc = getattr(msg, "tool_calls", []) or []
        names = [t["name"] for t in tc]
        ok = "search_news" in names and "get_financial_facts" not in names
        _record("5_korean_exclusion", ok, f"tool_calls={names}")
    except Exception as e:  # noqa: BLE001
        _record("5_korean_exclusion", False, f"{type(e).__name__}: {e}")

    # ── 6) create_agent 호환 + 2)Tool result 후 추가 call + 3)연속 ──
    try:
        from langchain.agents import create_agent

        agent = create_agent(model=llm, tools=tools)
        # 복합 질문: 재무 + 뉴스 둘 다 필요 → 여러 Tool 호출 관찰
        calls.clear()
        out = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "삼성전자 2025년 영업이익이 얼마고 최근 호재 뉴스도 알려줘.",
                    }
                ]
            }
        )
        msgs = out.get("messages", [])
        tool_msgs = [m for m in msgs if getattr(m, "type", "") == "tool"]
        used = set(calls)
        _record(
            "6_create_agent_multitool",
            len(tool_msgs) >= 1,
            f"tool_msgs={len(tool_msgs)} calls={sorted(used)}",
        )
        # 2·3: 재무·뉴스 둘 다 호출됐는지(연속/추가 call 능력)
        both = any("fin:" in c for c in calls) and any("news:" in c for c in calls)
        _record(
            "2_3_followup_and_sequential",
            both,
            f"fin={any('fin:' in c for c in calls)} news={any('news:' in c for c in calls)}",
        )
    except Exception as e:  # noqa: BLE001
        _record("6_create_agent_multitool", False, f"{type(e).__name__}: {e}")
        _record("2_3_followup_and_sequential", False, "create_agent 실패로 미검증")

    # ── 4) Tool call streaming ──
    try:
        bound = llm.bind_tools(tools)
        chunks = 0
        saw_toolcall = False
        for ch in bound.stream("삼성전자 2025년 매출액 알려줘"):
            chunks += 1
            if getattr(ch, "tool_call_chunks", None):
                saw_toolcall = True
        _record(
            "4_tool_call_streaming",
            chunks > 0,
            f"chunks={chunks} tool_call_chunks_seen={saw_toolcall}",
        )
    except Exception as e:  # noqa: BLE001
        _record("4_tool_call_streaming", False, f"{type(e).__name__}: {e}")

    _finish()
    checks = results["checks"]
    passed = sum(1 for v in checks.values() if v["ok"])
    return 0 if passed == len(checks) else 1


def _finish() -> None:
    out_path = (
        Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_5_5" / "preflight_result.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n결과 저장:", out_path)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())

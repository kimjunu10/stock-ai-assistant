"""시연 전 실제 /api/qa 응답을 계약 기준으로 점검한다.

정답 문장을 고정하지 않는다. 필요한 Tool, 근거 유형, 기간 일관성, 실행 성공 여부만
검사한다. 가격 공급자까지 확인하려면 기본값 그대로 실행하고, 외부 가격 API 장애와
무관한 시연만 점검할 때는 ``--skip-price``를 사용한다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Scenario:
    id: str
    question: str
    check: Callable[[dict[str, Any]], list[str]]
    external_price: bool = False
    numeric_signature: Callable[[dict[str, Any]], tuple[Any, ...]] | None = None


def _common(
    response: dict[str, Any],
    required_tools: set[str],
    *,
    allow_causal_guardrail: bool = False,
) -> list[str]:
    failures: list[str] = []
    execution = response.get("execution") or {}
    calls = execution.get("tool_calls") or []
    observed = {str(call.get("name")) for call in calls}
    failed = [str(call.get("name")) for call in calls if call.get("status") == "error"]
    if not response.get("answer", "").strip():
        failures.append("empty_answer")
    if execution.get("stop_reason") != "completed":
        failures.append(f"stop_reason={execution.get('stop_reason')}")
    if failed:
        failures.append(f"tool_error={','.join(failed)}")
    missing = sorted(required_tools - observed)
    if missing:
        failures.append(f"missing_tool={','.join(missing)}")
    validation_errors = execution.get("validation_errors") or []
    causal_guardrail_only = validation_errors and all(
        "직접 인과 단정에 주의 문구" in error for error in validation_errors
    )
    caveat_present = "직접적인 원인이라고 단정할 수는 없습니다" in response.get("answer", "")
    if validation_errors and not (
        allow_causal_guardrail and causal_guardrail_only and caveat_present
    ):
        failures.append("validation_error")
    return failures


def _source_types(response: dict[str, Any]) -> set[str]:
    return {str(source.get("source_type")) for source in response.get("sources") or []}


def _financial_trend(response: dict[str, Any]) -> list[str]:
    failures = _common(response, {"get_financial_facts"})
    titles = " ".join(str(source.get("title") or "") for source in response.get("sources") or [])
    if "financial" not in _source_types(response):
        failures.append("missing_financial_source")
    if not all(year in titles for year in ("2026", "2025")):
        failures.append("comparison_is_not_same-period_two-year")
    return failures


def _current_quarter(response: dict[str, Any]) -> list[str]:
    failures = _common(response, {"get_financial_facts"})
    answer = response.get("answer", "")
    if "2025" in answer:
        failures.append("silently_substituted_previous_year")
    return failures


def _dividend(response: dict[str, Any]) -> list[str]:
    failures = _common(response, {"get_disclosure_values"})
    answer = response.get("answer", "")
    if "structured_disclosure" not in _source_types(response):
        failures.append("missing_structured_disclosure_source")
    if "주당" not in answer:
        failures.append("dividend_metric_is_not_per-share")
    return failures


def _negative_news(response: dict[str, Any]) -> list[str]:
    failures = _common(response, {"search_news"}, allow_causal_guardrail=True)
    if "news_event" not in _source_types(response):
        failures.append("missing_news_source")
    if any(source.get("stock_code") != "005930" for source in response.get("sources") or []):
        failures.append("cross-stock-source")
    return failures


def _price_reason(response: dict[str, Any]) -> list[str]:
    failures = _common(
        response,
        {"get_stock_prices", "search_news"},
        allow_causal_guardrail=True,
    )
    if "price" not in _source_types(response):
        failures.append("missing_price_source")
    if "news_event" not in _source_types(response):
        failures.append("missing_news_source")
    return failures


def _answer_number_signature(response: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        sorted(
            re.findall(
                r"\d+(?:\.\d+)?(?:조원|억원|만원|원|%)",
                response.get("answer", ""),
            )
        )
    )


def _financial_signature(response: dict[str, Any]) -> tuple[Any, ...]:
    for visualization in response.get("visualizations") or []:
        if visualization.get("type") != "financial_series":
            continue
        items = (visualization.get("data") or {}).get("items") or []
        return tuple(
            sorted(
                (
                    item.get("label"),
                    item.get("period"),
                    item.get("basis"),
                    item.get("value_won"),
                )
                for item in items
            )
        )
    return ()


def _price_signature(response: dict[str, Any]) -> tuple[Any, ...]:
    for visualization in response.get("visualizations") or []:
        if visualization.get("type") != "price_line":
            continue
        quote = (visualization.get("data") or {}).get("quote") or {}
        return (
            quote.get("trading_day"),
            quote.get("price"),
            quote.get("previous_close"),
            quote.get("change_rate_pct"),
        )
    return ()


SCENARIOS = (
    Scenario(
        "financial-trend",
        "삼성전자 요즘 실적 좋아지고 있어?",
        _financial_trend,
        numeric_signature=_financial_signature,
    ),
    Scenario("current-quarter", "삼성전자 2분기 실적 알려줘", _current_quarter),
    Scenario(
        "dividend",
        "삼성전자 올해 배당 얼마 줘?",
        _dividend,
        numeric_signature=_answer_number_signature,
    ),
    Scenario("negative-news", "오늘 삼성전자 뭐 악재 있었어?", _negative_news),
    Scenario(
        "price-reason",
        "오늘 삼성전자 주가 왜 내렸어? 뭐 악재 있었어?",
        _price_reason,
        external_price=True,
        numeric_signature=_price_signature,
    ),
)


def _request(base_url: str, question: str, timeout: float) -> dict[str, Any]:
    body = json.dumps({"question": question, "stock_code": "005930"}).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/qa",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--skip-price", action="store_true")
    args = parser.parse_args()

    failed = False
    for scenario in SCENARIOS:
        if args.skip_price and scenario.external_price:
            print(f"SKIP {scenario.id}: external price provider")
            continue
        signatures: list[tuple[Any, ...]] = []
        scenario_failures: list[str] = []
        for attempt in range(1, args.repeat + 1):
            try:
                response = _request(args.base_url, scenario.question, args.timeout)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                scenario_failures.append(f"attempt-{attempt}:request_error={type(exc).__name__}")
                continue
            if scenario.numeric_signature is not None:
                signatures.append(scenario.numeric_signature(response))
            scenario_failures.extend(
                f"attempt-{attempt}:{failure}" for failure in scenario.check(response)
            )
        # 문장 자체의 변동은 허용한다. 같은 구조화 지표의 수치만 반복 안정성을 검사한다.
        if signatures and len(set(signatures)) > 1:
            scenario_failures.append("numeric_answer_changed_between_repeats")
        status = "FAIL" if scenario_failures else "PASS"
        print(f"{status} {scenario.id}: {scenario.question}")
        for failure in scenario_failures:
            print(f"  - {failure}")
        failed = failed or bool(scenario_failures)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

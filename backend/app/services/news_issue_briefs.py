"""Create one compact positive/negative issue brief for each supported stock.

The scheduler sends all changed stocks in one Solar request. Each stock's source
hash is persisted so an unchanged 30-minute cycle does not spend another call.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

import requests

from experiments.exp_b_factual_summaries import config as CFG

ISSUE_BRIEF_PROMPT_VERSION = "stock_issue_brief_v1"
ISSUE_BRIEF_MAX_ITEMS = 3
ISSUE_BRIEF_MAX_CANDIDATES_PER_DIRECTION = 12
ISSUE_BRIEF_SENTIMENT_THRESHOLD = 0.65

SYSTEM_PROMPT = (
    "너는 초보 투자자에게 오늘의 기업 이슈를 짧게 정리하는 금융 뉴스 편집자다. "
    "입력은 종목별 호재·악재 뉴스의 쉬운 설명 첫 문장이다.\n"
    "반드시 지킬 규칙:\n"
    "1. 같은 내용은 하나로 합치고, 각 방향에서 중요한 순서로 최대 3개만 남긴다.\n"
    "2. 각 문구는 38자 이내의 짧고 구체적인 한국어 한 문장으로 쓴다.\n"
    "3. 회사명을 매 문장마다 반복하지 않는다. "
    "'긍정 요인', '부정 요인', '호재', '악재'도 문구에 쓰지 않는다.\n"
    "4. 입력에 없는 사실, 해석, 주가 전망, 투자 추천을 만들지 않는다.\n"
    "5. 각 문구를 뒷받침하는 입력의 cluster_id를 cluster_ids에 넣는다.\n"
    "6. 입력이 없는 방향은 빈 배열로 둔다.\n"
    '출력은 반드시 {"stocks":{"종목코드":{"positive":[{"text":"...",'
    '"cluster_ids":[1]}],"negative":[...]}}} 형태의 JSON 하나만 출력한다.'
)


def _first_sentence(value: str) -> str:
    cleaned = " ".join((value or "").replace("**", "").split()).strip()
    for prefix in ("쉽게 말해,", "쉽게 말하면,", "이 기사는 "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    for marker in (". ", "! ", "? "):
        if marker in cleaned:
            return cleaned.split(marker, 1)[0].strip() + marker[0]
    return cleaned


def prepare_issue_brief_inputs(
    rows: list[dict[str, Any]],
    stock_names: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Normalize, rank and hash today's directional cluster summaries."""

    grouped: dict[str, dict[str, Any]] = {
        code: {"stock_name": name, "positive": [], "negative": []}
        for code, name in stock_names.items()
    }
    ranked = sorted(
        rows,
        key=lambda row: (
            int(row.get("article_count") or 0),
            float(row.get("sentiment_score") or 0),
            str(row.get("last_active_at") or ""),
        ),
        reverse=True,
    )
    for row in ranked:
        sentiment = row.get("sentiment_label")
        score = float(row.get("sentiment_score") or 0)
        stock_code = str(row.get("stock_code") or "")
        if (
            stock_code not in grouped
            or sentiment not in {"positive", "negative"}
            or score < ISSUE_BRIEF_SENTIMENT_THRESHOLD
        ):
            continue
        text = _first_sentence(str(row.get("easy_explanation") or ""))
        if not text:
            continue
        items = grouped[stock_code][sentiment]
        if len(items) >= ISSUE_BRIEF_MAX_CANDIDATES_PER_DIRECTION:
            continue
        items.append(
            {
                "cluster_id": int(row["id"]),
                "article_count": int(row.get("article_count") or 0),
                "text": text,
            }
        )

    for stock_code, value in grouped.items():
        source = {
            "stock_code": stock_code,
            "positive": value["positive"],
            "negative": value["negative"],
        }
        encoded = json.dumps(source, ensure_ascii=False, sort_keys=True).encode()
        value["source_hash"] = hashlib.sha256(encoded).hexdigest()
    return grouped


def build_issue_brief_prompt(inputs: dict[str, dict[str, Any]]) -> str:
    stocks = {}
    for stock_code, value in inputs.items():
        stocks[stock_code] = {
            "stock_name": value["stock_name"],
            "positive": value["positive"],
            "negative": value["negative"],
        }
    return "다음 종목들의 오늘 뉴스 쉬운 설명을 중복 제거해 핵심 글머리로 정리해라.\n" + json.dumps(
        {"stocks": stocks}, ensure_ascii=False, separators=(",", ":")
    )


def _parse_issue_briefs(
    raw: str,
    inputs: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], bool]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end < start:
            return {}, False
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {}, False

    output: dict[str, dict[str, list[dict[str, Any]]]] = {}
    stocks = parsed.get("stocks") if isinstance(parsed, dict) else None
    if not isinstance(stocks, dict):
        return {}, False

    for stock_code, source in inputs.items():
        generated = stocks.get(stock_code)
        if not isinstance(generated, dict):
            return {}, False
        output[stock_code] = {"positive": [], "negative": []}
        for sentiment in ("positive", "negative"):
            allowed_ids = {int(item["cluster_id"]) for item in source[sentiment]}
            raw_items = generated.get(sentiment)
            if not isinstance(raw_items, list):
                return {}, False
            for item in raw_items[:ISSUE_BRIEF_MAX_ITEMS]:
                if not isinstance(item, dict):
                    continue
                text = " ".join(str(item.get("text") or "").split()).strip()
                cluster_ids = [
                    int(cluster_id)
                    for cluster_id in item.get("cluster_ids", [])
                    if str(cluster_id).isdigit() and int(cluster_id) in allowed_ids
                ]
                if not text:
                    continue
                if not cluster_ids and source[sentiment]:
                    cluster_ids = [int(source[sentiment][0]["cluster_id"])]
                output[stock_code][sentiment].append(
                    {"text": text[:48], "clusterIds": list(dict.fromkeys(cluster_ids))}
                )
            if source[sentiment] and not output[stock_code][sentiment]:
                return {}, False
    return output, True


def call_solar_issue_briefs(
    api_key: str,
    inputs: dict[str, dict[str, Any]],
    max_retries: int = 3,
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], dict[str, Any]]:
    """Summarize all changed stocks in one Solar request."""

    payload = {
        "model": CFG.SOLAR_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_issue_brief_prompt(inputs)},
        ],
        "temperature": 0,
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    delay = 1.0
    last_error = ""
    for _attempt in range(max_retries):
        started = time.monotonic()
        try:
            response = requests.post(
                f"{CFG.SOLAR_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=90,
            )
        except requests.RequestException as exc:
            last_error = f"request_error: {exc}"
            time.sleep(delay)
            delay *= 2
            continue
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code == 429 or response.status_code >= 500:
            last_error = f"http_{response.status_code}"
            time.sleep(delay)
            delay *= 2
            continue
        if not response.ok:
            return {}, {
                "ok": False,
                "parse_success": False,
                "raw": response.text[:500],
                "latency_ms": latency_ms,
            }
        data = response.json()
        raw = data["choices"][0]["message"]["content"]
        parsed, parse_success = _parse_issue_briefs(raw, inputs)
        return parsed, {
            "ok": True,
            "parse_success": parse_success,
            "raw": raw,
            "latency_ms": latency_ms,
            "usage": data.get("usage", {}),
        }
    return {}, {
        "ok": False,
        "parse_success": False,
        "raw": last_error,
        "latency_ms": 0,
    }


def refresh_stock_issue_briefs(
    repo: Any,
    api_key: str,
    *,
    call_fn: Callable[
        [str, dict[str, dict[str, Any]]],
        tuple[dict[str, dict[str, list[dict[str, Any]]]], dict[str, Any]],
    ] = call_solar_issue_briefs,
) -> dict[str, int]:
    """Refresh changed stock briefs; use at most one Solar call per scheduler cycle."""

    inputs = prepare_issue_brief_inputs(
        repo.get_today_issue_brief_candidates(),
        repo.get_stock_names(),
    )
    states = repo.get_issue_brief_states(list(inputs))
    changed = {
        stock_code: value
        for stock_code, value in inputs.items()
        if states.get(stock_code, {}).get("source_hash") != value["source_hash"]
    }
    totals = {
        "issue_brief_calls": 0,
        "issue_briefs": 0,
        "issue_brief_skipped": len(inputs) - len(changed),
        "issue_brief_failed": 0,
    }
    if not changed:
        return totals

    nonempty = {
        code: value for code, value in changed.items() if value["positive"] or value["negative"]
    }
    generated: dict[str, dict[str, list[dict[str, Any]]]] = {}
    if nonempty:
        generated, meta = call_fn(api_key, nonempty)
        totals["issue_brief_calls"] = 1
        if not meta.get("ok") or not meta.get("parse_success"):
            totals["issue_brief_failed"] = len(nonempty)
            return totals

    for stock_code, value in changed.items():
        brief = generated.get(stock_code, {"positive": [], "negative": []})
        repo.save_issue_brief(
            stock_code=stock_code,
            positive_items=brief["positive"],
            negative_items=brief["negative"],
            source_cluster_ids=sorted(
                {
                    int(item["cluster_id"])
                    for sentiment in ("positive", "negative")
                    for item in value[sentiment]
                }
            ),
            source_hash=value["source_hash"],
            model=CFG.SOLAR_MODEL,
            prompt_version=ISSUE_BRIEF_PROMPT_VERSION,
        )
        totals["issue_briefs"] += 1
    return totals

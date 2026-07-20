"""EXP-5 [4] Solar Pro 라벨 비의존 사실 통합 본문 생성.

각 사건 클러스터의 여러 기사(제목·description·본문 일부)를 입력으로 Solar Pro에
넣어 중복을 제거한 사실 통합 `title`/`factual_body`를 만든다.

규칙(SPEC Step 6 / prompt.md):
- 중복 보도를 하나로 합치되 주체·행위·수치·시점·확정 여부를 보존한다.
- 기사 간 내용이 충돌하면 단정하지 않고 차이를 표시한다.
- 호재/악재/긍정/부정/매수/매도 등 투자 판단 표현을 금지한다.
- 감성 라벨/모델 예측을 입력으로 제공하지 않는다.
- 프롬프트와 버전을 저장해 재현 가능하게 한다.
"""

from __future__ import annotations

import json
import time

import requests

from . import config as CFG

SYSTEM_PROMPT = (
    "너는 한국어 금융 뉴스 편집 도우미다. 같은 사건을 보도한 여러 기사를 입력받아 "
    "사실 중심의 통합 제목과 통합 본문을 만든다.\n"
    "반드시 지켜야 할 규칙:\n"
    "1. 여러 언론사의 중복 내용을 하나로 정리한다.\n"
    "2. 중요한 사실, 수치, 발표 주체, 시점, 확정/예정/잠정 여부를 그대로 보존한다.\n"
    "3. 기사마다 내용이 다르면 단정하지 말고 차이나 불확실성을 그대로 표시한다.\n"
    "4. 호재, 악재, 긍정, 부정, 매수, 매도, 기대, 우려 같은 투자 판단·감성 표현을 절대 쓰지 않는다.\n"
    "5. 기사에 없는 사실을 새로 만들지 않는다.\n"
    "6. factual_body는 2~4문장으로 간결하게 쓴다.\n"
    '출력은 반드시 {"title": "...", "factual_body": "..."} 형태의 JSON 하나만 출력한다.'
)


def build_user_prompt(articles: list[dict], stock_name: str) -> str:
    """클러스터 소속 기사들을 번호 매겨 사용자 프롬프트로 구성.

    articles: [{press, title, description, body, published_at}] (발행 시간순, 이미 잘림 적용)
    """

    lines = [
        f"[종목] {stock_name}",
        "",
        "다음은 같은 사건을 보도한 기사들이다. 사실 통합 제목과 본문을 만들어라.",
        "",
    ]
    for i, a in enumerate(articles, 1):
        lines.append(
            f"[기사 {i}] ({a.get('press') or '언론사미상'}, {a.get('published_at', '')[:10]})"
        )
        if a.get("title"):
            lines.append(f"제목: {a['title']}")
        if a.get("description"):
            lines.append(f"요약: {a['description']}")
        body = (a.get("body") or "").strip()
        if body:
            lines.append(f"본문: {body[: CFG.MAX_BODY_CHARS]}")
        lines.append("")
    return "\n".join(lines)


def call_solar(api_key: str, user_prompt: str, max_retries: int = 4) -> tuple[dict, dict]:
    """Solar Pro 호출 → (parsed_json, meta). 지수 백오프 재시도.

    meta: {ok, status, latency_ms, usage, raw, parse_success}
    parsed: {"title", "factual_body"} (parse 실패 시 빈 dict)
    """

    payload = {
        "model": CFG.SOLAR_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": CFG.SOLAR_TEMPERATURE,
        "max_tokens": CFG.SOLAR_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    delay = 2.0
    last_err = ""
    for attempt in range(max_retries):
        t0 = time.time()
        try:
            r = requests.post(
                f"{CFG.SOLAR_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=90
            )
        except requests.RequestException as e:  # noqa: PERF203
            last_err = f"request_error: {e}"
            time.sleep(delay)
            delay *= 2
            continue
        latency = int((time.time() - t0) * 1000)
        if r.status_code == 429 or r.status_code >= 500:
            last_err = f"http_{r.status_code}"
            time.sleep(delay)
            delay *= 2
            continue
        if not r.ok:
            return {}, {
                "ok": False,
                "status": r.status_code,
                "raw": r.text[:500],
                "parse_success": False,
                "latency_ms": latency,
            }
        data = r.json()
        raw = data["choices"][0]["message"]["content"]
        parsed, ok = _parse(raw)
        return parsed, {
            "ok": True,
            "status": 200,
            "latency_ms": latency,
            "usage": data.get("usage", {}),
            "raw": raw,
            "parse_success": ok,
        }
    return {}, {
        "ok": False,
        "status": None,
        "raw": last_err,
        "parse_success": False,
        "latency_ms": 0,
    }


def _parse(raw: str) -> tuple[dict, bool]:
    """모델 출력에서 title/factual_body JSON 추출."""

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # 코드펜스 등 여분 텍스트 제거 후 첫 { ~ 마지막 } 시도
        s, e = raw.find("{"), raw.rfind("}")
        if s == -1 or e == -1:
            return {}, False
        try:
            obj = json.loads(raw[s : e + 1])
        except json.JSONDecodeError:
            return {}, False
    title = (obj.get("title") or "").strip()
    body = (obj.get("factual_body") or "").strip()
    if not title or not body:
        return {"title": title, "factual_body": body}, False
    return {"title": title, "factual_body": body}, True

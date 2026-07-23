"""EXP-5 [4] Solar Pro 라벨 비의존 사실 통합 본문 생성.

각 사건 클러스터의 여러 기사(제목·description·본문 일부)를 입력으로 Solar Pro에
넣어 중복을 제거한 사실 통합 `title`/`factual_body`와 초보자용
`easy_explanation`을 만든다.

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
    "6. factual_body는 사건의 배경, 핵심 행위, 중요한 수치, 현재 확정 상태를 "
    "가능한 범위에서 4~6문장, 900자 이내로 정리한다. 원문 정보가 적으면 억지로 늘리거나 추측하지 않는다.\n"
    "7. factual_body는 한 덩어리로 쓰지 말고 내용 흐름에 따라 2~3개 문단으로 나누며 문단 사이는 "
    "반드시 빈 줄(\\n\\n) 하나를 둔다. 각 문단은 가장 중요한 첫 문장 하나만 **문장** 형태로 감싸 강조하고, "
    "나머지는 보충 설명으로 쓴다. 불릿, 소제목, 다른 Markdown은 사용하지 않는다.\n"
    "8. 첫 문단은 지금 확인된 핵심 사실, 둘째 문단은 배경·수치·시장 반응, 마지막 문단은 확정된 "
    "향후 일정이나 아직 결정되지 않은 사항을 우선 배치한다. 정보가 없으면 해당 내용을 만들지 않는다.\n"
    "9. easy_explanation은 기사를 다시 요약하지 말고, 주식을 처음 보는 사람도 한 번에 핵심을 이해하도록 "
    "1~2문장, 140자 이내로 쓴다. '쉽게 말해', '쉽게 말하면', '이 기사는' 같은 상투적인 서두를 쓰지 말고 "
    "회사에 무슨 일이 생겼는지와 그 일이 회사에 어떤 의미인지 일상적인 말로 바로 설명한다. "
    "배경과 수치를 나열하지 말고 가장 중요한 "
    "내용 하나만 남긴다. 꼭 필요한 금융 용어가 있으면 두 번째 문장에서 짧게 뜻을 풀어준다. "
    "'~해요' 말투를 쓰고 호재·악재 판단이나 주가 예측은 넣지 않는다.\n"
    '출력은 반드시 {"title": "...", "easy_explanation": "...", "factual_body": "..."} '
    "형태의 JSON 하나만 출력한다."
)

COMPACT_RETRY_SYSTEM_PROMPT = (
    "직전 응답이 너무 길거나 JSON 형식이 깨졌다. 같은 기사만 근거로 다시 작성한다. "
    "title은 90자 이내, easy_explanation은 상투적인 서두 없이 핵심부터 쓰는 1~2문장·140자 이내, factual_body는 "
    "2~3문단·4~5문장·700자 이내로 제한한다. 각 문단 첫 문장만 **문장**으로 강조한다. "
    "불릿과 소제목을 쓰지 말고 불필요한 공백이나 반복을 만들지 않는다. "
    "기사에 없는 내용과 투자 판단을 추가하지 않는다. "
    '반드시 {"title":"...","easy_explanation":"...","factual_body":"..."} JSON 하나만 출력한다.'
)


def build_user_prompt(articles: list[dict], stock_name: str) -> str:
    """클러스터 소속 기사들을 번호 매겨 사용자 프롬프트로 구성.

    articles: [{press, title, description, body, published_at}] (발행 시간순, 이미 잘림 적용)
    """

    lines = [
        f"[종목] {stock_name}",
        "",
        "다음은 같은 사건을 보도한 기사들이다. 사실 통합 제목, 핵심만 짧고 일상적인 말로 푼 쉬운 설명, "
        "핵심 문장이 강조된 2~3문단의 사건 정리 본문을 만들어라.",
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
    parsed: {"title", "easy_explanation", "factual_body"} (parse 실패 시 빈 dict)
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
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    request_count = 0
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
        request_count += 1
        for key in usage_total:
            usage_total[key] += int((data.get("usage") or {}).get(key) or 0)
        choice = data["choices"][0]
        raw = choice["message"]["content"]
        parsed, ok = _parse(raw)
        if not ok and attempt < max_retries - 1:
            last_err = f"invalid_json finish_reason={choice.get('finish_reason')}"
            payload["messages"][0]["content"] = COMPACT_RETRY_SYSTEM_PROMPT
            payload["max_tokens"] = 1100
            time.sleep(min(delay, 1.0))
            continue
        return parsed, {
            "ok": True,
            "status": 200,
            "latency_ms": latency,
            "usage": usage_total,
            "raw": raw,
            "parse_success": ok,
            "finish_reason": choice.get("finish_reason"),
            "request_count": request_count,
        }
    return {}, {
        "ok": False,
        "status": None,
        "raw": last_err,
        "parse_success": False,
        "latency_ms": 0,
        "usage": usage_total,
        "request_count": request_count,
    }


def _parse(raw: str) -> tuple[dict, bool]:
    """모델 출력에서 title/easy_explanation/factual_body JSON 추출."""

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
    easy = (obj.get("easy_explanation") or "").strip()
    body = (obj.get("factual_body") or "").strip()
    parsed = {"title": title, "easy_explanation": easy, "factual_body": body}
    if not title or not easy or not body:
        return parsed, False
    return parsed, True


EASY_EXPLAIN_SYSTEM_PROMPT = (
    "너는 주식을 처음 접한 사람에게 어려운 뉴스 문구 하나만 풀어주는 설명 도우미다. "
    "선택 문구의 뜻과 이 뉴스에서의 의미만 남긴다. 기본은 자연스럽게 이어지는 1~2문장의 "
    "짧은 문단으로 쓴다. '뜻:', '여기서는:' 같은 접두어나 글머리 기호를 습관적으로 붙이지 "
    "않는다. 서로 다른 개념 두 개를 분리해야 이해가 쉬울 때만 글머리 기호를 사용한다. "
    "전체는 최대 2문장, 120자 이내로 쓴다. 기사 전체를 요약하거나 문맥의 "
    "수치와 사례를 나열하지 않는다. '쉽게 말해', '이 기사는' 같은 서두를 쓰지 않는다. "
    "전문용어를 새로 쓰지 말고 '~해요' 말투를 사용한다. "
    "투자 추천, 호재·악재 판단, 주가 예측은 하지 않는다. "
    '출력은 반드시 {"explanation":"..."} JSON 하나만 출력한다.'
)


def call_solar_easy_explain(
    api_key: str, selected_text: str, context: str, max_retries: int = 3
) -> tuple[dict, dict]:
    """선택한 뉴스 문구를 문맥에 맞게 쉬운 말로 설명한다."""

    payload = {
        "model": CFG.SOLAR_MODEL,
        "messages": [
            {"role": "system", "content": EASY_EXPLAIN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"[뉴스 문맥]\n{context[:3000]}\n\n[선택한 문구]\n{selected_text}",
            },
        ],
        "temperature": 0,
        "max_tokens": 240,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    delay, last_error = 1.0, ""
    for _attempt in range(max_retries):
        started = time.time()
        try:
            response = requests.post(
                f"{CFG.SOLAR_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )
        except requests.RequestException as exc:
            last_error = f"request_error: {exc}"
            time.sleep(delay)
            delay *= 2
            continue
        latency = int((time.time() - started) * 1000)
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
                "latency_ms": latency,
            }
        data = response.json()
        raw = data["choices"][0]["message"]["content"]
        parsed, parse_success = _parse_easy_explanation(raw)
        return parsed, {
            "ok": True,
            "parse_success": parse_success,
            "raw": raw,
            "latency_ms": latency,
            "usage": data.get("usage", {}),
        }
    return {}, {
        "ok": False,
        "parse_success": False,
        "raw": last_error,
        "latency_ms": 0,
    }


def _parse_easy_explanation(raw: str) -> tuple[dict, bool]:
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        start, end = str(raw).find("{"), str(raw).rfind("}")
        if start == -1 or end == -1:
            return {}, False
        try:
            obj = json.loads(str(raw)[start : end + 1])
        except json.JSONDecodeError:
            return {}, False
    explanation = (obj.get("explanation") or "").strip() if isinstance(obj, dict) else ""
    return {"explanation": explanation}, bool(explanation)

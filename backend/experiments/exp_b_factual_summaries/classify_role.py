"""뉴스 처리 v2: (article_id, stock_code) pair 의 역할(article_role) 분류.

정책(prompt.md v2):
  - 실제 회사 사건(company_event)만 event_eligible=true 로 동일사건 클러스터링 대상.
  - 칼럼·사설·시장종합·주가반응·전망/해설·단순언급 등은 event_eligible=false.
  - 명확한 오피니언 표지는 규칙(market_rules.is_opinion)으로 먼저 확정한다.
  - 규칙으로 확정 못 하는 relevant pair 는 Solar 로 역할을 판정한다.

역할 값: company_event | opinion | market_summary | price_reaction |
         background | incidental | unrelated

이 모듈은 Solar 호출을 call_fn 으로 주입 가능하게 해 테스트에서 Mock 을 넣는다.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import requests

from . import config as CFG
from . import market_rules

ROLE_VERSION = "role_title_event_v2"

VALID_ROLES = {
    "company_event",
    "opinion",
    "market_summary",
    "price_reaction",
    "background",
    "incidental",
    "unrelated",
}

# 규칙 게이트가 확정하는 역할은 event_eligible=false 다.
RULE_ROLE_OPINION = "opinion"

_EMPTY_SIGNATURE = {
    "core_subjects": [],
    "core_topic": None,
    "unique_anchors": [],
    "story_relation": "unknown",
}

_STORY_RELATIONS = {"initial", "follow_up", "reaction", "unknown"}

SYSTEM_PROMPT = (
    "너는 한국어 금융 뉴스의 '역할' 분류기다. 주어진 종목 관점에서 이 기사가 어떤 "
    "역할인지 판정한다.\n"
    "역할 값과 기준:\n"
    "1. company_event: 해당 회사가 중심이고, 실제로 발생·발표된 '하나의 구체적 사건'이 "
    "있다(계약·실적발표·투자·제품출시·인수합병·인사·소송·규제·사고 등). → event_eligible=true\n"
    "2. opinion: 칼럼·사설·기고·기자수첩·데스크칼럼·논설·시론·만평 등 의견/논평 글. → false\n"
    "3. market_summary: 증시·업종 전체를 다루는 시장/산업 종합. → false\n"
    "4. price_reaction: 주가 등락·수급만 다루는 기사. → false\n"
    "5. background: 전망·해설·기획 등 특정 사건 보도가 아닌 배경 설명. → false\n"
    "6. incidental: 해당 종목이 예시·비교 대상으로만 언급된 기사. → false\n"
    "7. unrelated: 해당 종목과 실질적 관련이 없는 기사. → false\n"
    "규칙:\n"
    "- 하나의 구체적 회사 사건을 식별할 수 없으면 company_event 가 아니다.\n"
    "- 애매하면 company_event 로 두지 말고 background/incidental 로 판정한다.\n"
    "- 역할과 event_signature는 반드시 제목만 근거로 판단한다. 검색 결과의 description이나 "
    "본문 배경정보를 사건 정보로 사용하지 않는다.\n"
    "- company_event 일 때만 event_signature를 채운다: core_subjects(핵심 인물·기관 배열), "
    "core_topic(기사가 다루는 핵심 사건 주제), unique_anchors(금액·계약명·제품명·행사명처럼 "
    "같은 이슈를 식별하는 고유 표현 배열), story_relation(최초 사건이면 initial, 기존 사건의 "
    "후속 조치면 follow_up, 반응·영향 보도면 reaction, 제목만으로 불명확하면 unknown).\n"
    '출력은 반드시 다음 JSON 하나만: {"article_role":"...","event_eligible":true/false,'
    '"reason":"...","event_signature":{"core_subjects":[],"core_topic":null,'
    '"unique_anchors":[],"story_relation":"unknown"}}. '
    "설명을 덧붙이지 않는다."
)


def rule_gate(title: str, description: str = "") -> dict | None:
    """규칙만으로 역할을 확정할 수 있으면 결과 dict 반환, 아니면 None(→ LLM 판정).

    현재는 명확한 오피니언 표지만 확정한다(오탐이 거의 없는 안전한 규칙)."""

    if market_rules.is_opinion(title, description):
        m = market_rules._OPINION_RE.search(title or "")
        return {
            "article_role": RULE_ROLE_OPINION,
            "event_eligible": False,
            "reason": f"rule:opinion({m.group() if m else 'marker'})",
            "event_signature": dict(_EMPTY_SIGNATURE),
            "role_source": "rule",
            "role_version": ROLE_VERSION,
        }
    return None


def build_user_prompt(stock_name: str, stock_code: str, article: dict) -> str:
    """LLM 입력: 종목명·코드 + 발행 시각 + 제목만."""

    lines = [
        f"[대상 종목] {stock_name} ({stock_code})",
        f"[발행 시각] {article.get('published_at', '')}",
        f"[제목] {article.get('title', '')}",
        "",
        "제목만 근거로 이 기사가 위 대상 종목 관점에서 어떤 역할인지 판정하고, "
        "company_event라면 단순화된 사건 정보를 추출하라.",
    ]
    return "\n".join(lines)


def _string_list(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def normalize_event_signature(value: object) -> dict:
    """단순 사건 스키마로 정규화하며, DB의 기존 상세 스키마도 읽는다."""

    if not isinstance(value, dict):
        return dict(_EMPTY_SIGNATURE)

    if any(key in value for key in _EMPTY_SIGNATURE):
        relation = str(value.get("story_relation") or "unknown").strip()
        if relation not in _STORY_RELATIONS:
            relation = "unknown"
        return {
            "core_subjects": _string_list(value.get("core_subjects")),
            "core_topic": str(value.get("core_topic") or "").strip() or None,
            "unique_anchors": _string_list(value.get("unique_anchors")),
            "story_relation": relation,
        }

    # 전환 전에 저장된 subject/action/object 스키마와의 호환성.
    topic_parts = [
        str(value.get(key) or "").strip()
        for key in ("action", "object", "product_or_project")
        if value.get(key)
    ]
    anchors: list[str] = []
    for key in ("amount", "event_date", "identifiers", "product_or_project"):
        for item in _string_list(value.get(key)):
            if item not in anchors:
                anchors.append(item)
    return {
        "core_subjects": _string_list(value.get("subject")),
        "core_topic": " ".join(topic_parts) or None,
        "unique_anchors": anchors,
        "story_relation": "unknown",
    }


def parse_role(raw: str) -> tuple[dict, bool]:
    """모델 출력에서 역할 판정 dict 추출 + 검증. 실패 시 (부분dict, False)."""

    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        s, e = raw.find("{"), raw.rfind("}")
        if s == -1 or e == -1:
            return {}, False
        try:
            obj = json.loads(raw[s : e + 1])
        except json.JSONDecodeError:
            return {}, False
    if not isinstance(obj, dict):
        return {}, False
    role = obj.get("article_role")
    if role not in VALID_ROLES:
        return {"article_role": role}, False
    eligible = obj.get("event_eligible")
    if not isinstance(eligible, bool):
        eligible = role == "company_event"
    # 일관성 강제: company_event 만 eligible=true.
    eligible = role == "company_event"
    sig = normalize_event_signature(obj.get("event_signature"))
    if role != "company_event":
        sig = dict(_EMPTY_SIGNATURE)
    return {
        "article_role": role,
        "event_eligible": eligible,
        "reason": str(obj.get("reason") or "")[:500],
        "event_signature": sig,
        "role_source": "llm",
        "role_version": ROLE_VERSION,
    }, True


def call_solar_role(
    api_key: str, user_prompt: str, *, max_retries: int = 3, timeout: float = 60.0
) -> tuple[dict, dict]:
    """Solar 역할 판정 호출 → (parsed, meta). 429/5xx 지수 백오프."""

    payload = {
        "model": CFG.LLM_ASSIGN_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    delay, last_err = 2.0, ""
    for _ in range(max_retries):
        t0 = time.time()
        try:
            r = requests.post(
                f"{CFG.SOLAR_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as e:
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
                "raw": r.text[:300],
                "parse_success": False,
                "latency_ms": latency,
            }
        data = r.json()
        raw = data["choices"][0]["message"]["content"]
        parsed, ok = parse_role(raw)
        return parsed, {
            "ok": True,
            "status": 200,
            "latency_ms": latency,
            "usage": data.get("usage", {}),
            "raw": raw,
            "parse_success": ok,
        }
    return {}, {"ok": False, "status": None, "raw": last_err, "parse_success": False}


class RoleClassifier:
    """pair 역할 분류기. 규칙 게이트 먼저, 없으면 LLM. call_fn 주입 가능."""

    def __init__(
        self,
        api_key: str = "",
        call_fn: Callable[[str], tuple[dict, dict]] | None = None,
    ) -> None:
        self.api_key = api_key
        self._call = call_fn or (lambda p: call_solar_role(api_key, p))
        self.calls = 0
        self.token_usage = {"prompt": 0, "completion": 0}

    def classify(self, stock_name: str, stock_code: str, article: dict) -> tuple[dict | None, str]:
        """(결과 dict 또는 None, 상태). 상태: 'rule' | 'llm' | 'pending_retry'.

        None 은 LLM 실패로 재시도 필요(pending_retry)."""

        # Search-result descriptions can quote an unrelated body paragraph.
        gated = rule_gate(article.get("title", ""))
        if gated is not None:
            return gated, "rule"

        prompt = build_user_prompt(stock_name, stock_code, article)
        parsed, meta = self._call(prompt)
        self.calls += 1
        if meta.get("usage"):
            self.token_usage["prompt"] += meta["usage"].get("prompt_tokens", 0)
            self.token_usage["completion"] += meta["usage"].get("completion_tokens", 0)
        if not meta.get("ok") or not meta.get("parse_success"):
            return None, "pending_retry"
        return parsed, "llm"

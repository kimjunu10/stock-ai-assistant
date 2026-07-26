"""자연어 의미 판정을 위한 LLM judge (평가 전용, 운영 경로 미사용).

grader.py 의 자연어 판정은 원래 한국어 키워드 부분 문자열 검사였다
(`"없" in text` 등). 이 방식은 의미가 같은 표현을 표현 차이만으로 실패
처리한다 — 예: "확인할 수 없습니다"는 통과하지만 뜻이 같은 "아직 공시되지
않았습니다"는 실패한다. 그러면 제품 프롬프트를 채점기 키워드에 맞춰 쓰게
되는 역방향 압력이 생긴다(평가지표를 속이는 것).

그래서 자연어 의미 판단만 Solar LLM judge 로 옮긴다. 객관적으로 검증
가능한 지표(Tool 호출, 문서 ID, 숫자, 기간, 거래일)는 기존 코드 채점을
그대로 쓴다 — LLM 에 맡기지 않는다.

judge 설계 원칙:
- temperature=0, JSON 스키마 강제.
- 입력은 질문 / 최종 답변 / 실제 Tool 근거(출처 목록)뿐이다.
- judge 는 자기 금융지식으로 사실 여부를 판단하지 않는다. "주어진 근거만
  보고 답변이 근거 범위 안에 있는가"만 본다(프롬프트에 명시).
- 결과는 캐시에 저장해 같은 (질문, 답변) 조합을 재호출하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

SOLAR_BASE_URL = os.environ.get("UPSTAGE_BASE_URL", "https://api.upstage.ai/v1")
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "solar-pro3-260323")

JUDGE_SYSTEM_PROMPT = """너는 한국어 금융 QA 답변의 채점자다.

너에게는 질문, 답변, 그리고 그 답변이 실제로 사용한 근거 목록이 주어진다.
너는 다음 세 가지만 판정한다.

1. handled_correctly
   - 이 질문이 "근거가 없어 답할 수 없는 질문"으로 표시된 경우에만 판정한다.
   - 답변이 값을 확인할 수 없다/데이터가 없다/아직 공시되지 않았다는 사실을
     사용자에게 전달했거나, 어떤 정보가 필요한지 되물었으면 true.
   - 표현 방식은 자유다. "확인할 수 없습니다", "아직 공시되지 않았습니다",
     "제공되지 않습니다" 등은 모두 같은 뜻이므로 모두 true 다.
   - 근거가 없는데도 구체적인 값·수치를 단정해 답한 것처럼 보이면 false.
   - 답할 수 있는 질문이면 null.

2. grounded
   - 답변이 근거 목록과 명백히 모순되는 주장을 했으면 false, 그 외에는 true.
   - 주의: 너에게 주어지는 근거 목록은 출처의 제목·종류·날짜뿐이고 실제 수치나
     본문은 포함되지 않는다. 따라서 답변의 숫자가 근거 목록에 안 보인다는 이유로
     false 를 주면 안 된다. 그 숫자는 근거 문서 안에 있지만 너에게 전달되지 않은
     것일 뿐이다.
   - 근거 목록에 있는 종류의 자료로 설명 가능한 답변이면 true 로 둔다.
   - 근거가 하나도 없는데 답변이 구체적인 값을 단정한 경우에만 false 를 준다.

3. exclusion_respected
   - 질문이 특정 주제를 제외해 달라고 요청한 경우에만 판정한다(제외 대상이 함께 주어진다).
   - 답변이 그 주제를 실제로 설명·주장했으면 false.
   - 그 주제를 다루지 않았거나 "그 내용은 제외했습니다"라고만 밝혔으면 true.
   - 제외 요청이 없으면 null.

절대 규칙:
- 너의 금융 지식으로 답변 내용이 진짜 사실인지 판단하지 마라. 너는 "주어진
  근거 안에 있는가"만 본다. 근거에 있는 값이면, 그 값이 실제 세계에서 틀렸다고
  생각되더라도 grounded=true 다.
- 답변의 문체·길이·서식이 마음에 드는지는 판정 대상이 아니다.
- 확신이 없으면 판정을 관대하게(true) 하지 말고 reason 에 불확실한 이유를 적어라.

출력은 반드시 다음 JSON 하나만 반환한다.
{"handled_correctly": true|false|null, "grounded": true|false,
 "exclusion_respected": true|false|null, "reason": "<한국어 한두 문장>"}
"""


@dataclass
class JudgeVerdict:
    handled_correctly: bool | None = None
    grounded: bool = True
    exclusion_respected: bool | None = None
    reason: str = ""
    ok: bool = True  # API 호출·파싱 성공 여부(실패면 호출부가 기존 채점으로 폴백)
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "handled_correctly": self.handled_correctly,
            "grounded": self.grounded,
            "exclusion_respected": self.exclusion_respected,
            "reason": self.reason,
            "ok": self.ok,
            "error": self.error,
        }


def build_user_prompt(
    *,
    question: str,
    answer: str,
    sources: list[dict],
    is_answerable: bool,
    forbidden_claims: list[str],
) -> str:
    """judge 입력. 질문·답변·실제 Tool 근거만 넣는다(gold 정답은 넣지 않는다)."""
    lines = [f"[질문]\n{question}", ""]
    if not is_answerable:
        lines.append("이 질문은 근거가 없어 답할 수 없는 질문으로 표시돼 있다.")
    if forbidden_claims:
        lines.append(f"이 질문은 다음 주제를 제외해 달라고 요청했다: {', '.join(forbidden_claims)}")
    lines.append("")
    lines.append(f"[답변]\n{answer or '(빈 답변)'}")
    lines.append("")
    lines.append("[답변이 사용한 근거 목록]")
    if not sources:
        lines.append("(근거 없음 — Tool 이 아무 자료도 반환하지 않았다)")
    else:
        for s in sources[:20]:
            stype = s.get("source_type") or "?"
            title = (s.get("title") or "").strip() or "(제목 없음)"
            when = (s.get("published_at") or "")[:10]
            pub = s.get("publisher") or ""
            extra = " · ".join(x for x in (when, pub) if x)
            lines.append(f"- [{stype}] {title}{(' (' + extra + ')') if extra else ''}")
    return "\n".join(lines)


def _cache_key(user_prompt: str) -> str:
    """모델·시스템 프롬프트·입력이 모두 같을 때만 캐시를 재사용한다.

    시스템 프롬프트를 고치면 판정 기준이 바뀌므로 캐시가 무효가 되어야 한다.
    프롬프트 본문을 키에 섞어 자동으로 무효화한다.
    """
    material = "\x00".join((JUDGE_MODEL, JUDGE_SYSTEM_PROMPT, user_prompt))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


@dataclass
class JudgeCache:
    """(질문, 답변, 근거) 조합별 판정 결과를 파일에 저장해 재호출을 막는다."""

    path: Path
    _data: dict[str, dict] = field(default_factory=dict)

    def load(self) -> JudgeCache:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text("utf-8"))
            except (ValueError, OSError):
                self._data = {}
        return self

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def put(self, key: str, value: dict) -> None:
        self._data[key] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def __len__(self) -> int:
        return len(self._data)


def judge_answer(
    *,
    question: str,
    answer: str,
    sources: list[dict],
    is_answerable: bool = True,
    forbidden_claims: list[str] | None = None,
    api_key: str = "",
    cache: JudgeCache | None = None,
    max_retries: int = 3,
    timeout: float = 60.0,
) -> JudgeVerdict:
    """Solar 로 자연어 의미 판정 1건. 캐시가 있으면 재호출하지 않는다."""
    user_prompt = build_user_prompt(
        question=question,
        answer=answer,
        sources=sources,
        is_answerable=is_answerable,
        forbidden_claims=forbidden_claims or [],
    )
    key = _cache_key(user_prompt)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return JudgeVerdict(**hit)

    if not api_key:
        return JudgeVerdict(ok=False, error="no_api_key")

    payload = {
        "model": JUDGE_MODEL,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    delay, last_err = 2.0, ""
    for _ in range(max_retries):
        try:
            r = requests.post(
                f"{SOLAR_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_err = f"request_error: {type(exc).__name__}"
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 429 or r.status_code >= 500:
            last_err = f"http_{r.status_code}"
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code != 200:
            return JudgeVerdict(ok=False, error=f"http_{r.status_code}")
        try:
            content = r.json()["choices"][0]["message"]["content"]
            parsed: dict[str, Any] = json.loads(content)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            return JudgeVerdict(ok=False, error=f"parse_error: {type(exc).__name__}")

        verdict = JudgeVerdict(
            handled_correctly=_tri(parsed.get("handled_correctly")),
            grounded=bool(parsed.get("grounded", True)),
            exclusion_respected=_tri(parsed.get("exclusion_respected")),
            reason=str(parsed.get("reason") or "")[:500],
            ok=True,
        )
        if cache is not None:
            cache.put(key, verdict.as_dict())
        return verdict

    return JudgeVerdict(ok=False, error=last_err or "exhausted_retries")


def _tri(value: Any) -> bool | None:
    """true/false/null 3값을 그대로 보존한다(판정 대상 아님 = None)."""
    if value is None:
        return None
    return bool(value)


def make_grader_judge(*, api_key: str, cache: JudgeCache | None = None):
    """grade_case(judge=...) 에 넘길 수 있는 어댑터를 만든다.

    grade_case 는 (case, record) 만 넘기므로, judge 입력에 필요한 값
    (질문·답변·출처·답변가능 여부·제외 대상)을 여기서 뽑아 전달한다.
    gold 정답은 넘기지 않는다 — judge 가 정답을 보고 채점하면 "근거 범위 안인가"
    가 아니라 "정답과 같은가"를 보게 되어 판정 성격이 바뀐다.
    """

    def _judge(case: Any, record: Any) -> JudgeVerdict:
        return judge_answer(
            question=record.question,
            answer=record.answer,
            sources=record.sources,
            is_answerable=case.is_answerable,
            forbidden_claims=case.forbidden_claims,
            api_key=api_key,
            cache=cache,
        )

    return _judge

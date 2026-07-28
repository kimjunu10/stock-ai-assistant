"""사건 후속 질문의 사건 확정 규칙 (prompt.md §4).

"그 뉴스 이후 주가가 어떻게 됐어?" 같은 후속 질문에서 **직전 자연어 답변을 다시 파싱하지
않고**, 구조화된 사건 문맥(EventContext)만으로 대상 사건을 확정한다.

우선순위:
  1. 사용자가 직접 선택한 사건(user_selected 또는 selected_event_id)
  2. 직전 응답에 서로 다른 사건이 정확히 1개인 경우(같은 사건 기사 여러 건은 1개로 클러스터)
  3. 그 외에는 자동 확정하지 않는다(명확화 요청).

이 모듈은 질문 문장을 키워드로 라우팅하지 않는다. 사건 문맥이 주어졌을 때 무엇을
확정할 수 있는지만 판정한다. 특정 인물·회사·질문 문장을 하드코딩하지 않는다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

from app.schemas.qa import EventContext


@dataclass
class EventCandidate:
    """명확화 후보 1건(사용자에게 되물을 때 보여줄 최소 정보)."""

    event_id: str
    title: str | None
    published_at: str | None
    stock_code: str | None


@dataclass
class EventResolution:
    """사건 확정 결과.

    status:
      - "resolved": 사건 1개 확정(event 채워짐)
      - "ambiguous": 서로 다른 사건이 2개 이상 — 임의 선택 금지, candidates 로 되묻는다
      - "none": 사건 문맥 없음 — 일반 기간 수익률로 대체하지 않는다
    """

    status: str
    event: EventContext | None = None
    candidates: list[EventCandidate] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"


def _event_day(published_at: str | None) -> date | None:
    """발표 시각(ISO) → 날짜. 파싱 실패하면 None(추정하지 않는다)."""
    if not published_at:
        return None
    raw = published_at.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def event_date_of(event: EventContext) -> date | None:
    """사건의 발표일. 없으면 None — 호출부는 날짜를 추정하지 않는다."""
    return _event_day(event.published_at)


def _cluster_key(event: EventContext) -> tuple:
    """같은 사건 판정 키.

    같은 사건을 다룬 기사 여러 건은 사건 클러스터 하나로 처리한다. 뉴스 파이프라인이
    이미 사건 단위(news_clusters)로 묶어 event_id 를 주므로 1차 키는 event_id 다.
    같은 종목·같은 발표일·같은 제목이면 서로 다른 출처라도 한 사건으로 본다.
    제목이 없으면 event_id 로만 구분한다(과도한 병합 방지).
    """
    day = _event_day(event.published_at)
    title = (event.title or "").strip()
    if title and day is not None:
        return ("titled", event.stock_code, day, title)
    return ("id", event.event_id)


def _reference_match_score(question: str | None, title: str | None) -> int:
    """질문과 사건 제목의 가장 긴 공통 구절 길이.

    회사별·공시별 키워드 목록을 두지 않고, 사용자가 직전 제목의 구체적인 표현을 다시
    언급했는지만 본다. 네 글자 미만의 일반 표현(뉴스·공시·주가 등)은 사건 선택 근거로
    쓰지 않는다.
    """

    def compact(value: str | None) -> str:
        return re.sub(
            r"[^0-9a-z가-힣]",
            "",
            unicodedata.normalize("NFKC", value or "").casefold(),
        )

    q, t = compact(question), compact(title)
    if not q or not t:
        return 0
    for size in range(min(len(q), len(t)), 3, -1):
        if any(t[start : start + size] in q for start in range(len(t) - size + 1)):
            return size
    return 0


def resolve_event(
    event_context: list[EventContext],
    *,
    selected_event_id: str | None = None,
    question: str | None = None,
) -> EventResolution:
    """구조화 사건 문맥에서 대상 사건을 확정한다(§4 우선순위)."""
    events = [e for e in event_context if e and e.event_id]
    if not events:
        return EventResolution(status="none")

    # (1) 사용자가 직접 선택한 사건이 최우선.
    if selected_event_id:
        picked = next((e for e in events if e.event_id == selected_event_id), None)
        if picked is not None:
            return EventResolution(status="resolved", event=picked)
    explicit = [e for e in events if e.user_selected]
    if len(explicit) == 1:
        return EventResolution(status="resolved", event=explicit[0])
    if len(explicit) > 1:
        return EventResolution(status="ambiguous", candidates=_candidates(explicit))

    # (2) 서로 다른 사건이 정확히 1개면 자동 연결(같은 사건 기사 여러 건 포함).
    clusters: dict[tuple, list[EventContext]] = {}
    for e in events:
        clusters.setdefault(_cluster_key(e), []).append(e)
    if len(clusters) == 1:
        group = next(iter(clusters.values()))
        return EventResolution(status="resolved", event=_representative(group))

    # (3) 사용자가 직전 사건 제목의 구체적 표현을 다시 언급했고 유일하게 일치하면 연결.
    representatives = [_representative(group) for group in clusters.values()]
    scored = [(event, _reference_match_score(question, event.title)) for event in representatives]
    best = max((score for _, score in scored), default=0)
    matched = [event for event, score in scored if score == best and score >= 4]
    if len(matched) == 1:
        return EventResolution(status="resolved", event=matched[0])

    # (4) 그 외에는 자동 확정하지 않는다.
    return EventResolution(
        status="ambiguous",
        candidates=_candidates(representatives),
    )


def _representative(group: list[EventContext]) -> EventContext:
    """사건 클러스터의 대표 1건: 발표일이 확인되는 것 중 가장 이른 원보도를 택한다."""
    dated = [(e, _event_day(e.published_at)) for e in group]
    with_day = [(e, d) for e, d in dated if d is not None]
    if with_day:
        return min(with_day, key=lambda t: t[1])[0]
    return group[0]


def _candidates(events: list[EventContext]) -> list[EventCandidate]:
    return [
        EventCandidate(
            event_id=e.event_id,
            title=e.title,
            published_at=e.published_at,
            stock_code=e.stock_code,
        )
        for e in events
    ]


def clarification_message(candidates: list[EventCandidate]) -> str:
    """여러 사건일 때 되물을 안내문(제목·날짜 후보만 짧게). 숫자를 만들지 않는다."""
    lines = ["어떤 사건을 기준으로 볼지 정해주세요. 최근 답변에 서로 다른 사건이 여러 개 있습니다."]
    for i, c in enumerate(candidates[:5], start=1):
        day = (c.published_at or "")[:10] or "발표일 미상"
        title = (c.title or "제목 미상").strip()
        lines.append(f"{i}. {day} · {title}")
    return "\n".join(lines)

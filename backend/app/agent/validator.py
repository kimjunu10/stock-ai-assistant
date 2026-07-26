"""Agent 답변 코드 검증 (Phase 5.5-E, SPEC §12.2).

모델에 맡기지 않고 코드로 검증하는 항목:
- source_id 유효성: 답변이 인용한 [n] 또는 source_id 가 실제 Tool 결과에 존재하는가
- 존재하지 않는 [n] 인용
- 숫자 주장: 답변의 숫자가 Tool 결과(재무 등)에 존재하는가
- 단위·기간 메타데이터 보존
- actual/forecast 라벨 존재
- 최신 정정 여부(latest correction) 위반 없음

검증 실패는 숫자를 임의 수정하지 않고 validation_errors 로 기록한다(SPEC §12.2).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


def _norm_name(text: str) -> str:
    """기관명 비교용 정규화.

    DB 의 publisher 는 NFD(자모 분리)로 저장된 값이 있고 모델 답변은 NFC 라,
    같은 '미래에셋증권' 도 코드포인트가 달라 문자열 비교가 실패한다(운영 결함).
    유니코드를 NFC 로 합치고 공백만 제거한다 — 그 이상 느슨하게 비교하지 않는다
    (근거에 없는 증권사는 계속 차단해야 하므로).
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


_CITATION_RE = re.compile(r"\[(\d+)\]")
# 답변 속 큰 숫자(천단위 콤마/조·억 단위 등) — 재무 주장 후보
_NUMBER_RE = re.compile(r"\d[\d,]{2,}")
# 증권사명 후보(답변에서 '○○증권' 형태를 뽑아 근거와 대조)
_BROKER_RE = re.compile(r"([가-힣A-Za-z]{2,10}(?:투자)?증권)")
# 목표주가 문맥의 금액(콤마형 또는 만원형) — 답변에서 목표가 주장 탐지
_TP_CTX_RE = re.compile(r"목표\s*주?가[^\n.]{0,30}?(\d{1,3}(?:,\d{3})+|\d{1,4}\s*만)\s*원?")
# 문장 분리(한국어 종결·줄바꿈·불릿 기준의 단순 분리).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|\n+")


@dataclass
class ToolEvidence:
    """Agent 실행 중 Tool 이 반환한 근거 모음(검증 기준)."""

    source_ids: set[str] = field(default_factory=set)
    numeric_cores: set[str] = field(default_factory=set)  # 콤마 제거 숫자 문자열
    value_kinds: set[str] = field(default_factory=set)  # actual/forecast/mixed 등
    has_financial: bool = False
    # 증권사 리포트 근거(prompt.md §7)
    brokers: set[str] = field(default_factory=set)  # Tool 이 반환한 증권사명
    stated_target_prices: set[int] = field(default_factory=set)  # status=stated 목표주가
    has_reports: bool = False  # 리포트 Tool 이 결과를 냈는가
    # 주가 근거(Phase 6): 실제 가격·수익률은 주가 Tool 결과값만 인용 가능
    has_price: bool = False  # 주가 Tool 이 결과를 냈는가
    price_numeric_cores: set[str] = field(default_factory=set)  # 가격·시작/종료가 정수 문자열
    # 사건 전후 주가 근거(prompt.md §6). "이 뉴스 이후" 주장의 필수 근거.
    has_event_return: bool = False  # 사건 기준(basis="event") 계산 결과가 ok 로 있는가
    event_ids: set[str] = field(default_factory=set)
    event_dates: set[str] = field(default_factory=set)  # 발표일(YYYY-MM-DD)
    event_trading_days: set[str] = field(default_factory=set)  # 실제 사용한 거래일
    # 일반 기간 수익률 근거만 있는 상태(사건 이후 주장에 쓰면 위반)
    has_period_return: bool = False
    # 뉴스·공시 등 문서 근거가 있는가(문서 본문의 수치는 그 문서가 출처다).
    has_documents: bool = False


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


def _tp_str_to_won(raw: str) -> int:
    """답변 목표주가 표기('320,000' 또는 '48만')를 원 단위 정수로."""
    raw = raw.strip()
    if "만" in raw:
        return int(raw.replace("만", "").strip()) * 10_000
    return int(raw.replace(",", ""))


def collect_evidence(tool_payloads: list[dict[str, Any]]) -> ToolEvidence:
    """Tool 결과(ToolResult dict) 목록에서 검증 근거를 수집한다."""
    ev = ToolEvidence()
    for p in tool_payloads:
        if not isinstance(p, dict):
            continue
        for s in p.get("sources", []) or []:
            sid = s.get("source_id")
            if sid:
                ev.source_ids.add(str(sid))
            vk = s.get("value_kind")
            if vk:
                ev.value_kinds.add(str(vk))
            if s.get("source_type") == "financial":
                ev.has_financial = True
            if s.get("source_type") == "price":
                ev.has_price = True
            if s.get("source_type") in ("news_event", "dart_document", "structured_disclosure"):
                ev.has_documents = True
        data = p.get("data")
        # 주가 Tool 결과: 가격·시작/종료가를 근거 숫자로 수집(정수부만).
        _collect_price_numbers(data, ev)
        _collect_event_evidence(p, data, ev)
        for fact in _iter_facts(data):
            val = fact.get("value_won")
            if val is not None:
                ev.numeric_cores.add(str(int(val)))
            vk = fact.get("value_kind")
            if vk:
                ev.value_kinds.add(str(vk))
        # 리포트 근거: 증권사명·stated 목표주가 수집
        if isinstance(data, dict):
            reports = data.get("reports")
            if isinstance(reports, list):
                for rp in reports:
                    if not isinstance(rp, dict):
                        continue
                    ev.has_reports = True
                    b = rp.get("broker")
                    if b:
                        ev.brokers.add(_norm_name(str(b)))
                    if rp.get("target_price_status") == "stated":
                        tp = rp.get("target_price")
                        if isinstance(tp, int):
                            ev.stated_target_prices.add(tp)
    return ev


def collect_report_opinions(tool_payloads: list[dict[str, Any]]) -> list[dict]:
    """리포트 Tool 결과에서 증권사 의견 카드(구조화)를 모은다(prompt.md §8, promptv2 §5).

    목표주가는 status='stated' 인 구조화 값만 싣는다. 답변 텍스트가 아니라 Tool 이
    확정해 내려준 값이므로 환각 위험이 없다. source_id 는 sources 순서로 매핑.

    promptv2 §5 — answer 검증과 동일한 최종 게이트를 카드에도 적용한다. 아래를 모두
    통과한 항목만 남긴다:
      - target_price_status='stated' 이고 target_price 가 있는 항목만 카드화(그 외 제외)
      - 완전중복(증권사·발행일·목표주가·source_id 동일) 제거
      - 증권사별 최신 발행일 1건만 유지
    (종목 귀속·현재값 여부는 검색 계층이 이미 강제하므로 mismatch/이력값은 여기서
     stated 가 아니게 되어 자동 탈락한다.)
    """
    raw: list[dict] = []
    for p in tool_payloads:
        if not isinstance(p, dict):
            continue
        data = p.get("data")
        if not isinstance(data, dict):
            continue
        reports = data.get("reports")
        if not isinstance(reports, list):
            continue
        sources = p.get("sources") or []
        for i, rp in enumerate(reports):
            if not isinstance(rp, dict):
                continue
            # §5: stated 목표주가가 확정된 항목만 카드에 포함한다.
            if not (
                rp.get("target_price_status") == "stated" and rp.get("target_price") is not None
            ):
                continue
            src = sources[i] if i < len(sources) else {}
            raw.append(
                {
                    "broker": rp.get("broker"),
                    "report_date": rp.get("report_date"),
                    "title": rp.get("title"),
                    "investment_opinion": rp.get("investment_opinion"),
                    "target_price": int(rp["target_price"]),
                    "target_price_currency": rp.get("target_price_currency"),
                    "target_price_status": "stated",
                    "summary": rp.get("snippet"),
                    "source_id": src.get("source_id") if isinstance(src, dict) else None,
                    "source_page": rp.get("target_price_source_page") or rp.get("page"),
                    "is_stale": bool(rp.get("is_stale", False)),
                }
            )

    # §5: 완전중복(증권사·발행일·목표주가·source_id) 제거.
    deduped: list[dict] = []
    seen: set[tuple] = set()
    for o in raw:
        key = (o["broker"], o["report_date"], o["target_price"], o["source_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(o)

    # §5: 증권사별 최신 발행일 1건만 유지(발행일 파싱 실패 시 빈 문자열 → 뒤로).
    best: dict[str, dict] = {}
    for o in deduped:
        b = o.get("broker") or "?"
        cur = best.get(b)
        if cur is None or (o.get("report_date") or "") > (cur.get("report_date") or ""):
            best[b] = o
    # 발행일 desc 정렬(편중 방지: 증권사당 1건).
    return sorted(best.values(), key=lambda o: o.get("report_date") or "", reverse=True)


def _iter_facts(data: Any):
    if isinstance(data, dict):
        for key in ("facts", "reports", "values"):
            for item in data.get(key, []) or []:
                if isinstance(item, dict):
                    yield item


def _collect_price_numbers(data: Any, ev: ToolEvidence) -> None:
    """주가 Tool 결과(quote/period)의 가격·시작/종료가를 근거 숫자로 수집한다.

    수익률(return_pct·change_rate_pct)은 소수 %라 큰 숫자 검증 대상이 아니므로 제외.
    가격은 정수부 문자열로 담아 답변의 '252,500원' 같은 주장과 대조한다.
    """
    if not isinstance(data, dict):
        return

    def _add(v: Any) -> None:
        if isinstance(v, (int, float)):
            ev.price_numeric_cores.add(str(int(v)))

    quote = data.get("quote")
    if isinstance(quote, dict):
        for k in ("price", "previous_close"):
            _add(quote.get(k))
    period = data.get("period")
    if isinstance(period, dict):
        for k in ("start_close", "end_close"):
            _add(period.get(k))
    # calculate_event_return 은 data 최상위에 start_close/end_close 를 둔다.
    for k in ("start_close", "end_close", "price", "previous_close"):
        if k in data:
            _add(data.get(k))


def _collect_event_evidence(payload: dict, data: Any, ev: ToolEvidence) -> None:
    """사건 기준 주가 계산 결과의 근거를 수집한다(prompt.md §6).

    basis="event" 이고 status="ok" 인 결과만 사건 근거로 인정한다. no_data(발표 후 거래일
    없음·사건 미확정)는 근거가 아니다 — 그 상태로 '이 뉴스 이후 N% 올랐다'고 쓰면 위반.
    """
    if not isinstance(data, dict):
        return
    status = payload.get("status")
    if data.get("basis") == "event":
        if status == "ok" and data.get("has_post_data"):
            ev.has_event_return = True
            eid = data.get("event_id")
            if eid:
                ev.event_ids.add(str(eid))
            edate = data.get("event_date")
            if edate:
                ev.event_dates.add(str(edate))
            for key in ("baseline_trading_day", "start_trading_day", "end_trading_day"):
                v = data.get(key)
                if v:
                    ev.event_trading_days.add(str(v))
            for h in data.get("horizons") or []:
                if isinstance(h, dict) and h.get("trading_day"):
                    ev.event_trading_days.add(str(h["trading_day"]))
        return
    # 일반 기간 수익률(get_stock_prices 의 period / lookback).
    if status == "ok":
        period = data.get("period")
        if isinstance(period, dict) and period.get("start_trading_day"):
            ev.has_period_return = True


# "이 뉴스 이후"류 사건 기반 주장 탐지(§6). 특정 인물·회사·질문 문장을 하드코딩하지 않는다.
_EVENT_CLAIM_RE = re.compile(
    r"(?:이|그|해당|본)\s*(?:뉴스|기사|소식|발표|공시|사건|이슈)\s*(?:가\s*나온\s*)?"
    r"(?:이?후|뒤|다음)|발표\s*(?:이?후|뒤)|사건\s*(?:전후|이?후)"
)
# 수익률·등락 주장(퍼센트 또는 상승/하락 표현) — 사건 주장과 결합될 때만 검사.
_MOVE_CLAIM_RE = re.compile(r"\d+(?:\.\d+)?\s*%|상승|하락|올랐|내렸|떨어졌|급등|급락")


def _has_event_claim(answer: str) -> bool:
    """답변이 '사건 이후 주가가 이렇게 됐다'는 의미를 주장하는가."""
    for sentence in _SENTENCE_SPLIT_RE.split(answer):
        if _EVENT_CLAIM_RE.search(sentence) and _MOVE_CLAIM_RE.search(sentence):
            return True
    return False


def validate_event_grounding(answer: str, evidence: ToolEvidence) -> list[str]:
    """사건 기반 주장에 필요한 근거가 모두 있는지 검증한다(prompt.md §6).

    숫자를 고치거나 보충하지 않는다. 근거가 없으면 오류만 기록한다.
    """
    if not _has_event_claim(answer):
        return []
    if evidence.has_event_return:
        errors: list[str] = []
        if not evidence.event_dates:
            errors.append("사건 이후 주가 주장에 사건 발표일 근거가 없음")
        if not evidence.event_trading_days:
            errors.append("사건 이후 주가 주장에 실제 사용 거래일 근거가 없음")
        return errors
    if evidence.has_period_return:
        return [
            "일반 기간 수익률만 근거로 있는데 답변이 '사건 이후 수익률'처럼 표현함"
            "(사건 전후 계산 결과 없음)"
        ]
    return ["사건 이후 주가 주장에 사건 전후 주가 계산 근거가 없음"]


# 날짜 표기(ISO·한국어). 연도 4자리가 재무 숫자로 오탐되지 않게 검사 전에 제거한다.
_DATE_LIKE_RE = re.compile(
    r"\d{4}\s*[-/.]\s*\d{1,2}(?:\s*[-/.]\s*\d{1,2})?"  # 2026-07-25 / 2026.7.25
    r"|\d{4}\s*년(?:\s*\d{1,2}\s*월)?(?:\s*\d{1,2}\s*일)?"  # 2026년 7월 25일
    r"|\d{4}\s*년\s*\d\s*분기"  # 2026년 3분기
)


# 종목코드 표기. 재무 주장이 아니므로 검사에서 제외한다. 6자리 가격(123456원)을 잘못
# 지우지 않도록 '종목(코드)' 문맥이 있거나 0으로 시작하는 코드형만 제외한다.
# 한국어 조사가 바로 붙으므로 \b 대신 숫자 인접만 배제한다.
_STOCK_CODE_RE = re.compile(
    # "종목코드 005930" / "005930 종목 코드" / 따옴표로 감싼 코드 / 0으로 시작하는 6자리.
    r"종목\s*코드\s*[\"'”’]?(?<![\d,.])\d{6}(?![\d,.])"
    r"|[\"'“”‘’](?<![\d,.])\d{6}(?![\d,.])[\"'”’]\s*(?:종목|코드)"
    r"|(?<![\d,.])\d{6}(?![\d,.])\s*(?:종목\s*코드|코드)"
    r"|(?<![\d,.])0\d{5}(?![\d,.])"
)
# 가정·예시 문맥의 숫자는 사실 주장이 아니다(용어 설명의 "예를 들어 15,000원에 …").
# 이런 문장은 회사 실적·목표주가를 주장하지 않으므로 숫자 근거 검증 대상에서 뺀다.
_EXAMPLE_CTX_RE = re.compile(r"(?:예를\s*들어|예시로|가령|만약|예:)")
# 페이지·건수·개수처럼 금액이 아닌 수량 표현.
_COUNT_CTX_RE = re.compile(r"\d[\d,]*\s*(?:페이지|쪽|건|개|명|회|번째)")


def _strip_non_claim_numbers(answer: str) -> str:
    """사실 주장이 아닌 숫자를 지운 사본(숫자 근거 검증용). 원문 답변은 바꾸지 않는다.

    검증 대상은 '회사 실적·목표주가·주가·금액을 사실로 주장하는 숫자'다.
    날짜·연도·종목코드·페이지·건수, 그리고 가정 예시 문장의 숫자는 제외한다
    (용어 설명의 "예를 들어 주당 15,000원에 빌린 주식을 …" 이 근거 없는 재무 숫자로
    오탐되던 운영 결함).

    Tool 결과에 없는 재무 숫자·목표주가는 계속 검증 대상으로 남는다.
    """
    kept = [s for s in _SENTENCE_SPLIT_RE.split(answer) if not _EXAMPLE_CTX_RE.search(s)]
    text = " ".join(kept)
    text = _COUNT_CTX_RE.sub(" ", text)
    return _STOCK_CODE_RE.sub(" ", _DATE_LIKE_RE.sub(" ", text))


# 이전 이름 유지(기존 테스트·호출부 호환).
_strip_dates = _strip_non_claim_numbers


def validate_answer(answer: str, evidence: ToolEvidence) -> ValidationResult:
    """답변을 근거에 대해 검증한다(SPEC §12.2). 숫자를 고치지 않고 오류만 기록."""
    errors: list[str] = []

    # 1) 존재하지 않는 인용 [n]: 근거 source 가 하나도 없는데 인용을 달면 위반
    citations = {int(m) for m in _CITATION_RE.findall(answer)}
    n_sources = len(evidence.source_ids)
    invalid = sorted(c for c in citations if c < 1 or c > max(n_sources, 0))
    if invalid:
        errors.append(f"존재하지 않는 인용 번호: {invalid} (근거 출처 {n_sources}개)")

    # 2) 숫자 주장: 답변에 큰 숫자가 있는데 재무 Tool 근거가 전혀 없으면 경고.
    #    단, stated 목표주가는 정당한 숫자 근거이므로 재무 근거 취급한다.
    #    날짜(2026-07-25·2026년 7월)의 연도는 재무 주장이 아니므로 먼저 제거한다 —
    #    사건 후보를 날짜와 함께 되묻는 답변이 오탐으로 실패하지 않게 한다.
    answer_nums = {m.replace(",", "") for m in _NUMBER_RE.findall(_strip_dates(answer))}
    big_nums = {n for n in answer_nums if len(n) >= 4}
    tp_cores = {str(v) for v in evidence.stated_target_prices}
    # 주가 Tool 결과의 가격도 정당한 숫자 근거로 인정한다.
    unsupported_big = big_nums - evidence.numeric_cores - tp_cores - evidence.price_numeric_cores
    # 뉴스·공시 본문에 실린 수치(지수 등락률·타사 주가 등)는 그 문서가 근거다. 재무·주가
    # Tool 근거가 없다는 이유로 위반 처리하지 않는다(§10 "출처 없는 수치 0건"의 대상은
    # 근거 문서 자체가 없는 경우다).
    if unsupported_big and not (
        evidence.has_financial or evidence.has_price or evidence.has_documents
    ):
        errors.append("답변에 재무성 숫자가 있으나 이를 뒷받침하는 숫자 Tool 근거가 없음")

    # 3) 증권사명 환각: 답변에 등장한 증권사가 리포트 Tool 근거에 없으면 위반(prompt.md §7)
    if evidence.has_reports:
        # 답변도 NFC 로 맞춘 뒤 추출한다(정규식 [가-힣] 은 NFD 자모를 잡지 못한다).
        answer_brokers = set(_BROKER_RE.findall(unicodedata.normalize("NFC", answer)))
        unknown = sorted(b for b in answer_brokers if _norm_name(b) not in evidence.brokers)
        if unknown:
            errors.append(f"Tool 결과에 없는 증권사를 답변에 생성함: {unknown}")

    # 4) 목표주가 환각: 답변의 '목표주가 N원' 이 stated 근거값과 일치하지 않으면 위반
    for m in _TP_CTX_RE.finditer(answer):
        raw = m.group(1)
        val = _tp_str_to_won(raw)
        if val not in evidence.stated_target_prices:
            errors.append(
                f"답변의 목표주가 {val:,}원이 구조화 근거(stated)와 일치하지 않음 "
                f"(허용값: {sorted(evidence.stated_target_prices) or '없음'})"
            )

    # 5) 사건 기반 주장 검증(prompt.md §6): "이 뉴스 이후 …% 올랐다"에 사건 근거 필수.
    errors.extend(validate_event_grounding(answer, evidence))

    return ValidationResult(ok=not errors, errors=errors)


def _is_hallucinated_sentence(sentence: str, evidence: ToolEvidence) -> bool:
    """이 문장이 근거 없는 증권사/목표주가 주장을 담고 있으면 True."""
    for b in _BROKER_RE.findall(unicodedata.normalize("NFC", sentence)):
        if _norm_name(b) not in evidence.brokers:
            return True
    for m in _TP_CTX_RE.finditer(sentence):
        raw = m.group(1)
        val = _tp_str_to_won(raw)
        if val not in evidence.stated_target_prices:
            return True
    return False


def sanitize_answer(answer: str, evidence: ToolEvidence) -> tuple[str, bool]:
    """근거 없는 증권사·목표주가 주장을 담은 문장을 제거한다(prompt.md §7).

    숫자를 다시 추측하지 않는다. 전체 답변을 실패시키지 않고, 문제 문장만 걸러
    검증된 내용만 남긴다. 목표주가 관련 문장이 지워지면 안내 문구를 덧붙인다.
    반환: (정화된 답변, 변경 여부).
    """
    if not evidence.has_reports:
        return answer, False
    # 문장 판정과 반환 문자열의 표기를 맞춘다(정규화 전후가 섞이면 비교가 어긋난다).
    answer = unicodedata.normalize("NFC", answer)
    parts = _SENTENCE_SPLIT_RE.split(answer)
    kept, removed_tp = [], False
    for s in parts:
        if s.strip() and _is_hallucinated_sentence(s, evidence):
            if _TP_CTX_RE.search(s) or "목표" in s:
                removed_tp = True
            continue
        kept.append(s)
    if len(kept) == len(parts):
        return answer, False
    cleaned = " ".join(k.strip() for k in kept if k.strip())
    if removed_tp:
        cleaned = (
            cleaned + " 일부 증권사의 구조화된 목표주가를 확인할 수 없어 해당 수치는 제외했습니다."
        ).strip()
    return cleaned, True

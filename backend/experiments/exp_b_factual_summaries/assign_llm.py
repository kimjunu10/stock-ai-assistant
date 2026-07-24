"""LLM 동일사건 배정 (하이브리드: BGE-M3 후보 검색 → Solar Pro3 판정).

기존 '유사도 >= 0.74 → 즉시 배정' 대신, company 기사에 대해:
  1. 같은 stock_code, 설정된 활성창(현재 24h) 안의 클러스터 중 임베딩 유사 후보 최대 5개 검색
  2. 후보 0개면 신규 클러스터
  3. 후보가 있으면 (새 기사 + 후보 5개 대표기사) 를 Solar Pro3 에 1회 호출
  4. Solar 가 'existing'+유효 cluster_id → 해당 클러스터 배정, 'new' → 신규
  5. 호출 실패/타임아웃/잘못된 JSON → pending_retry (임의 배정·신규 생성 금지)

임베딩 유사도·centroid 는 후보 검색·정렬에만 쓰고, 최종 배정 권한은 LLM 에 있다.
이 모듈은 Solar '요약' 기능(summarize.py)과 분리된 별도 기능이다.

market/info 기사는 이 모듈을 쓰지 않고 기존 규칙+거리 배정을 유지한다(호출자 책임).

Solar 호출은 call_fn 으로 주입 가능해 테스트에서 Mock 을 넣는다.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import requests

from . import config as CFG

# ------------------------------------------------------------------ 프롬프트
SYSTEM_PROMPT = (
    "너는 한국어 금융 뉴스의 '동일 사건' 판정기다. 새 기사가 후보 클러스터들 중 "
    "'완전히 같은 하나의 사건'을 보도한 것과 같은지 판단한다.\n"
    "판단 기준: 주체(누가), 행동(무엇을 했나), 대상·프로젝트(무엇에 대해), 발생 시점.\n"
    "규칙:\n"
    "1. 네 요소가 실질적으로 일치해야 같은 사건이다.\n"
    "2. 주제나 산업만 비슷하면(예: 같은 종목의 다른 발표, 같은 업종의 다른 회사) 다른 사건이다.\n"
    "3. 애매하면 합치지 말고 새 사건(new)으로 판정한다.\n"
    "4. 후보 중 같은 사건이 하나도 없으면 new.\n"
    '출력은 반드시 {"decision":"existing"|"new","matched_cluster_id":<cluster_id 또는 null>} '
    "형태의 JSON 하나만. 설명을 덧붙이지 않는다."
)


def build_user_prompt(article: dict, candidates: list[dict]) -> str:
    """새 기사 + 후보 대표기사(제목·description·cluster_id)로 사용자 프롬프트 구성.

    article: {title, description}
    candidates: [{cluster_id, title, description}]  (임베딩 유사도 순 정렬됨)
    """

    lines = [
        "[새 기사]",
        f"제목: {article.get('title', '')}",
        f"요약: {article.get('description', '')}",
        "",
        "[후보 클러스터] (각 클러스터의 대표 기사)",
    ]
    for c in candidates:
        lines.append(f"- cluster_id={c['cluster_id']}")
        lines.append(f"  제목: {c.get('title', '')}")
        if c.get("description"):
            lines.append(f"  요약: {c['description']}")
    lines.append("")
    lines.append(
        "새 기사가 위 후보 중 하나와 '완전히 같은 사건'이면 그 cluster_id 로 existing, "
        "아니면 new 로 판정하라."
    )
    return "\n".join(lines)


# ------------------------------------------------------------------ Solar 호출
def call_solar_assign(
    api_key: str,
    user_prompt: str,
    *,
    max_retries: int = 3,
    timeout: float = 60.0,
    system: str | None = None,
) -> tuple[dict, dict]:
    """Solar Pro 동일사건 판정 호출 → (parsed, meta). 429/5xx 지수 백오프.

    parsed: {"decision","matched_cluster_id"} (실패 시 {}).
    meta: {ok, status, latency_ms, usage, raw, parse_success}
    system: 시스템 프롬프트 override(기본은 v1 SYSTEM_PROMPT). v2 판정에 사용.
    """

    payload = {
        "model": CFG.LLM_ASSIGN_MODEL,
        "messages": [
            {"role": "system", "content": system or SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": CFG.LLM_ASSIGN_MAX_TOKENS,
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
        parsed, ok = parse_decision(raw)
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


def parse_decision(raw: str) -> tuple[dict, bool]:
    """모델 출력에서 {decision, matched_cluster_id} 추출 + 형식 검증.

    decision 은 'existing'|'new' 만 유효. existing 이면 matched_cluster_id 필수.
    유효성 실패 시 (부분dict, False).
    """

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
    decision = obj.get("decision")
    mcid = obj.get("matched_cluster_id", None)
    if decision not in ("existing", "new"):
        return {"decision": decision, "matched_cluster_id": mcid}, False
    if decision == "existing" and mcid in (None, "", "null"):
        return {"decision": decision, "matched_cluster_id": mcid}, False
    return {"decision": decision, "matched_cluster_id": mcid}, True


# ------------------------------------------------------------------ 클러스터 상태
@dataclass
class Cluster:
    cluster_id: int
    stock_code: str
    centroid: np.ndarray
    # 판정용 anchor: 클러스터 '최초 기사'의 title+description. 새 기사가 들어와도 불변.
    anchor_title: str
    anchor_description: str
    # UI용 대표 기사(anchor 와 분리 가능; 정책에 따라 갱신 가능). 기본은 anchor 와 동일.
    rep_title: str
    rep_description: str
    member_article_ids: list[str] = field(default_factory=list)
    last_active_h: float = 0.0


@dataclass
class AssignResult:
    article_id: str
    cluster_id: int | None  # 배정된 cluster_id (pending_retry 면 None)
    status: str  # 'assigned_existing' | 'assigned_new' | 'pending_retry' | 'duplicate'
    n_candidates: int = 0
    llm_called: bool = False
    reason: str = ""
    error: str | None = None  # 'invalid_response' 등(pending_retry 원인 분류)


# ------------------------------------------------------------------ 배정기
class LLMAssigner:
    """company 기사에 대한 하이브리드 배정기. 상태(클러스터·처리기록)를 들고 있다.

    call_fn(user_prompt) -> (parsed, meta) 를 주입한다. 기본은 실제 Solar 호출.
    테스트는 결정적 Mock 을 넘긴다.
    """

    def __init__(
        self,
        api_key: str = "",
        call_fn: Callable[[str], tuple[dict, dict]] | None = None,
        window_hours: float = None,  # type: ignore[assignment]
        max_candidates: int = None,  # type: ignore[assignment]
        candidate_min_sim: float = None,  # type: ignore[assignment]
        use_llm: bool = None,  # type: ignore[assignment]
    ) -> None:
        self.api_key = api_key
        self._call = call_fn or (lambda p: call_solar_assign(api_key, p))
        self.window_h = CFG.ACTIVE_WINDOW_HOURS if window_hours is None else window_hours
        self.max_cand = CFG.LLM_ASSIGN_MAX_CANDIDATES if max_candidates is None else max_candidates
        self.min_sim = (
            CFG.LLM_ASSIGN_CANDIDATE_MIN_SIM if candidate_min_sim is None else candidate_min_sim
        )
        # feature flag: False 면 기존 거리 단독 배정(유사도>=threshold 즉시)으로 롤백.
        self.use_llm = CFG.USE_LLM_ASSIGN if use_llm is None else use_llm
        self.clusters: dict[int, Cluster] = {}
        self._next_id = 1
        self._seen: dict[str, int] = {}  # article_id -> cluster_id (idempotent)
        self.calls = 0  # 총 LLM 호출 수
        self.token_usage = {"prompt": 0, "completion": 0}

    # ---- 후보 검색 (임베딩만; 정렬용) ----
    def _find_candidates(
        self, stock_code: str, vec: np.ndarray, t_h: float
    ) -> list[tuple[float, Cluster]]:
        out = []
        for cl in self.clusters.values():
            if cl.stock_code != stock_code:
                continue
            if t_h - cl.last_active_h > self.window_h:
                continue
            sim = float(np.dot(vec, cl.centroid))
            if sim >= self.min_sim:
                out.append((sim, cl))
        out.sort(key=lambda x: -x[0])
        return out[: self.max_cand]

    def _new_cluster(self, stock_code: str, vec: np.ndarray, art: dict, t_h: float) -> int:
        cid = self._next_id
        self._next_id += 1
        title = art.get("title", "")
        desc = art.get("description", "")
        self.clusters[cid] = Cluster(
            cluster_id=cid,
            stock_code=stock_code,
            centroid=vec.copy(),
            anchor_title=title,  # 최초 기사 = 고정 anchor (이후 불변)
            anchor_description=desc,
            rep_title=title,  # UI 대표(분리 가능)
            rep_description=desc,
            member_article_ids=[art["article_id"]],
            last_active_h=t_h,
        )
        return cid

    def _add_to_cluster(self, cid: int, vec: np.ndarray, art: dict, t_h: float) -> None:
        cl = self.clusters[cid]
        n = len(cl.member_article_ids)
        cen = (cl.centroid * n + vec) / (n + 1)
        nrm = np.linalg.norm(cen)
        cl.centroid = cen / nrm if nrm else cen
        cl.member_article_ids.append(art["article_id"])
        cl.last_active_h = max(cl.last_active_h, t_h)

    def assign(self, art: dict, vec: np.ndarray, t_h: float) -> AssignResult:
        """company 기사 하나를 배정. art: {article_id, stock_code, title, description}.

        vec 는 L2 정규화된 임베딩, t_h 는 published_at 의 시각(시간 단위).
        idempotent: 같은 article_id 를 다시 넣으면 재배정 없이 duplicate 반환.
        """

        aid = art["article_id"]
        if aid in self._seen:
            return AssignResult(aid, self._seen[aid], "duplicate", reason="already processed")

        stock = art["stock_code"]

        # feature flag OFF → 기존 거리 단독 배정(유사도>=threshold 즉시, LLM 미호출).
        if not self.use_llm:
            best = None
            best_sim = CFG.COSINE_THRESHOLD
            for cl in self.clusters.values():
                if cl.stock_code != stock or t_h - cl.last_active_h > self.window_h:
                    continue
                sim = float(np.dot(vec, cl.centroid))
                if sim >= best_sim:
                    best_sim, best = sim, cl
            if best is None:
                cid = self._new_cluster(stock, vec, art, t_h)
                self._seen[aid] = cid
                return AssignResult(aid, cid, "assigned_new", 0, False, "distance: new")
            self._add_to_cluster(best.cluster_id, vec, art, t_h)
            self._seen[aid] = best.cluster_id
            return AssignResult(
                aid, best.cluster_id, "assigned_existing", 1, False, "distance: >=threshold"
            )

        cands = self._find_candidates(stock, vec, t_h)

        # 후보 없음 → 신규 (LLM 호출 안 함)
        if not cands:
            cid = self._new_cluster(stock, vec, art, t_h)
            self._seen[aid] = cid
            return AssignResult(aid, cid, "assigned_new", 0, False, "no candidates")

        # 판정에는 anchor(최초 기사)의 title+description 만 전달(정책 3).
        cand_payload = [
            {
                "cluster_id": cl.cluster_id,
                "title": cl.anchor_title,
                "description": cl.anchor_description,
            }
            for _sim, cl in cands
        ]
        valid_ids = {c["cluster_id"] for c in cand_payload}
        prompt = build_user_prompt(art, cand_payload)

        parsed, meta = self._call(prompt)
        self.calls += 1
        if meta.get("usage"):
            self.token_usage["prompt"] += meta["usage"].get("prompt_tokens", 0)
            self.token_usage["completion"] += meta["usage"].get("completion_tokens", 0)

        # 통신 실패/타임아웃 → pending_retry (재시도 가능하게 seen 에 안 넣음)
        if not meta.get("ok"):
            return AssignResult(
                aid,
                None,
                "pending_retry",
                len(cands),
                True,
                reason="llm transport fail",
                error="transport_error",
            )

        # 응답 자체가 잘못된 모든 경우(잘못된 JSON·필수필드 누락·decision 오류·
        # 후보에 없는 cluster_id) → invalid_response → pending_retry.
        # 이 경우 배정도, 신규 생성도 하지 않는다(정책 1).
        decision = parsed.get("decision")
        mcid = parsed.get("matched_cluster_id")

        def _invalid(why: str) -> AssignResult:
            return AssignResult(
                aid, None, "pending_retry", len(cands), True, reason=why, error="invalid_response"
            )

        # parse_decision 이 형식 검증 실패로 표시(잘못된 JSON·필드 누락·decision 오류)
        if not meta.get("parse_success"):
            return _invalid(f"invalid response (decision={decision!r}, mcid={mcid!r})")

        if decision == "existing":
            try:
                mcid_int = int(mcid)
            except (TypeError, ValueError):
                return _invalid(f"matched_cluster_id not int: {mcid!r}")
            if mcid_int not in valid_ids:
                # 후보에 없는 cluster_id(환각) → invalid_response(신규 생성 금지)
                return _invalid(f"matched_cluster_id not in candidates: {mcid_int}")
            self._add_to_cluster(mcid_int, vec, art, t_h)
            self._seen[aid] = mcid_int
            return AssignResult(
                aid, mcid_int, "assigned_existing", len(cands), True, "llm existing"
            )

        if decision == "new":
            cid = self._new_cluster(stock, vec, art, t_h)
            self._seen[aid] = cid
            return AssignResult(aid, cid, "assigned_new", len(cands), True, "llm new")

        # 여기 도달하면 decision 값 오류(위 parse_success 로 대부분 걸러지나 방어적)
        return _invalid(f"decision invalid: {decision!r}")

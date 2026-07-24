"""뉴스 처리 v2: 동일사건 배정 (event_signature 비교 포함).

기존 assign_llm.LLMAssigner 를 건드리지 않고 v2 정책을 별도 구현한다.
정책(prompt.md v2):
  - BGE-M3 로 같은 종목·시간창 후보를 찾고, 최종 existing/new 는 Solar 가 판정.
  - 같은 회사·산업·키워드만으로 병합하지 않는다. 실제 같은 발표/발생 사건만 병합.
  - 후보에는 최초 기사만이 아니라 다음을 전달한다:
      클러스터 event_signature / 최초 기사 / 대표 기사 / 최근 기사 최대 2개.
  - 새 기사와 후보의 event_signature(주체·행동·대상·제품·시점·금액·식별자)가
    충돌하면 새 클러스터를 만든다.
  - 실패·환각·후보밖 id → pending_retry (임의 배정·신규 생성 금지).

BGE-M3 후보검색·centroid 갱신은 검증된 assign_llm 과 동일하게 유지한다.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from . import config as CFG
from .assign_llm import call_solar_assign

logger = logging.getLogger(__name__)

ASSIGN_V2_PROMPT_VERSION = "same_event_sig_v5_multiprototype"

SYSTEM_PROMPT_V2 = (
    "너는 한국어 금융 뉴스의 '동일 사건' 판정기다. 새 기사가 후보 클러스터들 중 "
    "'같은 하나의 사건'을 보도한 것과 같은지 판단한다. 여러 언론사가 같은 사건을 "
    "서로 다른 제목·강조점·수치 표현으로 보도하는 것이 정상임을 전제로 한다.\n"
    "핵심 판단 기준 — 아래 요소를 모두 비교한다:\n"
    "  · 주체(누가): 발표·발언·결정을 한 사람/기관/회사\n"
    "  · 행동(무엇을 했나): 발표·지시·투자·계약·실적발표 등 사건의 행위\n"
    "  · 대상(무엇에 대해): 그 행동이 향한 제품·프로젝트·정책·상대방\n"
    "  · 사건 정체성: 행사명, 주최·초청 주체, 행사 형태, 개최 목적\n"
    "규칙:\n"
    "1. 주체·행동·대상과 사건 정체성이 실질적으로 일치하면 existing 으로 판정한다. "
    "같은 발표·발언·사건을 다룬 기사면 제목 표현, 강조하는 세부 수치, 금액·인용문 "
    "차이는 무시한다(같은 사건의 다른 보도 각도일 뿐이다).\n"
    "2. 같은 회사·인물·산업·키워드·날짜·도시가 겹쳐도 행사명, 주최 주체, 행사 형태나 "
    "개최 목적이 다르면 반드시 new 로 판정한다. 참석자 일부가 같다는 사실만으로는 "
    "동일 사건의 증거가 아니다.\n"
    "3. 같은 회사·같은 산업·같은 키워드일 뿐 서로 다른 발표/사건이면 new 로 판정한다. "
    "예: 같은 회사의 '실적 발표'와 '공장 증설 발표'는 다른 사건이다.\n"
    "4. 서로 다른 시점의 명백히 별개인 사건은 new 다. 단, 같은 사건에 대한 후속·"
    "반응 보도(같은 발언의 추가 보도, 같은 발표에 대한 시장 반응)는 existing 으로 본다.\n"
    "5. 같은 일정이나 연속 행사에 포함돼도 실제 발생 행위가 다르면 별도 사건일 수 있다. "
    "반대로 하나의 발표·출발·계약·실적발표를 기사마다 다른 의제나 참석자 중심으로 "
    "강조한 것이라면 같은 사건이다.\n"
    "6. 핵심 요소와 사건 정체성이 같은데 기사별 강조점과 세부만 다를 때는 existing 을 "
    "우선한다. "
    "후보 중 같은 사건이 하나도 없을 때만 new 로 판정한다.\n"
    '출력은 반드시 {"decision":"existing"|"new","matched_cluster_id":<cluster_id 또는 null>} '
    "형태의 JSON 하나만. 설명을 덧붙이지 않는다."
)


def _sig_line(sig: dict | None) -> str:
    if not sig:
        return "  event_signature: (없음)"
    parts = []
    for k in ("subject", "action", "object", "product_or_project", "amount", "event_date"):
        v = sig.get(k)
        if v:
            parts.append(f"{k}={v}")
    ids = sig.get("identifiers") or []
    if ids:
        parts.append(f"identifiers={','.join(map(str, ids))}")
    return "  event_signature: " + ("; ".join(parts) if parts else "(비어있음)")


def build_user_prompt_v2(article: dict, candidates: list[dict]) -> str:
    """새 기사(제목·요약·event_signature) + 후보별 상세(시그니처/최초/대표/최근2)."""

    lines = [
        "[새 기사]",
        f"제목: {article.get('title', '')}",
        f"요약: {article.get('description', '')}",
        _sig_line(article.get("event_signature")),
        "",
        "[후보 클러스터]",
    ]
    for c in candidates:
        lines.append(f"- cluster_id={c['cluster_id']}")
        lines.append(_sig_line(c.get("event_signature")))
        lines.append(
            f"  최초 기사: {c.get('anchor_title', '')} / {c.get('anchor_description', '')}"
        )
        if c.get("rep_title"):
            lines.append(f"  대표 기사: {c.get('rep_title', '')} / {c.get('rep_description', '')}")
        for i, recent in enumerate(c.get("recent", [])[:2], 1):
            lines.append(
                f"  최근 기사{i}: {recent.get('title', '')} / {recent.get('description', '')}"
            )
    lines.append("")
    lines.append(
        "새 기사의 주체·행동·대상뿐 아니라 행사명, 주최·초청 주체, 행사 형태와 목적까지 "
        "후보와 비교하라. 제목 표현이나 기사별 강조 의제, 세부 수치·금액만 다르고 동일한 "
        "발표·발언·행사라면 existing 이다. 인물·날짜·장소·산업만 겹치고 실제 행위와 행사 "
        "정체성이 다르면 new 다. 같은 사건이 후보에 없을 때도 new 다."
    )
    return "\n".join(lines)


_SIGNATURE_FIELDS = (
    ("subject", 0.25),
    ("action", 0.25),
    ("object", 0.15),
    ("product_or_project", 0.20),
    ("event_date", 0.10),
    ("identifiers", 0.05),
)
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


def _normalise_signature_value(value: object) -> str:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    return " ".join(_TOKEN_RE.findall(str(value or "").lower()))


def _value_similarity(left: object, right: object) -> float:
    a = _normalise_signature_value(left)
    b = _normalise_signature_value(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        return 0.9
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    return len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))


def signature_similarity(left: dict | None, right: dict | None) -> tuple[float, int]:
    """Return comparable-field weighted similarity and meaningful match count.

    The score is used only to recover candidate recall. Solar remains the final
    same-event judge, so a structured match never forces an automatic merge.
    """

    if not left or not right:
        return 0.0, 0
    weighted = 0.0
    denominator = 0.0
    matches = 0
    for field_name, weight in _SIGNATURE_FIELDS:
        left_value = left.get(field_name)
        right_value = right.get(field_name)
        if not left_value or not right_value:
            continue
        similarity = _value_similarity(left_value, right_value)
        weighted += similarity * weight
        denominator += weight
        if similarity >= 0.5:
            matches += 1
    if not denominator:
        return 0.0, 0
    return weighted / denominator, matches


@dataclass
class ClusterV2:
    cluster_id: int
    stock_code: str
    centroid: np.ndarray
    anchor_title: str
    anchor_description: str
    rep_title: str
    rep_description: str
    event_signature: dict | None = None
    recent: list[dict] = field(default_factory=list)  # 최근 기사 [{title, description}]
    # 후보 검색용 실제 기사 벡터. centroid 하나의 평균화 손실을 보완한다.
    prototype_vectors: list[np.ndarray] = field(default_factory=list)
    member_article_ids: list[str] = field(default_factory=list)
    last_active_h: float = 0.0


@dataclass(frozen=True)
class CandidateV2:
    cluster: ClusterV2
    centroid_similarity: float
    prototype_similarity: float
    signature_similarity: float
    signature_matches: int

    @property
    def dense_similarity(self) -> float:
        return max(self.centroid_similarity, self.prototype_similarity)

    @property
    def rank_score(self) -> float:
        # Structured identity can recover a semantically shifted article, but it
        # does not itself merge anything. The LLM receives and judges the candidate.
        return max(self.dense_similarity, self.signature_similarity * 0.92)

    def debug_payload(self) -> dict:
        return {
            "cluster_id": self.cluster.cluster_id,
            "centroid": round(self.centroid_similarity, 4),
            "prototype": round(self.prototype_similarity, 4),
            "signature": round(self.signature_similarity, 4),
            "signature_matches": self.signature_matches,
            "rank": round(self.rank_score, 4),
        }


@dataclass
class AssignResultV2:
    article_id: str
    cluster_id: int | None
    status: str  # assigned_existing | assigned_new | pending_retry | duplicate
    n_candidates: int = 0
    llm_called: bool = False
    reason: str = ""
    error: str | None = None
    candidates: tuple[dict, ...] = ()


class LLMAssignerV2:
    """v2 동일사건 배정기. event_signature 를 후보와 함께 Solar 에 전달한다."""

    def __init__(
        self,
        api_key: str = "",
        call_fn: Callable[[str], tuple[dict, dict]] | None = None,
        window_hours: float | None = None,
        max_candidates: int | None = None,
        candidate_min_sim: float | None = None,
    ) -> None:
        self.api_key = api_key
        self._call = call_fn or (lambda p: call_solar_assign(api_key, p, system=SYSTEM_PROMPT_V2))
        self.window_h = CFG.ACTIVE_WINDOW_HOURS if window_hours is None else window_hours
        self.max_cand = CFG.LLM_ASSIGN_MAX_CANDIDATES if max_candidates is None else max_candidates
        self.min_sim = (
            CFG.LLM_ASSIGN_CANDIDATE_MIN_SIM if candidate_min_sim is None else candidate_min_sim
        )
        self.clusters: dict[int, ClusterV2] = {}
        self._next_id = 1
        self._seen: dict[str, int] = {}
        self.calls = 0
        self.token_usage = {"prompt": 0, "completion": 0}

    def _find_candidates(
        self,
        stock_code: str,
        vec: np.ndarray,
        t_h: float,
        event_signature: dict | None,
    ) -> list[CandidateV2]:
        dense_candidates: list[CandidateV2] = []
        signature_candidates: list[CandidateV2] = []
        for cl in self.clusters.values():
            if cl.stock_code != stock_code:
                continue
            if t_h - cl.last_active_h > self.window_h:
                continue
            centroid_sim = float(np.dot(vec, cl.centroid))
            prototype_sim = max(
                (float(np.dot(vec, prototype)) for prototype in cl.prototype_vectors),
                default=-1.0,
            )
            signature_sim, signature_matches = signature_similarity(
                event_signature, cl.event_signature
            )
            candidate = CandidateV2(
                cluster=cl,
                centroid_similarity=centroid_sim,
                prototype_similarity=prototype_sim,
                signature_similarity=signature_sim,
                signature_matches=signature_matches,
            )
            if candidate.dense_similarity >= self.min_sim:
                dense_candidates.append(candidate)
            if signature_sim >= 0.55 and signature_matches >= 2:
                signature_candidates.append(candidate)

        dense_candidates.sort(key=lambda item: -item.dense_similarity)
        signature_candidates.sort(key=lambda item: -item.signature_similarity)

        # Preserve three semantic-retrieval slots and reserve up to two slots for
        # structured event identity. This avoids one signal crowding out the other.
        selected: dict[int, CandidateV2] = {}
        dense_slots = max(1, self.max_cand - min(2, self.max_cand))
        for candidate in dense_candidates[:dense_slots]:
            selected[candidate.cluster.cluster_id] = candidate
        for candidate in signature_candidates[: min(2, self.max_cand)]:
            if len(selected) >= self.max_cand:
                break
            selected[candidate.cluster.cluster_id] = candidate

        remaining = sorted(
            [*dense_candidates, *signature_candidates],
            key=lambda item: -item.rank_score,
        )
        for candidate in remaining:
            if len(selected) >= self.max_cand:
                break
            selected.setdefault(candidate.cluster.cluster_id, candidate)
        return sorted(selected.values(), key=lambda item: -item.rank_score)

    def _new_cluster(self, stock_code: str, vec: np.ndarray, art: dict, t_h: float) -> int:
        cid = self._next_id
        self._next_id += 1
        title = art.get("title", "")
        desc = art.get("description", "")
        self.clusters[cid] = ClusterV2(
            cluster_id=cid,
            stock_code=stock_code,
            centroid=vec.copy(),
            anchor_title=title,
            anchor_description=desc,
            rep_title=title,
            rep_description=desc,
            event_signature=art.get("event_signature"),
            recent=[{"title": title, "description": desc}],
            prototype_vectors=[vec.copy()],
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
        # 대표 기사 = 가장 최근 기사(시간순 처리이므로 현재 기사), 최근 목록 갱신.
        cl.rep_title = art.get("title", "")
        cl.rep_description = art.get("description", "")
        cl.recent.append({"title": art.get("title", ""), "description": art.get("description", "")})
        cl.recent = cl.recent[-2:]
        cl.prototype_vectors.append(vec.copy())
        # Keep the immutable anchor plus the three most recent article vectors.
        if len(cl.prototype_vectors) > 4:
            cl.prototype_vectors = [cl.prototype_vectors[0], *cl.prototype_vectors[-3:]]

    def assign(self, art: dict, vec: np.ndarray, t_h: float) -> AssignResultV2:
        aid = art["article_id"]
        if aid in self._seen:
            return AssignResultV2(aid, self._seen[aid], "duplicate", reason="already processed")
        stock = art["stock_code"]

        cands = self._find_candidates(stock, vec, t_h, art.get("event_signature"))
        candidate_debug = tuple(candidate.debug_payload() for candidate in cands)
        logger.info(
            "NEWS_CLUSTER_CANDIDATES article_id=%s stock_code=%s candidates=%s",
            aid,
            stock,
            json.dumps(candidate_debug, ensure_ascii=False, separators=(",", ":")),
        )
        if not cands:
            cid = self._new_cluster(stock, vec, art, t_h)
            self._seen[aid] = cid
            logger.info(
                "NEWS_CLUSTER_DECISION article_id=%s stock_code=%s decision=new "
                "matched_cluster_id=null candidate_count=0 reason=no_candidates",
                aid,
                stock,
            )
            return AssignResultV2(
                aid,
                cid,
                "assigned_new",
                0,
                False,
                "no candidates",
                candidates=candidate_debug,
            )

        cand_payload = [
            {
                "cluster_id": cl.cluster_id,
                "event_signature": cl.event_signature,
                "anchor_title": cl.anchor_title,
                "anchor_description": cl.anchor_description,
                "rep_title": cl.rep_title,
                "rep_description": cl.rep_description,
                "recent": cl.recent,
            }
            for candidate in cands
            for cl in [candidate.cluster]
        ]
        valid_ids = {c["cluster_id"] for c in cand_payload}
        prompt = build_user_prompt_v2(art, cand_payload)

        parsed, meta = self._call(prompt)
        self.calls += 1
        if meta.get("usage"):
            self.token_usage["prompt"] += meta["usage"].get("prompt_tokens", 0)
            self.token_usage["completion"] += meta["usage"].get("completion_tokens", 0)

        if not meta.get("ok"):
            return AssignResultV2(
                aid,
                None,
                "pending_retry",
                len(cands),
                True,
                reason="llm transport fail",
                error="transport_error",
                candidates=candidate_debug,
            )

        decision = parsed.get("decision")
        mcid = parsed.get("matched_cluster_id")

        def _invalid(why: str) -> AssignResultV2:
            return AssignResultV2(
                aid,
                None,
                "pending_retry",
                len(cands),
                True,
                reason=why,
                error="invalid_response",
                candidates=candidate_debug,
            )

        if not meta.get("parse_success"):
            return _invalid(f"invalid response (decision={decision!r}, mcid={mcid!r})")

        if decision == "existing":
            try:
                mcid_int = int(mcid)
            except (TypeError, ValueError):
                return _invalid(f"matched_cluster_id not int: {mcid!r}")
            if mcid_int not in valid_ids:
                return _invalid(f"matched_cluster_id not in candidates: {mcid_int}")
            self._add_to_cluster(mcid_int, vec, art, t_h)
            self._seen[aid] = mcid_int
            logger.info(
                "NEWS_CLUSTER_DECISION article_id=%s stock_code=%s decision=existing "
                "matched_cluster_id=%s candidate_count=%d",
                aid,
                stock,
                mcid_int,
                len(cands),
            )
            return AssignResultV2(
                aid,
                mcid_int,
                "assigned_existing",
                len(cands),
                True,
                "llm existing",
                candidates=candidate_debug,
            )

        if decision == "new":
            cid = self._new_cluster(stock, vec, art, t_h)
            self._seen[aid] = cid
            logger.info(
                "NEWS_CLUSTER_DECISION article_id=%s stock_code=%s decision=new "
                "matched_cluster_id=null candidate_count=%d",
                aid,
                stock,
                len(cands),
            )
            return AssignResultV2(
                aid,
                cid,
                "assigned_new",
                len(cands),
                True,
                "llm new",
                candidates=candidate_debug,
            )

        return _invalid(f"decision invalid: {decision!r}")


__all__ = [
    "LLMAssignerV2",
    "ClusterV2",
    "AssignResultV2",
    "build_user_prompt_v2",
    "SYSTEM_PROMPT_V2",
    "ASSIGN_V2_PROMPT_VERSION",
    "signature_similarity",
]

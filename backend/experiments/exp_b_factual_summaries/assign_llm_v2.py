"""뉴스 처리 v2: 동일사건 배정 (event_signature 비교 포함).

기존 assign_llm.LLMAssigner 를 건드리지 않고 v2 정책을 별도 구현한다.
정책(prompt.md v2):
  - BGE-M3 로 같은 종목·시간창 후보를 찾는다.
  - dense cosine 유사도가 0.85를 초과하면 가장 유사한 후보에 즉시 병합한다.
  - 0.85 이하의 애매한 후보만 최종 existing/new 를 Solar 가 판정한다.
  - 같은 회사·산업·키워드만으로 병합하지 않는다. 제목상 같은 이슈 흐름과 직접
    후속 보도만 병합한다.
  - 후보에는 최초 기사만이 아니라 다음을 전달한다:
      단순 event_signature / 최초 제목 / 대표 제목 / 최근 제목 최대 2개.
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
from .classify_role import normalize_event_signature

logger = logging.getLogger(__name__)

ASSIGN_V2_PROMPT_VERSION = "same_story_title_v6_multiprototype"

SYSTEM_PROMPT_V2 = (
    "너는 한국어 금융 뉴스의 '같은 이슈 흐름' 판정기다. 새 기사 제목이 후보 "
    "클러스터의 제목들과 같은 핵심 사건 또는 그 사건의 직접 후속 보도인지 판단한다. "
    "검색 결과 요약과 본문은 신뢰하지 않고 제목과 단순 사건 정보만 사용한다.\n"
    "핵심 판단 기준:\n"
    "  · 핵심 주체: 사건의 중심 인물·기관·회사\n"
    "  · 핵심 사건 주제: 무엇에 관한 이슈인지\n"
    "  · 고유 식별어: 금액·계약명·제품명·행사명 등\n"
    "  · 이슈 관계: 최초 사건, 그 사건의 후속 조치, 반응·영향 보도\n"
    "규칙:\n"
    "1. 핵심 주제와 고유 식별어가 같으면 기사별 표현과 강조점이 달라도 existing 이다.\n"
    "2. 최초 사건에서 직접 이어진 후속 조치·자금 마련·공식 반응·시장 영향은 같은 "
    "이슈의 연속 보도이므로 existing 이다. 예: '9440억원 재산분할 판결'과 "
    "'9440억원 마련을 위한 지분 활용 검토'.\n"
    "3. 같은 회사·인물·산업·날짜만 겹치고 핵심 주제나 고유 식별어가 다르면 new 다.\n"
    "4. 같은 순방이나 행사 일정이어도 별개의 회동·발표라면 new 다. 반대로 같은 출발·"
    "회동·발표를 참석자나 의제만 달리 강조한 제목은 existing 이다.\n"
    "5. 제목만으로 직접 연결을 확인할 수 없으면 억지로 합치지 말고 new 로 판정한다. "
    "후보 중 같은 사건이 하나도 없을 때만 new 로 판정한다.\n"
    '출력은 반드시 {"decision":"existing"|"new","matched_cluster_id":<cluster_id 또는 null>} '
    "형태의 JSON 하나만. 설명을 덧붙이지 않는다."
)


def _sig_line(sig: dict | None) -> str:
    normalized = normalize_event_signature(sig)
    if not normalized.get("core_subjects") and not normalized.get("core_topic"):
        return "  event_signature: (없음)"
    parts = []
    subjects = normalized.get("core_subjects") or []
    if subjects:
        parts.append(f"core_subjects={','.join(map(str, subjects))}")
    if normalized.get("core_topic"):
        parts.append(f"core_topic={normalized['core_topic']}")
    anchors = normalized.get("unique_anchors") or []
    if anchors:
        parts.append(f"unique_anchors={','.join(map(str, anchors))}")
    parts.append(f"story_relation={normalized.get('story_relation', 'unknown')}")
    return "  event_signature: " + ("; ".join(parts) if parts else "(비어있음)")


def build_user_prompt_v2(article: dict, candidates: list[dict]) -> str:
    """새 제목과 후보 클러스터 제목들만으로 동일 이슈를 판정한다."""

    lines = [
        "[새 기사]",
        f"제목: {article.get('title', '')}",
        _sig_line(article.get("event_signature")),
        "",
        "[후보 클러스터]",
    ]
    for c in candidates:
        lines.append(f"- cluster_id={c['cluster_id']}")
        lines.append(_sig_line(c.get("event_signature")))
        lines.append(f"  최초 제목: {c.get('anchor_title', '')}")
        if c.get("rep_title"):
            lines.append(f"  대표 제목: {c.get('rep_title', '')}")
        for i, recent in enumerate(c.get("recent", [])[:2], 1):
            lines.append(f"  최근 제목{i}: {recent.get('title', '')}")
    lines.append("")
    lines.append(
        "제목의 핵심 주체·핵심 사건 주제·고유 식별어를 후보 제목들과 비교하라. 같은 "
        "사건의 후속 조치나 반응이면 existing, 단순히 인물·회사·산업만 같으면 new 다."
    )
    return "\n".join(lines)


_SIGNATURE_FIELDS = (
    ("core_subjects", 0.30),
    ("core_topic", 0.35),
    ("unique_anchors", 0.35),
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

    left = normalize_event_signature(left)
    right = normalize_event_signature(right)
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

        # 명확히 가까운 후보는 LLM의 보수적인 new 판정으로 쪼개지지 않도록 즉시
        # 병합한다. centroid와 prototype 중 더 높은 BGE-M3 cosine을 사용하되,
        # 여러 후보가 기준을 넘으면 dense cosine이 가장 높은 하나를 선택한다.
        auto_candidate = max(cands, key=lambda candidate: candidate.dense_similarity)
        auto_similarity = auto_candidate.dense_similarity
        if auto_similarity > CFG.LLM_ASSIGN_AUTO_MERGE_MIN_SIM:
            cid = auto_candidate.cluster.cluster_id
            self._add_to_cluster(cid, vec, art, t_h)
            self._seen[aid] = cid
            logger.info(
                "NEWS_CLUSTER_DECISION article_id=%s stock_code=%s decision=existing "
                "matched_cluster_id=%s candidate_count=%d reason=auto_dense_similarity "
                "dense_similarity=%.4f threshold=%.2f",
                aid,
                stock,
                cid,
                len(cands),
                auto_similarity,
                CFG.LLM_ASSIGN_AUTO_MERGE_MIN_SIM,
            )
            return AssignResultV2(
                aid,
                cid,
                "assigned_existing",
                len(cands),
                False,
                (
                    f"auto dense similarity {auto_similarity:.4f} > "
                    f"{CFG.LLM_ASSIGN_AUTO_MERGE_MIN_SIM:.2f}"
                ),
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

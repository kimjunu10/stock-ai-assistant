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

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from . import config as CFG
from .assign_llm import call_solar_assign

ASSIGN_V2_PROMPT_VERSION = "same_event_sig_v3_core"

SYSTEM_PROMPT_V2 = (
    "너는 한국어 금융 뉴스의 '동일 사건' 판정기다. 새 기사가 후보 클러스터들 중 "
    "'같은 하나의 사건'을 보도한 것과 같은지 판단한다. 여러 언론사가 같은 사건을 "
    "서로 다른 제목·강조점·수치 표현으로 보도하는 것이 정상임을 전제로 한다.\n"
    "핵심 판단 기준 — 아래 3요소가 같으면 같은 사건이다:\n"
    "  · 주체(누가): 발표·발언·결정을 한 사람/기관/회사\n"
    "  · 행동(무엇을 했나): 발표·지시·투자·계약·실적발표 등 사건의 행위\n"
    "  · 대상(무엇에 대해): 그 행동이 향한 제품·프로젝트·정책·상대방\n"
    "규칙:\n"
    "1. 핵심 3요소(주체·행동·대상)가 실질적으로 일치하면 existing 으로 판정한다. "
    "같은 발표·발언·사건을 다룬 기사면 제목 표현, 강조하는 세부 수치, 금액·인용문 "
    "차이는 무시한다(같은 사건의 다른 보도 각도일 뿐이다).\n"
    "2. 같은 회사·같은 산업·같은 키워드일 뿐 서로 다른 발표/사건이면 new 로 판정한다. "
    "예: 같은 회사의 '실적 발표'와 '공장 증설 발표'는 다른 사건이다.\n"
    "3. 서로 다른 시점의 명백히 별개인 사건은 new 다. 단, 같은 사건에 대한 후속·"
    "반응 보도(같은 발언의 추가 보도, 같은 발표에 대한 시장 반응)는 existing 으로 본다.\n"
    "4. 핵심 3요소가 같은데 세부만 다를 때는 existing 을 우선한다(과도하게 쪼개지 않는다).\n"
    "5. 후보 중 같은 사건이 하나도 없을 때만 new.\n"
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
        "새 기사의 핵심 3요소(주체·행동·대상)가 위 후보 중 하나와 실질적으로 같으면 "
        "그 cluster_id 로 existing 으로 판정하라. 제목 표현이나 세부 수치·금액이 달라도 "
        "같은 발표·발언·사건이면 existing 이다. 핵심 3요소가 다른 별개의 사건이거나 "
        "같은 사건이 후보에 없을 때만 new 로 판정하라."
    )
    return "\n".join(lines)


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
    member_article_ids: list[str] = field(default_factory=list)
    last_active_h: float = 0.0


@dataclass
class AssignResultV2:
    article_id: str
    cluster_id: int | None
    status: str  # assigned_existing | assigned_new | pending_retry | duplicate
    n_candidates: int = 0
    llm_called: bool = False
    reason: str = ""
    error: str | None = None


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
        self, stock_code: str, vec: np.ndarray, t_h: float
    ) -> list[tuple[float, ClusterV2]]:
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

    def assign(self, art: dict, vec: np.ndarray, t_h: float) -> AssignResultV2:
        aid = art["article_id"]
        if aid in self._seen:
            return AssignResultV2(aid, self._seen[aid], "duplicate", reason="already processed")
        stock = art["stock_code"]

        cands = self._find_candidates(stock, vec, t_h)
        if not cands:
            cid = self._new_cluster(stock, vec, art, t_h)
            self._seen[aid] = cid
            return AssignResultV2(aid, cid, "assigned_new", 0, False, "no candidates")

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
            for _sim, cl in cands
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
            )

        decision = parsed.get("decision")
        mcid = parsed.get("matched_cluster_id")

        def _invalid(why: str) -> AssignResultV2:
            return AssignResultV2(
                aid, None, "pending_retry", len(cands), True, reason=why, error="invalid_response"
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
            return AssignResultV2(
                aid, mcid_int, "assigned_existing", len(cands), True, "llm existing"
            )

        if decision == "new":
            cid = self._new_cluster(stock, vec, art, t_h)
            self._seen[aid] = cid
            return AssignResultV2(aid, cid, "assigned_new", len(cands), True, "llm new")

        return _invalid(f"decision invalid: {decision!r}")


__all__ = [
    "LLMAssignerV2",
    "ClusterV2",
    "AssignResultV2",
    "build_user_prompt_v2",
    "SYSTEM_PROMPT_V2",
    "ASSIGN_V2_PROMPT_VERSION",
]

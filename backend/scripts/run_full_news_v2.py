"""뉴스 처리 v2 단일 실행: 역할분류 → 클러스터링 → 요약 → 검사 → 활성화.

한 번의 명령으로 전체 relevant 데이터를 v2 로 재처리한다. 기존 v1(clustering_version
!= V2_VERSION)은 수정·삭제하지 않고, 모든 단계가 성공한 뒤에만 API 읽기 버전을 v2 로
전환한다. 같은 --run-key 로 재실행하면 완료된 부분(역할분류 캐시·v2 배정·성공 요약)을
건너뛰고 이어서 처리한다.

정책 요약(prompt.md v2):
  - 실제 회사 사건(company_event, event_eligible=true)만 v2 동일사건 클러스터링.
  - 사건이 아닌 relevant 기사는 클러스터/요약을 만들지 않고 related_articles 로 노출
    (API 가 event_eligible=false 를 개별 기사로 반환. 이 스크립트는 클러스터링 대상에서
     제외하는 것으로 충분하며 별도 저장이 필요 없다).
  - 미처리·pending·요약실패가 남으면 v2 를 활성화하지 않는다.

사용:
    uv run python -m scripts.run_full_news_v2 \\
      --run-key full-news-v2-20260721 --workers 4 --execute --activate
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from app.core.config import settings
from app.db.client import create_supabase_client, get_supabase_client
from app.repositories.news_v2 import V2_VERSION, NewsV2Repository
from app.services.news_clustering import BgeM3Embedder
from experiments.exp_b_factual_summaries import assign_llm_v2, classify_role, summarize
from experiments.exp_b_factual_summaries import config as CFG

logger = logging.getLogger("run_full_news_v2")


def _hours(value: str) -> float:
    from datetime import datetime

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.timestamp() / 3600.0


def _save_with_retry(
    repo: NewsV2Repository, article_id: int, stock_code: str, result: dict
) -> None:
    """Supabase 저장의 일시적 네트워크 오류(SSL/connect timeout)를 몇 차례 재시도."""
    import time

    last: Exception | None = None
    for attempt in range(4):
        try:
            repo.save_role(article_id, stock_code, result)
            return
        except Exception as exc:  # noqa: BLE001 - 일시 네트워크 오류 재시도
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"save_role failed after retries: {last}")


def phase_roles(repo: NewsV2Repository, totals: dict, workers: int) -> list[dict]:
    """1) 전체 relevant pair 역할 분류(규칙 게이트 → LLM). 결과를 article_stocks 에 저장.

    pair 는 독립이고 저장이 pair 단위 upsert 라 워커 병렬 처리한다. 각 워커는 자기
    supabase client 로 별도 repo 를 쓴다(스레드 안전). 규칙 게이트는 LLM 미호출이라
    비용 없이 빠르게 확정된다."""
    stock_names = repo.get_stock_names()
    pairs = repo.get_relevant_pairs_for_roles(only_unclassified=True)
    logger.info("ROLE_PHASE start: %d pairs to classify (workers=%d)", len(pairs), workers)
    lock = threading.Lock()
    counters = {"done": 0, "llm_calls": 0}
    newly_classified_events: list[dict] = []

    def worker(chunk: list[dict]) -> None:
        wrepo = NewsV2Repository(create_supabase_client(), settings, version=repo.version)
        clf = classify_role.RoleClassifier(api_key=settings.upstage_api_key)
        for p in chunk:
            name = stock_names.get(p["stock_code"], p["stock_code"])
            # pair 하나의 실패(LLM·네트워크·저장)가 전체를 죽이지 않도록 격리한다.
            # 실패 pair 는 role_version 이 갱신되지 않으므로 재실행 시 자동 재시도된다.
            outcome = "role_pending"
            try:
                result, status = clf.classify(name, p["stock_code"], p)
                if status != "pending_retry" and result is not None:
                    _save_with_retry(wrepo, p["article_id"], p["stock_code"], result)
                    outcome = "role_rule" if status == "rule" else "role_llm"
            except Exception as exc:  # noqa: BLE001 - pair 단위 격리, 재실행이 재시도
                logger.warning("ROLE_PAIR_FAILED %s/%s: %s", p["article_id"], p["stock_code"], exc)
            with lock:
                counters["done"] += 1
                if outcome == "role_pending":
                    totals["role_pending"] += 1
                else:
                    totals["role_classified"] += 1
                    totals[outcome] += 1
                    if result and result.get("article_role") == "company_event" and result.get(
                        "event_eligible"
                    ):
                        newly_classified_events.append(
                            {**p, "event_signature": result.get("event_signature")}
                        )
                if counters["done"] % 200 == 0:
                    logger.info("  role progress %d/%d", counters["done"], len(pairs))
        with lock:
            counters["llm_calls"] += clf.calls

    # 라운드로빈으로 워커에 분배(같은 워커가 rule/LLM 섞여 처리).
    chunks: list[list[dict]] = [[] for _ in range(max(1, workers))]
    for i, p in enumerate(pairs):
        chunks[i % len(chunks)].append(p)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        list(ex.map(worker, chunks))
    totals["role_llm_calls"] = counters["llm_calls"]
    return newly_classified_events


def phase_cluster(
    repo: NewsV2Repository,
    totals: dict,
    *,
    candidates: list[dict] | None = None,
) -> dict[int, int]:
    """3~4) company_event pair 를 종목별 시간순으로 v2 클러스터링. 대표기사 선정 포함.

    이미 배정된 pair 는 배치로 한 번에 조회해 스킵하고, 재실행 시 미배정이 없으면
    임베딩 로딩·순회를 통째로 건너뛴다(무거운 BGE-M3 로딩·전체 재순회 방지)."""
    if candidates is None:
        # Explicit full-backfill mode keeps the historical scan for resumability.
        pairs = repo.get_event_pairs()
        assigned = repo.get_assigned_v2_pairs()
    else:
        # Scheduler mode passes only events classified in this cycle plus due retries.
        deduplicated = {
            (int(p["article_id"]), p["stock_code"]): p
            for p in [*candidates, *repo.get_retryable_v2_event_pairs()]
        }
        pairs = list(deduplicated.values())
        assigned = set()
        for p in pairs:
            current = repo.get_v2_assignment(int(p["article_id"]), p["stock_code"])
            if current and current.get("status") in {"assigned_new", "assigned_existing"}:
                assigned.add((int(p["article_id"]), p["stock_code"]))
    totals["cluster_skipped"] = len(assigned)
    todo = [p for p in pairs if (p["article_id"], p["stock_code"]) not in assigned]
    logger.info(
        "CLUSTER_PHASE start: %d company_event pairs (%d 미배정 처리 대상)",
        len(pairs),
        len(todo),
    )
    if not todo:
        return {}  # 새로 배정할 게 없으면 임베딩 로딩 자체를 건너뛴다.

    # 기존 클러스터는 DB에서 hydrate하므로 미배정 pair만 임베딩하고 처리한다.
    # 과거 전체 pair를 매 증분 실행마다 다시 임베딩하면 스케줄러 비용이 선형 증가한다.
    by_stock: dict[str, list[dict]] = {}
    for p in todo:
        by_stock.setdefault(p["stock_code"], []).append(p)

    # 임베딩 배치 계산(처리 대상 종목의 기사만).
    embedder = BgeM3Embedder(settings.news_embedding_device)
    uniq = {p["article_id"]: p for items in by_stock.values() for p in items}
    arts = list(uniq.values())
    vecs = embedder.encode_many(arts) if arts else np.empty((0,))
    vec_cache = {a["article_id"]: v for a, v in zip(arts, vecs, strict=True)}

    for stock_code, items in by_stock.items():
        # 한 종목의 오류가 전체 클러스터링을 죽이지 않도록 종목 단위로 격리한다.
        # 실패 종목은 배정이 남으므로 재실행 시 이어서 처리된다.
        try:
            _cluster_one_stock(repo, items, vec_cache, assigned, totals)
        except Exception as exc:  # noqa: BLE001 - 종목 단위 격리, 재실행이 재시도
            logger.warning("CLUSTER_STOCK_FAILED %s: %s", stock_code, exc)
    return {}


def _cluster_one_stock(repo, items, vec_cache, assigned, totals) -> None:
    """한 종목의 company_event pair 를 시간순으로 v2 클러스터링(대표기사 갱신 포함).

    assigned: 이미 v2 성공 배정된 (article_id, stock_code) 집합(배치 조회, 개별 조회 회피)."""
    items.sort(key=lambda r: (r["published_at"], r["article_id"]))
    stock_code = items[0]["stock_code"]
    from datetime import datetime, timedelta

    earliest = min(
        datetime.fromisoformat(item["published_at"].replace("Z", "+00:00")) for item in items
    )
    active_since = (earliest - timedelta(hours=CFG.ACTIVE_WINDOW_HOURS)).isoformat()
    assigner = _hydrate_v2_assigner(
        repo.get_v2_assignment_clusters(stock_code, active_since=active_since)
    )
    stock_local_to_db: dict[int, int] = {}  # local cluster_id -> DB cluster_id
    for p in items:
        if (p["article_id"], p["stock_code"]) in assigned:
            continue
        art = {
            "article_id": f"{p['stock_code']}:{p['article_id']}",
            "stock_code": p["stock_code"],
            "title": p["title"],
            "description": p["description"],
            "event_signature": p.get("event_signature"),
        }
        vec = vec_cache[p["article_id"]]
        res = assigner.assign(art, vec, _hours(p["published_at"]))
        if res.status == "pending_retry":
            totals["cluster_pending"] += 1
            repo.save_v2_assignment(
                article_id=p["article_id"],
                stock_code=p["stock_code"],
                cluster_id=None,
                status="pending_retry",
                llm_called=res.llm_called,
                candidate_count=res.n_candidates,
                reason=res.reason,
                error_code=res.error,
            )
            continue
        local_cid = int(res.cluster_id)
        cl = assigner.clusters[local_cid]
        db_article = {"article_id": p["article_id"], "published_at": p["published_at"]}
        if res.status == "assigned_new":
            db_cid = repo.create_v2_cluster(
                article=db_article,
                stock_code=p["stock_code"],
                centroid=cl.centroid.astype(float).tolist(),
                event_signature=p.get("event_signature"),
            )
            stock_local_to_db[local_cid] = db_cid
            # The in-memory id is allocated locally, while Postgres owns the real
            # identity value. Remap immediately so later articles in this same run
            # can match and update the newly persisted cluster safely.
            if db_cid != local_cid:
                del assigner.clusters[local_cid]
                cl.cluster_id = db_cid
                assigner.clusters[db_cid] = cl
                assigner._seen[art["article_id"]] = db_cid
                assigner._next_id = max(assigner._next_id, db_cid + 1)
        else:
            db_cid = stock_local_to_db.get(local_cid, local_cid)
            repo.update_v2_cluster(
                db_cid,
                centroid=cl.centroid.astype(float).tolist(),
                article_count=len(cl.member_article_ids),
                last_active_at=p["published_at"],
                representative_article_id=p["article_id"],
            )
        repo.save_v2_assignment(
            article_id=p["article_id"],
            stock_code=p["stock_code"],
            cluster_id=db_cid,
            status=res.status,
            llm_called=res.llm_called,
            candidate_count=res.n_candidates,
            reason=res.reason,
            error_code=None,
        )
        totals[res.status] += 1
    totals["assign_llm_calls"] += assigner.calls


def _hydrate_v2_assigner(rows: list[dict]) -> assign_llm_v2.LLMAssignerV2:
    """Restore persisted v2 clusters before assigning a resumed/incremental batch."""

    assigner = assign_llm_v2.LLMAssignerV2(api_key=settings.upstage_api_key)
    max_id = 0
    for row in rows:
        cluster_id = int(row["id"])
        anchor = row.get("anchor") or {}
        representative = row.get("representative") or anchor
        count = max(1, int(row.get("article_count") or 1))
        recent = []
        if representative.get("title") or representative.get("description"):
            recent.append(
                {
                    "title": representative.get("title") or "",
                    "description": representative.get("description") or "",
                }
            )
        assigner.clusters[cluster_id] = assign_llm_v2.ClusterV2(
            cluster_id=cluster_id,
            stock_code=row["stock_code"],
            centroid=np.asarray(row["centroid"], dtype=np.float32),
            anchor_title=anchor.get("title") or "",
            anchor_description=anchor.get("description") or "",
            rep_title=representative.get("title") or "",
            rep_description=representative.get("description") or "",
            event_signature=row.get("event_signature"),
            recent=recent,
            member_article_ids=[f"persisted:{cluster_id}:{i}" for i in range(count)],
            last_active_h=_hours(row["last_active_at"]),
        )
        max_id = max(max_id, cluster_id)
    assigner._next_id = max_id + 1
    return assigner


def phase_summary(repo: NewsV2Repository, totals: dict) -> None:
    """5) v2 사건 클러스터 통합 요약 생성(미완료만)."""
    stock_names = repo.get_stock_names()
    clusters = repo.get_v2_clusters(only_unsummarized=True)
    logger.info("SUMMARY_PHASE start: %d clusters to summarize", len(clusters))
    calls = 0
    for i, c in enumerate(clusters, 1):
        cid = int(c["id"])
        articles = repo.get_v2_cluster_articles(cid)[: CFG.MAX_ARTICLES_PER_SUMMARY]
        if not articles:
            continue
        name = stock_names.get(c["stock_code"], c["stock_code"])
        prompt = summarize.build_user_prompt(articles, name)
        try:
            parsed, meta = summarize.call_solar(settings.upstage_api_key, prompt)
            calls += 1
        except Exception as exc:  # noqa: BLE001 - 요약 실패는 개별 격리·재시도
            parsed, meta = {}, {"ok": False, "parse_success": False, "raw": str(exc)}
        repo.save_v2_summary(cid, parsed, meta, 1)
        if meta.get("ok") and meta.get("parse_success"):
            totals["summaries"] += 1
        else:
            totals["summary_failed"] += 1
        if i % 50 == 0:
            logger.info("  summary progress %d/%d", i, len(clusters))
    totals["summary_calls"] = calls


def phase_verify(repo: NewsV2Repository, totals: dict) -> tuple[bool, list[str]]:
    """7~8) 누락·pending·요약실패 검사. 활성화 가능 여부 판정."""
    problems: list[str] = []
    pending_roles = repo.count_pending_roles()
    if pending_roles:
        problems.append(f"미분류 relevant pair {pending_roles}건")
    if totals["cluster_pending"]:
        problems.append(f"클러스터 배정 pending {totals['cluster_pending']}건")
    unsummarized = repo.count_unsummarized_v2()
    if unsummarized:
        problems.append(f"미완료 v2 요약 {unsummarized}건")
    totals["pending_roles"] = pending_roles
    totals["unsummarized_v2"] = unsummarized
    return (not problems), problems


def build_report(repo: NewsV2Repository, totals: dict, activated: bool, run_key: str) -> dict:
    roles = repo.count_roles()
    event_pairs = roles.get("company_event", 0)
    related = sum(v for k, v in roles.items() if k != "company_event")
    v2_clusters = len(repo.get_v2_clusters())
    summarized = len([c for c in repo.get_v2_clusters() if c["summary_status"] == "success"])
    return {
        "relevant_pairs_total": sum(roles.values()),
        "roles": roles,
        "event_clustering_targets": event_pairs,
        "related_articles": related,
        "v2_clusters": v2_clusters,
        "v2_summaries": summarized,
        "role_llm_calls": totals.get("role_llm_calls", 0),
        "assign_llm_calls": totals.get("assign_llm_calls", 0),
        "summary_calls": totals.get("summary_calls", 0),
        "failed_or_pending": {
            "role_pending": totals.get("role_pending", 0),
            "cluster_pending": totals.get("cluster_pending", 0),
            "summary_failed": totals.get("summary_failed", 0),
            "unsummarized_v2": totals.get("unsummarized_v2", 0),
        },
        "v2_activated": activated,
        "resume_command": (
            f"uv run python -m scripts.run_full_news_v2 --run-key {run_key} "
            f"--workers 4 --execute --activate"
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="뉴스 처리 v2 단일 실행")
    ap.add_argument("--run-key", default="full-news-v2-20260721")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--activate", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.execute:
        raise SystemExit("run_full_news_v2 requires --execute")

    client = get_supabase_client()
    repo = NewsV2Repository(client, settings, version=V2_VERSION)

    totals = {
        "role_classified": 0,
        "role_rule": 0,
        "role_llm": 0,
        "role_pending": 0,
        "assigned_new": 0,
        "assigned_existing": 0,
        "cluster_pending": 0,
        "cluster_skipped": 0,
        "assign_llm_calls": 0,
        "summaries": 0,
        "summary_failed": 0,
    }

    phase_roles(repo, totals, args.workers)
    phase_cluster(repo, totals)
    phase_summary(repo, totals)
    ok, problems = phase_verify(repo, totals)

    activated = False
    if ok and args.activate:
        repo.activate_v2(args.run_key)
        activated = True
        logger.info("V2 ACTIVATED (active_version=%s)", V2_VERSION)
    elif not ok:
        logger.warning("V2 NOT activated. 문제: %s", "; ".join(problems))

    report = build_report(repo, totals, activated, args.run_key)
    print("FULL_NEWS_V2_RESULT=" + json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

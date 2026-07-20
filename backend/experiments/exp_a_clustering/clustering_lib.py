"""실험 A 공용 라이브러리: 입력 텍스트 구성, 임베딩(캐시), 클러스터링, 평가.

로컬(코드 검증)과 Colab(GPU 실행) 양쪽에서 동일하게 import해서 쓴다.
무거운 의존성(torch, sentence-transformers, igraph/leidenalg)은 함수 안에서 지연 import
하므로, 데이터/평가 유틸만 쓸 때는 설치 없이도 로드된다.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------- 입력 텍스트
INPUT_TYPES = ("A_title", "B_title_desc", "C_title_desc_body")

# 전처리 로직 버전. build_input_text / format_for_model 을 바꾸면 이 값을 올려
# 기존 임베딩 캐시를 무효화한다(#2). 캐시 키에 포함된다.
PREPROCESS_VERSION = "v1"


def build_input_text(row: dict, input_type: str) -> str:
    """A: title / B: title+description / C: title+description+body_head.

    body_head가 비면 C는 자동으로 B와 동일해진다(프롬프트 규칙).
    """

    title = (row.get("title") or "").strip()
    desc = (row.get("description") or "").strip()
    body = (row.get("body_head") or "").strip()
    if input_type == "A_title":
        return title
    if input_type == "B_title_desc":
        return " ".join(p for p in (title, desc) if p)
    if input_type == "C_title_desc_body":
        parts = [title, desc] + ([body] if body else [])
        return " ".join(p for p in parts if p)
    raise ValueError(f"unknown input_type: {input_type}")


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 임베딩 캐시
@dataclass
class EmbeddingCache:
    """(model, revision, input_type, text_sha256) → vector 캐시.

    디스크에 npz+json으로 저장해 재실행 시 임베딩 재계산을 피한다.
    """

    cache_dir: Path
    _mem: dict[str, np.ndarray] = field(default_factory=dict)

    def key(
        self,
        model: str,
        revision: str,
        input_type: str,
        sha: str,
        preprocess_version: str = PREPROCESS_VERSION,
        max_seq_length: int | str = "default",
    ) -> str:
        """캐시 키. sha는 **전처리 완료(prepared) 텍스트**의 SHA-256를 넘겨야 한다.

        전처리(E5 instruction 등)나 max_seq_length가 바뀌면 키도 바뀌어야 하므로
        preprocess_version과 max_seq_length를 키에 포함한다(#2).
        """

        return (
            f"{model}||{revision}||{input_type}||{preprocess_version}||msl={max_seq_length}||{sha}"
        )

    def path(self, model: str) -> Path:
        safe = model.replace("/", "__")
        return self.cache_dir / f"emb_{safe}.npz"

    def load(self, model: str) -> None:
        p = self.path(model)
        if p.exists():
            data = np.load(p, allow_pickle=True)
            keys = list(data["keys"])
            vecs = data["vecs"]
            for k, v in zip(keys, vecs):
                self._mem[str(k)] = v

    def save(self, model: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{model}||"
        items = [(k, v) for k, v in self._mem.items() if k.startswith(prefix)]
        if not items:
            return
        keys = np.array([k for k, _ in items], dtype=object)
        vecs = np.vstack([v for _, v in items])
        np.savez_compressed(self.path(model), keys=keys, vecs=vecs)

    def get(self, key: str) -> np.ndarray | None:
        return self._mem.get(key)

    def put(self, key: str, vec: np.ndarray) -> None:
        self._mem[key] = vec


def l2_normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


# ---------------------------------------------------------------- 임베더
# 뉴스-뉴스 대칭 유사도용 instruction (E5-instruct 계열). 대칭 태스크이므로 모든
# 문장에 동일한 instruction을 붙인다(질의/문서 비대칭 아님).
_E5_INSTRUCT = "Instruct: Retrieve news articles that report the same news event\nQuery: "


def format_for_model(text: str, model_name: str) -> str:
    """모델별 권장 입력 프리픽스 적용 (#6).

    - e5-*-instruct: 대칭 유사도이므로 모든 문장에 동일 instruction 프리픽스.
    - e5 (non-instruct): 대칭 비교에는 'query:' 프리픽스를 양쪽에 동일 적용.
    - bge-m3: 프리픽스 없음(원문 그대로).
    """

    name = model_name.lower()
    t = text or ""
    if "e5" in name and "instruct" in name:
        return _E5_INSTRUCT + t
    if "e5" in name:
        return f"query: {t}"
    return t  # bge-m3 등


def embed_sentence_transformer(
    prepared_texts: list[str],
    model_name: str,
    revision: str | None,
    device: str,
    batch_size: int = 64,
    max_seq_length: int | None = None,
) -> tuple[np.ndarray, dict]:
    """BGE-M3 / E5 계열 임베딩.

    입력은 **이미 전처리(format_for_model)된 prepared 텍스트**여야 한다. 캐시 키가
    prepared 텍스트 SHA로 계산되므로, 임베딩 입력과 키가 정확히 일치하도록
    이 함수는 프리픽스를 다시 붙이지 않는다(#2). truncation 비율을 함께 보고(#6).

    반환: (vecs, meta).
    """

    from sentence_transformers import SentenceTransformer

    st = SentenceTransformer(model_name, revision=revision, device=device)
    if max_seq_length:
        st.max_seq_length = max_seq_length

    tok = st.tokenizer
    limit = st.max_seq_length
    lengths = [len(tok.encode(t, add_special_tokens=True)) for t in prepared_texts]
    truncated = sum(1 for n in lengths if n > limit)
    meta = {
        "max_seq_length": int(limit),
        "truncation_rate": round(truncated / len(prepared_texts), 4) if prepared_texts else 0.0,
        "max_token_len": int(max(lengths)) if lengths else 0,
        "resolved_revision": _resolve_st_revision(st, model_name, revision),
    }

    vecs = st.encode(
        prepared_texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    return vecs.astype(np.float32), meta


def embedding_meta_only(
    prepared_texts: list[str],
    model_name: str,
    revision: str | None,
    max_seq_length: int | None = None,
) -> dict:
    """임베딩 벡터 계산 없이 metadata(truncation 비율, max_token_len, revision)만 산출.

    100% cache hit이어도 truncation/revision 메타를 채우기 위해 사용(#3-테스트).
    토크나이저만 로드하므로 임베딩 인코딩보다 훨씬 가볍다.
    """

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_name, revision=revision)
    limit = max_seq_length or getattr(tok, "model_max_length", 512)
    if limit is None or limit > 100000:
        limit = 512
    lengths = [len(tok.encode(t, add_special_tokens=True)) for t in prepared_texts]
    truncated = sum(1 for n in lengths if n > limit)
    return {
        "max_seq_length": int(limit),
        "truncation_rate": round(truncated / len(prepared_texts), 4) if prepared_texts else 0.0,
        "max_token_len": int(max(lengths)) if lengths else 0,
        "resolved_revision": revision or "main",
        "from_cache": True,
    }


def _resolve_st_revision(st, model_name: str, revision: str | None) -> str:
    """실제 로드된 모델의 commit hash를 최대한 회수(#5). 실패 시 요청 revision."""

    try:
        from huggingface_hub import HfApi

        info = HfApi().model_info(model_name, revision=revision or "main")
        return info.sha or (revision or "main")
    except Exception:  # noqa: BLE001
        return revision or "main"


def embed_upstage(texts: list[str], api_key: str, model: str = "embedding-passage") -> np.ndarray:
    """Upstage passage 임베딩 API. 호출량/비용 집계를 위해 (vecs, n_calls, n_tokens)는
    호출측에서 래핑. 여기선 벡터만 반환."""

    import requests

    url = "https://api.upstage.ai/v1/solar/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    out: list[list[float]] = []
    B = 100
    for i in range(0, len(texts), B):
        chunk = texts[i : i + B]
        r = requests.post(url, headers=headers, json={"model": model, "input": chunk}, timeout=60)
        r.raise_for_status()
        data = r.json()["data"]
        out.extend(d["embedding"] for d in sorted(data, key=lambda d: d["index"]))
    return l2_normalize(np.array(out, dtype=np.float32))


# ---------------------------------------------------------------- 클러스터링
def parse_hours(ts: str) -> float:
    """ISO 시각 → 시(hour) 단위 실수(시간 창 비교용)."""
    from datetime import datetime

    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() / 3600.0


def cluster_online_centroid(
    ids: list[str], vecs: np.ndarray, times_h: list[float], threshold: float, window_h: float
) -> dict[str, int]:
    """온라인 centroid 매칭 (시간순 스트리밍 휴리스틱).

    기사를 발행 시간순으로 처리하며, 활성 클러스터 중 (cosine>=threshold)이고 시간창
    안(현재기사 시각 - 클러스터의 마지막 기사 시각 <= window_h)인 최고 유사 클러스터에
    합류시킨다. 없으면 새 클러스터를 만든다.

    ⚠️ 시간창은 "클러스터의 **마지막** 기사 시각" 기준이다(sliding inactivity window):
    관련 기사가 계속 유입되면 클러스터가 오래 유지된다. 최초 기사 기준 최대 지속시간
    제한이 아니다(#9). 운영 클러스터링과 동일한 증분 방식을 모사한다.
    """

    order = sorted(range(len(ids)), key=lambda i: times_h[i])
    centroids: list[np.ndarray] = []
    csizes: list[int] = []
    ctime: list[float] = []
    labels = [-1] * len(ids)
    for i in order:
        v = vecs[i]
        best, best_sim = -1, threshold
        for c in range(len(centroids)):
            if times_h[i] - ctime[c] > window_h:
                continue
            sim = float(np.dot(v, centroids[c]))  # 정규화됨 → dot=cosine
            if sim >= best_sim:
                best_sim, best = sim, c
        if best == -1:
            centroids.append(v.copy())
            csizes.append(1)
            ctime.append(times_h[i])
            labels[i] = len(centroids) - 1
        else:
            n = csizes[best]
            centroids[best] = (centroids[best] * n + v) / (n + 1)
            centroids[best] /= np.linalg.norm(centroids[best]) or 1.0
            csizes[best] += 1
            ctime[best] = max(ctime[best], times_h[i])
            labels[i] = best
    return {ids[i]: labels[i] for i in range(len(ids))}


def cluster_agglomerative(ids: list[str], vecs: np.ndarray, threshold: float) -> dict[str, int]:
    from sklearn.cluster import AgglomerativeClustering

    if len(ids) == 1:
        return {ids[0]: 0}
    model = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="average",
        distance_threshold=1.0 - threshold,
    )
    labels = model.fit_predict(vecs)
    return {ids[i]: int(labels[i]) for i in range(len(ids))}


def knn_edges(vecs: np.ndarray, k: int, edge_threshold: float) -> dict[tuple[int, int], float]:
    """대칭 k-NN 엣지 집합. pair를 (min,max)로 정규화해 비대칭 이웃 관계에서도
    엣지가 누락되지 않게 한다(순서 무관, 결정적).

    반환: {(a,b): weight} — 같은 pair가 양쪽에서 나오면 최대 유사도 사용.
    """

    n = vecs.shape[0]
    sims = vecs @ vecs.T
    kk = min(k, n - 1)
    edge_pairs: dict[tuple[int, int], float] = {}
    for i in range(n):
        # 자기 인덱스를 명시적으로 제거한다. argsort는 동일/동점 벡터에서 self가
        # 첫 번째임을 보장하지 않으므로 [1:kk+1] 슬라이싱은 self-loop를 만들 수 있다(#1).
        order = np.argsort(-sims[i])
        nbr = order[order != i][:kk]
        for j in nbr:
            jj = int(j)
            s = float(sims[i, jj])
            if s >= edge_threshold:
                a, b = (i, jj) if i < jj else (jj, i)
                prev = edge_pairs.get((a, b))
                if prev is None or s > prev:
                    edge_pairs[(a, b)] = s
    return edge_pairs


def _leiden_from_edges(
    n: int, edge_pairs: dict[tuple[int, int], float], resolution: float
) -> list[int]:
    """엣지 집합 → Leiden membership. 엣지가 없으면 모두 singleton."""

    if not edge_pairs:
        return list(range(n))  # 전부 singleton (명시적 분기, #11)

    import igraph as ig
    import leidenalg as la

    # 결정적: pair 정렬 순서로 엣지/가중치 구성
    items = sorted(edge_pairs.items())
    edges = [e for e, _ in items]
    weights = [w for _, w in items]
    g = ig.Graph(n=n, edges=edges)
    g.es["weight"] = weights
    part = la.find_partition(
        g,
        la.RBConfigurationVertexPartition,
        weights="weight",
        resolution_parameter=resolution,
        seed=42,
    )
    return list(part.membership)


def cluster_leiden(
    ids: list[str], vecs: np.ndarray, k: int, edge_threshold: float, resolution: float
) -> dict[str, int]:
    """k-NN 그래프 + Leiden. 코사인>=edge_threshold 엣지만 유지.

    엣지는 대칭 pair로 정규화하므로 기사 입력 순서에 무관하게 동일한 그래프가 나온다.
    엣지가 없으면 모든 기사를 singleton으로 처리한다.

    구현 메모: 매 호출마다 sims = vecs @ vecs.T 를 재계산한다(종목 내부 소규모 전제).
    대규모로 확장 시 종목별 sims/이웃을 사전계산해 재사용해야 한다(#8).
    """

    n = len(ids)
    if n == 1:
        return {ids[0]: 0}
    edge_pairs = knn_edges(vecs, k, edge_threshold)
    labels = _leiden_from_edges(n, edge_pairs, resolution)
    return {ids[i]: int(labels[i]) for i in range(n)}


# ---------------------------------------------------------------- 평가지표
def _clusters_from_labels(labels: dict[str, int]) -> dict[int, set]:
    out = defaultdict(set)
    for k, v in labels.items():
        out[v].add(k)
    return out


def bcubed(pred: dict[str, int], gold: dict[str, int]) -> tuple[float, float, float]:
    """B-cubed precision/recall/F1 (주지표)."""

    items = list(gold.keys())
    gold_c = _clusters_from_labels(gold)
    pred_c = _clusters_from_labels(pred)
    gmap = {i: [c for c, s in gold_c.items() if i in s][0] for i in items}
    pmap = {i: pred[i] for i in items}
    prec, rec = 0.0, 0.0
    for i in items:
        pc = pred_c[pmap[i]]
        gc = gold_c[gmap[i]]
        inter = len(pc & gc)
        prec += inter / len(pc)
        rec += inter / len(gc)
    n = len(items)
    prec, rec = prec / n, rec / n
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1


def pairwise_prf(pred: dict[str, int], gold: dict[str, int]) -> tuple[float, float, float]:
    items = list(gold.keys())
    gl = np.array([gold[it] for it in items])
    pl = np.array([pred[it] for it in items])
    tp = fp = fn = 0
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            same_g = gl[a] == gl[b]
            same_p = pl[a] == pl[b]
            if same_p and same_g:
                tp += 1
            elif same_p and not same_g:
                fp += 1
            elif not same_p and same_g:
                fn += 1
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1


def over_under_merge(pred: dict[str, int], gold: dict[str, int]) -> tuple[float, float]:
    """over-merge: 서로 다른 gold인데 같은 pred로 묶인 쌍 비율.
    under-merge: 같은 gold인데 다른 pred로 쪼개진 쌍 비율."""

    items = list(gold.keys())
    gl = [gold[it] for it in items]
    pl = [pred[it] for it in items]
    diff_g_pairs = same_g_pairs = 0
    over = under = 0
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            sg = gl[a] == gl[b]
            sp = pl[a] == pl[b]
            if sg:
                same_g_pairs += 1
                if not sp:
                    under += 1
            else:
                diff_g_pairs += 1
                if sp:
                    over += 1
    over_rate = over / diff_g_pairs if diff_g_pairs else 0.0
    under_rate = under / same_g_pairs if same_g_pairs else 0.0
    return over_rate, under_rate


def ari_nmi(pred: dict[str, int], gold: dict[str, int]) -> tuple[float, float]:
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

    items = list(gold.keys())
    gl = [gold[it] for it in items]
    pl = [pred[it] for it in items]
    return adjusted_rand_score(gl, pl), normalized_mutual_info_score(gl, pl)


def evaluate(pred: dict[str, int], gold: dict[str, int]) -> dict:
    bp, br, bf = bcubed(pred, gold)
    pp, pr, pf = pairwise_prf(pred, gold)
    over, under = over_under_merge(pred, gold)
    ari, nmi = ari_nmi(pred, gold)
    return {
        "bcubed_precision": bp,
        "bcubed_recall": br,
        "bcubed_f1": bf,
        "pairwise_precision": pp,
        "pairwise_recall": pr,
        "pairwise_f1": pf,
        "over_merge_rate": over,
        "under_merge_rate": under,
        "ari": ari,
        "nmi": nmi,
    }


def evaluate_per_stock(
    pred: dict[str, int], rows: list[dict], eligible_only: bool = True, strict: bool = True
) -> dict:
    """종목별 gold로 평가 후 macro 평균. pred/gold 모두 종목 내에서만 비교.

    strict=True(기본): 어떤 종목의 eligible 기사 중 pred에 없는 것이 있으면 예외.
    클러스터링 구현 오류로 예측이 누락된 종목이 조용히 평가에서 빠져 성능이
    과대평가되는 것을 막는다(#4). 예측은 반드시 평가 대상 전원을 덮어야 한다.
    """

    by_stock = defaultdict(list)
    for r in rows:
        if eligible_only and r.get("evaluation_eligible") != "true":
            continue
        by_stock[r["stock_code"]].append(r)
    per = {}
    skipped: dict[str, int] = {}
    for stock, srows in by_stock.items():
        ids = [r["article_stock_id"] for r in srows]
        gold = {r["article_stock_id"]: r["gold_event_id"] for r in srows}
        gmap = {g: i for i, g in enumerate(sorted(set(gold.values())))}
        gold_i = {k: gmap[v] for k, v in gold.items()}
        missing = [i for i in ids if i not in pred]
        if missing:
            if strict:
                raise ValueError(
                    f"{stock}: 예측 누락 {len(missing)}건 (예: {missing[:5]}). "
                    "클러스터링이 평가 대상 전원을 덮지 않음 — 조용한 제외 대신 실패 처리."
                )
            skipped[stock] = len(missing)
            continue
        pred_i = {i: pred[i] for i in ids}
        per[stock] = evaluate(pred_i, gold_i)
    if not per:
        return {"per_stock": {}, "macro": {}, "skipped_stocks": skipped}
    keys = next(iter(per.values())).keys()
    macro = {k: float(np.mean([per[s][k] for s in per])) for k in keys}
    return {"per_stock": per, "macro": macro, "skipped_stocks": skipped}

"""clustering_lib 검증 테스트.

로컬 실행:  python test_clustering_lib.py
(numpy, scikit-learn, python-igraph, leidenalg 필요)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clustering_lib as C  # noqa: E402


def _rand_unit(n, d=32, seed=0):
    rng = np.random.default_rng(seed)
    m = rng.standard_normal((n, d)).astype(np.float32)
    return C.l2_normalize(m)


def test_leiden_order_invariant():
    """기사 순서를 바꿔도 Leiden 결과(파티션)가 동일해야 한다."""
    vecs = _rand_unit(30, seed=1)
    ids = [f"a{i}" for i in range(30)]
    lab1 = C.cluster_leiden(ids, vecs, k=10, edge_threshold=0.2, resolution=1.0)
    perm = list(np.random.default_rng(7).permutation(30))
    ids2 = [ids[i] for i in perm]
    vecs2 = vecs[perm]
    lab2 = C.cluster_leiden(ids2, vecs2, k=10, edge_threshold=0.2, resolution=1.0)

    def groups(lab):
        from collections import defaultdict

        g = defaultdict(set)
        for k, v in lab.items():
            g[v].add(k)
        return {frozenset(s) for s in g.values()}

    assert groups(lab1) == groups(lab2), "Leiden 결과가 입력 순서에 의존함"


def test_knn_edges_symmetric():
    """비대칭 k-NN에서도 pair가 정규화되어 엣지가 누락되지 않는다."""
    v = np.array([[1, 0], [0.9, 0.1], [0.8, 0.2], [0, 1]], dtype=np.float32)
    v = C.l2_normalize(v)
    edges = C.knn_edges(v, k=1, edge_threshold=0.0)
    assert all(a < b for a, b in edges), "엣지가 정규화되지 않음"
    assert len(edges) == len({tuple(sorted(e)) for e in edges})


def test_empty_graph_singletons():
    """엣지가 없으면 모두 singleton."""
    v = _rand_unit(5, seed=3)
    ids = [f"x{i}" for i in range(5)]
    lab = C.cluster_leiden(ids, v, k=3, edge_threshold=0.999, resolution=1.0)
    assert len(set(lab.values())) == 5, "엣지 없을 때 singleton 아님"


def test_singleton_stock():
    """단독 기사 종목이 정상 처리."""
    v = _rand_unit(1, seed=4)
    assert C.cluster_leiden(["only"], v, 5, 0.8, 1.0) == {"only": 0}
    assert C.cluster_agglomerative(["only"], v, 0.8) == {"only": 0}
    assert C.cluster_online_centroid(["only"], v, [0.0], 0.8, 24) == {"only": 0}


def test_missing_prediction_fails():
    """예측 누락 종목은 strict에서 실패해야 한다."""
    rows = [
        {
            "article_stock_id": "a",
            "stock_code": "s1",
            "gold_event_id": "e1",
            "evaluation_eligible": "true",
        },
        {
            "article_stock_id": "b",
            "stock_code": "s1",
            "gold_event_id": "e1",
            "evaluation_eligible": "true",
        },
    ]
    pred = {"a": 0}  # b 누락
    try:
        C.evaluate_per_stock(pred, rows, strict=True)
        raise AssertionError("누락인데 예외가 안 남")
    except ValueError:
        pass


def test_cache_key_distinguishes_revision():
    """캐시 키가 revision·input_type을 구분한다."""
    c = C.EmbeddingCache(cache_dir=Path("/tmp/emb_cache_test"))
    k1 = c.key("m", "rev1", "A_title", "sha")
    k2 = c.key("m", "rev2", "A_title", "sha")
    k3 = c.key("m", "rev1", "B_title_desc", "sha")
    assert k1 != k2 and k1 != k3


def test_e5_prefix_symmetric():
    """E5-instruct는 instruction 프리픽스, bge-m3는 원문 그대로."""
    t = "삼성전자 실적"
    e5 = C.format_for_model(t, "intfloat/multilingual-e5-large-instruct")
    bge = C.format_for_model(t, "BAAI/bge-m3")
    assert e5.startswith("Instruct:") and t in e5
    assert bge == t


def test_cross_stock_never_merged():
    """서로 다른 종목 기사는 절대 같은 클러스터가 되지 않는다."""
    import run_experiment as R

    rows = [
        {"article_stock_id": "a", "stock_code": "s1", "published_at": "2026-07-01T00:00:00+00:00"},
        {"article_stock_id": "b", "stock_code": "s2", "published_at": "2026-07-01T00:00:00+00:00"},
    ]
    v = _rand_unit(2, seed=9)
    vbi = {"a": v[0], "b": v[1]}
    pred = R.cluster_per_stock(rows, vbi, "agglomerative", {"threshold": 0.0})
    assert pred["a"] != pred["b"]


def test_no_self_loop_identical_vectors():
    """동일 벡터 여러 개 + k=1에서도 self-loop 엣지가 없어야 한다."""
    v = np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    v = C.l2_normalize(v)
    edges = C.knn_edges(v, k=1, edge_threshold=0.0)
    assert all(a != b for a, b in edges), f"self-loop 발생: {edges}"
    assert len(edges) >= 1


def test_knn_selects_k_real_neighbors():
    """자기 제외 후 실제 타 문서 k개를 이웃으로 선택한다."""
    v = _rand_unit(5, seed=11)
    edges = C.knn_edges(v, k=2, edge_threshold=-1.0)
    from collections import Counter

    deg = Counter()
    for a, b in edges:
        deg[a] += 1
        deg[b] += 1
    assert all(a != b for a, b in edges)
    assert all(deg[i] >= 2 for i in range(5)), f"degree 부족: {deg}"


def test_cache_key_preprocess_version_changes():
    """전처리 버전이 바뀌면 캐시 키가 바뀐다."""
    c = C.EmbeddingCache(cache_dir=Path("/tmp/emb_cache_test2"))
    k1 = c.key("m", "rev", "A_title", "sha", preprocess_version="v1")
    k2 = c.key("m", "rev", "A_title", "sha", preprocess_version="v2")
    assert k1 != k2


def test_cache_key_max_seq_length_changes():
    """max_seq_length가 바뀌면 캐시 키가 바뀐다."""
    c = C.EmbeddingCache(cache_dir=Path("/tmp/emb_cache_test3"))
    k1 = c.key("m", "rev", "A_title", "sha", max_seq_length="default")
    k2 = c.key("m", "rev", "A_title", "sha", max_seq_length=256)
    assert k1 != k2


def test_prepared_text_sha_differs_by_model():
    """E5 프리픽스가 붙으면 prepared 텍스트 SHA가 bge와 달라진다."""
    t = "삼성전자 실적"
    sha_e5 = C.text_sha256(C.format_for_model(t, "intfloat/multilingual-e5-large-instruct"))
    sha_bge = C.text_sha256(C.format_for_model(t, "BAAI/bge-m3"))
    assert sha_e5 != sha_bge


def test_embedding_cache_reuse():
    """같은 (모델,입력,전처리,텍스트)면 캐시 키가 동일 → 재사용된다."""
    c = C.EmbeddingCache(cache_dir=Path("/tmp/emb_reuse_test"))
    sha = C.text_sha256(C.format_for_model("삼성 실적", "BAAI/bge-m3"))
    k1 = c.key("BAAI/bge-m3", "rev", "B_title_desc", sha)
    k2 = c.key("BAAI/bge-m3", "rev", "B_title_desc", sha)
    assert k1 == k2
    c.put(k1, np.zeros(4, dtype=np.float32))
    assert c.get(k2) is not None


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} 테스트 통과")


if __name__ == "__main__":
    _run_all()

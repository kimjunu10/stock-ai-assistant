"""RRF 결합 로직 단위 테스트 (SPEC §10.3)."""

from __future__ import annotations

from app.rag.fusion import rrf_fuse


def test_item_in_both_lists_ranks_highest():
    # A 는 두 리스트 모두 1위 → 단독 상위인 다른 항목보다 점수 높아야.
    sem = ["A", "B", "C"]
    lex = ["A", "D", "E"]
    fused = rrf_fuse(sem, lex, rrf_k=50)
    assert fused[0][0] == "A"


def test_rrf_formula_values():
    fused = dict(rrf_fuse(["A", "B"], ["B", "A"], rrf_k=10))
    # A: 1/(10+1) + 1/(10+2); B: 1/(10+2) + 1/(10+1) → 동일
    assert abs(fused["A"] - fused["B"]) < 1e-12
    assert abs(fused["A"] - (1 / 11 + 1 / 12)) < 1e-12


def test_weights_shift_ranking():
    # lexical 가중치를 크게 주면 lexical 1위가 semantic 1위를 앞선다.
    sem = ["S", "X"]
    lex = ["L", "X"]
    fused = dict(rrf_fuse(sem, lex, rrf_k=50, semantic_weight=1.0, lexical_weight=5.0))
    assert fused["L"] > fused["S"]


def test_only_semantic_still_ranks():
    fused = rrf_fuse(["A", "B", "C"], [], rrf_k=50)
    assert [c for c, _ in fused] == ["A", "B", "C"]

"""요약 지연(비용 절감) 모드 단위 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.core.config import Settings
from scripts.run_full_news_v2 import phase_verify


def _repo(pending_roles: int, unsummarized: int) -> MagicMock:
    repo = MagicMock()
    repo.count_pending_roles.return_value = pending_roles
    repo.count_unsummarized_v2.return_value = unsummarized
    return repo


def test_verify_ignores_unsummarized_when_deferred():
    repo = _repo(0, 5)
    ok, problems = phase_verify(repo, {"cluster_pending": 0}, require_summaries=False)
    assert ok is True
    assert problems == []


def test_verify_flags_unsummarized_when_required():
    repo = _repo(0, 5)
    ok, problems = phase_verify(repo, {"cluster_pending": 0}, require_summaries=True)
    assert ok is False
    assert any("요약" in p for p in problems)


def test_verify_still_flags_pending_roles_even_when_deferred():
    repo = _repo(3, 0)
    ok, problems = phase_verify(repo, {"cluster_pending": 0}, require_summaries=False)
    assert ok is False
    assert any("미분류" in p for p in problems)


def test_summary_disabled_by_default():
    # 비용 절감: 기본은 요약 끔.
    assert Settings().news_summary_enabled is False

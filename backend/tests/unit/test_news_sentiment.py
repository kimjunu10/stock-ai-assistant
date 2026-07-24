from __future__ import annotations

from types import SimpleNamespace

import torch

from app.core.config import Settings
from app.services.news_sentiment import (
    LABEL_BY_INDEX,
    SENTIMENT_INPUT_VERSION,
    NewsSentimentService,
    SentimentResult,
    get_news_sentiment_service,
    initialize_news_sentiment_service,
    label_for_index,
    reset_news_sentiment_service_for_tests,
    sentiment_input_hash,
)
from scripts.backfill_news_sentiment import run_backfill
from scripts.run_full_news_v2 import classify_and_save_cluster_sentiment


class FakeTokenizer:
    def __init__(self):
        self.calls = []

    def __call__(self, titles, **kwargs):
        self.calls.append((titles, kwargs))
        return {"input_ids": torch.ones((len(titles), 2), dtype=torch.long)}


class FakeModel:
    def __init__(self, logits):
        self.logits = torch.tensor(logits, dtype=torch.float32)

    def __call__(self, **_kwargs):
        return SimpleNamespace(logits=self.logits)


def loaded_service(logits) -> NewsSentimentService:
    service = NewsSentimentService(Settings(sentiment_enabled=False))
    service.enabled = True
    service._tokenizer = FakeTokenizer()
    service._model = FakeModel(logits)
    return service


def result(label: str = "positive") -> SentimentResult:
    scores = {
        "negative": (0.8, 0.1, 0.1),
        "neutral": (0.1, 0.8, 0.1),
        "positive": (0.1, 0.1, 0.8),
    }[label]
    return SentimentResult(
        label=label,
        score=max(scores),
        negative_score=scores[0],
        neutral_score=scores[1],
        positive_score=scores[2],
        model_id="test-model",
        model_revision="test-revision",
    )


def test_fisa_label_mapping_is_fixed() -> None:
    assert LABEL_BY_INDEX == {0: "negative", 1: "neutral", 2: "positive"}
    assert label_for_index(0) == "negative"
    assert label_for_index(1) == "neutral"
    assert label_for_index(2) == "positive"
    NewsSentimentService._validate_label_mapping({0: "negative", 1: "neutral", 2: "positive"})


def test_process_uses_one_sentiment_service_instance() -> None:
    reset_news_sentiment_service_for_tests()
    cfg = Settings(sentiment_enabled=False)

    initialized = initialize_news_sentiment_service(cfg)
    reused = get_news_sentiment_service(cfg)

    assert reused is initialized
    reset_news_sentiment_service_for_tests()


def test_empty_title_returns_unknown_without_inference() -> None:
    service = loaded_service([[0.0, 0.0, 1.0]])

    sentiment = service.analyze("   ")

    assert sentiment.label == "unknown"
    assert sentiment.error == "empty_title"
    assert service._tokenizer.calls == []


def test_inference_uses_summary_title_only_and_expected_tokenizer_options() -> None:
    service = loaded_service([[0.0, 0.0, 5.0]])

    sentiment = service.analyze("  회사가 신규 계약을 체결했다  ")

    assert sentiment.label == "positive"
    titles, options = service._tokenizer.calls[0]
    assert titles == ["회사가 신규 계약을 체결했다"]
    assert options == {
        "max_length": 128,
        "truncation": True,
        "padding": False,
        "return_tensors": "pt",
    }


def test_inference_failure_returns_unknown() -> None:
    class FailingModel:
        def __call__(self, **_kwargs):
            raise RuntimeError("inference exploded")

    service = loaded_service([[0.0, 0.0, 1.0]])
    service._model = FailingModel()

    sentiment = service.analyze("대표 기사 제목")

    assert sentiment.label == "unknown"
    assert "inference exploded" in (sentiment.error or "")


def test_cluster_sentiment_skips_same_title_and_reanalyzes_changed_title() -> None:
    class Repo:
        def __init__(self):
            self.state = {
                "sentiment_label": "positive",
                "sentiment_model": "test-model",
                "sentiment_model_revision": "test-revision",
                "sentiment_input_version": SENTIMENT_INPUT_VERSION,
                "sentiment_input_hash": sentiment_input_hash("같은 제목"),
            }
            self.saved = []

        def get_cluster_sentiment_state(self, _cluster_id):
            return self.state

        def save_cluster_sentiment(self, cluster_id, value, *, input_hash):
            self.saved.append((cluster_id, value, input_hash))

    class Service:
        model_id = "test-model"
        model_revision = "test-revision"

        def __init__(self):
            self.titles = []

        def analyze(self, title):
            self.titles.append(title)
            return result()

    repo = Repo()
    service = Service()

    assert classify_and_save_cluster_sentiment(repo, 7, "같은   제목", service) == "skipped"
    assert service.titles == []
    assert classify_and_save_cluster_sentiment(repo, 7, "변경된 제목", service) == "analyzed"
    assert service.titles == ["변경된 제목"]
    assert repo.saved[0][0] == 7


def test_sentiment_storage_failure_does_not_escape_pipeline_boundary() -> None:
    class Repo:
        def get_cluster_sentiment_state(self, _cluster_id):
            return {}

        def save_cluster_sentiment(self, *_args, **_kwargs):
            raise RuntimeError("database write failed")

    class Service:
        model_id = "test-model"
        model_revision = "test-revision"

        def analyze(self, _title):
            return result()

    assert classify_and_save_cluster_sentiment(Repo(), 9, "대표 제목", Service()) == "failed"


def test_backfill_skips_current_force_reprocesses_and_resumes_after_failure() -> None:
    current = {
        "sentiment_label": "positive",
        "sentiment_model": "test-model",
        "sentiment_model_revision": "test-revision",
        "sentiment_input_version": SENTIMENT_INPUT_VERSION,
        "sentiment_input_hash": sentiment_input_hash("현재 제목"),
    }

    class Repo:
        def __init__(self):
            self.rows = [
                {"id": 1, "summary_title": "새 제목"},
                {"id": 2, "summary_title": "현재 제목", **current},
            ]
            self.fail_once = {1}

        def get_sentiment_backfill_batch(self, *, after_id, batch_size):
            return [row for row in self.rows if row["id"] > after_id][:batch_size]

        def save_cluster_sentiment(self, cluster_id, value, *, input_hash):
            if cluster_id in self.fail_once:
                self.fail_once.remove(cluster_id)
                raise RuntimeError("temporary save failure")
            row = next(item for item in self.rows if item["id"] == cluster_id)
            row.update(
                sentiment_label=value.label,
                sentiment_model=value.model_id,
                sentiment_model_revision=value.model_revision,
                sentiment_input_version=value.input_version,
                sentiment_input_hash=input_hash,
            )

    class Service:
        model_id = "test-model"
        model_revision = "test-revision"
        available = True

        def analyze_batch(self, titles):
            return [result() for _title in titles]

    repo = Repo()
    service = Service()
    first = run_backfill(repo, service, batch_size=1, force=False)
    resumed = run_backfill(repo, service, batch_size=2, force=False)
    forced = run_backfill(repo, service, batch_size=2, force=True)

    assert first == {"scanned": 2, "success": 0, "failed": 1, "skipped": 1}
    assert resumed == {"scanned": 2, "success": 1, "failed": 0, "skipped": 1}
    assert forced == {"scanned": 2, "success": 2, "failed": 0, "skipped": 0}

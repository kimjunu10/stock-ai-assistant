"""FISA sentiment classification for news-cluster representative article titles."""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from typing import Any

import torch

from app.core.config import Settings, settings

logger = logging.getLogger(__name__)

SENTIMENT_INPUT_VERSION = "cluster_title_v1"
SENTIMENT_MAX_LENGTH = 128
LABEL_BY_INDEX = {0: "negative", 1: "neutral", 2: "positive"}
VALID_LABELS = frozenset((*LABEL_BY_INDEX.values(), "unknown"))


@dataclass(frozen=True)
class SentimentResult:
    label: str
    score: float | None
    positive_score: float | None
    neutral_score: float | None
    negative_score: float | None
    model_id: str
    model_revision: str
    input_version: str = SENTIMENT_INPUT_VERSION
    error: str | None = None


def normalize_sentiment_title(title: str | None) -> str:
    """Normalize only whitespace; the model still receives the representative title alone."""

    return " ".join((title or "").split())


def sentiment_input_hash(title: str | None) -> str:
    normalized = normalize_sentiment_title(title)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def sentiment_state_is_current(
    state: dict[str, Any],
    title: str | None,
    service: NewsSentimentService,
) -> bool:
    return (
        state.get("sentiment_label") not in {None, "unknown"}
        and state.get("sentiment_model") == service.model_id
        and state.get("sentiment_model_revision") == service.model_revision
        and state.get("sentiment_input_version") == SENTIMENT_INPUT_VERSION
        and state.get("sentiment_input_hash") == sentiment_input_hash(title)
    )


def _unknown(model_id: str, model_revision: str, error: str) -> SentimentResult:
    return SentimentResult(
        label="unknown",
        score=None,
        positive_score=None,
        neutral_score=None,
        negative_score=None,
        model_id=model_id,
        model_revision=model_revision,
        error=error,
    )


def label_for_index(index: int) -> str:
    try:
        return LABEL_BY_INDEX[index]
    except KeyError as exc:
        raise ValueError(f"Unexpected FISA sentiment label index: {index}") from exc


class NewsSentimentService:
    """One process-wide tokenizer/model pair with failure-safe inference."""

    def __init__(self, cfg: Settings = settings) -> None:
        self.enabled = cfg.sentiment_enabled
        self.model_id = cfg.sentiment_model_id
        self.model_revision = cfg.sentiment_model_revision
        self.cache_dir = cfg.sentiment_model_cache_dir or None
        self.device_name = cfg.sentiment_device
        self._device = "cpu"
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._load_error: str | None = None
        self._inference_lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self._tokenizer is not None and self._model is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self) -> bool:
        if not self.enabled:
            logger.info("NEWS_SENTIMENT_DISABLED")
            return False
        if self.available:
            return True
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._device = self._resolve_device()
            kwargs: dict[str, Any] = {
                "revision": self.model_revision,
                "trust_remote_code": False,
            }
            if self.cache_dir:
                kwargs["cache_dir"] = self.cache_dir
            tokenizer = AutoTokenizer.from_pretrained(self.model_id, **kwargs)
            model = AutoModelForSequenceClassification.from_pretrained(self.model_id, **kwargs)
            self._validate_label_mapping(model.config.id2label)
            model.to(self._device)
            model.eval()
            self._tokenizer = tokenizer
            self._model = model
            self._load_error = None
            logger.info(
                "NEWS_SENTIMENT_MODEL_READY model=%s revision=%s device=%s",
                self.model_id,
                self.model_revision,
                self._device,
            )
            return True
        except Exception as exc:  # noqa: BLE001 - sentiment must not prevent API startup
            self._tokenizer = None
            self._model = None
            self._load_error = f"{type(exc).__name__}: {exc}"
            logger.exception(
                "NEWS_SENTIMENT_MODEL_UNAVAILABLE model=%s revision=%s",
                self.model_id,
                self.model_revision,
            )
            return False

    def _resolve_device(self) -> str:
        requested = self.device_name.strip().lower()
        if requested == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        if requested not in {"cpu", "cuda"}:
            raise ValueError("SENTIMENT_DEVICE must be auto, cpu, or cuda")
        if requested == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("SENTIMENT_DEVICE=cuda but CUDA is not available")
        return requested

    @staticmethod
    def _validate_label_mapping(id2label: dict[Any, Any]) -> None:
        actual = {int(key): str(value).lower() for key, value in id2label.items()}
        if actual != LABEL_BY_INDEX:
            raise RuntimeError(
                f"Unexpected FISA id2label mapping: expected={LABEL_BY_INDEX}, actual={actual}"
            )

    def analyze(self, title: str) -> SentimentResult:
        return self.analyze_batch([title])[0]

    def analyze_batch(self, titles: list[str]) -> list[SentimentResult]:
        if not titles:
            return []
        normalized = [normalize_sentiment_title(title) for title in titles]
        results: list[SentimentResult | None] = [None] * len(normalized)
        valid_positions = [index for index, title in enumerate(normalized) if title]
        for index, title in enumerate(normalized):
            if not title:
                results[index] = _unknown(self.model_id, self.model_revision, "empty_title")
        if not valid_positions:
            return [result for result in results if result is not None]
        if not self.available:
            reason = self._load_error or "model_not_loaded"
            for index in valid_positions:
                results[index] = _unknown(self.model_id, self.model_revision, reason)
            return [result for result in results if result is not None]

        valid_titles = [normalized[index] for index in valid_positions]
        try:
            with self._inference_lock:
                encoded = self._tokenizer(
                    valid_titles,
                    max_length=SENTIMENT_MAX_LENGTH,
                    truncation=True,
                    padding=len(valid_titles) > 1,
                    return_tensors="pt",
                )
                encoded = {key: value.to(self._device) for key, value in encoded.items()}
                with torch.inference_mode():
                    logits = self._model(**encoded).logits
                    probabilities = torch.softmax(logits, dim=-1).detach().cpu()
            for index, row in zip(valid_positions, probabilities, strict=True):
                values = [float(value) for value in row.tolist()]
                label_index = max(range(len(values)), key=values.__getitem__)
                label = label_for_index(label_index)
                results[index] = SentimentResult(
                    label=label,
                    score=values[label_index],
                    positive_score=values[2],
                    neutral_score=values[1],
                    negative_score=values[0],
                    model_id=self.model_id,
                    model_revision=self.model_revision,
                )
        except Exception as exc:  # noqa: BLE001 - return unknown and keep clustering alive
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("NEWS_SENTIMENT_INFERENCE_FAILED batch_size=%d", len(valid_titles))
            for index in valid_positions:
                results[index] = _unknown(self.model_id, self.model_revision, error)
        return [result for result in results if result is not None]


_service: NewsSentimentService | None = None
_service_lock = threading.Lock()


def initialize_news_sentiment_service(cfg: Settings = settings) -> NewsSentimentService:
    global _service
    with _service_lock:
        if _service is None:
            _service = NewsSentimentService(cfg)
            _service.load()
        return _service


def get_news_sentiment_service(cfg: Settings = settings) -> NewsSentimentService:
    return initialize_news_sentiment_service(cfg)


def reset_news_sentiment_service_for_tests() -> None:
    global _service
    with _service_lock:
        _service = None

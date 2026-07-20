"""OpenDART API 공통 어댑터.

SPEC.md §4-5 (공통 수집·멱등·오류 규칙) 준수:
- 호출 사이 짧은 sleep(기본 0.25초), status=020이면 지수 백오프.
- 외부 호출 재시도 1회. 인증 오류(010/011/012/901)는 재시도 없이 즉시 중단.
- status=013은 실패가 아니라 "데이터 없음"으로 처리.
"""

from __future__ import annotations

import io
import logging
import time
import zipfile
from dataclasses import dataclass, field
from typing import Any

import requests

from app.core.config import Settings

logger = logging.getLogger(__name__)

DART_BASE_URL = "https://opendart.fss.or.kr/api"

# status 코드 분류 (SPEC §4-5)
STATUS_OK = "000"
STATUS_NO_DATA = "013"  # 정상적인 데이터 없음
STATUS_RATE_LIMIT = "020"  # 요청 제한 초과 → 지수 백오프
AUTH_ERROR_STATUSES = {"010", "011", "012", "901"}  # 재시도 없이 중단


class DartAuthError(RuntimeError):
    """인증/키 관련 치명적 오류. 재시도하지 않고 전체 작업을 명확히 중단한다."""


class DartRateLimitError(RuntimeError):
    """요청 제한 초과가 백오프 후에도 지속될 때."""


@dataclass
class DartResult:
    """JSON API 한 번 호출의 정규화된 결과."""

    status: str
    message: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    total_count: int | None = None
    total_page: int | None = None
    page_no: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def no_data(self) -> bool:
        return self.status == STATUS_NO_DATA


class DartClient:
    """OpenDART REST 호출을 감싸는 얇은 클라이언트."""

    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        if not settings.dart_api_key:
            raise RuntimeError("DART_API_KEY is required")
        self._key = settings.dart_api_key
        self._cfg = settings
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": settings.user_agent})

    def close(self) -> None:
        self._session.close()

    # -- 저수준 HTTP -------------------------------------------------------
    def _sleep_between_calls(self) -> None:
        delay = self._cfg.dart_request_delay_seconds
        if delay > 0:
            time.sleep(delay)

    def _get(self, endpoint: str, params: dict[str, Any], *, expect: str) -> requests.Response:
        """단일 GET 호출 + 재시도 1회. expect='json'|'binary'."""

        query = {"crtfc_key": self._key, **params}
        url = f"{DART_BASE_URL}/{endpoint}"
        last_exc: Exception | None = None
        for attempt in range(2):  # 최초 1회 + 재시도 1회 (SPEC §4-5)
            try:
                resp = self._session.get(
                    url, params=query, timeout=self._cfg.dart_request_timeout_seconds
                )
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("DART %s 호출 실패 (시도 %d/2): %s", endpoint, attempt + 1, exc)
                if attempt == 0:
                    time.sleep(min(1.0, self._cfg.dart_request_delay_seconds * 4))
        raise RuntimeError(f"DART {endpoint} 호출이 재시도 후에도 실패") from last_exc

    # -- JSON 엔드포인트 (status 처리 + 백오프) ----------------------------
    def get_json(self, endpoint: str, params: dict[str, Any]) -> DartResult:
        """`.json` 엔드포인트 호출. status에 따라 분류/백오프/중단."""

        backoff = self._cfg.dart_request_delay_seconds or 0.25
        json_endpoint = endpoint if endpoint.endswith(".json") else f"{endpoint}.json"
        while True:
            self._sleep_between_calls()
            resp = self._get(json_endpoint, params, expect="json")
            try:
                payload = resp.json()
            except ValueError as exc:
                raise RuntimeError(f"DART {endpoint} JSON 파싱 실패") from exc

            status = str(payload.get("status", ""))
            message = str(payload.get("message", ""))

            if status in AUTH_ERROR_STATUSES:
                raise DartAuthError(
                    f"DART 인증 오류 status={status} message={message} endpoint={endpoint}"
                )

            if status == STATUS_RATE_LIMIT:
                if backoff > self._cfg.dart_max_backoff_seconds:
                    raise DartRateLimitError(f"DART 요청 제한 지속 status=020 endpoint={endpoint}")
                logger.warning("DART 요청 제한(020) — %.2fs 백오프 후 재시도", backoff)
                time.sleep(backoff)
                backoff *= 2
                continue

            rows = payload.get("list") or []
            if not isinstance(rows, list):
                rows = []
            return DartResult(
                status=status,
                message=message,
                rows=rows,
                total_count=_to_int(payload.get("total_count")),
                total_page=_to_int(payload.get("total_page")),
                page_no=_to_int(payload.get("page_no")),
                raw=payload,
            )

    # -- 바이너리 엔드포인트 (corpCode.xml, document.xml → zip) ------------
    def get_zip_members(self, endpoint: str, params: dict[str, Any]) -> dict[str, bytes]:
        """zip 응답을 파일명→bytes 딕셔너리로 반환.

        corpCode.xml / document.xml 모두 zip으로 반환된다. JSON 오류 응답이
        올 수도 있으므로(예: 인증 오류) content-type/시그니처를 확인한다.
        """

        self._sleep_between_calls()
        resp = self._get(endpoint, params, expect="binary")
        content = resp.content
        if content[:2] != b"PK":
            # zip이 아니면 대개 JSON 오류 응답이다.
            text = content.decode("utf-8", errors="replace")
            if '"status"' in text:
                status = _extract_status(text)
                if status in AUTH_ERROR_STATUSES:
                    raise DartAuthError(f"DART 인증 오류 endpoint={endpoint} body={text[:200]}")
                if status == STATUS_NO_DATA:
                    return {}
            raise RuntimeError(f"DART {endpoint} zip 아님: {text[:200]}")
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            return {name: zf.read(name) for name in zf.namelist()}


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _extract_status(text: str) -> str:
    import re

    m = re.search(r'"status"\s*:\s*"?(\d+)"?', text)
    return m.group(1) if m else ""

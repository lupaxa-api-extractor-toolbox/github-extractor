"""In-memory GitHub responses. No network."""

from __future__ import annotations

from typing import Any

import requests


class FakeResponse:
    """Minimal response with status, JSON, and headers."""

    def __init__(self, status_code: int, payload: Any, headers: dict[str, str] | None = None, *, json_raises: BaseException | None = None, content: bytes | None = None) -> None:
        """Store one canned response."""
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self._json_raises = json_raises
        self.content = content if content is not None else (b"" if status_code == 204 else b"json")

    def json(self) -> Any:
        """Return the canned payload."""
        if self._json_raises is not None:
            raise self._json_raises
        return self._payload


class FakeSession:
    """Return queued responses and record each GET."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        """Queue responses in call order."""
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None, timeout: float) -> FakeResponse:
        """Pop the next canned response."""
        self.calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        if not self._responses:
            message = f"unexpected GET {url}"
            raise AssertionError(message)
        return self._responses.pop(0)


class TimeoutSession(FakeSession):
    """Raise requests.Timeout on the first GET."""

    def get(self, url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None, timeout: float) -> FakeResponse:
        """Record the call, then time out."""
        self.calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        raise requests.Timeout("timed out")

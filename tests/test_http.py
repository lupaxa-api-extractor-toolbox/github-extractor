"""GitHub HTTP requests, paging, and errors."""

from __future__ import annotations

import threading
import time
from typing import Any, cast

import pytest
import requests

from lupaxa.github_extractor import GitHubExtractor
from lupaxa.github_extractor.constants import API_ROOT
from lupaxa.github_extractor.errors import (
    AuthenticationError,
    ForbiddenError,
    NotFoundError,
    RateLimitExceededError,
    RequestError,
    RequestTimeoutError,
)
from lupaxa.github_extractor.http import GitHubHttp
from tests.support import FakeResponse, FakeSession, TimeoutSession

TOKEN = "secret-token"
NEXT_URL = f"{API_ROOT}/user/repos?page=2"


def make_http(session: FakeSession) -> GitHubHttp:
    """Build a client around an in-memory session."""
    return GitHubHttp(
        TOKEN,
        timeout=4.5,
        session=cast(requests.Session, cast(Any, session)),
    )


def test_max_pages_one_does_not_follow_next_link() -> None:
    """The first response counts as page 1."""
    session = FakeSession([FakeResponse(200, [{"id": 1}], {"Link": f'<{API_ROOT}/repos/acme/widget/commits?page=2>; rel="next"'})])
    http = GitHubHttp("secret-token", 10, cast(requests.Session, cast(Any, session)), max_pages=1)

    assert http.get_json("/repos/acme/widget/commits") == [{"id": 1}]
    assert len(session.calls) == 1


def test_max_pages_none_follows_the_next_link() -> None:
    """No cap follows every next link."""
    session = FakeSession(
        [
            FakeResponse(200, [{"id": 1}], {"Link": f'<{API_ROOT}/more>; rel="next"'}),
            FakeResponse(200, [{"id": 2}]),
        ]
    )
    http = GitHubHttp("secret-token", 10, cast(requests.Session, cast(Any, session)), max_pages=None)

    assert http.get_json("/items") == [{"id": 1}, {"id": 2}]


def test_max_pages_zero_is_rejected() -> None:
    """Zero is not a page cap."""
    with pytest.raises(ValueError, match="max_pages must be a positive integer"):
        GitHubExtractor("secret-token", max_pages=0)


def test_http_max_pages_zero_is_rejected() -> None:
    """GitHubHttp rejects zero before any request."""
    with pytest.raises(ValueError, match="max_pages must be a positive integer"):
        GitHubHttp("secret-token", 10, max_pages=0)


def test_api_root_rejects_a_non_https_url() -> None:
    """The API root must be https with a hostname."""
    with pytest.raises(ValueError, match="api_root must be an https URL"):
        GitHubHttp("secret-token", 10, api_root="http://github.example/api/v3")


def test_next_link_on_another_host_is_not_requested() -> None:
    """A next link off the API host is not fetched."""
    session = FakeSession([FakeResponse(200, [{"id": 1}], {"Link": '<https://evil.example/more>; rel="next"'})])
    http = make_http(session)

    with pytest.raises(RequestError, match="Request failed"):
        http.get_json("/items")

    assert len(session.calls) == 1


def test_rate_limit_sleeps_until_reset_and_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reset timestamp is the wait when Retry-After is absent."""
    monkeypatch.setattr(time, "time", lambda: 1_000.0)
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    session = FakeSession(
        [
            FakeResponse(403, {"message": "API rate limit exceeded"}, {"X-RateLimit-Reset": "1005"}),
            FakeResponse(200, [{"id": 1}]),
        ]
    )
    http = GitHubHttp("secret-token", 10, cast(requests.Session, cast(Any, session)))

    assert http.get_json("/user/repos") == [{"id": 1}]
    assert sleeps == [5.0]
    assert len(session.calls) == 2


def test_second_rate_limit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """One retry is the limit."""
    monkeypatch.setattr(time, "time", lambda: 1_000.0)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    session = FakeSession(
        [
            FakeResponse(403, {"message": "API rate limit exceeded"}, {"X-RateLimit-Reset": "1005"}),
            FakeResponse(403, {"message": "API rate limit exceeded"}, {"X-RateLimit-Reset": "1010"}),
        ]
    )
    http = GitHubHttp("secret-token", 10, cast(requests.Session, cast(Any, session)))

    with pytest.raises(RateLimitExceededError):
        http.get_json("/user/repos")
    assert len(session.calls) == 2


def test_invalid_retry_after_uses_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unparseable Retry-After falls back to X-RateLimit-Reset."""
    monkeypatch.setattr(time, "time", lambda: 1_000.0)
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    session = FakeSession(
        [
            FakeResponse(
                403,
                {"message": "API rate limit exceeded"},
                {"Retry-After": "nope", "X-RateLimit-Reset": "1005"},
            ),
            FakeResponse(200, []),
        ]
    )
    http = GitHubHttp("secret-token", 10, cast(requests.Session, cast(Any, session)))

    assert http.get_json("/user/repos") == []
    assert sleeps == [5.0]
    assert len(session.calls) == 2


def test_invalid_retry_after_without_reset_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unparseable Retry-After with no reset raises without sleeping."""
    monkeypatch.setattr(time, "sleep", lambda _seconds: (_ for _ in ()).throw(AssertionError("slept")))
    session = FakeSession(
        [
            FakeResponse(403, {"message": "API rate limit exceeded"}, {"Retry-After": "nope"}),
        ]
    )
    http = GitHubHttp("secret-token", 10, cast(requests.Session, cast(Any, session)))

    with pytest.raises(RateLimitExceededError, match="Rate limit exceeded"):
        http.get_json("/user/repos")
    assert len(session.calls) == 1


def test_retry_after_seconds_is_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """A numeric Retry-After wins over the reset timestamp."""
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    session = FakeSession(
        [
            FakeResponse(403, {"message": "secondary rate limit"}, {"Retry-After": "2", "X-RateLimit-Reset": "999999"}),
            FakeResponse(200, []),
        ]
    )
    http = GitHubHttp("secret-token", 10, cast(requests.Session, cast(Any, session)))

    http.get_json("/user/repos")
    assert sleeps == [2.0]


def test_forbidden_403_does_not_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal forbidden response is not a rate limit."""
    monkeypatch.setattr(time, "sleep", lambda _seconds: (_ for _ in ()).throw(AssertionError("slept")))
    session = FakeSession([FakeResponse(403, {"message": "Resource not accessible"}, {})])
    http = GitHubHttp("secret-token", 10, cast(requests.Session, cast(Any, session)))

    with pytest.raises(ForbiddenError):
        http.get_json("/user/repos")


def test_429_sleeps_for_retry_after_and_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 429 with Retry-After sleeps once and retries the same request."""
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    session = FakeSession(
        [
            FakeResponse(429, {"message": "secret"}, {"Retry-After": "3"}),
            FakeResponse(200, [{"id": 1}]),
        ]
    )

    assert make_http(session).get_json("/items") == [{"id": 1}]
    assert sleeps == [3.0]
    assert len(session.calls) == 2
    assert session.calls[0]["url"] == session.calls[1]["url"]
    assert session.calls[0]["params"] == session.calls[1]["params"]


def test_429_invalid_retry_after_uses_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unparseable Retry-After on 429 falls back to X-RateLimit-Reset."""
    monkeypatch.setattr(time, "time", lambda: 1_000.0)
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    session = FakeSession(
        [
            FakeResponse(
                429,
                {"message": "secret"},
                {"Retry-After": "nope", "X-RateLimit-Reset": "1005"},
            ),
            FakeResponse(200, [{"id": 1}]),
        ]
    )
    http = GitHubHttp("secret-token", 10, cast(requests.Session, cast(Any, session)))

    assert http.get_json("/user/repos") == [{"id": 1}]
    assert sleeps == [5.0]
    assert len(session.calls) == 2


def test_second_429_raises_after_one_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """One 429 retry is the limit."""
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    session = FakeSession(
        [
            FakeResponse(429, {"message": "secret"}, {"Retry-After": "1"}),
            FakeResponse(429, {"message": "secret"}),
        ]
    )
    http = GitHubHttp("secret-token", 10, cast(requests.Session, cast(Any, session)))

    with pytest.raises(RateLimitExceededError, match="Rate limit exceeded"):
        http.get_json("/user/repos")
    assert sleeps == [1.0]
    assert len(session.calls) == 2


def test_429_without_a_wait_does_not_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 429 with no wait header raises before sleeping."""
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    session = FakeSession([FakeResponse(429, {"message": "secret"})])

    with pytest.raises(RateLimitExceededError, match="Rate limit exceeded"):
        make_http(session).get_json("/items")

    assert sleeps == []


def test_max_pages_true_is_rejected() -> None:
    """A boolean is not a page cap."""
    with pytest.raises(ValueError, match="max_pages must be a positive integer"):
        GitHubExtractor("secret-token", max_pages=True)  # type: ignore[arg-type]


def test_worker_session_copies_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    """A worker session receives the owner session proxies."""
    owner = requests.Session()
    owner.proxies = {"https": "http://proxy.example:8080"}
    created: list[Any] = []

    class RecordingSession:
        def __init__(self) -> None:
            created.append(self)
            self.proxies: dict[str, str] = {}

        def get(self, url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None, timeout: float) -> FakeResponse:
            return FakeResponse(200, {"ok": True})

    monkeypatch.setattr("lupaxa.github_extractor.http.requests.Session", RecordingSession)
    http = GitHubHttp("secret-token", 10, session=cast(requests.Session, owner))
    holder: dict[str, Any] = {}

    def run() -> None:
        holder["body"] = http.get_json("/user")

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()

    assert holder["body"] == {"ok": True}
    assert created[0].proxies == {"https": "http://proxy.example:8080"}


def test_worker_requests_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two worker threads can be inside GET at the same time."""
    entered = threading.Barrier(2)
    release = threading.Event()

    class OverlappingSession:
        def get(self, url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None, timeout: float) -> FakeResponse:
            entered.wait(timeout=2)
            release.wait(timeout=2)
            return FakeResponse(200, [{"id": 1}])

    monkeypatch.setattr(requests, "Session", OverlappingSession)
    http = GitHubHttp("secret-token", 10, session=None)
    errors: list[BaseException] = []

    def fetch() -> None:
        try:
            http.get_json("/repos/acme/widget/commits")
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    first = threading.Thread(target=fetch)
    second = threading.Thread(target=fetch)
    first.start()
    second.start()
    first.join(timeout=3)
    second.join(timeout=3)
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert errors == []
    assert not first.is_alive()
    assert not second.is_alive()


def test_list_paging_sends_headers_and_concatenates_pages() -> None:
    """List responses follow the exact next URL and combine each page."""
    session = FakeSession(
        [
            FakeResponse(
                200,
                [{"id": 1}],
                {"Link": f'<{NEXT_URL}>; rel="next"'},
            ),
            FakeResponse(200, [{"id": 2}]),
        ]
    )

    result = make_http(session).get_json("/user/repos")

    assert result == [{"id": 1}, {"id": 2}]
    assert session.calls[0] == {
        "url": f"{API_ROOT}/user/repos",
        "headers": {
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "lupaxa-github-extractor",
        },
        "params": {"per_page": "100"},
        "timeout": 4.5,
    }
    assert session.calls[1]["url"] == NEXT_URL
    assert session.calls[1]["params"] is None


def test_workflow_paging_merges_items_and_recalculates_total() -> None:
    """Workflow dictionaries merge their selected lists across pages."""
    next_url = f"{API_ROOT}/repos/a/b/actions/workflows?page=2"
    session = FakeSession(
        [
            FakeResponse(
                200,
                {"total_count": 4, "workflows": [{"id": 1}]},
                {"Link": f'<{next_url}>; rel="next"'},
            ),
            FakeResponse(
                200,
                {"total_count": 4, "workflows": [{"id": 2}, {"id": 3}]},
            ),
        ]
    )

    result = make_http(session).get_json(
        "/repos/a/b/actions/workflows",
        merge_key="workflows",
    )

    assert result == {
        "total_count": 3,
        "workflows": [{"id": 1}, {"id": 2}, {"id": 3}],
    }


def test_object_pages_concatenate_list_fields_and_keep_the_first_scalar() -> None:
    """List fields grow across pages. Scalars stay from page 1."""
    session = FakeSession(
        [
            FakeResponse(
                200,
                {"total_count": 2, "items": [{"id": 1}]},
                {"Link": f'<{API_ROOT}/search?page=2>; rel="next"'},
            ),
            FakeResponse(200, {"total_count": 99, "items": [{"id": 2}]}),
        ]
    )

    assert make_http(session).get_json("/search") == {"total_count": 2, "items": [{"id": 1}, {"id": 2}]}


def test_object_without_a_list_does_not_follow_its_next_link() -> None:
    """An object with only scalars is the first page."""
    session = FakeSession([FakeResponse(200, {"id": 1}, {"Link": f'<{API_ROOT}/more>; rel="next"'})])

    assert make_http(session).get_json("/user") == {"id": 1}
    assert len(session.calls) == 1


def test_plain_object_returns_without_following_next_link() -> None:
    """A plain object is complete even when a Link header is present."""
    session = FakeSession(
        [
            FakeResponse(
                200,
                {"Python": 12},
                {"Link": f'<{API_ROOT}/unused>; rel="next"'},
            ),
            FakeResponse(200, {"unused": True}),
        ]
    )

    result = make_http(session).get_json("/repos/a/b/languages")

    assert result == {"Python": 12}
    assert len(session.calls) == 1


def test_no_content_returns_empty_list_without_parsing_json() -> None:
    """A successful no-content response represents an empty addon list."""
    session = FakeSession(
        [
            FakeResponse(
                204,
                None,
                json_raises=AssertionError("204 JSON must not be parsed"),
            )
        ]
    )

    assert make_http(session).get_json("/repos/acme/empty/contributors") == []


def test_success_with_invalid_json_raises_safe_request_error() -> None:
    """A non-empty successful response must contain valid JSON."""
    session = FakeSession(
        [
            FakeResponse(
                200,
                None,
                json_raises=ValueError(f"{TOKEN} is not JSON"),
                content=b"not-json",
            )
        ]
    )

    with pytest.raises(RequestError) as exc_info:
        make_http(session).get_json("/user/repos")

    assert TOKEN not in str(exc_info.value)


def test_success_with_empty_body_other_than_204_raises_request_error() -> None:
    """Only a 204 response may safely represent an empty list."""
    session = FakeSession([FakeResponse(200, None, content=b"")])

    with pytest.raises(RequestError):
        make_http(session).get_json("/user/repos")


@pytest.mark.parametrize(
    ("status", "payload", "headers", "error_type"),
    [
        (401, {"message": "Bad credentials"}, {}, AuthenticationError),
        (
            403,
            {"message": "Forbidden"},
            {"X-RateLimit-Remaining": "0"},
            RateLimitExceededError,
        ),
        (403, {"message": "API rate limit exceeded"}, {}, RateLimitExceededError),
        (403, {"message": "Forbidden"}, {"Retry-After": "1"}, RateLimitExceededError),
        (
            403,
            {"message": "Resource not accessible by integration"},
            {"X-RateLimit-Remaining": "50"},
            ForbiddenError,
        ),
        (404, {"message": "Not Found"}, {}, NotFoundError),
        (500, {"message": "Server error"}, {}, RequestError),
    ],
)
def test_status_codes_raise_safe_errors(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    payload: dict[str, str],
    headers: dict[str, str],
    error_type: type[Exception],
) -> None:
    """HTTP failures map to domain errors without exposing the token."""
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    responses = [FakeResponse(status, payload, headers)]
    if headers.get("Retry-After") is not None:
        responses.append(FakeResponse(status, payload, headers))
    session = FakeSession(responses)

    with pytest.raises(error_type) as exc_info:
        make_http(session).get_response("/resource")

    assert TOKEN not in str(exc_info.value)


def test_forbidden_403_with_non_json_body_raises_forbidden_error() -> None:
    """403 without rate-limit headers and invalid JSON maps to ForbiddenError."""
    session = FakeSession(
        [
            FakeResponse(
                403,
                None,
                {},
                json_raises=ValueError("No JSON object could be decoded"),
            )
        ]
    )

    with pytest.raises(ForbiddenError) as exc_info:
        make_http(session).get_response("/resource")

    assert TOKEN not in str(exc_info.value)


def test_timeout_raises_safe_domain_error() -> None:
    """Request timeouts become a token-safe domain error."""
    session = TimeoutSession([])

    with pytest.raises(RequestTimeoutError) as exc_info:
        make_http(session).get_response("/slow")

    assert TOKEN not in str(exc_info.value)

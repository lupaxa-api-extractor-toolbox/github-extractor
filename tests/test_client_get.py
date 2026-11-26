"""Generic read-only GitHub GET."""

from __future__ import annotations

import pytest

from lupaxa.github_extractor import GitHubExtractor
from lupaxa.github_extractor.constants import API_ROOT
from tests.support import FakeResponse, FakeSession


def test_get_pages_a_list() -> None:
    """A list path concatenates later pages."""
    session = FakeSession(
        [
            FakeResponse(200, [{"id": 1}], {"Link": f'<{API_ROOT}/repos/acme/widget/commits?page=2>; rel="next"'}),
            FakeResponse(200, [{"id": 2}]),
        ]
    )
    result = GitHubExtractor("secret-token", session=session).get("/repos/acme/widget/commits")
    assert result == [{"id": 1}, {"id": 2}]
    assert session.calls[0]["params"] == {"per_page": "100"}
    assert session.calls[1]["params"] is None


def test_get_returns_an_object_without_following_link() -> None:
    """A JSON object is returned as a dict."""
    session = FakeSession([FakeResponse(200, {"login": "ada"}, {"Link": f'<{API_ROOT}/unused>; rel="next"'})])
    result = GitHubExtractor("secret-token", session=session).get("/user")
    assert result == {"login": "ada"}
    assert len(session.calls) == 1


def test_get_requests_an_absolute_api_url_with_per_page() -> None:
    """An absolute GitHub API URL is requested unchanged with per_page."""
    session = FakeSession([FakeResponse(200, {"login": "ada"})])

    result = GitHubExtractor("secret-token", session=session).get(f"{API_ROOT}/user")

    assert result == {"login": "ada"}
    assert session.calls[0]["url"] == f"{API_ROOT}/user"
    assert session.calls[0]["params"] == {"per_page": "100"}


def test_get_keeps_an_explicit_per_page() -> None:
    """A per_page query already on the path is not replaced."""
    session = FakeSession([FakeResponse(200, [])])
    GitHubExtractor("secret-token", session=session).get("/repos/acme/widget/commits?per_page=5")
    assert session.calls[0]["params"] == {}


@pytest.mark.parametrize(
    "path",
    [
        "https://example.com/x",
        "//example.com/x",
        "http://api.github.com/user",
        "https://api.github.com.evil.com/x",
        "https://user@api.github.com/user",
    ],
)
def test_get_rejects_a_foreign_target_without_requesting(path: str) -> None:
    """Only api.github.com HTTPS URLs and single-slash paths are fetched."""
    session = FakeSession([])
    with pytest.raises(ValueError, match="path must be a GitHub API path"):
        GitHubExtractor("secret-token", session=session).get(path)
    assert session.calls == []


def test_custom_api_root_is_prefixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Relative paths join the configured API root."""
    session = FakeSession([FakeResponse(200, {"login": "ada"})])
    monkeypatch.setattr("lupaxa.github_extractor.http.requests.Session", lambda: session)
    extractor = GitHubExtractor("secret-token", api_root="https://github.example/api/v3/")

    assert extractor.get("/user") == {"login": "ada"}
    assert session.calls[0]["url"] == "https://github.example/api/v3/user"


def test_absolute_get_on_another_host_is_rejected() -> None:
    """get only accepts the configured API host."""
    extractor = GitHubExtractor("secret-token", api_root="https://github.example/api/v3")

    with pytest.raises(ValueError, match="path must be a GitHub API path"):
        extractor.get("https://api.github.com/user")

"""Client construction, token metadata, and authenticated-user extraction."""

from __future__ import annotations

from typing import Any, cast

import pytest
import requests

from lupaxa.github_extractor import (
    AuthenticationError,
    GitHubExtractor,
    MissingTokenError,
    NotFoundError,
)
from lupaxa.github_extractor.constants import API_ROOT
from lupaxa.github_extractor.models import Repository, ResourceError
from tests.support import FakeResponse, FakeSession

TOKEN = "secret-token"
USER = {"login": "ada", "followers": 1, "following": 2}
WIDGET = {"full_name": "acme/widget", "name": "widget", "owner": {"login": "ada"}}


def _patch_worker_session(monkeypatch: pytest.MonkeyPatch, session: FakeSession) -> None:
    """Make per-thread Session() constructors return the shared fake session."""
    monkeypatch.setattr(
        "lupaxa.github_extractor.http.requests.Session",
        lambda: cast(requests.Session, cast(Any, session)),
    )


def make_extractor(responses: list[FakeResponse]) -> tuple[GitHubExtractor, FakeSession]:
    """Build an extractor and expose its in-memory session."""
    session = FakeSession(responses)
    extractor = GitHubExtractor(
        TOKEN,
        session=cast(requests.Session, cast(Any, session)),
    )
    return extractor, session


@pytest.mark.parametrize("token", ["", "   "])
def test_blank_token_is_rejected_without_requesting_github(token: str) -> None:
    """Blank tokens fail before any GitHub request can be sent."""
    session = FakeSession([])

    with pytest.raises(MissingTokenError):
        GitHubExtractor(
            token,
            session=cast(requests.Session, cast(Any, session)),
        )

    assert session.calls == []


def test_omitted_token_does_not_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The library does not read GITHUB_TOKEN when no token is passed."""
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")

    with pytest.raises(TypeError):
        GitHubExtractor()  # type: ignore[call-arg]


def test_blank_token_does_not_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit blank token is not replaced by the environment."""
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")

    with pytest.raises(MissingTokenError):
        GitHubExtractor("")


def test_nan_timeout_is_rejected_without_requesting_github() -> None:
    """NaN timeouts fail before any GitHub request can be sent."""
    session = FakeSession([])

    with pytest.raises(ValueError, match="timeout must be greater than zero"):
        GitHubExtractor(
            TOKEN,
            timeout=float("nan"),
            session=cast(requests.Session, cast(Any, session)),
        )

    assert session.calls == []


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("timeout", 0),
        ("timeout", -1),
        ("max_workers", 0),
        ("max_workers", True),
        ("max_workers", 1.5),
    ],
)
def test_invalid_constructor_settings_are_rejected(argument: str, value: float | bool) -> None:
    """Timeout and worker settings must meet their documented constraints."""
    kwargs: dict[str, Any] = {argument: value}

    with pytest.raises(ValueError, match="must"):
        GitHubExtractor(TOKEN, **kwargs)


def test_token_information_reads_only_expected_response_headers() -> None:
    """Token metadata comes from the authenticated-user response headers."""
    headers = {
        "X-OAuth-Scopes": "repo, read:user",
        "X-RateLimit-Limit": "5000",
        "X-RateLimit-Remaining": "4998",
        "X-RateLimit-Used": "2",
        "X-RateLimit-Reset": "1730000000",
    }
    extractor, session = make_extractor([FakeResponse(200, USER, headers)])

    result = extractor.token_information()

    assert result.raw == {
        "scopes": "repo, read:user",
        "rate_limit_limit": "5000",
        "rate_limit_remaining": "4998",
        "rate_limit_used": "2",
        "rate_limit_reset": "1730000000",
    }
    assert [call["url"] for call in session.calls] == [f"{API_ROOT}/user"]


def test_token_information_defaults_missing_headers() -> None:
    """Missing scopes default to empty text and rate-limit values to None."""
    extractor, _ = make_extractor([FakeResponse(200, USER)])

    result = extractor.token_information()

    assert result.raw == {
        "scopes": "",
        "rate_limit_limit": None,
        "rate_limit_remaining": None,
        "rate_limit_used": None,
        "rate_limit_reset": None,
    }


def test_authenticated_user_without_extras_makes_one_request() -> None:
    """The default request returns the user object without requesting add-ons."""
    extractor, session = make_extractor([FakeResponse(200, USER)])

    result = extractor.authenticated_user()

    assert result.raw == USER
    assert [call["url"] for call in session.calls] == [f"{API_ROOT}/user"]


def test_authenticated_user_string_resources_make_no_request() -> None:
    """A string is not a list of resource names."""
    extractor, session = make_extractor([])

    with pytest.raises(ValueError, match="resources must be a list of names"):
        extractor.authenticated_user(resources="emails")  # type: ignore[arg-type]

    assert session.calls == []


def test_authenticated_user_string_params_make_no_request() -> None:
    """Params must be a mapping of resource names."""
    extractor, session = make_extractor([])

    with pytest.raises(ValueError, match="params must be a mapping of resource names"):
        extractor.authenticated_user(params="state")  # type: ignore[arg-type]

    assert session.calls == []


@pytest.mark.parametrize(
    ("flag", "path", "stored_key"),
    [
        ("emails", "/user/emails", "emails"),
        ("followers", "/user/followers", "followers"),
        ("following", "/user/following", "following"),
        ("gpg_keys", "/user/gpg_keys", "gpg_keys"),
        ("ssh_keys", "/user/keys", "ssh_keys"),
        ("repos", "/user/repos", "repos"),
        ("starred", "/user/starred", "starred"),
        ("subscriptions", "/user/subscriptions", "subscriptions"),
    ],
)
def test_authenticated_user_stores_each_requested_extra(flag: str, path: str, stored_key: str) -> None:
    """Each optional flag requests and stores its documented add-on."""
    extra = [{"id": 7}]
    extractor, session = make_extractor([FakeResponse(200, USER), FakeResponse(200, extra)])

    result = extractor.authenticated_user(resources=(flag,))

    assert [item.raw for item in getattr(result, stored_key)] == extra
    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/user",
        f"{API_ROOT}{path}",
    ]


def test_authenticated_user_repository_api_fields_stay_raw() -> None:
    """Repository extras preserve unrequested forks and topic names."""
    repository = {
        "full_name": "acme/widget",
        "forks": 3,
        "topics": ["api"],
    }
    extractor, session = make_extractor([FakeResponse(200, USER), FakeResponse(200, [repository])])

    result = extractor.authenticated_user(resources=("repos",))

    assert isinstance(result.repos[0], Repository)
    assert result.repos[0].forks is None
    assert result.repos[0].topics is None
    assert result.repos[0].raw["forks"] == 3
    assert result.repos[0].raw["topics"] == ["api"]
    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/user",
        f"{API_ROOT}/user/repos",
    ]


def test_missing_user_extra_is_recorded_and_omitted() -> None:
    """A missing add-on records a safe error while retaining the user."""
    extractor, _ = make_extractor(
        [
            FakeResponse(200, USER),
            FakeResponse(404, {"message": "Not Found"}),
        ]
    )

    result = extractor.authenticated_user(resources=("emails",))

    assert result.emails == []
    assert result.errors == [ResourceError(addon="emails", status=404, message="Not found")]


def test_user_extra_conflict_is_an_empty_list() -> None:
    """A conflict on a user extra is an empty list plus a recorded error."""
    extractor, _ = make_extractor(
        [
            FakeResponse(200, USER),
            FakeResponse(409, {"message": "secret response"}),
        ]
    )

    result = extractor.authenticated_user(resources=("emails",))

    assert result.emails == []
    assert result.errors == [ResourceError(addon="emails", status=409, message="Conflict")]


def test_authentication_failure_for_user_extra_propagates() -> None:
    """Authentication failures from add-ons are not converted to user errors."""
    extractor, _ = make_extractor(
        [
            FakeResponse(200, USER),
            FakeResponse(401, {"message": "Bad credentials"}),
        ]
    )

    with pytest.raises(AuthenticationError):
        extractor.authenticated_user(resources=("emails",))


def test_notifications_default_to_all() -> None:
    """Notifications request all=true unless the caller sets all."""
    extractor, session = make_extractor(
        [
            FakeResponse(200, USER),
            FakeResponse(200, [{"id": "1", "reason": "mention"}]),
        ]
    )

    result = extractor.authenticated_user(resources=("notifications",))

    assert result.notifications is not None
    assert result.notifications[0].reason == "mention"
    assert session.calls[-1]["params"]["all"] == "true"


def test_missing_authenticated_user_stops_before_extras() -> None:
    """A missing user propagates and prevents all optional requests."""
    extractor, session = make_extractor([FakeResponse(404, {"message": "Not Found"})])

    with pytest.raises(NotFoundError):
        extractor.authenticated_user(resources=("emails",))

    assert [call["url"] for call in session.calls] == [f"{API_ROOT}/user"]


def test_user_repos_receive_repository_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repository extras attach to repos returned with the user."""
    session = FakeSession(
        [
            FakeResponse(200, USER),
            FakeResponse(200, [WIDGET]),
            FakeResponse(200, {"names": ["api"]}),
        ]
    )
    _patch_worker_session(monkeypatch, session)
    extractor = GitHubExtractor(TOKEN, session=cast(requests.Session, cast(Any, session)))

    result = extractor.authenticated_user(resources=("repos",), repository_resources=("topics",))

    assert result.repos is not None
    assert result.repos[0].topics is not None
    assert result.repos[0].topics.names == ["api"]
    assert session.calls[-1]["url"] == f"{API_ROOT}/repos/acme/widget/topics"


def test_repository_resources_without_a_repo_list_makes_no_request() -> None:
    """Nested extras require a user list that contains repositories."""
    extractor, session = make_extractor([])

    with pytest.raises(ValueError, match="repository_resources requires repos, starred, or subscriptions"):
        extractor.authenticated_user(resources=("emails",), repository_resources=("topics",))

    assert session.calls == []


def test_string_repository_resources_make_no_request() -> None:
    """A string is not a list of repository resource names."""
    extractor, session = make_extractor([])

    with pytest.raises(ValueError, match="repository_resources must be a list of names"):
        extractor.authenticated_user(resources=("repos",), repository_resources="topics")  # type: ignore[arg-type]

    assert session.calls == []

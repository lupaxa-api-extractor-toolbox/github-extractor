"""Organisation listing, filtering, aliases, and optional members."""

from __future__ import annotations

from typing import Any, cast

import pytest
import requests

from lupaxa.github_extractor import AuthenticationError, GitHubExtractor
from lupaxa.github_extractor.constants import API_ROOT
from lupaxa.github_extractor.models import ResourceError
from tests.support import FakeResponse, FakeSession

TOKEN = "secret-token"


def make_extractor(monkeypatch: pytest.MonkeyPatch, responses: list[FakeResponse]) -> tuple[GitHubExtractor, FakeSession]:
    """Build an extractor and expose its in-memory session."""
    session = FakeSession(responses)
    monkeypatch.setattr("lupaxa.github_extractor.http.requests.Session", lambda: cast(requests.Session, cast(Any, session)))
    extractor = GitHubExtractor(
        TOKEN,
        session=cast(requests.Session, cast(Any, session)),
    )
    return extractor, session


def test_organisations_are_sorted_by_casefolded_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """Organisation rows are returned in case-insensitive login order."""
    extractor, _ = make_extractor(monkeypatch, [FakeResponse(200, [{"login": "b"}, {"login": "A"}])])

    result = extractor.organisations()

    assert [item.raw for item in result] == [{"login": "A"}, {"login": "b"}]


def test_organisations_apply_include_and_ignore_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Include globs select matches while ignore globs take precedence."""
    extractor, _ = make_extractor(
        monkeypatch,
        [
            FakeResponse(
                200,
                [
                    {"login": "Other"},
                    {"login": "Acme-old"},
                    {"login": "Acme"},
                ],
            )
        ],
    )

    result = extractor.organisations(
        include=["acme*"],
        ignore=["acme-old"],
    )

    assert result[0].raw == {"login": "Acme"}


def test_slug_mode_skips_members_even_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    """Slug mode returns logins without making member requests."""
    extractor, session = make_extractor(monkeypatch, [FakeResponse(200, [{"login": "acme"}])])

    assert extractor.organisations(resources=("members",), slugs=True) == ["acme"]
    assert [call["url"] for call in session.calls] == [f"{API_ROOT}/user/orgs"]


def test_members_are_stored_on_each_organisation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Requested members are stored under the organisation's members key."""
    members = [{"login": "ada"}]
    extractor, session = make_extractor(
        monkeypatch,
        [
            FakeResponse(200, [{"login": "acme"}]),
            FakeResponse(200, members),
        ],
    )

    result = extractor.organisations(resources=("members",))

    assert result[0].raw == {"login": "acme"}
    assert [member.raw for member in result[0].members] == members
    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/user/orgs",
        f"{API_ROOT}/orgs/acme/members",
    ]


def test_missing_members_are_recorded_as_an_addon_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing members endpoint records the required safe error."""
    extractor, _ = make_extractor(
        monkeypatch,
        [
            FakeResponse(200, [{"login": "acme"}]),
            FakeResponse(404, {"message": "Not Found"}),
        ],
    )

    result = extractor.organisations(resources=("members",))

    assert result[0].raw == {"login": "acme"}
    assert result[0].members == []
    assert result[0].errors == [ResourceError(addon="members", status=404, message="Not found")]


def test_organisation_authentication_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """An authentication failure is raised rather than converted to no rows."""
    extractor, _ = make_extractor(monkeypatch, [FakeResponse(401, {"message": "Bad credentials"})])

    with pytest.raises(AuthenticationError):
        extractor.organisations()


def test_audit_log_is_stored_on_the_organisation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The audit log is an organisation resource."""
    extractor, session = make_extractor(
        monkeypatch,
        [
            FakeResponse(200, [{"login": "acme"}]),
            FakeResponse(200, [{"action": "repo.create"}]),
        ],
    )

    result = extractor.organisations(resources=("audit_log",))

    assert result[0].audit_log is not None
    assert result[0].audit_log[0].action == "repo.create"
    assert session.calls[-1]["url"] == f"{API_ROOT}/orgs/acme/audit-log"


def test_organizations_alias_returns_the_same_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """The US-spelling alias delegates to the organisation implementation."""
    rows = [{"login": "acme"}]
    british, _ = make_extractor(monkeypatch, [FakeResponse(200, rows)])
    american, _ = make_extractor(monkeypatch, [FakeResponse(200, rows)])

    assert american.organizations() == british.organisations()

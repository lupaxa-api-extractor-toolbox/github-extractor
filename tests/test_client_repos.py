"""Repository listing, filtering, sorting, and slug behavior."""

from __future__ import annotations

from typing import Any, cast

import pytest
import requests

from lupaxa.github_extractor import AuthenticationError, GitHubExtractor, MissingOrgNameError
from lupaxa.github_extractor.constants import API_ROOT
from tests.support import FakeResponse, FakeSession

TOKEN = "secret-token"


def make_extractor(responses: list[FakeResponse]) -> tuple[GitHubExtractor, FakeSession]:
    """Build an extractor and expose its in-memory session."""
    session = FakeSession(responses)
    extractor = GitHubExtractor(TOKEN, session=cast(requests.Session, cast(Any, session)))
    return extractor, session


@pytest.mark.parametrize("org", ["", "  "])
def test_repositories_by_org_rejects_blank_names_without_get(org: str) -> None:
    """Blank organisation names fail before an HTTP request."""
    extractor, session = make_extractor([])

    with pytest.raises(MissingOrgNameError):
        extractor.repositories_by_org(org)

    assert session.calls == []


def test_user_repositories_keep_only_authenticated_owner() -> None:
    """Authenticated user repositories keep rows owned by that login."""
    ada = {"full_name": "ada/one", "name": "one", "owner": {"login": "ada"}}
    grace = {
        "full_name": "grace/two",
        "name": "two",
        "owner": {"login": "grace"},
    }
    extractor, session = make_extractor([FakeResponse(200, {"login": "ada"}), FakeResponse(200, [grace, ada])])

    result = extractor.user_repositories()

    assert result[0].raw == ada
    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/user",
        f"{API_ROOT}/user/repos",
    ]


def test_named_user_repositories_use_named_endpoint_and_owner() -> None:
    """A named user uses its endpoint and keeps only that owner's rows."""
    grace = {
        "full_name": "grace/two",
        "name": "two",
        "owner": {"login": "grace"},
    }
    other = {"full_name": "ada/one", "name": "one", "owner": {"login": "ada"}}
    extractor, session = make_extractor([FakeResponse(200, [other, grace])])

    result = extractor.user_repositories(username="grace")

    assert result[0].raw == grace
    assert [call["url"] for call in session.calls] == [f"{API_ROOT}/users/grace/repos"]


def test_named_user_owner_comparison_is_case_insensitive() -> None:
    """GitHub's canonical owner casing does not drop a requested user's rows."""
    grace = {
        "full_name": "grace/two",
        "name": "two",
        "owner": {"login": "grace"},
    }
    extractor, _ = make_extractor([FakeResponse(200, [grace])])

    result = extractor.user_repositories(username="Grace")

    assert result[0].raw == grace


def test_named_user_path_segment_is_percent_encoded() -> None:
    """Reserved characters in a requested login stay inside one URL segment."""
    extractor, session = make_extractor([FakeResponse(200, [])])

    assert extractor.user_repositories(username="Grace ?") == []
    assert session.calls[0]["url"] == f"{API_ROOT}/users/Grace%20%3F/repos"


def test_whitespace_username_is_treated_as_omitted() -> None:
    """Whitespace-only usernames use the authenticated user path."""
    extractor, session = make_extractor([FakeResponse(200, {"login": "ada"}), FakeResponse(200, [])])

    assert extractor.user_repositories(username="  ") == []
    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/user",
        f"{API_ROOT}/user/repos",
    ]


def test_visible_repositories_keep_all_owners() -> None:
    """Visible repositories keep every owner returned by GitHub."""
    rows = [
        {"full_name": "grace/two", "name": "two", "owner": {"login": "grace"}},
        {"full_name": "ada/one", "name": "one", "owner": {"login": "ada"}},
    ]
    extractor, _ = make_extractor([FakeResponse(200, rows)])

    result = extractor.visible_repositories()

    assert [item.raw for item in result] == [rows[1], rows[0]]


def test_skip_private_drops_true_but_keeps_missing_key() -> None:
    """Private filtering keeps rows with no private key."""
    private = {"full_name": "ada/a", "name": "a", "private": True}
    unknown = {"full_name": "ada/b", "name": "b"}
    extractor, _ = make_extractor([FakeResponse(200, [private, unknown])])

    result = extractor.visible_repositories(skip_private=True)

    assert result[0].raw == unknown


def test_organisation_repositories_filter_orgs_repos_and_duplicates() -> None:
    """Organisation walking applies org and repo filters before deduplication."""
    first = {"full_name": "acme/keep-one", "name": "keep-one", "id": 1}
    duplicate = {"full_name": "acme/keep-one", "name": "keep-one", "id": 2}
    dropped = {"full_name": "acme/drop", "name": "drop"}
    extractor, session = make_extractor(
        [
            FakeResponse(200, [{"login": "skip-me"}, {"login": "acme"}]),
            FakeResponse(200, [duplicate, dropped, first]),
        ]
    )

    result = extractor.organisation_repositories(ignore_orgs=["skip*"], include=["acme/keep*"])

    assert result[0].raw == duplicate
    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/user/orgs",
        f"{API_ROOT}/orgs/acme/repos",
    ]


def test_repository_results_sort_by_casefolded_full_name() -> None:
    """Repository rows are sorted case-insensitively by full name."""
    rows = [
        {"full_name": "zeta/B", "name": "B"},
        {"full_name": "Acme/a", "name": "a"},
    ]
    extractor, _ = make_extractor([FakeResponse(200, rows)])

    result = extractor.visible_repositories()

    assert [item.raw for item in result] == [rows[1], rows[0]]


def test_slugs_return_full_names() -> None:
    """Slug mode returns repository full names rather than objects."""
    rows = [
        {"full_name": "zeta/B", "name": "B"},
        {"full_name": "Acme/a", "name": "a"},
    ]
    extractor, _ = make_extractor([FakeResponse(200, rows)])

    assert extractor.visible_repositories(slugs=True) == ["Acme/a", "zeta/B"]


def test_org_repository_authentication_failure_propagates() -> None:
    """Authentication errors from an organisation repository request propagate."""
    extractor, _ = make_extractor([FakeResponse(401, {"message": "Bad credentials"})])

    with pytest.raises(AuthenticationError):
        extractor.repositories_by_org("acme")

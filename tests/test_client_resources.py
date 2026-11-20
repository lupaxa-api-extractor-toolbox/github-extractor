"""Named repository and organisation resources."""

from __future__ import annotations

import concurrent.futures
import threading
from typing import Any, cast

import pytest
import requests

from lupaxa.github_extractor import AuthenticationError, GitHubExtractor, RequestError
from lupaxa.github_extractor.constants import API_ROOT
from lupaxa.github_extractor.convert import to_jsonable
from lupaxa.github_extractor.models import Commit, Repository, ResourceError
from tests.support import FakeResponse

TOKEN = "secret-token"
WIDGET = {"full_name": "acme/widget", "name": "widget", "owner": {"login": "ada"}}


class RoutingSession:
    """Return canned responses by URL while recording each GET."""

    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        """Store URL-specific responses."""
        self._responses = responses
        self._lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None, timeout: float) -> FakeResponse:
        """Return the response registered for one URL."""
        with self._lock:
            self.calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
            response = self._responses.get(url)
        if response is None:
            raise AssertionError(f"unexpected GET {url}")
        return response


def _patch_worker_session(monkeypatch: pytest.MonkeyPatch, session: RoutingSession) -> None:
    """Make per-thread Session() constructors return the shared routing session."""
    monkeypatch.setattr(
        "lupaxa.github_extractor.http.requests.Session",
        lambda: cast(requests.Session, cast(Any, session)),
    )


def make_extractor(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, FakeResponse],
) -> tuple[GitHubExtractor, RoutingSession]:
    """Build an extractor backed by URL-routed in-memory responses."""
    session = RoutingSession(responses)
    _patch_worker_session(monkeypatch, session)
    extractor = GitHubExtractor(TOKEN, session=cast(requests.Session, cast(Any, session)))
    return extractor, session


def test_string_resources_make_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """A string is not a list of resource names."""
    extractor, session = make_extractor(monkeypatch, {})

    with pytest.raises(ValueError, match="resources must be a list of names"):
        extractor.user_repositories(username="ada", resources="commits")  # type: ignore[arg-type]

    assert session.calls == []


def test_unknown_repository_resource_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """An organisation-only resource name is rejected before the user request."""
    extractor, session = make_extractor(monkeypatch, {})

    with pytest.raises(ValueError, match="unknown resource: teams"):
        extractor.user_repositories(username="ada", resources=("teams",))

    assert session.calls == []


@pytest.mark.parametrize("name", ["commits", "issues", "pulls", "milestones", "forks", "stargazers", "subscribers"])
def test_each_repository_resource_is_stored(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Each repository resource is fetched from its own path and stored."""
    extractor, session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/users/ada/repos": FakeResponse(200, [WIDGET]),
            f"{API_ROOT}/repos/acme/widget/{name}": FakeResponse(200, [{"id": 1}]),
        },
    )

    result = extractor.user_repositories(username="ada", resources=(name,))

    assert [item.raw for item in getattr(result[0], name)] == [{"id": 1}]
    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/users/ada/repos",
        f"{API_ROOT}/repos/acme/widget/{name}",
    ]


def test_named_repository_result_is_a_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repository row is a Repository and its commits are Commit models."""
    extractor, _session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/users/ada/repos": FakeResponse(200, [WIDGET]),
            f"{API_ROOT}/repos/acme/widget/commits": FakeResponse(200, [{"sha": "abc"}]),
        },
    )

    result = extractor.user_repositories(username="ada", resources=("commits",))

    assert isinstance(result[0], Repository)
    assert result[0].raw["full_name"] == "acme/widget"
    assert isinstance(result[0].commits[0], Commit)
    assert result[0].commits[0].raw == {"sha": "abc"}


def test_repository_api_fields_are_not_attachments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unrequested forks and topic names remain ordinary repository JSON."""
    repository = {**WIDGET, "forks": 3, "topics": ["api"]}
    extractor, session = make_extractor(
        monkeypatch,
        {f"{API_ROOT}/users/ada/repos": FakeResponse(200, [repository])},
    )

    result = extractor.user_repositories(username="ada")

    assert isinstance(result[0], Repository)
    assert result[0].forks is None
    assert result[0].topics is None
    assert result[0].raw["forks"] == 3
    assert result[0].raw["topics"] == ["api"]
    assert [call["url"] for call in session.calls] == [f"{API_ROOT}/users/ada/repos"]


def test_duplicate_resource_names_request_the_path_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repeated resource name is fetched once."""
    extractor, session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/users/ada/repos": FakeResponse(200, [WIDGET]),
            f"{API_ROOT}/repos/acme/widget/commits": FakeResponse(200, [{"id": 1}]),
        },
    )

    extractor.user_repositories(username="ada", resources=("commits", "commits"))

    assert [call["url"] for call in session.calls].count(f"{API_ROOT}/repos/acme/widget/commits") == 1


def test_resource_not_found_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing resource is recorded and the repository is still returned."""
    extractor, _session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/users/ada/repos": FakeResponse(200, [WIDGET]),
            f"{API_ROOT}/repos/acme/widget/commits": FakeResponse(404, {"message": "Not Found"}),
        },
    )

    result = extractor.user_repositories(username="ada", resources=("commits",))

    assert result[0].commits == []
    assert result[0].errors == [ResourceError(addon="commits", status=404, message="Not found")]


def test_commit_conflict_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A commit conflict is recorded and the repository is still returned."""
    extractor, _session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/users/ada/repos": FakeResponse(200, [WIDGET]),
            f"{API_ROOT}/repos/acme/widget/commits": FakeResponse(409, {"message": "secret response"}),
        },
    )

    result = extractor.user_repositories(username="ada", resources=("commits",))

    assert result[0].commits == []
    assert result[0].errors == [ResourceError(addon="commits", status=409, message="Conflict")]


def test_issues_gone_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A gone issues resource is recorded and the repository is returned."""
    extractor, _session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/users/ada/repos": FakeResponse(200, [WIDGET]),
            f"{API_ROOT}/repos/acme/widget/issues": FakeResponse(410, {"message": "secret response"}),
        },
    )

    result = extractor.user_repositories(username="ada", resources=("issues",))

    assert result[0].issues == []
    assert result[0].errors == [ResourceError(addon="issues", status=410, message="Gone")]


def test_branch_conflict_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A branch conflict is recorded and the repository is returned."""
    extractor, _session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/users/ada/repos": FakeResponse(200, [WIDGET]),
            f"{API_ROOT}/repos/acme/widget/branches": FakeResponse(409, {"message": "secret response"}),
        },
    )

    result = extractor.user_repositories(username="ada", resources=("branches",))

    assert result[0].branches == []
    assert result[0].errors == [ResourceError(addon="branches", status=409, message="Conflict")]


def test_failed_languages_and_topics_are_empty_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Languages and topics failures replace the field with an empty list."""
    extractor, _session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/users/ada/repos": FakeResponse(200, [{**WIDGET, "topics": ["api"]}]),
            f"{API_ROOT}/repos/acme/widget/languages": FakeResponse(404, {"message": "Not Found"}),
            f"{API_ROOT}/repos/acme/widget/topics": FakeResponse(409, {"message": "secret response"}),
        },
    )

    result = extractor.user_repositories(username="ada", resources=("languages", "topics"))

    assert result[0].languages == []
    assert result[0].topics == []
    assert "topics" not in result[0].raw
    assert [error.addon for error in result[0].errors] == ["languages", "topics"]


def test_resource_authentication_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Authentication failure while fetching a resource is not swallowed."""
    extractor, _session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/users/ada/repos": FakeResponse(200, [WIDGET]),
            f"{API_ROOT}/repos/acme/widget/commits": FakeResponse(401, {"message": "Bad credentials"}),
        },
    )

    with pytest.raises(AuthenticationError):
        extractor.user_repositories(username="ada", resources=("commits",))


def test_slugs_do_not_request_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Slug mode returns full names and does not fetch resources."""
    extractor, session = make_extractor(monkeypatch, {f"{API_ROOT}/users/ada/repos": FakeResponse(200, [WIDGET])})

    assert extractor.user_repositories(username="ada", resources=("commits",), slugs=True) == ["acme/widget"]
    assert [call["url"] for call in session.calls] == [f"{API_ROOT}/users/ada/repos"]


def test_empty_repository_list_does_not_construct_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    """No repositories means no worker pool, even when a resource was requested."""
    extractor, _session = make_extractor(monkeypatch, {f"{API_ROOT}/users/ada/repos": FakeResponse(200, [])})

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("pool constructed")

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", fail)

    assert extractor.user_repositories(username="ada", resources=("commits",)) == []


def test_repository_name_is_rejected_for_organisations(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repository resource name is rejected before the organisation request."""
    extractor, session = make_extractor(monkeypatch, {})

    with pytest.raises(ValueError, match="unknown resource: commits"):
        extractor.organisations(resources=("commits",))

    assert session.calls == []


@pytest.mark.parametrize("name", ["teams", "events", "hooks"])
def test_each_organisation_resource_is_stored(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Each organisation resource is fetched from its own path and stored."""
    extractor, session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/user/orgs": FakeResponse(200, [{"login": "acme"}]),
            f"{API_ROOT}/orgs/acme/{name}": FakeResponse(200, [{"id": 7}]),
        },
    )

    result = extractor.organisations(resources=(name,))

    assert [item.raw for item in getattr(result[0], name)] == [{"id": 7}]
    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/user/orgs",
        f"{API_ROOT}/orgs/acme/{name}",
    ]


def test_organisation_resource_not_found_is_recorded_after_members(monkeypatch: pytest.MonkeyPatch) -> None:
    """Members are stored, then a missing resource is recorded."""
    extractor, session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/user/orgs": FakeResponse(200, [{"login": "acme"}]),
            f"{API_ROOT}/orgs/acme/members": FakeResponse(200, [{"login": "ada"}]),
            f"{API_ROOT}/orgs/acme/teams": FakeResponse(404, {"message": "Not Found"}),
        },
    )

    result = extractor.organisations(resources=("members", "teams"))

    assert [member.raw for member in result[0].members] == [{"login": "ada"}]
    assert result[0].teams == []
    assert result[0].errors == [ResourceError(addon="teams", status=404, message="Not found")]
    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/user/orgs",
        f"{API_ROOT}/orgs/acme/members",
        f"{API_ROOT}/orgs/acme/teams",
    ]


def test_organisation_resource_conflict_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resource conflict is recorded and the organisation is returned."""
    extractor, _session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/user/orgs": FakeResponse(200, [{"login": "acme"}]),
            f"{API_ROOT}/orgs/acme/teams": FakeResponse(409, {"message": "secret response"}),
        },
    )

    result = extractor.organisations(resources=("teams",))

    assert result[0].teams == []
    assert result[0].errors == [ResourceError(addon="teams", status=409, message="Conflict")]


def test_get_conflict_still_raises_request_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A primary get does not turn a conflict into a recorded resource error."""
    extractor, _session = make_extractor(monkeypatch, {f"{API_ROOT}/user": FakeResponse(409, {"message": "secret response"})})

    with pytest.raises(RequestError, match="Conflict"):
        extractor.get("/user")


def test_slugs_do_not_request_organisation_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Slug mode returns logins and does not fetch resources."""
    extractor, session = make_extractor(monkeypatch, {f"{API_ROOT}/user/orgs": FakeResponse(200, [{"login": "acme"}])})

    assert extractor.organisations(resources=("teams",), slugs=True) == ["acme"]
    assert [call["url"] for call in session.calls] == [f"{API_ROOT}/user/orgs"]


def test_empty_organisation_list_does_not_construct_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    """No organisations means no worker pool."""
    extractor, _session = make_extractor(monkeypatch, {f"{API_ROOT}/user/orgs": FakeResponse(200, [])})

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("pool constructed")

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", fail)

    assert extractor.organisations(resources=("teams",)) == []


def test_issues_default_to_every_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issues request state=all unless the caller sets state."""
    extractor, session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/users/ada/repos": FakeResponse(200, [WIDGET]),
            f"{API_ROOT}/repos/acme/widget/issues": FakeResponse(200, [{"number": 1}]),
        },
    )

    result = extractor.user_repositories(username="ada", resources=("issues",))

    assert result[0].issues is not None
    assert result[0].issues[0].number == 1
    assert session.calls[-1]["params"]["state"] == "all"


def test_issue_state_param_overrides_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller state replaces state=all."""
    extractor, session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/users/ada/repos": FakeResponse(200, [WIDGET]),
            f"{API_ROOT}/repos/acme/widget/issues": FakeResponse(200, []),
        },
    )

    extractor.user_repositories(username="ada", resources=("issues",), params={"issues": {"state": "closed"}})

    assert session.calls[-1]["params"]["state"] == "closed"


def test_unknown_param_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """A params key that was not requested is rejected first."""
    extractor, session = make_extractor(monkeypatch, {})

    with pytest.raises(ValueError, match="unknown resource: issues"):
        extractor.user_repositories(username="ada", resources=("commits",), params={"issues": {"state": "all"}})

    assert session.calls == []


def test_contents_object_becomes_one_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single contents object is stored as a one-item list."""
    extractor, _session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/users/ada/repos": FakeResponse(200, [WIDGET]),
            f"{API_ROOT}/repos/acme/widget/contents": FakeResponse(200, {"name": "README.md", "path": "README.md", "type": "file"}),
        },
    )

    result = extractor.user_repositories(username="ada", resources=("contents",))

    assert result[0].contents is not None
    assert [item.path for item in result[0].contents] == ["README.md"]


def test_workflow_runs_store_the_inner_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Workflow runs drop the wrapper total_count."""
    extractor, _session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/users/ada/repos": FakeResponse(200, [WIDGET]),
            f"{API_ROOT}/repos/acme/widget/actions/runs": FakeResponse(200, {"total_count": 1, "workflow_runs": [{"id": 9, "name": "CI"}]}),
        },
    )

    result = extractor.user_repositories(username="ada", resources=("workflow_runs",))

    assert result[0].workflow_runs is not None
    assert result[0].workflow_runs[0].id == 9
    assert "total_count" not in to_jsonable(result[0])


def test_organizations_forwards_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    """The US spelling alias passes resource names through."""
    extractor, session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/user/orgs": FakeResponse(200, [{"login": "acme"}]),
            f"{API_ROOT}/orgs/acme/teams": FakeResponse(200, [{"id": 7}]),
        },
    )

    result = extractor.organizations(resources=("teams",))

    assert [team.raw for team in result[0].teams] == [{"id": 7}]
    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/user/orgs",
        f"{API_ROOT}/orgs/acme/teams",
    ]


def test_repository_attaches_topics(monkeypatch: pytest.MonkeyPatch) -> None:
    """One repository is fetched and then its extras."""
    extractor, session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/repos/acme/widget": FakeResponse(200, WIDGET),
            f"{API_ROOT}/repos/acme/widget/topics": FakeResponse(200, {"names": ["api"]}),
        },
    )

    result = extractor.repository("acme/widget", resources=("topics",))

    assert result.full_name == "acme/widget"
    assert result.topics is not None
    assert result.topics.names == ["api"]
    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/repos/acme/widget",
        f"{API_ROOT}/repos/acme/widget/topics",
    ]


def test_repository_records_a_missing_extra_as_an_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing extra on one repository is an empty list plus an error."""
    extractor, _session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/repos/acme/widget": FakeResponse(200, WIDGET),
            f"{API_ROOT}/repos/acme/widget/topics": FakeResponse(404, {"message": "Not Found"}),
        },
    )

    result = extractor.repository("acme/widget", resources=("topics",))

    assert result.topics == []
    assert result.errors == [ResourceError(addon="topics", status=404, message="Not found")]


def test_bad_full_name_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """A full name needs an owner and a name."""
    extractor, session = make_extractor(monkeypatch, {})

    with pytest.raises(ValueError, match="full_name must be owner/name"):
        extractor.repository("acme")

    assert session.calls == []

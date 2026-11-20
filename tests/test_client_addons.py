"""Repository add-on fetching and error behavior."""

from __future__ import annotations

import concurrent.futures
import threading
from typing import Any, cast

import pytest
import requests

from lupaxa.github_extractor import AuthenticationError, GitHubExtractor
from lupaxa.github_extractor.constants import API_ROOT
from lupaxa.github_extractor.models import ResourceError
from tests.support import FakeResponse

TOKEN = "secret-token"


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
            self.calls.append(
                {
                    "url": url,
                    "headers": headers,
                    "params": params,
                    "timeout": timeout,
                }
            )
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
    extractor = GitHubExtractor(
        TOKEN,
        session=cast(requests.Session, cast(Any, session)),
    )
    return extractor, session


def test_empty_repository_list_does_not_construct_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty result avoids constructing a thread pool."""

    def reject_executor(*args: object, **kwargs: object) -> None:
        raise AssertionError("ThreadPoolExecutor must not be constructed")

    monkeypatch.setattr(
        concurrent.futures,
        "ThreadPoolExecutor",
        reject_executor,
    )
    extractor, _ = make_extractor(monkeypatch, {f"{API_ROOT}/user/repos": FakeResponse(200, [])})

    assert extractor.visible_repositories(resources=("branches",)) == []


def test_branch_not_found_is_recorded_without_stopping_other_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing branch endpoint records an error on only that repository."""
    alpha = {"full_name": "acme/alpha", "name": "alpha"}
    widget = {"full_name": "acme/widget", "name": "widget"}
    extractor, _ = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/user/repos": FakeResponse(200, [widget, alpha]),
            f"{API_ROOT}/repos/acme/alpha/branches": FakeResponse(404, {"message": "Not Found"}),
            f"{API_ROOT}/repos/acme/widget/branches": FakeResponse(200, [{"name": "main"}]),
        },
    )

    result = extractor.visible_repositories(resources=("branches",))

    assert result[0].raw == alpha
    assert result[0].branches == []
    assert result[0].errors == [ResourceError(addon="branches", status=404, message="Not found")]
    assert result[1].raw == widget
    assert [branch.raw for branch in result[1].branches] == [{"name": "main"}]


def test_branch_authentication_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Authentication failures from an add-on request are not hidden."""
    alpha = {"full_name": "acme/alpha", "name": "alpha"}
    widget = {"full_name": "acme/widget", "name": "widget"}
    extractor, _ = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/user/repos": FakeResponse(200, [alpha, widget]),
            f"{API_ROOT}/repos/acme/alpha/branches": FakeResponse(401, {"message": "Bad credentials"}),
            f"{API_ROOT}/repos/acme/widget/branches": FakeResponse(200, [{"name": "main"}]),
        },
    )

    with pytest.raises(AuthenticationError):
        extractor.visible_repositories(resources=("branches",))


def test_addon_authentication_error_cancels_later_repository_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fatal addon error prevents queued repositories from issuing requests."""
    alpha = {"full_name": "acme/alpha", "name": "alpha"}
    widget = {"full_name": "acme/widget", "name": "widget"}
    session = RoutingSession(
        {
            f"{API_ROOT}/user/repos": FakeResponse(200, [alpha, widget]),
            f"{API_ROOT}/repos/acme/alpha/branches": FakeResponse(401, {"message": "Bad credentials"}),
        }
    )
    _patch_worker_session(monkeypatch, session)
    extractor = GitHubExtractor(
        TOKEN,
        max_workers=1,
        session=cast(requests.Session, cast(Any, session)),
    )

    with pytest.raises(AuthenticationError):
        extractor.visible_repositories(resources=("branches",))

    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/user/repos",
        f"{API_ROOT}/repos/acme/alpha/branches",
    ]


@pytest.mark.parametrize(
    ("flag", "suffix", "payload"),
    [
        ("branches", "branches", [{"name": "main"}]),
        ("contributors", "contributors", [{"login": "ada"}]),
        ("languages", "languages", {"Python": 10}),
        ("releases", "releases", [{"tag_name": "v1.0.0"}]),
        ("tags", "tags", [{"name": "v1.0.0"}]),
        ("topics", "topics", {"names": ["api"]}),
    ],
)
def test_addon_uses_exact_path_and_preserves_payload(monkeypatch: pytest.MonkeyPatch, flag: str, suffix: str, payload: object) -> None:
    """Each standard add-on uses its specified path and storage key."""
    row = {"full_name": "acme/widget", "name": "widget"}
    addon_url = f"{API_ROOT}/repos/acme/widget/{suffix}"
    extractor, session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/user/repos": FakeResponse(200, [row]),
            addon_url: FakeResponse(200, payload),
        },
    )

    result = extractor.visible_repositories(resources=(flag,))

    assert result[0].raw == row
    if flag == "languages":
        assert result[0].languages == payload
    elif flag == "topics":
        assert result[0].topics.raw == payload
    else:
        assert [item.raw for item in getattr(result[0], flag)] == payload
    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/user/repos",
        addon_url,
    ]


def test_workflows_stores_merged_workflows_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """Workflow requests use dictionary pagination and store its object."""
    row = {"full_name": "acme/widget", "name": "widget"}
    workflows = [{"id": 1, "name": "CI"}]
    addon_url = f"{API_ROOT}/repos/acme/widget/actions/workflows"
    extractor, session = make_extractor(
        monkeypatch,
        {
            f"{API_ROOT}/user/repos": FakeResponse(200, [row]),
            addon_url: FakeResponse(200, {"total_count": 1, "workflows": workflows}),
        },
    )

    result = extractor.visible_repositories(resources=("workflows",))

    assert result[0].raw == row
    assert [item.raw for item in result[0].workflows] == workflows
    assert [call["url"] for call in session.calls] == [
        f"{API_ROOT}/user/repos",
        addon_url,
    ]


def test_slug_mode_skips_requested_addons(monkeypatch: pytest.MonkeyPatch) -> None:
    """Slug mode returns full names without requesting add-on endpoints."""
    row = {"full_name": "acme/widget", "name": "widget"}
    extractor, session = make_extractor(monkeypatch, {f"{API_ROOT}/user/repos": FakeResponse(200, [row])})

    assert extractor.visible_repositories(slugs=True, resources=("branches",)) == ["acme/widget"]
    assert [call["url"] for call in session.calls] == [f"{API_ROOT}/user/repos"]


@pytest.mark.parametrize(
    ("method_name", "method_args", "responses"),
    [
        (
            "user_repositories",
            {},
            {
                f"{API_ROOT}/user": FakeResponse(200, {"login": "acme"}),
                f"{API_ROOT}/user/repos": FakeResponse(
                    200,
                    [
                        {
                            "full_name": "acme/widget",
                            "name": "widget",
                            "owner": {"login": "acme"},
                        }
                    ],
                ),
            },
        ),
        (
            "repositories_by_org",
            {"org": "acme"},
            {f"{API_ROOT}/orgs/acme/repos": FakeResponse(200, [{"full_name": "acme/widget", "name": "widget"}])},
        ),
        (
            "visible_repositories",
            {},
            {f"{API_ROOT}/user/repos": FakeResponse(200, [{"full_name": "acme/widget", "name": "widget"}])},
        ),
        (
            "organisation_repositories",
            {},
            {
                f"{API_ROOT}/user/orgs": FakeResponse(200, [{"login": "acme"}]),
                f"{API_ROOT}/orgs/acme/repos": FakeResponse(200, [{"full_name": "acme/widget", "name": "widget"}]),
            },
        ),
    ],
)
def test_every_repository_list_method_fetches_addons(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    method_args: dict[str, str],
    responses: dict[str, FakeResponse],
) -> None:
    """Every repository list method attaches requested add-ons."""
    branches = [{"name": "main"}]
    responses[f"{API_ROOT}/repos/acme/widget/branches"] = FakeResponse(200, branches)
    extractor, _ = make_extractor(monkeypatch, responses)
    method = getattr(extractor, method_name)

    result = method(**method_args, resources=("branches",))

    assert [branch.raw for branch in result[0].branches] == branches

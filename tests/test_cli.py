"""Command-line token resolution, dispatch, output, and errors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import subprocess
from typing import Any

import pytest

from lupaxa.github_extractor import AuthenticationError, ForbiddenError, NotFoundError, RateLimitExceededError, RequestError, cli
from lupaxa.github_extractor.convert import repository_from


class FakeExtractor:
    """Record construction and method calls without using GitHub."""

    instances: list[FakeExtractor] = []
    error: Exception | None = None
    payload: Any = None

    def __init__(self, token: str, timeout: float = 10, max_workers: int = 8, max_pages: int | None = None, *, session: object = None, api_root: str = "https://api.github.com") -> None:
        """Record client settings."""
        self.token = token
        self.timeout = timeout
        self.max_workers = max_workers
        self.max_pages = max_pages
        self.api_root = api_root
        self.calls: list[tuple[str, dict[str, Any]]] = []
        type(self).instances.append(self)

    def _result(self, method: str, **kwargs: Any) -> Any:
        """Record one method call, then raise or return the configured payload."""
        self.calls.append((method, kwargs))
        if self.error is not None:
            raise self.error
        if self.payload is not None:
            return self.payload
        return {"method": method, "token": "[hidden]"}

    def token_information(self) -> dict[str, Any]:
        """Return fake token information."""
        return self._result("token_information")

    def authenticated_user(self, **kwargs: Any) -> dict[str, Any]:
        """Return a fake user."""
        return self._result("authenticated_user", **kwargs)

    def organisations(self, **kwargs: Any) -> dict[str, Any]:
        """Return fake organisations."""
        return self._result("organisations", **kwargs)

    def organizations(self, **kwargs: Any) -> dict[str, Any]:
        """Return fake organizations."""
        return self._result("organizations", **kwargs)

    def user_repositories(self, **kwargs: Any) -> dict[str, Any]:
        """Return fake user repositories."""
        return self._result("user_repositories", **kwargs)

    def repositories_by_org(self, org: str, **kwargs: Any) -> dict[str, Any]:
        """Return fake organisation repositories."""
        return self._result("repositories_by_org", org=org, **kwargs)

    def visible_repositories(self, **kwargs: Any) -> dict[str, Any]:
        """Return fake visible repositories."""
        return self._result("visible_repositories", **kwargs)

    def organisation_repositories(self, **kwargs: Any) -> dict[str, Any]:
        """Return fake repositories across organisations."""
        return self._result("organisation_repositories", **kwargs)

    def repository(self, full_name: str, *, resources: Sequence[str] = (), params: Mapping[str, Mapping[str, str]] | None = None) -> dict[str, Any]:
        """Record a one-repository call."""
        return self._result("repository", full_name=full_name, resources=resources, params=params)

    def get(self, path: str) -> Any:
        """Return a fake generic read."""
        return self._result("get", path=path)


@pytest.fixture(autouse=True)
def fake_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the client and reset its shared records."""
    FakeExtractor.instances = []
    FakeExtractor.error = None
    FakeExtractor.payload = None
    monkeypatch.setattr(cli, "GitHubExtractor", FakeExtractor)


def test_missing_all_token_sources_exits_two(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """An empty environment and missing gh command produce no stdout."""
    monkeypatch.setenv("GITHUB_TOKEN", "")

    def missing_gh(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    monkeypatch.setattr(cli.subprocess, "run", missing_gh)

    assert cli.main(["token"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "A token is required" in captured.err


def test_explicit_token_wins_without_calling_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stripped explicit token takes precedence over every fallback."""
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")

    def unexpected_gh(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("gh must not be called")

    monkeypatch.setattr(cli.subprocess, "run", unexpected_gh)

    assert cli.main(["token", "--token", "  explicit  "]) == 0
    assert FakeExtractor.instances[0].token == "explicit"


def test_environment_token_constructs_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """GITHUB_TOKEN is used when no explicit token is supplied."""
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")

    assert cli.main(["token"]) == 0
    assert FakeExtractor.instances[0].token == "from-env"


def test_gh_token_constructs_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The GitHub CLI is the final token source."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def fake_gh(command: list[str], *, check: bool, capture_output: bool, text: bool, timeout: int) -> subprocess.CompletedProcess[str]:
        assert command == ["gh", "auth", "token"]
        assert (check, capture_output, text, timeout) == (False, True, True, 10)
        return subprocess.CompletedProcess(command, 0, "  from-gh\n", "")

    monkeypatch.setattr(cli.subprocess, "run", fake_gh)

    assert cli.main(["token"]) == 0
    assert FakeExtractor.instances[0].token == "from-gh"


def test_gh_token_timeout_falls_through_to_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stalled GitHub CLI token lookup is treated as unavailable."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def timed_out(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["gh", "auth", "token"], 10)

    monkeypatch.setattr(cli.subprocess, "run", timed_out)

    assert cli.main(["token"]) == 2


def test_token_command_prints_json_without_secret(capsys: pytest.CaptureFixture[str]) -> None:
    """Successful output is indented JSON with a trailing newline."""
    assert cli.main(["token", "--token", "secret"]) == 0

    captured = capsys.readouterr()
    expected = '{\n  "method": "token_information",\n  "token": "[hidden]"\n}\n'
    assert captured.out == expected
    assert captured.err == ""
    assert "secret" not in captured.out


def test_max_pages_reaches_the_client() -> None:
    """The shared flag is the client page cap."""
    assert cli.main(["token", "--max-pages", "3", "--token", "secret"]) == 0
    assert FakeExtractor.instances[0].max_pages == 3


def test_success_json_redacts_resolved_token(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Successful JSON output redacts every resolved token occurrence."""
    secret = "review-secret"

    def leaky_token_information(self: FakeExtractor) -> dict[str, Any]:
        return {"method": "token_information", "token": secret}

    monkeypatch.setattr(FakeExtractor, "token_information", leaky_token_information)

    assert cli.main(["token", "--token", secret]) == 0
    captured = capsys.readouterr()
    expected = '{\n  "method": "token_information",\n  "token": "[redacted]"\n}\n'
    assert captured.out == expected
    assert captured.err == ""
    assert secret not in captured.out
    assert secret not in captured.err
    assert "[redacted]" in captured.out


def test_success_redacts_only_the_resolved_explicit_token(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Output keeps unrelated environment text while redacting the used token."""
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    monkeypatch.setattr(FakeExtractor, "token_information", lambda self: {"used": "used-secret", "environment": "from-env"})

    assert cli.main(["--token", "used-secret", "token"]) == 0
    captured = capsys.readouterr()
    assert "used-secret" not in captured.out
    assert "from-env" in captured.out


def test_circular_payload_serialization_exits_one(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Circular JSON payloads are runtime failures, not usage errors."""
    secret = "review-secret"
    circular: dict[str, Any] = {}
    circular["self"] = circular

    monkeypatch.setattr(FakeExtractor, "token_information", lambda self: circular)

    assert cli.main(["token", "--token", secret]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert secret not in captured.out
    assert secret not in captured.err


def test_runtime_error_redacts_token(capsys: pytest.CaptureFixture[str]) -> None:
    """Unexpected request failures redact every token occurrence."""
    FakeExtractor.error = RequestError("secret blew up; secret")

    assert cli.main(["token", "--token", "secret"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "[redacted] blew up; [redacted]\n"


def test_shared_token_flag_before_command_succeeds_and_is_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    """Shared flags are accepted before the subcommand."""
    secret = "review-secret"

    assert cli.main(["--token", secret, "token"]) == 0
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


def test_malformed_command_redacts_abbreviated_token_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """Argparse token abbreviations never expose the supplied secret."""
    secret = "review-secret"

    assert cli.main(["--tok", secret, "unknown"]) == 2
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


def test_json_serialization_error_redacts_token(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Serialization failures are reported safely as runtime errors."""
    secret = "serialization-secret"
    payload = object()
    monkeypatch.setattr(FakeExtractor, "token_information", lambda self: payload)
    monkeypatch.setattr(cli.json, "dumps", lambda value, **kwargs: (_ for _ in ()).throw(TypeError(f"{secret} failed")))

    assert cli.main(["token", "--token", secret]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert secret not in captured.err
    assert captured.err == "[redacted] failed\n"


@pytest.mark.parametrize(
    ("error", "exit_code"),
    [
        (AuthenticationError(), 3),
        (RateLimitExceededError(), 4),
        (NotFoundError(), 5),
        (ForbiddenError(), 1),
    ],
)
def test_mapped_errors_return_expected_exit_codes(error: Exception, exit_code: int) -> None:
    """Public request errors map to stable process exit codes."""
    FakeExtractor.error = error

    assert cli.main(["token", "--token", "secret"]) == exit_code


def test_zero_timeout_exits_two() -> None:
    """Client validation errors are reported as bad usage."""
    assert cli.main(["token", "--token", "secret", "--timeout", "0"]) == 2


def test_repos_org_requires_org_argument() -> None:
    """Argparse rejects a missing organisation before client construction."""
    assert cli.main(["repos", "org", "--token", "secret"]) == 2
    assert FakeExtractor.instances == []


def test_organisation_repo_filters_are_dispatched() -> None:
    """Organisation and repository globs map to their client keywords."""
    assert (
        cli.main(
            [
                "repos",
                "organisations",
                "--token",
                "secret",
                "--include-org",
                "acme*",
                "--ignore",
                "skip*",
            ]
        )
        == 0
    )
    assert FakeExtractor.instances[0].calls == [
        (
            "organisation_repositories",
            {
                "include_orgs": ["acme*"],
                "ignore_orgs": [],
                "include": [],
                "ignore": ["skip*"],
                "include_names": [],
                "ignore_names": [],
                "skip_private": False,
                "slugs": False,
                "resources": [],
                "params": {},
            },
        )
    ]


def test_user_extra_is_dispatched() -> None:
    """User flags are passed by their Python keyword names."""
    assert cli.main(["user", "--token", "secret", "--emails"]) == 0
    assert FakeExtractor.instances[0].calls[0][0] == "authenticated_user"
    assert FakeExtractor.instances[0].calls[0][1]["resources"] == ["emails"]


def test_named_user_repo_is_dispatched() -> None:
    """The repository username reaches user_repositories."""
    assert cli.main(["repos", "user", "--token", "secret", "--username", "grace"]) == 0
    assert FakeExtractor.instances[0].calls[0][0] == "user_repositories"
    assert FakeExtractor.instances[0].calls[0][1]["username"] == "grace"


def test_repository_flags_fill_resources() -> None:
    """Repository flags become resource names in table order."""
    assert cli.main(["repos", "org", "acme", "--issues", "--workflows", "--commits", "--topics", "--token", "secret"]) == 0
    assert FakeExtractor.instances[0].calls[0][1]["resources"] == ["topics", "workflows", "commits", "issues"]


def test_organisation_flags_fill_resources() -> None:
    """Organisation flags become resource names in table order."""
    assert cli.main(["organisations", "--hooks", "--members", "--teams", "--token", "secret"]) == 0
    assert FakeExtractor.instances[0].calls[0][1]["resources"] == ["members", "teams", "hooks"]


def test_get_command_prints_json(capsys: pytest.CaptureFixture[str]) -> None:
    """The get command prints the client payload and hides the token."""
    FakeExtractor.payload = [{"id": 1}]

    assert cli.main(["get", "/repos/acme/widget/commits", "--token", "secret"]) == 0

    captured = capsys.readouterr()
    assert captured.out == '[\n  {\n    "id": 1\n  }\n]\n'
    assert "secret" not in captured.out
    assert "secret" not in captured.err


def test_repository_model_prints_raw_json(capsys: pytest.CaptureFixture[str]) -> None:
    """CLI output is the GitHub object plus attached resources."""
    FakeExtractor.payload = repository_from({"full_name": "acme/widget", "private": False, "commits": [{"sha": "abc"}]})

    assert cli.main(["repos", "org", "acme", "--token", "secret"]) == 0

    captured = capsys.readouterr()
    assert '"full_name": "acme/widget"' in captured.out
    assert '"sha": "abc"' in captured.out


def test_workflows_print_as_a_list(capsys: pytest.CaptureFixture[str]) -> None:
    """CLI output drops workflow response metadata and prints the workflow list."""
    FakeExtractor.payload = repository_from(
        {
            "full_name": "acme/widget",
            "workflows": {"total_count": 1, "workflows": [{"id": 1, "name": "CI"}]},
        }
    )

    assert cli.main(["repos", "org", "acme", "--token", "secret"]) == 0

    captured = capsys.readouterr()
    assert '"name": "CI"' in captured.out
    assert "total_count" not in captured.out


def test_get_rejects_a_foreign_url(capsys: pytest.CaptureFixture[str]) -> None:
    """A rejected get path is usage exit 2."""
    FakeExtractor.error = ValueError("path must be a GitHub API path")

    assert cli.main(["get", "https://example.com/x", "--token", "secret"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "secret" not in captured.err


def test_repo_command_dispatches_one_repository(capsys: pytest.CaptureFixture[str]) -> None:
    """repo FULL_NAME calls repository with the selected resources."""
    FakeExtractor.payload = {"full_name": "acme/widget"}

    assert cli.main(["repo", "acme/widget", "--topics", "--token", "secret"]) == 0

    assert FakeExtractor.instances[0].calls[0][0] == "repository"
    assert FakeExtractor.instances[0].calls[0][1]["full_name"] == "acme/widget"
    assert FakeExtractor.instances[0].calls[0][1]["resources"] == ["topics"]


def test_repos_organizations_matches_organisations(capsys: pytest.CaptureFixture[str]) -> None:
    """The US spelling lists organisation repositories."""
    FakeExtractor.payload = []

    assert cli.main(["repos", "organizations", "--token", "secret"]) == 0

    assert FakeExtractor.instances[0].calls[0][0] == "organisation_repositories"


def test_param_flag_reaches_the_client(capsys: pytest.CaptureFixture[str]) -> None:
    """--param name.key=value becomes the params mapping. The last value wins."""
    FakeExtractor.payload = []

    assert cli.main(["repos", "org", "acme", "--issues", "--param", "issues.state=open", "--param", "issues.state=closed", "--token", "secret"]) == 0

    assert FakeExtractor.instances[0].calls[0][1]["params"] == {"issues": {"state": "closed"}}


def test_bad_param_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    """A param without name.key=value is a usage error."""
    assert cli.main(["repo", "acme/widget", "--param", "issues", "--token", "secret"]) == 2


def test_user_repository_flags_are_repository_resources(capsys: pytest.CaptureFixture[str]) -> None:
    """Repository flags on user become repository_resources."""
    FakeExtractor.payload = {"login": "ada"}

    assert cli.main(["user", "--repos", "--topics", "--token", "secret"]) == 0

    options = FakeExtractor.instances[0].calls[0][1]
    assert options["resources"] == ["repos"]
    assert options["repository_resources"] == ["topics"]


def test_api_root_is_passed_to_the_client(capsys: pytest.CaptureFixture[str]) -> None:
    """--api-root is the extractor API root."""
    FakeExtractor.payload = []

    assert cli.main(["token", "--api-root", "https://github.example/api/v3", "--token", "secret"]) == 0

    assert FakeExtractor.instances[0].api_root == "https://github.example/api/v3"

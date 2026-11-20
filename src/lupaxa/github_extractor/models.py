"""Dataclass models for GitHub objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class GitHubObject:
    """A GitHub object backed by its raw JSON."""

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceError:
    """An error recorded while fetching an attached resource."""

    addon: str
    status: int
    message: str


def _optional(key: str) -> property:
    """Read a JSON key, or None when GitHub omitted it."""

    def getter(self: GitHubObject) -> Any:  # noqa: ANN401
        return self.raw.get(key)

    return property(getter)


def _required(key: str) -> property:
    """Read a JSON key the client already requires."""

    def getter(self: GitHubObject) -> Any:  # noqa: ANN401
        return self.raw[key]

    return property(getter)


@dataclass
class TokenInformation(GitHubObject):
    """Token metadata and rate-limit information."""

    scopes = _optional("scopes")
    rate_limit_limit = _optional("rate_limit_limit")
    rate_limit_remaining = _optional("rate_limit_remaining")
    rate_limit_used = _optional("rate_limit_used")
    rate_limit_reset = _optional("rate_limit_reset")


@dataclass
class Email(GitHubObject):
    """One email address."""

    email = _optional("email")
    primary = _optional("primary")
    verified = _optional("verified")


@dataclass
class GpgKey(GitHubObject):
    """One GPG key."""

    key_id = _optional("key_id")
    public_key = _optional("public_key")


@dataclass
class SshKey(GitHubObject):
    """One SSH key."""

    id = _optional("id")
    key = _optional("key")
    title = _optional("title")


@dataclass
class Branch(GitHubObject):
    """One repository branch."""

    name = _optional("name")
    protected = _optional("protected")


@dataclass
class Contributor(GitHubObject):
    """One repository contributor."""

    login = _optional("login")
    contributions = _optional("contributions")


@dataclass
class Release(GitHubObject):
    """One repository release."""

    tag_name = _optional("tag_name")
    name = _optional("name")


@dataclass
class Tag(GitHubObject):
    """One repository tag."""

    name = _optional("name")
    commit = _optional("commit")


@dataclass
class Topics(GitHubObject):
    """Repository topic names."""

    names = _optional("names")


@dataclass
class Workflow(GitHubObject):
    """One GitHub Actions workflow."""

    id = _optional("id")
    name = _optional("name")
    state = _optional("state")
    path = _optional("path")


@dataclass
class Commit(GitHubObject):
    """One repository commit."""

    sha = _optional("sha")
    commit = _optional("commit")


@dataclass
class Issue(GitHubObject):
    """One repository issue."""

    number = _optional("number")
    title = _optional("title")
    state = _optional("state")


@dataclass
class PullRequest(GitHubObject):
    """One pull request."""

    number = _optional("number")
    title = _optional("title")
    state = _optional("state")


@dataclass
class Milestone(GitHubObject):
    """One repository milestone."""

    number = _optional("number")
    title = _optional("title")
    state = _optional("state")


@dataclass
class Fork(GitHubObject):
    """One repository fork."""

    full_name = _required("full_name")
    name = _optional("name")
    private = _optional("private")


@dataclass
class Stargazer(GitHubObject):
    """One repository stargazer."""

    login = _required("login")


@dataclass
class Subscriber(GitHubObject):
    """One repository subscriber."""

    login = _required("login")


@dataclass
class Team(GitHubObject):
    """One organisation team."""

    name = _optional("name")
    slug = _optional("slug")


@dataclass
class Event(GitHubObject):
    """One organisation event."""

    id = _optional("id")
    type = _optional("type")


@dataclass
class Hook(GitHubObject):
    """One organisation hook."""

    id = _optional("id")
    name = _optional("name")
    active = _optional("active")


@dataclass
class Collaborator(GitHubObject):
    """One repository collaborator."""

    login = _required("login")


@dataclass
class Label(GitHubObject):
    """One issue label."""

    name = _optional("name")
    color = _optional("color")


@dataclass
class WorkflowRun(GitHubObject):
    """One GitHub Actions workflow run."""

    id = _optional("id")
    name = _optional("name")
    status = _optional("status")
    conclusion = _optional("conclusion")


@dataclass
class Deployment(GitHubObject):
    """One repository deployment."""

    id = _optional("id")
    environment = _optional("environment")
    sha = _optional("sha")


@dataclass
class Environment(GitHubObject):
    """One repository environment."""

    name = _optional("name")


@dataclass
class Content(GitHubObject):
    """One file or directory from the contents list."""

    name = _optional("name")
    path = _optional("path")
    type = _optional("type")


@dataclass
class Notification(GitHubObject):
    """One notification for the authenticated user."""

    id = _optional("id")
    reason = _optional("reason")


@dataclass
class AuditEvent(GitHubObject):
    """One organisation audit-log event."""

    action = _optional("action")


@dataclass
class Repository(GitHubObject):
    """One repository plus the resources that were requested."""

    branches: list[Branch] | None = None
    contributors: list[Contributor] | None = None
    languages: dict[str, int] | list[Any] | None = None
    releases: list[Release] | None = None
    tags: list[Tag] | None = None
    topics: Topics | list[Any] | None = None
    workflows: list[Workflow] | None = None
    commits: list[Commit] | None = None
    issues: list[Issue] | None = None
    pulls: list[PullRequest] | None = None
    milestones: list[Milestone] | None = None
    forks: list[Fork] | None = None
    stargazers: list[Stargazer] | None = None
    subscribers: list[Subscriber] | None = None
    collaborators: list[Collaborator] | None = None
    labels: list[Label] | None = None
    workflow_runs: list[WorkflowRun] | None = None
    deployments: list[Deployment] | None = None
    environments: list[Environment] | None = None
    contents: list[Content] | None = None
    errors: list[ResourceError] = field(default_factory=list)
    attached: ClassVar[tuple[str, ...]] = (
        "branches",
        "contributors",
        "languages",
        "releases",
        "tags",
        "topics",
        "workflows",
        "commits",
        "issues",
        "pulls",
        "milestones",
        "forks",
        "stargazers",
        "subscribers",
        "collaborators",
        "labels",
        "workflow_runs",
        "deployments",
        "environments",
        "contents",
    )
    full_name = _required("full_name")
    name = _optional("name")
    private = _optional("private")


@dataclass
class Organisation(GitHubObject):
    """One organisation plus the resources that were requested."""

    members: list[User] | None = None
    teams: list[Team] | None = None
    events: list[Event] | None = None
    hooks: list[Hook] | None = None
    audit_log: list[AuditEvent] | None = None
    errors: list[ResourceError] = field(default_factory=list)
    attached: ClassVar[tuple[str, ...]] = ("members", "teams", "events", "hooks", "audit_log")
    login = _required("login")
    id = _optional("id")
    description = _optional("description")


@dataclass
class User(GitHubObject):
    """One user plus the resources that were requested."""

    emails: list[Email] | None = None
    followers: list[User] | None = None
    following: list[User] | None = None
    gpg_keys: list[GpgKey] | None = None
    ssh_keys: list[SshKey] | None = None
    repos: list[Repository] | None = None
    starred: list[Repository] | None = None
    subscriptions: list[Repository] | None = None
    notifications: list[Notification] | None = None
    errors: list[ResourceError] = field(default_factory=list)
    attached: ClassVar[tuple[str, ...]] = ("emails", "followers", "following", "gpg_keys", "ssh_keys", "repos", "starred", "subscriptions", "notifications")
    login = _required("login")
    id = _optional("id")
    name = _optional("name")

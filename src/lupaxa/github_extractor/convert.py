"""Build models from GitHub JSON and write them back."""

from __future__ import annotations

from typing import Any

from .models import (
    AuditEvent,
    Branch,
    Collaborator,
    Commit,
    Content,
    Contributor,
    Deployment,
    Email,
    Environment,
    Event,
    Fork,
    GitHubObject,
    GpgKey,
    Hook,
    Issue,
    Label,
    Milestone,
    Notification,
    Organisation,
    PullRequest,
    Release,
    Repository,
    ResourceError,
    SshKey,
    Stargazer,
    Subscriber,
    Tag,
    Team,
    TokenInformation,
    Topics,
    User,
    Workflow,
    WorkflowRun,
)


def _errors_from(rows: list[dict[str, Any]]) -> list[ResourceError]:
    """Build recorded resource errors."""
    return [ResourceError(addon=row["addon"], status=row["status"], message=row["message"]) for row in rows]


def _leaf_models(rows: list[dict[str, Any]], model: type[GitHubObject]) -> list[GitHubObject]:
    """Build leaf models from JSON rows."""
    return [model(raw=dict(row)) for row in rows]


def repository_from(row: dict[str, Any]) -> Repository:
    """Build a repository and its requested attachments."""
    raw = dict(row)
    failed = {row["addon"] for row in raw.get("errors", [])}
    errors = _errors_from(raw.pop("errors", []))
    attachments: dict[str, Any] = {}
    list_attachments = {
        "branches",
        "contributors",
        "releases",
        "tags",
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
    }
    for name in Repository.attached:
        if name not in raw:
            continue
        value = raw[name]
        is_attachment = (
            value is None
            or (name in list_attachments and isinstance(value, list))
            or (name in {"languages", "topics"} and isinstance(value, dict))
            or (name in {"languages", "topics"} and name in failed and value == [])
            or (name == "workflows" and (isinstance(value, list) or (isinstance(value, dict) and isinstance(value.get("workflows"), list))))
        )
        if is_attachment:
            attachments[name] = raw.pop(name)
    model = Repository(raw=raw, errors=errors)
    leaf_types: dict[str, type[GitHubObject]] = {
        "branches": Branch,
        "contributors": Contributor,
        "releases": Release,
        "tags": Tag,
        "commits": Commit,
        "issues": Issue,
        "pulls": PullRequest,
        "milestones": Milestone,
        "forks": Fork,
        "stargazers": Stargazer,
        "subscribers": Subscriber,
        "collaborators": Collaborator,
        "labels": Label,
        "workflow_runs": WorkflowRun,
        "deployments": Deployment,
        "environments": Environment,
        "contents": Content,
    }
    for name, value in attachments.items():
        if value is None or name == "languages" or (name == "topics" and value == []):
            setattr(model, name, value)
        elif name == "topics":
            model.topics = Topics(raw=dict(value))
        elif name == "workflows":
            rows = value["workflows"] if isinstance(value, dict) else value
            model.workflows = [Workflow(raw=dict(item)) for item in rows]
        else:
            setattr(model, name, _leaf_models(value, leaf_types[name]))
    return model


def organisation_from(row: dict[str, Any]) -> Organisation:
    """Build an organisation and its requested attachments."""
    raw = dict(row)
    errors = _errors_from(raw.pop("errors", []))
    attachments = {name: raw.pop(name) for name in Organisation.attached if name in raw and (raw[name] is None or isinstance(raw[name], list))}
    model = Organisation(raw=raw, errors=errors)
    leaf_types: dict[str, type[GitHubObject]] = {"teams": Team, "events": Event, "hooks": Hook, "audit_log": AuditEvent}
    for name, value in attachments.items():
        if value is None:
            setattr(model, name, None)
        elif name == "members":
            model.members = [user_from(item) for item in value]
        else:
            setattr(model, name, _leaf_models(value, leaf_types[name]))
    return model


def user_from(row: dict[str, Any]) -> User:
    """Build a user and its requested attachments."""
    raw = dict(row)
    errors = _errors_from(raw.pop("errors", []))
    attachments = {name: raw.pop(name) for name in User.attached if name in raw and (raw[name] is None or isinstance(raw[name], list))}
    model = User(raw=raw, errors=errors)
    leaf_types: dict[str, type[GitHubObject]] = {"emails": Email, "gpg_keys": GpgKey, "ssh_keys": SshKey, "notifications": Notification}
    for name, value in attachments.items():
        if value is None:
            setattr(model, name, None)
        elif name in {"followers", "following"}:
            setattr(model, name, [user_from(item) for item in value])
        elif name in {"repos", "starred", "subscriptions"}:
            setattr(model, name, [repository_from(item) for item in value])
        else:
            setattr(model, name, _leaf_models(value, leaf_types[name]))
    return model


def token_from(row: dict[str, Any]) -> TokenInformation:
    """Build token information from one JSON object."""
    return TokenInformation(raw=dict(row))


def to_jsonable(value: Any) -> Any:  # noqa: ANN401
    """Return GitHub JSON for a model, list, error, or plain value."""
    if isinstance(value, ResourceError):
        return {"addon": value.addon, "status": value.status, "message": value.message}
    if isinstance(value, GitHubObject):
        payload = dict(value.raw)
        for name in getattr(value, "attached", ()):
            attached = getattr(value, name)
            if attached is not None:
                payload[name] = to_jsonable(attached)
        errors = getattr(value, "errors", [])
        if errors:
            payload["errors"] = to_jsonable(errors)
        return payload
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value

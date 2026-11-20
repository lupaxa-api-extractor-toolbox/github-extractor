"""Optional GitHub resource names and the paths that fetch them."""

from __future__ import annotations

from collections.abc import Sequence

_REPOSITORY_ADDONS = (
    ("branches", "branches", None),
    ("contributors", "contributors", None),
    ("languages", "languages", None),
    ("releases", "releases", None),
    ("tags", "tags", None),
    ("topics", "topics", None),
    ("workflows", "actions/workflows", "workflows"),
    ("commits", "commits", None),
    ("issues", "issues", None),
    ("pulls", "pulls", None),
    ("milestones", "milestones", None),
    ("forks", "forks", None),
    ("stargazers", "stargazers", None),
    ("subscribers", "subscribers", None),
    ("collaborators", "collaborators", None),
    ("labels", "labels", None),
    ("workflow_runs", "actions/runs", "workflow_runs"),
    ("deployments", "deployments", None),
    ("environments", "environments", "environments"),
    ("contents", "contents", None),
)
REPOSITORY_RESOURCES = tuple(name for name, _suffix, _merge_key in _REPOSITORY_ADDONS)
ORGANISATION_RESOURCES = ("members", "teams", "events", "hooks", "audit_log")
_USER_EXTRA_PATHS = {
    "emails": "/user/emails",
    "followers": "/user/followers",
    "following": "/user/following",
    "gpg_keys": "/user/gpg_keys",
    "ssh_keys": "/user/keys",
    "repos": "/user/repos",
    "starred": "/user/starred",
    "subscriptions": "/user/subscriptions",
    "notifications": "/notifications",
}
USER_RESOURCES = tuple(_USER_EXTRA_PATHS)


def normalize_resources(resources: Sequence[str], allowed: tuple[str, ...]) -> list[str]:
    """Keep the first copy of each allowed resource name."""
    if isinstance(resources, str):
        raise ValueError("resources must be a list of names")
    chosen: list[str] = []
    for name in resources:
        if name not in allowed:
            raise ValueError(f"unknown resource: {name}")
        if name not in chosen:
            chosen.append(name)
    return chosen


def repository_addons(names: Sequence[str]) -> list[tuple[str, str, str | None]]:
    """Turn resource names into storage key, path suffix, and merge key."""
    paths = {name: (suffix, merge_key) for name, suffix, merge_key in _REPOSITORY_ADDONS}
    return [(name, paths[name][0], paths[name][1]) for name in names]


def user_resource_path(name: str) -> str:
    """Return the API path for one authenticated-user resource."""
    return _USER_EXTRA_PATHS[name]

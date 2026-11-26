"""High-level GitHub extraction client."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import partial
from typing import Any, cast
from urllib.parse import quote

import requests

from .constants import API_ROOT, DEFAULT_MAX_WORKERS, DEFAULT_TIMEOUT
from .convert import organisation_from, repository_from, token_from, user_from
from .errors import (
    MissingOrgNameError,
    MissingTokenError,
    NotFoundError,
    ResourceStatusError,
)
from .filters import filter_repositories, selected
from .http import GitHubHttp, _normalise_api_root, _same_api_host
from .models import Organisation, Repository, TokenInformation, User
from .pool import run_workers
from .resources import ORGANISATION_RESOURCES, REPOSITORY_RESOURCES, USER_RESOURCES, normalize_resources, repository_addons, user_resource_path

_DEFAULT_QUERIES: dict[str, dict[str, str]] = {
    "issues": {"state": "all"},
    "pulls": {"state": "all"},
    "notifications": {"all": "true"},
}


def _normalize_params(params: object | None, allowed: set[str]) -> dict[str, dict[str, str]]:
    """Return caller queries, or reject a params key this call will not fetch."""
    if params is None:
        return {}
    if isinstance(params, str) or not isinstance(params, Mapping):
        raise ValueError("params must be a mapping of resource names")
    chosen: dict[str, dict[str, str]] = {}
    for name, query in params.items():
        if name not in allowed:
            raise ValueError(f"unknown resource: {name}")
        if isinstance(query, str) or not isinstance(query, Mapping):
            raise ValueError("params must be a mapping of resource names")
        chosen[name] = {str(key): str(value) for key, value in query.items()}
    return chosen


def _query_for(name: str, params: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
    """Return the default query for a resource, overridden by caller pairs."""
    query = dict(_DEFAULT_QUERIES.get(name, {}))
    query.update(params.get(name, {}))
    return query


def _api_target(path: str, api_root: str) -> str:
    """Return a path or absolute URL on the API root, or reject it."""
    target = path.strip()
    if target.startswith("/") and not target.startswith("//"):
        return target
    if _same_api_host(target, api_root):
        return target
    raise ValueError("path must be a GitHub API path")


class GitHubExtractor:
    """Extract authenticated GitHub account data."""

    def __init__(
        self, token: str, timeout: float = DEFAULT_TIMEOUT, max_workers: int = DEFAULT_MAX_WORKERS, *, session: requests.Session | None = None, max_pages: int | None = None, api_root: str = API_ROOT
    ) -> None:
        """Validate client settings and prepare authenticated HTTP access."""
        if not token.strip():
            raise MissingTokenError
        if not timeout > 0:
            raise ValueError("timeout must be greater than zero")
        if type(max_workers) is not int or max_workers <= 0:
            raise ValueError("max_workers must be a positive integer")
        if max_pages is not None and (type(max_pages) is not int or max_pages <= 0):
            raise ValueError("max_pages must be a positive integer")
        self._max_workers = max_workers
        self._api_root = _normalise_api_root(api_root)
        self._http = GitHubHttp(token, timeout, session, max_pages=max_pages, api_root=self._api_root)

    def get(self, path: str) -> Any:  # noqa: ANN401
        """Return JSON from one read-only GitHub API path."""
        return self._http.get_json(_api_target(path, self._api_root))

    def token_information(self) -> TokenInformation:
        """Return token scope and rate-limit information from GitHub headers."""
        headers = self._http.get_response("/user").headers
        return token_from(
            {
                "scopes": headers.get("X-OAuth-Scopes", ""),
                "rate_limit_limit": headers.get("X-RateLimit-Limit"),
                "rate_limit_remaining": headers.get("X-RateLimit-Remaining"),
                "rate_limit_used": headers.get("X-RateLimit-Used"),
                "rate_limit_reset": headers.get("X-RateLimit-Reset"),
            }
        )

    def organisations(
        self, *, include: Sequence[str] = (), ignore: Sequence[str] = (), slugs: bool = False, resources: Sequence[str] = (), params: Mapping[str, Mapping[str, str]] | None = None
    ) -> list[Organisation] | list[str]:
        """Return filtered organisations with optional related data."""
        resource_names = normalize_resources(resources, ORGANISATION_RESOURCES)
        normalized_params = _normalize_params(params, set(resource_names))
        response = cast(list[dict[str, Any]], self._http.get_json("/user/orgs"))
        organisations = [dict(row) for row in response if selected(cast(str, row["login"]), include, ignore)]
        organisations.sort(key=lambda row: cast(str, row["login"]).casefold())
        if slugs:
            return [cast(str, row["login"]) for row in organisations]
        self._attach_organisation_resources(organisations, resource_names, normalized_params)
        return [organisation_from(row) for row in organisations]

    def organizations(
        self, *, include: Sequence[str] = (), ignore: Sequence[str] = (), slugs: bool = False, resources: Sequence[str] = (), params: Mapping[str, Mapping[str, str]] | None = None
    ) -> list[Organisation] | list[str]:
        """Return organisations using the US-spelling alias."""
        return self.organisations(include=include, ignore=ignore, slugs=slugs, resources=resources, params=params)

    def user_repositories(
        self,
        *,
        username: str | None = None,
        include: Sequence[str] = (),
        ignore: Sequence[str] = (),
        include_names: Sequence[str] = (),
        ignore_names: Sequence[str] = (),
        skip_private: bool = False,
        slugs: bool = False,
        resources: Sequence[str] = (),
        params: Mapping[str, Mapping[str, str]] | None = None,
    ) -> list[Repository] | list[str]:
        """Return repositories owned by the requested or authenticated user."""
        resource_names = normalize_resources(resources, REPOSITORY_RESOURCES)
        normalized_params = _normalize_params(params, set(resource_names))
        addons = repository_addons(resource_names)
        login = username.strip() if username is not None else ""
        if login:
            path = f"/users/{_encode_segment(login)}/repos"
        else:
            user = cast(dict[str, Any], self._http.get_json("/user"))
            login = cast(str, user["login"])
            path = "/user/repos"
        rows = cast(list[dict[str, Any]], self._http.get_json(path))
        owned = [row for row in rows if _repository_owner(row).casefold() == login.casefold()]
        return self._repository_result(
            owned,
            include=include,
            ignore=ignore,
            include_names=include_names,
            ignore_names=ignore_names,
            skip_private=skip_private,
            slugs=slugs,
            addons=addons,
            params=normalized_params,
        )

    def repositories_by_org(
        self,
        org: str,
        *,
        include: Sequence[str] = (),
        ignore: Sequence[str] = (),
        include_names: Sequence[str] = (),
        ignore_names: Sequence[str] = (),
        skip_private: bool = False,
        slugs: bool = False,
        resources: Sequence[str] = (),
        params: Mapping[str, Mapping[str, str]] | None = None,
    ) -> list[Repository] | list[str]:
        """Return filtered repositories for one organisation."""
        resource_names = normalize_resources(resources, REPOSITORY_RESOURCES)
        normalized_params = _normalize_params(params, set(resource_names))
        addons = repository_addons(resource_names)
        login = org.strip()
        if not login:
            raise MissingOrgNameError
        rows = cast(list[dict[str, Any]], self._http.get_json(f"/orgs/{_encode_segment(login)}/repos"))
        return self._repository_result(
            rows,
            include=include,
            ignore=ignore,
            include_names=include_names,
            ignore_names=ignore_names,
            skip_private=skip_private,
            slugs=slugs,
            addons=addons,
            params=normalized_params,
        )

    def visible_repositories(
        self,
        *,
        include: Sequence[str] = (),
        ignore: Sequence[str] = (),
        include_names: Sequence[str] = (),
        ignore_names: Sequence[str] = (),
        skip_private: bool = False,
        slugs: bool = False,
        resources: Sequence[str] = (),
        params: Mapping[str, Mapping[str, str]] | None = None,
    ) -> list[Repository] | list[str]:
        """Return every repository visible to the authenticated token."""
        resource_names = normalize_resources(resources, REPOSITORY_RESOURCES)
        normalized_params = _normalize_params(params, set(resource_names))
        addons = repository_addons(resource_names)
        rows = cast(list[dict[str, Any]], self._http.get_json("/user/repos"))
        return self._repository_result(
            rows,
            include=include,
            ignore=ignore,
            include_names=include_names,
            ignore_names=ignore_names,
            skip_private=skip_private,
            slugs=slugs,
            addons=addons,
            params=normalized_params,
        )

    def organisation_repositories(
        self,
        *,
        include_orgs: Sequence[str] = (),
        ignore_orgs: Sequence[str] = (),
        include: Sequence[str] = (),
        ignore: Sequence[str] = (),
        include_names: Sequence[str] = (),
        ignore_names: Sequence[str] = (),
        skip_private: bool = False,
        slugs: bool = False,
        resources: Sequence[str] = (),
        params: Mapping[str, Mapping[str, str]] | None = None,
    ) -> list[Repository] | list[str]:
        """Return filtered repositories from each selected organisation."""
        resource_names = normalize_resources(resources, REPOSITORY_RESOURCES)
        normalized_params = _normalize_params(params, set(resource_names))
        addons = repository_addons(resource_names)
        organisations = cast(list[dict[str, Any]], self._http.get_json("/user/orgs"))
        rows: list[dict[str, Any]] = []
        for organisation in organisations:
            login = cast(str, organisation["login"])
            if selected(login, include_orgs, ignore_orgs):
                rows.extend(cast(list[dict[str, Any]], self._http.get_json(f"/orgs/{_encode_segment(login)}/repos")))
        filtered = filter_repositories(rows, include=include, ignore=ignore, include_names=include_names, ignore_names=ignore_names, skip_private=skip_private)
        unique = list({cast(str, row["full_name"]): row for row in reversed(filtered)}.values())
        self._attach_repository_addons(unique, addons, slugs=slugs, params=normalized_params)
        return _format_repositories(unique, slugs=slugs)

    def repository(self, full_name: str, *, resources: Sequence[str] = (), params: Mapping[str, Mapping[str, str]] | None = None) -> Repository:
        """Return one repository and the extras that were requested."""
        names = normalize_resources(resources, REPOSITORY_RESOURCES)
        queries = _normalize_params(params, set(names))
        owner, separator, name = full_name.strip().partition("/")
        if separator != "/" or not owner or not name:
            raise ValueError("full_name must be owner/name")
        row = dict(cast(dict[str, Any], self._http.get_json(f"/repos/{_encode_full_name(f'{owner}/{name}')}")))
        self._attach_repository_addons([row], repository_addons(names), slugs=False, params=queries)
        return repository_from(row)

    def _repository_result(
        self,
        rows: Sequence[dict[str, Any]],
        *,
        include: Sequence[str],
        ignore: Sequence[str],
        include_names: Sequence[str],
        ignore_names: Sequence[str],
        skip_private: bool,
        slugs: bool,
        addons: list[tuple[str, str, str | None]],
        params: dict[str, dict[str, str]],
    ) -> list[Repository] | list[str]:
        """Filter repositories, attach requested add-ons, and format them."""
        filtered = filter_repositories(rows, include=include, ignore=ignore, include_names=include_names, ignore_names=ignore_names, skip_private=skip_private)
        self._attach_repository_addons(filtered, addons, slugs=slugs, params=params)
        return _format_repositories(filtered, slugs=slugs)

    def _attach_repository_addons(self, repositories: list[dict[str, Any]], addons: list[tuple[str, str, str | None]], *, slugs: bool, params: dict[str, dict[str, str]]) -> None:
        """Attach requested add-ons concurrently to repository objects."""
        if not addons or slugs:
            return
        run_workers(repositories, partial(self._add_repository_addons, addons=addons, params=params), self._max_workers)

    def _add_repository_addons(self, repository: dict[str, Any], addons: list[tuple[str, str, str | None]], params: dict[str, dict[str, str]]) -> None:
        """Fetch enabled add-ons for one repository in flag order."""
        full_name = cast(str, repository["full_name"])
        encoded_full_name = _encode_full_name(full_name)
        for stored_key, suffix, merge_key in addons:
            path = f"/repos/{encoded_full_name}/{suffix}"
            try:
                payload = self._get_addon(path, merge_key, params=_query_for(stored_key, params))
                if merge_key is not None and isinstance(payload, dict):
                    payload = payload.get(merge_key, [])
                if stored_key == "contents" and isinstance(payload, dict):
                    payload = [payload]
                repository[stored_key] = payload
            except NotFoundError as error:
                _record_resource_error(repository, stored_key, 404, str(error))
            except ResourceStatusError as error:
                _record_resource_error(repository, stored_key, error.status, str(error))

    def _get_addon(self, path: str, merge_key: str | None, *, params: dict[str, str] | None = None) -> Any:  # noqa: ANN401
        """Fetch one repository add-on with its required paging mode."""
        if merge_key is None:
            return self._http.get_json(path, params=params)
        return self._http.get_json(path, params=params, merge_key=merge_key)

    def _attach_organisation_resources(self, organisations: list[dict[str, Any]], names: Sequence[str], params: dict[str, dict[str, str]]) -> None:
        """Attach requested resources concurrently to organisation objects."""
        if not names:
            return
        run_workers(organisations, partial(self._add_organisation_resources, names=names, params=params), self._max_workers)

    def _add_organisation_resources(self, organisation: dict[str, Any], names: Sequence[str], params: dict[str, dict[str, str]]) -> None:
        """Store one organisation's requested resources or record a 404, 409, or 410."""
        login = _encode_segment(cast(str, organisation["login"]))
        for name in names:
            suffix = "audit-log" if name == "audit_log" else name
            try:
                organisation[name] = self._get_addon(f"/orgs/{login}/{suffix}", None, params=_query_for(name, params))
            except NotFoundError as error:
                _record_resource_error(organisation, name, 404, str(error))
            except ResourceStatusError as error:
                _record_resource_error(organisation, name, error.status, str(error))

    def authenticated_user(self, *, resources: Sequence[str] = (), repository_resources: Sequence[str] = (), params: Mapping[str, Mapping[str, str]] | None = None) -> User:
        """Return the authenticated user with selected account and repository data."""
        if isinstance(repository_resources, str):
            raise ValueError("repository_resources must be a list of names")
        repo_names = normalize_resources(repository_resources, REPOSITORY_RESOURCES)
        user_names = normalize_resources(resources, USER_RESOURCES)
        if repo_names and not {"repos", "starred", "subscriptions"}.intersection(user_names):
            raise ValueError("repository_resources requires repos, starred, or subscriptions")
        queries = _normalize_params(params, set(user_names).union(repo_names))
        user = dict(cast(dict[str, Any], self._http.get_json("/user")))
        addons = repository_addons(repo_names)
        for name in user_names:
            self._add_user_extra(user, name, user_resource_path(name), repo_addons=addons, params=queries)
        return user_from(user)

    def _add_user_extra(self, user: dict[str, Any], stored_key: str, path: str, *, repo_addons: list[tuple[str, str, str | None]], params: dict[str, dict[str, str]]) -> None:
        """Store one requested user add-on, or an empty list when it fails."""
        try:
            user[stored_key] = self._http.get_json(path, params=_query_for(stored_key, params))
            if repo_addons and stored_key in {"repos", "starred", "subscriptions"}:
                rows = user[stored_key]
                if isinstance(rows, list):
                    self._attach_repository_addons(rows, repo_addons, slugs=False, params=params)
        except NotFoundError as error:
            _record_resource_error(user, stored_key, 404, str(error))
        except ResourceStatusError as error:
            _record_resource_error(user, stored_key, error.status, str(error))


def _record_resource_error(target: dict[str, Any], name: str, status: int, message: str) -> None:
    """Record a failed extra and keep that name as an empty list."""
    errors = cast(list[dict[str, Any]], target.setdefault("errors", []))
    errors.append({"addon": name, "status": status, "message": message})
    target[name] = []


def _format_repositories(rows: list[dict[str, Any]], *, slugs: bool) -> list[Repository] | list[str]:
    """Sort repository rows and return objects or full-name slugs."""
    rows.sort(key=lambda row: cast(str, row["full_name"]).casefold())
    if slugs:
        return [cast(str, row["full_name"]) for row in rows]
    return [repository_from(row) for row in rows]


def _repository_owner(row: dict[str, Any]) -> str:
    """Return a repository owner's login."""
    owner = cast(dict[str, Any], row.get("owner", {}))
    return cast(str, owner.get("login", ""))


def _encode_segment(segment: str) -> str:
    """Percent-encode one dynamic GitHub URL path segment."""
    return quote(segment, safe="")


def _encode_full_name(full_name: str) -> str:
    """Encode a repository owner and name while retaining their separator."""
    owner, repository = full_name.split("/", 1)
    return f"{_encode_segment(owner)}/{_encode_segment(repository)}"

"""Synchronous GitHub HTTP access with paging and safe domain errors."""

from __future__ import annotations

from datetime import UTC
from email.utils import parsedate_to_datetime
import threading
import time
from typing import Any, cast
from urllib.parse import parse_qsl, urlsplit

import requests

from .constants import API_ACCEPT, API_ROOT, API_VERSION, PER_PAGE, USER_AGENT
from .errors import AuthenticationError, ForbiddenError, NotFoundError, RateLimitExceededError, RequestError, RequestTimeoutError, ResourceStatusError


def _normalise_api_root(api_root: str) -> str:
    """Return an https API root, or reject it."""
    root = api_root.strip().rstrip("/")
    parts = urlsplit(root)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("api_root must be an https URL")
    return root


def _copy_session_settings(source: requests.Session, target: requests.Session) -> None:
    """Copy transport settings. Skip attributes the source does not have."""
    if hasattr(source, "proxies"):
        target.proxies = dict(source.proxies)
    for name in ("verify", "cert", "trust_env", "max_redirects"):
        if hasattr(source, name):
            setattr(target, name, getattr(source, name))
    cookies = getattr(source, "cookies", None)
    if cookies is not None and hasattr(cookies, "copy") and hasattr(target, "cookies"):
        target.cookies = cookies.copy()
    adapters = getattr(source, "adapters", None)
    if isinstance(adapters, dict) and hasattr(target, "mount"):
        for prefix, adapter in adapters.items():
            target.mount(prefix, adapter)


def _same_api_host(url: str, api_root: str) -> bool:
    """Return whether a URL is https on the API root host with no userinfo."""
    parts = urlsplit(url)
    root = urlsplit(api_root)
    return parts.scheme == "https" and parts.hostname == root.hostname and parts.username is None and parts.password is None


class GitHubHttp:
    """Send authenticated requests to the GitHub REST API."""

    def __init__(self, token: str, timeout: float, session: requests.Session | None = None, *, max_pages: int | None = None, api_root: str = API_ROOT) -> None:
        """Store request settings and create a session when needed."""
        if max_pages is not None and (type(max_pages) is not int or max_pages <= 0):
            raise ValueError("max_pages must be a positive integer")
        self._api_root = _normalise_api_root(api_root)
        self._owner_thread = threading.get_ident()
        self._local = threading.local()
        self._timeout = timeout
        self._session = session or requests.Session()
        self._lock = threading.Lock()
        self._max_pages = max_pages
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": API_ACCEPT,
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        }

    def get_response(self, path: str) -> requests.Response:
        """Return one checked response without following pagination."""
        return self._get(path, params=None)

    def get_json(self, path: str, *, params: dict[str, Any] | None = None, merge_key: str | None = None) -> Any:  # noqa: ANN401 - JSON may contain any valid JSON value.
        """Return JSON, following list or selected dictionary pagination."""
        query_names = {key for key, _value in parse_qsl(urlsplit(path).query, keep_blank_values=True)}
        request_params = dict(params or {})
        if "per_page" not in query_names and "per_page" not in request_params:
            request_params["per_page"] = PER_PAGE
        response = self._get(path, params=request_params)
        body = _response_json(response)
        if merge_key is not None:
            return self._merge_pages(response, body, merge_key)
        if isinstance(body, list):
            return self._merge_list_pages(response, body)
        if isinstance(body, dict) and _list_keys(body) and _next_url(response) is not None:
            return self._merge_object_pages(response, body)
        return body

    def _request_url(self, path: str) -> str:
        """Join a relative path, or reject an absolute URL on another host."""
        if path.startswith("/") and not path.startswith("//"):
            return f"{self._api_root}{path}"
        if _same_api_host(path, self._api_root):
            return path
        raise RequestError("Request failed")

    def _get(self, path: str, *, params: dict[str, Any] | None, retried: bool = False) -> requests.Response:
        """Send one GET request and map transport and HTTP failures."""
        url = self._request_url(path)
        try:
            response = self._session_for_request().get(url, headers=self._headers, params=params, timeout=self._timeout)
        except requests.Timeout:
            raise RequestTimeoutError("Request timed out") from None
        except requests.RequestException:
            raise RequestError("Request failed") from None
        if not retried and _is_rate_limited(response):
            wait = _rate_limit_wait(response, time.time())
            if wait is None:
                raise RateLimitExceededError("Rate limit exceeded")
            time.sleep(wait)
            return self._get(path, params=params, retried=True)
        self._check_status(response)
        return response

    def _session_for_request(self) -> requests.Session:
        """Use the caller session on its thread and a private session on workers."""
        if threading.get_ident() == self._owner_thread:
            return self._session
        existing = getattr(self._local, "session", None)
        if existing is not None:
            return cast(requests.Session, existing)
        with self._lock:
            existing = getattr(self._local, "session", None)
            if existing is None:
                existing = requests.Session()
                _copy_session_settings(self._session, existing)
                self._local.session = existing
        return cast(requests.Session, existing)

    def _merge_list_pages(self, response: requests.Response, body: list[Any]) -> list[Any]:
        """Follow list pages and concatenate their items."""
        items = list(body)
        pages = 1
        next_url = _next_url(response)
        while next_url is not None and (self._max_pages is None or pages < self._max_pages):
            response = self._get(next_url, params=None)
            pages += 1
            items.extend(cast(list[Any], _response_json(response)))
            next_url = _next_url(response)
        return items

    def _merge_object_pages(self, response: requests.Response, body: dict[str, Any]) -> dict[str, Any]:
        """Concatenate list fields and keep scalars from the first page."""
        merged = dict(body)
        keys = _list_keys(body)
        for key in keys:
            merged[key] = list(merged[key])
        pages = 1
        next_url = _next_url(response)
        while next_url is not None and (self._max_pages is None or pages < self._max_pages):
            response = self._get(next_url, params=None)
            pages += 1
            page = _response_json(response)
            if isinstance(page, dict):
                for key in keys:
                    extra = page.get(key, [])
                    if isinstance(extra, list):
                        cast(list[Any], merged[key]).extend(extra)
            next_url = _next_url(response)
        return merged

    def _merge_pages(self, response: requests.Response, body: object, merge_key: str) -> dict[str, Any]:
        """Follow dictionary pages and merge one selected item list."""
        items = _items_for_key(body, merge_key)
        pages = 1
        next_url = _next_url(response)
        while next_url is not None and (self._max_pages is None or pages < self._max_pages):
            response = self._get(next_url, params=None)
            pages += 1
            items.extend(_items_for_key(_response_json(response), merge_key))
            next_url = _next_url(response)
        return {"total_count": len(items), merge_key: items}

    @staticmethod
    def _check_status(response: requests.Response) -> None:
        """Raise a safe domain error for a failed HTTP status."""
        if response.status_code < 400:
            return
        if response.status_code == 401:
            raise AuthenticationError("Authentication failed")
        if response.status_code == 403:
            if _is_rate_limited(response):
                raise RateLimitExceededError("Rate limit exceeded")
            raise ForbiddenError("Forbidden")
        if response.status_code == 404:
            raise NotFoundError("Not found")
        if response.status_code == 409:
            raise ResourceStatusError(409, "Conflict")
        if response.status_code == 410:
            raise ResourceStatusError(410, "Gone")
        if response.status_code == 429:
            raise RateLimitExceededError("Rate limit exceeded")
        raise RequestError("Request failed")


def _response_json(response: requests.Response) -> Any:  # noqa: ANN401
    """Return successful JSON while mapping empty or invalid bodies safely."""
    if response.status_code == 204:
        return []
    if not response.content:
        raise RequestError("Request returned an empty response")
    try:
        return response.json()
    except ValueError:
        raise RequestError("Request returned invalid JSON") from None


def _list_keys(body: dict[str, Any]) -> list[str]:
    """Return keys whose first-page value is a list."""
    return [key for key, value in body.items() if isinstance(value, list)]


def _items_for_key(body: object, merge_key: str) -> list[Any]:
    """Read a merge list from a dictionary response body."""
    response_body = cast(dict[str, Any], body)
    return list(cast(list[Any], response_body.get(merge_key, [])))


def _is_rate_limited(response: requests.Response) -> bool:
    """Return whether a forbidden response represents rate limiting."""
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    if response.headers.get("X-RateLimit-Remaining") == "0":
        return True
    if response.headers.get("Retry-After") is not None:
        return True
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    message = body.get("message")
    return isinstance(message, str) and "rate limit" in message.casefold()


def _rate_limit_wait(response: requests.Response, now: float) -> float | None:
    """Return the non-negative seconds to wait, or None when no wait is known."""
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(retry_after)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return max(0.0, parsed.timestamp() - now)
            except (ValueError, TypeError):
                pass
    reset = response.headers.get("X-RateLimit-Reset")
    if reset is None:
        return None
    try:
        return max(0.0, float(reset) - now)
    except ValueError:
        return None


def _next_url(response: requests.Response) -> str | None:
    """Extract the next-page URL from a GitHub Link header."""
    link = response.headers.get("Link", "")
    for part in link.split(","):
        if 'rel="next"' not in part:
            continue
        start = part.find("<")
        end = part.find(">", start + 1)
        if start >= 0 and end > start:
            return part[start + 1 : end]
    return None

"""Glob include and ignore filters for organisations and repositories."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import fnmatch
from typing import Any


def selected(value: str, include: Sequence[str], ignore: Sequence[str]) -> bool:
    """Return whether a value passes include and ignore globs."""
    folded = value.casefold()
    for pattern in ignore:
        if fnmatch.fnmatch(folded, pattern.casefold()):
            return False
    if not include:
        return True
    return any(fnmatch.fnmatch(folded, pattern.casefold()) for pattern in include)


def keep_repo(repo: Mapping[str, Any], *, include: Sequence[str], ignore: Sequence[str], include_names: Sequence[str], ignore_names: Sequence[str], skip_private: bool) -> bool:
    """Return whether a repository dict passes repository-level filters."""
    if skip_private and repo.get("private") is True:
        return False
    full_name = str(repo.get("full_name") or "")
    name = str(repo.get("name") or "")
    return selected(full_name, include, ignore) and selected(name, include_names, ignore_names)


def filter_repositories(
    rows: Sequence[Mapping[str, Any]], *, include: Sequence[str], ignore: Sequence[str], include_names: Sequence[str], ignore_names: Sequence[str], skip_private: bool
) -> list[dict[str, Any]]:
    """Copy repository rows that pass all repository filters."""
    return [dict(row) for row in rows if keep_repo(row, include=include, ignore=ignore, include_names=include_names, ignore_names=ignore_names, skip_private=skip_private)]

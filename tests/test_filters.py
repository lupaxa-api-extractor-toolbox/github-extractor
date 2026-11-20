"""Glob include and ignore filters for organisations and repositories."""

from __future__ import annotations

from typing import Any

from lupaxa.github_extractor.filters import keep_repo, selected


def test_selected_include_pattern_match() -> None:
    """A value matching an include pattern is selected."""
    assert selected("Testing", ["test*"], []) is True


def test_selected_ignore_pattern_match() -> None:
    """A value matching an ignore pattern is not selected."""
    assert selected("Testing", [], ["test*"]) is False


def test_selected_include_pattern_no_match() -> None:
    """A value not matching include patterns is not selected."""
    assert selected("Other", ["test*"], []) is False


def test_selected_empty_include_and_ignore() -> None:
    """With no patterns, every value is selected."""
    assert selected("Other", [], []) is True


def test_selected_ignore_wins_over_include() -> None:
    """Ignore patterns take precedence over include patterns."""
    assert selected("Testing", ["test*"], ["testing"]) is False


def test_keep_repo_full_name_include() -> None:
    """A repository matching the full_name include glob is kept."""
    repo: dict[str, Any] = {"full_name": "Acme/Widget", "name": "Widget"}
    assert (
        keep_repo(
            repo,
            include=["acme/*"],
            ignore=[],
            include_names=[],
            ignore_names=[],
            skip_private=False,
        )
        is True
    )


def test_keep_repo_skip_private_true_when_private() -> None:
    """Private repositories are dropped when skip_private is enabled."""
    repo: dict[str, Any] = {
        "full_name": "Acme/Widget",
        "name": "Widget",
        "private": True,
    }
    assert (
        keep_repo(
            repo,
            include=["acme/*"],
            ignore=[],
            include_names=[],
            ignore_names=[],
            skip_private=True,
        )
        is False
    )


def test_keep_repo_skip_private_when_private_absent() -> None:
    """Repositories without a private field are kept when skip_private is on."""
    repo: dict[str, Any] = {"full_name": "Acme/Widget", "name": "Widget"}
    assert (
        keep_repo(
            repo,
            include=["acme/*"],
            ignore=[],
            include_names=[],
            ignore_names=[],
            skip_private=True,
        )
        is True
    )


def test_keep_repo_include_names_can_exclude() -> None:
    """Name include globs can drop repos even when full_name matches."""
    repo: dict[str, Any] = {"full_name": "Acme/Widget", "name": "Widget"}
    assert (
        keep_repo(
            repo,
            include=["acme/*"],
            ignore=[],
            include_names=["nope*"],
            ignore_names=[],
            skip_private=False,
        )
        is False
    )

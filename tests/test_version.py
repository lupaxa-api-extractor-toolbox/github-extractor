"""Version strings stay semantic and agree with each other."""

from __future__ import annotations

from lupaxa.github_extractor import get_version, version as version_mod


def test_version_is_semantic() -> None:
    """Major and minor are numeric. The patch may carry a suffix."""
    assert isinstance(version_mod.__version__, str)
    parts = version_mod.__version__.split(".")
    assert len(parts) >= 2
    assert all(part.isdigit() for part in parts[:2])
    assert get_version() == version_mod.__version__

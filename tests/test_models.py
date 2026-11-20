"""Dataclass models over GitHub JSON."""

from __future__ import annotations

from lupaxa.github_extractor.convert import repository_from, to_jsonable
from lupaxa.github_extractor.models import Commit, Repository, ResourceError, Topics


def test_repository_exposes_raw_and_required_full_name() -> None:
    """The original object is kept and the identity field is required."""
    row = {"full_name": "acme/widget", "name": "widget", "private": False}
    model = repository_from(row)

    assert isinstance(model, Repository)
    assert model.raw == row
    assert model.full_name == "acme/widget"
    assert model.commits is None
    assert model.errors == []


def test_attached_commits_are_models_and_serialise_back() -> None:
    """Attached resources leave raw and return in CLI JSON."""
    model = repository_from({"full_name": "acme/widget", "commits": [{"sha": "abc"}], "languages": {"Python": 10}})

    assert model.commits is not None
    assert isinstance(model.commits[0], Commit)
    assert model.commits[0].raw == {"sha": "abc"}
    assert model.languages == {"Python": 10}
    assert "commits" not in model.raw
    assert to_jsonable(model)["commits"] == [{"sha": "abc"}]
    assert to_jsonable(model)["full_name"] == "acme/widget"


def test_topics_wrap_the_names_object() -> None:
    """Topics are one object, not a list of topic names."""
    model = repository_from({"full_name": "acme/widget", "topics": {"names": ["api"]}})

    assert isinstance(model.topics, Topics)
    assert model.topics.names == ["api"]


def test_repository_scalar_forks_and_topic_names_stay_raw() -> None:
    """Ordinary repository fields are not mistaken for requested attachments."""
    model = repository_from({"full_name": "acme/widget", "forks": 3, "topics": ["api"]})

    assert isinstance(model, Repository)
    assert model.forks is None
    assert model.topics is None
    assert model.raw["forks"] == 3
    assert model.raw["topics"] == ["api"]


def test_errors_become_records() -> None:
    """A recorded addon failure is a ResourceError."""
    model = repository_from({"full_name": "acme/widget", "errors": [{"addon": "commits", "status": 404, "message": "Not found"}]})

    assert model.errors == [ResourceError(addon="commits", status=404, message="Not found")]


def test_recorded_failure_serialises_as_an_empty_list() -> None:
    """A failed extra is present as an empty list beside its error."""
    model = repository_from(
        {
            "full_name": "acme/widget",
            "commits": [],
            "languages": [],
            "topics": [],
            "errors": [
                {"addon": "commits", "status": 404, "message": "Not found"},
                {"addon": "languages", "status": 409, "message": "Conflict"},
                {"addon": "topics", "status": 410, "message": "Gone"},
            ],
        }
    )

    assert model.commits == []
    assert model.languages == []
    assert model.topics == []
    assert "commits" not in model.raw
    assert "languages" not in model.raw
    assert "topics" not in model.raw
    payload = to_jsonable(model)
    assert payload["commits"] == []
    assert payload["languages"] == []
    assert payload["topics"] == []
    assert payload["errors"][0]["addon"] == "commits"


def test_github_topic_names_stay_raw_when_topics_were_not_requested() -> None:
    """An empty topic-name list from GitHub is not a failed topics extra."""
    model = repository_from({"full_name": "acme/widget", "topics": []})

    assert model.topics is None
    assert model.raw["topics"] == []


def test_new_repository_lists_become_models() -> None:
    """New repository extras leave raw and keep their identity fields."""
    model = repository_from(
        {
            "full_name": "acme/widget",
            "collaborators": [{"login": "ada"}],
            "labels": [{"name": "bug", "color": "d73a4a"}],
            "workflow_runs": [{"id": 1, "name": "CI", "status": "completed", "conclusion": "success"}],
            "deployments": [{"id": 2, "environment": "prod", "sha": "abc"}],
            "environments": [{"name": "prod"}],
            "contents": [{"name": "README.md", "path": "README.md", "type": "file"}],
        }
    )

    assert model.collaborators is not None
    assert model.collaborators[0].login == "ada"
    assert model.labels is not None
    assert model.labels[0].name == "bug"
    assert model.workflow_runs is not None
    assert model.workflow_runs[0].conclusion == "success"
    assert model.deployments is not None
    assert model.deployments[0].sha == "abc"
    assert model.environments is not None
    assert model.environments[0].name == "prod"
    assert model.contents is not None
    assert model.contents[0].path == "README.md"
    assert "labels" not in model.raw

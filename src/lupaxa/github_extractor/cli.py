"""Command-line interface for GitHub Extractor."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from contextlib import redirect_stderr
import io
import json
import os
import subprocess
import sys
from typing import Any

from .client import GitHubExtractor
from .constants import API_ROOT, DEFAULT_MAX_WORKERS, DEFAULT_TIMEOUT, GH_AUTH_TIMEOUT
from .convert import to_jsonable
from .errors import (
    AuthenticationError,
    ForbiddenError,
    MissingOrgNameError,
    MissingTokenError,
    NotFoundError,
    RateLimitExceededError,
)
from .resources import ORGANISATION_RESOURCES, REPOSITORY_RESOURCES, USER_RESOURCES


def _selected_flag_names(args: argparse.Namespace, names: tuple[str, ...]) -> list[str]:
    """Return flag names that were set, in table order."""
    return [name for name in names if getattr(args, name)]


def _shared_parser(*, suppress_defaults: bool = False) -> argparse.ArgumentParser:
    """Build options shared by every command."""
    parser = argparse.ArgumentParser(add_help=False)
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument("--token", default=default)
    parser.add_argument(
        "--timeout",
        type=float,
        default=argparse.SUPPRESS if suppress_defaults else DEFAULT_TIMEOUT,
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=argparse.SUPPRESS if suppress_defaults else DEFAULT_MAX_WORKERS,
    )
    parser.add_argument("--max-pages", type=int, default=argparse.SUPPRESS if suppress_defaults else None)
    parser.add_argument("--api-root", default=argparse.SUPPRESS if suppress_defaults else API_ROOT)
    return parser


def _parse_params(values: list[str]) -> dict[str, dict[str, str]]:
    """Turn NAME.KEY=VALUE flags into a params mapping. The last value wins."""
    parsed: dict[str, dict[str, str]] = {}
    for item in values:
        name, dot, rest = item.partition(".")
        key, equals, value = rest.partition("=")
        if not dot or not name or not equals or not key:
            raise ValueError("param must be name.key=value")
        parsed.setdefault(name, {})[key] = value
    return parsed


def _add_param_option(parser: argparse.ArgumentParser) -> None:
    """Add repeatable query-parameter flags to a parser."""
    parser.add_argument("--param", action="append", default=[])


def _add_resource_flags(parser: argparse.ArgumentParser, names: tuple[str, ...]) -> None:
    """Add boolean resource flags; argparse dest keeps the Python name."""
    for flag in names:
        parser.add_argument(f"--{flag.replace('_', '-')}", action="store_true")


def _add_organisation_options(parser: argparse.ArgumentParser) -> None:
    """Add organisation-list options to a parser."""
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--ignore", action="append", default=[])
    parser.add_argument("--slugs", action="store_true")
    _add_resource_flags(parser, ORGANISATION_RESOURCES)
    _add_param_option(parser)


def _add_repository_resource_options(parser: argparse.ArgumentParser) -> None:
    """Add repository resource flags and query parameters to a parser."""
    _add_resource_flags(parser, REPOSITORY_RESOURCES)
    _add_param_option(parser)


def _add_repository_options(parser: argparse.ArgumentParser) -> None:
    """Add repository filters and addon flags to a parser."""
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--ignore", action="append", default=[])
    parser.add_argument("--include-name", action="append", default=[])
    parser.add_argument("--ignore-name", action="append", default=[])
    parser.add_argument("--skip-private", action="store_true")
    parser.add_argument("--slugs", action="store_true")
    _add_resource_flags(parser, REPOSITORY_RESOURCES)
    _add_param_option(parser)


def _add_user_options(parser: argparse.ArgumentParser) -> None:
    """Add authenticated-user extra flags to a parser."""
    _add_resource_flags(parser, USER_RESOURCES)
    _add_resource_flags(parser, REPOSITORY_RESOURCES)
    _add_param_option(parser)


def build_parser() -> argparse.ArgumentParser:
    """Build the complete command-line parser."""
    parser = argparse.ArgumentParser(
        prog="github-extractor",
        parents=[_shared_parser()],
    )
    shared = _shared_parser(suppress_defaults=True)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("token", parents=[shared])

    get_command = commands.add_parser("get", parents=[shared])
    get_command.add_argument("path")

    user = commands.add_parser("user", parents=[shared])
    _add_user_options(user)

    repo = commands.add_parser("repo", parents=[shared])
    repo.add_argument("full_name")
    _add_repository_resource_options(repo)

    for name in ("organisations", "organizations"):
        organisation = commands.add_parser(name, parents=[shared])
        _add_organisation_options(organisation)

    repos = commands.add_parser("repos", parents=[shared])
    repo_commands = repos.add_subparsers(dest="repo_command", required=True)

    repo_user = repo_commands.add_parser("user", parents=[shared])
    _add_repository_options(repo_user)
    repo_user.add_argument("--username")

    repo_org = repo_commands.add_parser("org", parents=[shared])
    repo_org.add_argument("org")
    _add_repository_options(repo_org)

    repo_visible = repo_commands.add_parser("visible", parents=[shared])
    _add_repository_options(repo_visible)

    repo_organisations = repo_commands.add_parser(
        "organisations",
        parents=[shared],
    )
    _add_repository_options(repo_organisations)
    repo_organisations.add_argument("--include-org", action="append", default=[])
    repo_organisations.add_argument("--ignore-org", action="append", default=[])

    repo_organizations = repo_commands.add_parser(
        "organizations",
        parents=[shared],
    )
    _add_repository_options(repo_organizations)
    repo_organizations.add_argument("--include-org", action="append", default=[])
    repo_organizations.add_argument("--ignore-org", action="append", default=[])
    return parser


def resolve_token(explicit: str | None) -> str:
    """Resolve a token from an argument, environment, or GitHub CLI."""
    token = explicit.strip() if explicit is not None else ""
    if token:
        return token
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],  # noqa: S607
            check=False,
            capture_output=True,
            text=True,
            timeout=GH_AUTH_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is not None and result.returncode == 0:
        token = result.stdout.strip()
        if token:
            return token
    raise MissingTokenError


def _user_options(args: argparse.Namespace) -> dict[str, Any]:
    """Return authenticated-user options from parsed arguments."""
    return {
        "resources": _selected_flag_names(args, USER_RESOURCES),
        "repository_resources": _selected_flag_names(args, REPOSITORY_RESOURCES),
        "params": _parse_params(args.param),
    }


def _organisation_options(args: argparse.Namespace) -> dict[str, Any]:
    """Return organisation options from parsed arguments."""
    return {
        "include": args.include,
        "ignore": args.ignore,
        "slugs": args.slugs,
        "resources": _selected_flag_names(args, ORGANISATION_RESOURCES),
        "params": _parse_params(args.param),
    }


def _repository_options(args: argparse.Namespace) -> dict[str, Any]:
    """Return repository options from parsed arguments."""
    return {
        "include": args.include,
        "ignore": args.ignore,
        "include_names": args.include_name,
        "ignore_names": args.ignore_name,
        "skip_private": args.skip_private,
        "slugs": args.slugs,
        "resources": _selected_flag_names(args, REPOSITORY_RESOURCES),
        "params": _parse_params(args.param),
    }


def _dispatch_repositories(client: GitHubExtractor, args: argparse.Namespace) -> Any:  # noqa: ANN401
    """Dispatch one repository subcommand."""
    options = _repository_options(args)
    handlers: dict[str, Callable[[], Any]] = {
        "user": lambda: client.user_repositories(
            username=args.username,
            **options,
        ),
        "org": lambda: client.repositories_by_org(args.org, **options),
        "visible": lambda: client.visible_repositories(**options),
        "organisations": lambda: client.organisation_repositories(
            include_orgs=args.include_org,
            ignore_orgs=args.ignore_org,
            **options,
        ),
        "organizations": lambda: client.organisation_repositories(
            include_orgs=args.include_org,
            ignore_orgs=args.ignore_org,
            **options,
        ),
    }
    return handlers[args.repo_command]()


def dispatch(client: GitHubExtractor, args: argparse.Namespace) -> Any:  # noqa: ANN401
    """Dispatch one top-level command to the client."""
    handlers: dict[str, Callable[[], Any]] = {
        "token": client.token_information,
        "get": lambda: client.get(args.path),
        "user": lambda: client.authenticated_user(**_user_options(args)),
        "organisations": lambda: client.organisations(**_organisation_options(args)),
        "organizations": lambda: client.organizations(**_organisation_options(args)),
        "repos": lambda: _dispatch_repositories(client, args),
        "repo": lambda: client.repository(
            args.full_name,
            resources=_selected_flag_names(args, REPOSITORY_RESOURCES),
            params=_parse_params(args.param),
        ),
    }
    return handlers[args.command]()


def _exit_code(error: Exception) -> int:
    """Map a public error to its process exit code."""
    if isinstance(error, (MissingTokenError, MissingOrgNameError, ValueError)):
        return 2
    if isinstance(error, AuthenticationError):
        return 3
    if isinstance(error, RateLimitExceededError):
        return 4
    if isinstance(error, NotFoundError):
        return 5
    if isinstance(error, ForbiddenError):
        return 1
    return 1


def _redaction_tokens(token: str | None) -> list[str]:
    """Collect only the token actually used for the successful request."""
    return [token] if token else []


def _print_error(error: Exception, token: str | None) -> None:
    """Write one safe error message to stderr."""
    print(_redact(str(error), [token] if token else []), file=sys.stderr)


_TOKEN_FLAG = "--token"  # noqa: S105


def _token_like_flag(flag: str) -> bool:
    """Return whether an argv item names --token, including abbreviations."""
    if not flag.startswith("--"):
        return False
    if "=" in flag:
        flag = flag.partition("=")[0]
    return flag.startswith(_TOKEN_FLAG) or _TOKEN_FLAG.startswith(flag)


def _redact(message: str, tokens: Iterable[str]) -> str:
    """Replace every supplied token in a message, longest values first."""
    unique = {token for token in tokens if token}
    for token in sorted(unique, key=len, reverse=True):
        message = message.replace(token, "[redacted]")
    return message


def _argument_tokens(arguments: list[str]) -> list[str]:
    """Collect token values before argparse can include them in an error."""
    tokens: list[str] = []
    for index, argument in enumerate(arguments):
        if "=" in argument and argument.startswith("--"):
            flag, _, value = argument.partition("=")
            if value and _token_like_flag(flag):
                tokens.append(value)
            continue
        if _token_like_flag(argument) and index + 1 < len(arguments):
            value = arguments[index + 1]
            if value:
                tokens.append(value)
    environment_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if environment_token:
        tokens.append(environment_token)
    return tokens


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse arguments while redacting errors before writing to stderr."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    error_output = io.StringIO()
    try:
        with redirect_stderr(error_output):
            return build_parser().parse_args(arguments)
    except SystemExit:
        sys.stderr.write(_redact(error_output.getvalue(), _argument_tokens(arguments)))
        raise


def _validate_client_settings(timeout: float, max_workers: int) -> None:
    """Reject invalid client settings before construction."""
    if not timeout > 0:
        raise ValueError("timeout must be greater than zero")
    if max_workers <= 0:
        raise ValueError("max_workers must be a positive integer")


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface and return its exit status."""
    try:
        args = _parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 1

    token: str | None = None
    try:
        token = resolve_token(args.token)
        _validate_client_settings(args.timeout, args.max_workers)
        client = GitHubExtractor(
            token,
            timeout=args.timeout,
            max_workers=args.max_workers,
            max_pages=getattr(args, "max_pages", None),
            api_root=getattr(args, "api_root", API_ROOT),
        )
        payload = dispatch(client, args)
        redaction = _redaction_tokens(token)
        try:
            serialized = json.dumps(to_jsonable(payload), indent=2)
        except (TypeError, ValueError) as error:
            print(_redact(str(error), redaction), file=sys.stderr)
            return 1
        print(_redact(serialized, redaction))
    except Exception as error:  # noqa: BLE001
        _print_error(error, token)
        return _exit_code(error)

    return 0

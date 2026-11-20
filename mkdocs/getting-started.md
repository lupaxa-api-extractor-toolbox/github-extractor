# Getting Started

## Install

Install the package from PyPI. The `github-extractor` command is installed
with it.

```bash
pip install lupaxa-github-extractor
```

Import the client from the same package:

```python
from lupaxa.github_extractor import GitHubExtractor
```

## Token Order

The command resolves a token in this order:

1. The `--token` option.
2. The `GITHUB_TOKEN` environment variable.
3. The token printed by `gh auth token`.

The library takes the token you pass in. It does not read the environment.

```python
client = GitHubExtractor(token)
```

A blank token raises `MissingTokenError` before any request. The token is not
written to command output, error messages, or logs.

## What a Call Returns

Named methods return model objects. `repository.full_name` and
`repository.raw` are the repository itself. Requested extras hang off the
same object: `repository.topics`, `repository.workflows`, `repository.commits`,
and the other fields in [Reference](reference.md). Unrequested extras are
`None`. A requested extra that returns `404`, `409`, or `410` is an empty
list, and the failure is recorded on `errors`.

`get` returns the JSON body as GitHub sent it. `slugs=True` returns a list of
`full_name` or organisation `login` strings and does not fetch extras.

The command prints the same data as JSON, indented with two spaces. Attached
resources are included. Empty `errors` are omitted.

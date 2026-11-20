<p align="center">
  <a href="https://github.com/lupaxa-api-extractor-toolbox">
    <img src="https://raw.githubusercontent.com/the-lupaxa-project/brand-assets/master/logos/organisations/api-extractor-toolbox/readme-logo.png" alt="API Extractor Toolbox" />
  </a>
</p>

<h1 align="center">GitHub Extractor</h1>

Read-only access to GitHub organisations, repositories, and the related data
you ask for. It is a Python library, `lupaxa.github_extractor`, and a
`github-extractor` command. It does not create, update, or delete GitHub data.

## Installation

```bash
pip install lupaxa-github-extractor
```

> **Note:** The command reads the token from `--token`, then `GITHUB_TOKEN`,
> then `gh auth token`, and passes that string into `GitHubExtractor`. The
> library does not read the environment.

## Library

```python
from lupaxa.github_extractor import GitHubExtractor

client = GitHubExtractor(token)
repos = client.repositories_by_org(
    "acme",
    resources=("topics", "workflows", "languages", "commits", "issues"),
)

for repo in repos:
    names = [] if repo.topics is None else repo.topics.names
    workflows = [] if repo.workflows is None else [item.name for item in repo.workflows]
    print(repo.full_name, names, workflows, repo.languages)
    for failure in repo.errors:
        print(failure.addon, failure.status, failure.message)
```

`resources` is one list. These names can be mixed in the same call:
`branches`, `contributors`, `languages`, `releases`, `tags`, `topics`,
`workflows`, `commits`, `issues`, `pulls`, `milestones`, `forks`,
`stargazers`, `subscribers`, `collaborators`, `labels`, `workflow_runs`,
`deployments`, `environments`, and `contents`. Organisation extras include
`audit_log`. User extras include `notifications`. A name that was not
requested is `None`.

`params` sets query strings per resource name. Each key must appear in the
`resources` list for that call. `issues` and `pulls` default to `state=all`.
`notifications` defaults to `all=true`. Caller values replace defaults.

```python
repo = client.repository(
    "acme/widget",
    resources=("topics", "workflows", "workflow_runs", "issues"),
    params={"issues": {"state": "closed"}},
)
user = client.authenticated_user(
    resources=("repos", "notifications"),
    repository_resources=("topics", "commits"),
)
```

`repository(full_name, ...)` returns one repository. On `authenticated_user`,
`repository_resources` fetches extras on each repo in `repos`, `starred`, or
`subscriptions` when one of those lists is requested.

`topics` is one object with `names`. `workflows` is a list of workflow
objects, without `total_count`. `languages` is a dictionary of byte counts.
`forks` in that list replaces GitHub's integer fork count. Other fields from
the repository JSON stay on `repo.raw`.

A `404`, `409`, or `410` on one extra stores an empty list for that name and
records the failure on `errors`. The rest of the result is still returned.
Authentication failures, rate limits, and other `403` responses raise.

`slugs=True` stays a boolean. It returns names only and does not fetch
`resources`, even when that list is set.

```python
names = client.repositories_by_org("acme", slugs=True)
```

The other list methods are `user_repositories` (omit `username` for the
authenticated user), `visible_repositories`, and `organisation_repositories`.
`organisations(resources=("members", "teams", "hooks"))` lists the token's
organisations. `authenticated_user(resources=("emails", "repos"))` returns the
token's user. `get("/repos/acme/widget/commits")` returns raw JSON for any
read-only API path. `max_pages=None` follows every page. A positive integer
stops after that many pages.

## Command Line

Flags are the command-line form of the same resource names. Order on the
command line does not matter.

```bash
github-extractor repo acme/widget --topics --workflows --workflow-runs
github-extractor repos org acme --topics --workflows --languages --commits --issues
github-extractor repos user --username ada --releases --tags --pulls
github-extractor repos visible --skip-private --include 'acme/*' --topics
github-extractor repos organisations --include-org 'acme*'
github-extractor repos organizations --include-org 'acme*'
github-extractor organisations --members --teams --hooks
github-extractor user --repos --topics --notifications
github-extractor repos org acme --issues --param issues.state=closed --api-root https://github.example/api/v3
github-extractor repos org acme --slugs
github-extractor get /repos/acme/widget/commits --max-pages 2
```

`--include` and `--ignore` are case-insensitive globs on `full_name`.
`--include-name` and `--ignore-name` match the repository name.
`--include-org` and `--ignore-org` limit `repos organisations` and
`repos organizations`. Repeat a flag to pass more than one glob. `--param`
sets `name.key=value` query parameters. `--api-root` overrides the API host.
`--max-pages` caps paging. `--timeout` and `--max-workers` default to 10
seconds and 8 workers.

The command prints JSON indented with two spaces. It exits `0` on success,
`2` for usage and a missing token, `3` for authentication, `4` for a rate
limit, `5` when a primary request is not found, and `1` for everything else.

## Documentation

Longer walks and the full method list are in the
[documentation](https://github-extractor.thelupaxaproject.org/).

<a href="https://github.com/the-lupaxa-project">
  <img src="https://raw.githubusercontent.com/the-lupaxa-project/brand-assets/master/logos/components/footer-for-child-orgs.svg" alt="The Lupaxa Project Footer" width="100%" />
</a>

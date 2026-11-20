# Usage

## Client

`GitHubExtractor` takes the token and three optional limits.

```python
client = GitHubExtractor(token, timeout=10, max_workers=8, max_pages=None)
```

`timeout` is the per-request timeout in seconds. `max_workers` is how many
repositories are fetched at once. The default is 8. `max_pages=None` follows
every page. A positive integer stops after that many pages. The first response
counts as page 1. Optional `session` is a `requests.Session`. Worker threads
use private sessions that copy proxies, verify, cert, trust_env,
max_redirects, cookies, and adapters from that session. Optional `api_root`
overrides the default `https://api.github.com` host.

## One Repository

`repository(full_name, ...)` fetches one repository and optional extras.

```python
repo = client.repository(
    "acme/widget",
    resources=("topics", "workflow_runs"),
)
```

```bash
github-extractor repo acme/widget --topics --workflow-runs
```

## Repository Lists

These methods return `list[Repository]`, or `list[str]` when `slugs=True`.

| Method                      | What it lists                                                                |
| --------------------------- | ---------------------------------------------------------------------------- |
| `user_repositories`         | Repositories owned by a user. Omit `username` to use the authenticated user. |
| `repositories_by_org`       | Repositories in one organisation.                                            |
| `visible_repositories`      | Repositories the token can see.                                              |
| `organisation_repositories` | Repositories across the token's organisations.                               |

`resources` is the only way to ask for extras. Pass a list or tuple of names.
Allowed names are `branches`, `contributors`, `languages`, `releases`, `tags`,
`topics`, `workflows`, `commits`, `issues`, `pulls`, `milestones`, `forks`,
`stargazers`, `subscribers`, `collaborators`, `labels`, `workflow_runs`,
`deployments`, `environments`, and `contents`. A string such as
`resources="commits"` raises
`ValueError` before any request, because a string would otherwise be read
character by character. Duplicate names are fetched once, in the order given.

`params` is a mapping from resource name to query parameters. Each key must
name a resource in the same call. Values replace built-in defaults where they
overlap. `issues` and `pulls` use `state=all` when `state` is not set.
`notifications` uses `all=true` when `all` is not set.

```python
repos = client.repositories_by_org(
    "acme",
    resources=("topics", "workflows", "languages", "commits", "issues"),
)
```

The command uses one flag per name. Flag order on the command line does not
matter. Names are requested in the order listed above.

```bash
github-extractor repos org acme --topics --workflows --languages --commits --issues
```

## How to Read a Repository

`full_name` is required. Other repository fields from GitHub stay on `raw`,
including the integer `forks` count and the list of topic name strings that
GitHub puts on the repository object itself.

Requested extras replace those raw fields when they use the same key:

| Name in `resources` | Attribute   | Shape                                                   |
| ------------------- | ----------- | ------------------------------------------------------- |
| `topics`            | `topics`    | One `Topics` model. `names` is the list of topic names. |
| `workflows`         | `workflows` | `list[Workflow]`. `total_count` is not kept.            |
| `languages`         | `languages` | `dict[str, int]` of byte counts.                        |
| `commits`           | `commits`   | `list[Commit]`.                                         |
| `forks`             | `forks`     | `list[Fork]`. This replaces GitHub's integer count.     |

```python
for repo in repos:
    topic_names = [] if repo.topics is None else repo.topics.names
    workflow_names = [item.name for item in repo.workflows or []]
    languages = repo.languages or {}
    print(repo.full_name, topic_names, workflow_names, languages)
```

An extra that was not requested is `None`. Check that before reading `names`
or indexing the list.

## Recorded Failures

A `404`, `409`, or `410` on an extra stores an empty list for that name and
records the failure. The walk continues. This includes `languages` and
`topics`, which are a dictionary and a `Topics` object when the request
succeeds.

Each recorded failure is a `ResourceError` with `addon`, `status`, and
`message`. The message is `Not found`, `Conflict`, or `Gone`. The GitHub body
is not copied, so a secret in that body is not kept.

```python
for repo in repos:
    for failure in repo.errors:
        print(repo.full_name, failure.addon, failure.status, failure.message)
```

Authentication failures, rate limits, other `403` responses, timeouts, and
network errors raise. They are not stored on `errors`.

## Filters

`include` and `ignore` are case-insensitive globs matched against
`full_name`. `include_names` and `ignore_names` match `name`. On the command
line those are `--include`, `--ignore`, `--include-name`, and `--ignore-name`.
Repeat the option to pass more than one glob.

`skip_private=True` (`--skip-private`) drops private repositories.
`include_orgs` and `ignore_orgs` (`--include-org`, `--ignore-org`) limit
`organisation_repositories` to organisation logins.

An empty `include` list keeps every name that is not ignored. `slugs=True`
still applies the filters, then returns names only and skips extra requests.

```python
repos = client.organisation_repositories(
    include_orgs=("acme*",),
    include=("*/widget*",),
    skip_private=True,
    resources=("topics", "workflows"),
)
```

```bash
github-extractor repos organisations --include-org 'acme*' --include '*/widget*' --skip-private --topics --workflows
```

## Organisations and the Authenticated User

`organisations` lists the token's organisations. `resources` accepts
`members`, `teams`, `events`, `hooks`, and `audit_log`. `organizations` is the
same method.

```python
orgs = client.organisations(resources=("members", "teams", "hooks"))
```

```bash
github-extractor organisations --members --teams --hooks
```

`authenticated_user` returns the token's user. `resources` accepts `emails`,
`followers`, `following`, `gpg_keys`, `ssh_keys`, `repos`, `starred`,
`subscriptions`, and `notifications`. `repository_resources` is a second list
of repository extras. It runs only when `repos`, `starred`, or `subscriptions`
is in `resources`, and it attaches those extras to each repository in those
lists.

```python
user = client.authenticated_user(
    resources=("repos", "notifications"),
    repository_resources=("topics", "commits"),
)
```

```bash
github-extractor user --repos --topics --commits --notifications
```

Repository rows from `authenticated_user` are full `Repository` models. A
repository's own `forks` count stays on `raw` unless you request `forks` in
`repository_resources`.

`token_information` reads scope and rate-limit headers from `GET /user`.

```bash
github-extractor token
```

## Generic Read

`get` sends one read-only GET. A relative path starts with `/` and is not
protocol-relative (`//...`). An absolute URL must use `https`, stay on the
same host as `api_root`, and omit username and password. The default root is
`https://api.github.com`. JSON arrays are concatenated across `Link` pages. A
JSON object that contains at least one list field is merged across pages: list
fields are concatenated, and scalar fields such as `total_count` stay from the
first page. An object with no list field is returned from the first page and
its next link is not followed. `204` becomes `[]`.

```python
commits = client.get("/repos/acme/widget/commits")
```

```bash
github-extractor get /repos/acme/widget/commits
```

`get` does not wrap the body in a model. A `409` or `410` from `get` raises
`RequestError`.

## Page Cap

`max_pages=None` follows every next link. `max_pages=2` keeps the first page
and one more, for both ordinary lists and the workflows object. There is no
truncation marker. The command flag is `--max-pages`.

```python
client = GitHubExtractor(token, max_pages=2)
repos = client.repositories_by_org("acme", resources=("workflows", "topics"))
```

```bash
github-extractor repos org acme --workflows --topics --max-pages 2
```

`0`, a negative integer, `True`, and `False` raise `ValueError`.

## Query Parameters on the Command Line

`--param` repeats as `name.key=value`. The last value for a key wins.
Parameters apply only to resources that the command also requests.

```bash
github-extractor repos org acme --issues --param issues.state=closed
```

`--api-root` sets the HTTPS API root for every request on that command.

```bash
github-extractor token --api-root https://github.example/api/v3
```

## Rate Limit

A rate-limited response sleeps once, then retries the same URL and query
once. That includes HTTP `429` and the usual `403` rate-limit cases. The wait
is `Retry-After` when that header parses as a number of seconds or an HTTP
date. Otherwise it is `X-RateLimit-Reset` minus the current time. There is no
maximum wait, so a primary limit can pause until GitHub's reset. A second rate
limit raises `RateLimitExceededError`. Other statuses do not sleep.

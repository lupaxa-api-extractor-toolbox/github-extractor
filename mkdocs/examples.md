# Examples

These calls are read-only. Each one asks for more than the repository or
organisation list itself. The library snippets assume `token` is already set.
The commands use `GITHUB_TOKEN` or `gh auth token` when `--token` is omitted.

## Workflows and Topics

Fetch both for every repository in an organisation.

```python
from lupaxa.github_extractor import GitHubExtractor

client = GitHubExtractor(token)
repos = client.repositories_by_org("acme", resources=("topics", "workflows"))

for repo in repos:
    names = [] if repo.topics is None else repo.topics.names
    workflows = [] if repo.workflows is None else [item.name for item in repo.workflows]
    print(repo.full_name)
    print("  topics:", ", ".join(names) or "(none)")
    print("  workflows:", ", ".join(workflows) or "(none)")
    for failure in repo.errors:
        print("  missing:", failure.addon, failure.status, failure.message)
```

```bash
github-extractor repos org acme --topics --workflows
```

The JSON from the command includes `topics.names` and a `workflows` list on
each repository. `total_count` is not in that list.

## One Repository, Topics and Workflow Runs

```python
repo = client.repository(
    "acme/widget",
    resources=("topics", "workflow_runs"),
)

topic_names = [] if repo.topics is None else repo.topics.names
run_names = [] if repo.workflow_runs is None else [run.name for run in repo.workflow_runs]
print(repo.full_name, topic_names, run_names)
```

```bash
github-extractor repo acme/widget --topics --workflow-runs
```

## Topics, Workflows, Languages, Commits, and Issues

Every extra is a name in `resources`.

```python
repos = client.repositories_by_org(
    "acme",
    resources=("topics", "workflows", "languages", "commits", "issues"),
)

for repo in repos:
    print(repo.full_name, repo.languages)
    print("  commits:", 0 if repo.commits is None else len(repo.commits))
    print("  issues:", 0 if repo.issues is None else len(repo.issues))
```

```bash
github-extractor repos org acme --topics --workflows --languages --commits --issues
```

A missing extra is an empty list and is recorded on `errors` with status
`404`, `409`, or `410`. The repository is still returned.

## One User, Several Extras

Releases, tags, topics, workflows, pull requests, and milestones are names in
the same list.

```python
repos = client.user_repositories(
    username="ada",
    resources=("releases", "tags", "topics", "workflows", "pulls", "milestones"),
)
```

```bash
github-extractor repos user --username ada --releases --tags --topics --workflows --pulls --milestones
```

Omit `--username` to use the authenticated user. That is
`user_repositories()` with no username.

## Visible Repositories, Private Ones Dropped

```python
repos = client.visible_repositories(
    skip_private=True,
    include=("acme/*",),
    resources=("topics", "languages"),
)
```

```bash
github-extractor repos visible --skip-private --include 'acme/*' --topics --languages
```

`--include` matches `full_name`. `--include-name` matches the repository name
only.

## Every Organisation, Selected Repositories

```python
repos = client.organisation_repositories(
    include_orgs=("acme*", "labs*"),
    ignore=("*/*-archive",),
    resources=("workflows", "topics", "commits"),
)
```

```bash
github-extractor repos organisations --include-org 'acme*' --include-org 'labs*' --ignore '*/*-archive' --workflows --topics --commits
```

`repos organizations` is not a command. The organisation list itself accepts
both spellings: `organisations` and `organizations`.

## Names Only

`slugs=True` returns strings and does not request topics, workflows, or any
other extra, even if those flags are set.

```python
names = client.repositories_by_org("acme", slugs=True, resources=("topics", "workflows"))
```

`names` is a list of strings such as `acme/widget`.

```bash
github-extractor repos org acme --slugs
```

## Organisation Members, Teams, and Hooks

```python
orgs = client.organisations(resources=("members", "teams", "hooks"))

for org in orgs:
    member_logins = [] if org.members is None else [member.login for member in org.members]
    team_names = [] if org.teams is None else [team.name for team in org.teams]
    print(org.login, member_logins, team_names)
```

```bash
github-extractor organisations --members --teams --hooks
```

## Authenticated User

```python
user = client.authenticated_user(resources=("emails", "repos", "starred"))
print(user.login)
print([] if user.repos is None else [repo.full_name for repo in user.repos])
```

```bash
github-extractor user --emails --repos --starred
```

## Authenticated User, Repository Extras on `repos`

`repository_resources` attaches extras to each repository in the user's
`repos` list.

```python
user = client.authenticated_user(
    resources=("repos",),
    repository_resources=("topics", "commits"),
)

for repo in user.repos or []:
    names = [] if repo.topics is None else repo.topics.names
    commit_count = 0 if repo.commits is None else len(repo.commits)
    print(repo.full_name, names, commit_count)
```

```bash
github-extractor user --repos --topics --commits
```

## A Single Endpoint

`get` is the escape hatch for a path the named methods do not cover. The
result is JSON, not a model. `--max-pages` still applies.

```python
client = GitHubExtractor(token, max_pages=2)
page = client.get("/repos/acme/widget/commits")
```

```bash
github-extractor get /repos/acme/widget/commits --max-pages 2
```

## Cap a Large Walk

```python
client = GitHubExtractor(token, max_pages=2, max_workers=4)
repos = client.repositories_by_org("acme", resources=("workflows", "topics", "issues", "commits"))
```

```bash
github-extractor repos org acme --workflows --topics --issues --commits --max-pages 2 --max-workers 4
```

`--timeout` is the per-request timeout in seconds. The default is 10.

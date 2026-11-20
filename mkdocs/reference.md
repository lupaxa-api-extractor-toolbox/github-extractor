# Reference

## Library Methods

| Method                                                              | Returns                             | Extras                                                                                                    |
| ------------------------------------------------------------------- | ----------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `GitHubExtractor(token, ...)`                                       | Client                              | `token` is required. Default `api_root` is `https://api.github.com`. Optional `session`.                  |
| `get(path)`                                                         | Raw JSON                            | No model. Lists concatenate across pages; object pages merge list fields.                                 |
| `token_information()`                                               | `TokenInformation`                  | Scopes and rate-limit headers.                                                                            |
| `authenticated_user(...)`                                           | `User`                              | User `resources`, optional `repository_resources`, optional `params`.                                     |
| `organisations(...)`                                                | `list[Organisation]` or `list[str]` | `resources`: `members`, `teams`, `events`, `hooks`, `audit_log`. `organizations` is the same.             |
| `user_repositories(...)`                                            | `list[Repository]` or `list[str]`   | `resources` names below.                                                                                  |
| `repositories_by_org(org, ...)`                                     | `list[Repository]` or `list[str]`   | Same extras as `user_repositories`.                                                                       |
| `visible_repositories(...)`                                         | `list[Repository]` or `list[str]`   | Same extras.                                                                                              |
| `organisation_repositories(...)`                                    | `list[Repository]` or `list[str]`   | Same extras, plus `include_orgs` and `ignore_orgs`.                                                       |
| `repository(full_name, ...)`                                        | `Repository`                        | Same repository extras as the list methods. Optional `params`.                                            |

`slugs=True` returns names and skips extras. `resources` must be a list or
tuple of names. Unknown names raise `ValueError` before a request. Optional
`params` is a mapping of resource name to query string values. Each key must
match a name in `resources` (or in `repository_resources` on
`authenticated_user`). `authenticated_user` also accepts `repository_resources`
for extras on `repos`, `starred`, or `subscriptions`.

## Repository Extras

Every repository extra is a `resources` name. The path suffix is under
`/repos/{owner}/{repo}/`:

| Flag            | Attribute       | Path suffix         | JSON shape                                           |
| --------------- | --------------- | ------------------- | ---------------------------------------------------- |
| `branches`      | `branches`      | `branches`          | `list[Branch]`                                       |
| `contributors`  | `contributors`  | `contributors`      | `list[Contributor]`                                  |
| `languages`     | `languages`     | `languages`         | `dict[str, int]` byte counts                         |
| `releases`      | `releases`      | `releases`          | `list[Release]`                                      |
| `tags`          | `tags`          | `tags`              | `list[Tag]`                                          |
| `topics`        | `topics`        | `topics`            | `Topics`, with `names`                               |
| `workflows`     | `workflows`     | `actions/workflows` | `list[Workflow]`, no `total_count`                   |
| `collaborators` | `collaborators` | `collaborators`     | `list[Collaborator]`                                 |
| `labels`        | `labels`        | `labels`            | `list[Label]`                                        |
| `workflow_runs` | `workflow_runs` | `actions/runs`      | `list[WorkflowRun]`, inner `workflow_runs`           |
| `deployments`   | `deployments`   | `deployments`       | `list[Deployment]`                                   |
| `environments`  | `environments`  | `environments`      | `list[Environment]`, inner `environments`            |
| `contents`      | `contents`      | `contents`          | `list[Content]`, one item when the body is an object |

Further `resources` names, stored under the same attribute name:

| Name          | Attribute     | Model                                     |
| ------------- | ------------- | ----------------------------------------- |
| `commits`     | `commits`     | `list[Commit]`                            |
| `issues`      | `issues`      | `list[Issue]`, default query `state=all`  |
| `pulls`       | `pulls`       | `list[PullRequest]`, default `state=all`  |
| `milestones`  | `milestones`  | `list[Milestone]`                         |
| `forks`       | `forks`       | `list[Fork]`, replacing the integer count |
| `stargazers`  | `stargazers`  | `list[Stargazer]`                         |
| `subscribers` | `subscribers` | `list[Subscriber]`                        |

`subscribers` is GitHub's subscribers list, the current form of the old
watchers list.

Issues are not filtered to drop pull requests. Workflows are one list, not
grouped by state. Languages stay byte counts, not a list of language names.

## Organisation and User Extras

| `resources` name | Method               | Attribute                                                                  |
| ---------------- | -------------------- | -------------------------------------------------------------------------- |
| `members`        | `organisations`      | `members`: `list[User]`                                                    |
| `teams`          | `organisations`      | `teams`: `list[Team]`                                                      |
| `events`         | `organisations`      | `events`: `list[Event]`                                                    |
| `hooks`          | `organisations`      | `hooks`: `list[Hook]`                                                      |
| `audit_log`      | `organisations`      | `audit_log`: `list[AuditEvent]` at `/orgs/{login}/audit-log`               |
| `emails`         | `authenticated_user` | `emails`: `list[Email]`                                                    |
| `followers`      | `authenticated_user` | `followers`: `list[User]`                                                  |
| `following`      | `authenticated_user` | `following`: `list[User]`                                                  |
| `gpg_keys`       | `authenticated_user` | `gpg_keys`: `list[GpgKey]`                                                 |
| `ssh_keys`       | `authenticated_user` | `ssh_keys`: `list[SshKey]` from `/user/keys`                               |
| `repos`          | `authenticated_user` | `repos`: `list[Repository]`                                                |
| `starred`        | `authenticated_user` | `starred`: `list[Repository]`                                              |
| `subscriptions`  | `authenticated_user` | `subscriptions`: `list[Repository]`                                        |
| `notifications`  | `authenticated_user` | `notifications`: `list[Notification]` on `/notifications`, `all=true`      |

## Models

Every GitHub object is a dataclass with `raw`. Required identity fields use
the live attribute (`Repository.full_name`, `User.login`, `Organisation.login`,
`Fork.full_name`, `Stargazer.login`, `Subscriber.login`). Other documented
fields read through `raw` and are `None` when GitHub omitted the key.

Public classes:

- `GitHubObject`
- `ResourceError`
- `TokenInformation`
- `User`
- `Email`
- `GpgKey`
- `SshKey`
- `Organisation`
- `Repository`
- `Branch`
- `Contributor`
- `Release`
- `Tag`
- `Topics`
- `Workflow`
- `Commit`
- `Issue`
- `PullRequest`
- `Milestone`
- `Fork`
- `Stargazer`
- `Subscriber`
- `Collaborator`
- `Label`
- `WorkflowRun`
- `Deployment`
- `Environment`
- `Content`
- `Notification`
- `AuditEvent`
- `Team`
- `Event`
- `Hook`

`ResourceError` is not a `GitHubObject`. It has `addon`, `status`, and
`message`. `errors` on a repository, organisation, or user is a list of those
records, empty when nothing failed. A recorded extra is also present as an
empty list. An extra that was not requested stays `None`.

`get` returns raw JSON. `slugs=True` returns a list of strings.

## Errors

| Error                    | When                                                                          |
| ------------------------ | ----------------------------------------------------------------------------- |
| `MissingTokenError`      | The token is missing or blank.                                                |
| `MissingOrgNameError`    | An organisation name is required and missing.                                 |
| `AuthenticationError`    | GitHub returned `401`.                                                        |
| `RateLimitExceededError` | Rate limited after one retry, including HTTP `429`, or no wait was known.     |
| `ForbiddenError`         | GitHub returned `403` and it is not a rate limit.                             |
| `NotFoundError`          | A primary request returned `404`. Extra `404` responses are recorded instead. |
| `RequestTimeoutError`    | The request exceeded `timeout`.                                               |
| `RequestError`           | Any other failed request, including `get` responses of `409` and `410`.       |

`ValueError` is raised for a bad `resources` value, a bad `max_pages`, a bad
`timeout`, a bad `max_workers`, or a path that is not a GitHub API path.

## Command Line

Shared options: `--token`, `--timeout`, `--max-workers`, `--max-pages`,
`--api-root`, and repeatable `--param name.key=value`.

| Command                                | Library method              |
| -------------------------------------- | --------------------------- |
| `github-extractor token`               | `token_information`         |
| `github-extractor user`                | `authenticated_user`        |
| `github-extractor repo FULL_NAME`      | `repository`                |
| `github-extractor organisations`       | `organisations`             |
| `github-extractor organizations`       | `organisations`             |
| `github-extractor repos user`          | `user_repositories`         |
| `github-extractor repos org ORG`       | `repositories_by_org`       |
| `github-extractor repos visible`       | `visible_repositories`      |
| `github-extractor repos organisations` | `organisation_repositories` |
| `github-extractor repos organizations` | `organisation_repositories` |
| `github-extractor get PATH`            | `get`                       |

User flags: `--emails`, `--followers`, `--following`, `--gpg-keys`,
`--ssh-keys`, `--repos`, `--starred`, `--subscriptions`, `--notifications`.
Repository flags on `user` populate `repository_resources`, not `resources`.

Organisation flags: `--include`, `--ignore`, `--members`, `--slugs`,
`--teams`, `--events`, `--hooks`, `--audit-log`.

Repository list flags: `--include`, `--ignore`, `--include-name`,
`--ignore-name`, `--skip-private`, `--slugs`, plus the resource flags below.
`repo FULL_NAME` accepts resource flags and `--param` only.

Resource flags: `--branches`, `--contributors`, `--languages`, `--releases`,
`--tags`, `--topics`, `--workflows`, `--commits`, `--issues`, `--pulls`,
`--milestones`, `--forks`, `--stargazers`, `--subscribers`, `--collaborators`,
`--labels`, `--workflow-runs`, `--deployments`, `--environments`, `--contents`.
`repos user` also takes `--username`. `repos organisations` also takes
`--include-org` and `--ignore-org`.

Repeat `--include`, `--ignore`, `--include-name`, `--ignore-name`,
`--include-org`, and `--ignore-org` for more than one glob.

```bash
github-extractor repos org acme --topics --workflows --commits --issues --max-pages 2
```

The process exits with these codes:

| Code | Meaning                                                               |
| ---- | --------------------------------------------------------------------- |
| `0`  | Success.                                                              |
| `2`  | Usage, a missing token, a missing organisation name, or `ValueError`. |
| `3`  | Authentication.                                                       |
| `4`  | Rate limit.                                                           |
| `5`  | Not found on a primary request.                                       |
| `1`  | Forbidden and every other error.                                      |

# GitHub Extractor

GitHub Extractor lists organisations, repositories, and the related data you
ask for. It is a Python library and a `github-extractor` command. Both are
read-only: they do not create, update, or delete GitHub data.

One call can attach several kinds of data to every repository it returns.
Pass the names you want in `resources`, for example topics, workflows,
languages, commits, and issues. The command uses one flag per name.

Start with [Getting Started](getting-started.md) for install and the token.
[Usage](usage.md) explains the client and the command. [Examples](examples.md)
shows library and command-line calls that pull more than one set of data.
[Reference](reference.md) lists methods, flags, models, and exit codes.

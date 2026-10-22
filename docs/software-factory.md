# Software factory

This repository is public, but the software factory treats repository text as untrusted input. The factory exists to test whether AFK implementation reduces maintainer coordination without reducing delivery quality.

## Trust boundaries

- `ready-for-agent` means that an issue is fully specified. It does not authorize execution.
- `agent:implement` is the explicit execution label. Only the maintainer adds it after checking the issue, its dependencies, and its acceptance criteria.
- External issues, comments, pull requests, and fork branches are not factory instructions. A maintainer must copy an accepted request into a maintainer-owned issue before it can enter the factory.
- The first implementation workflow must verify the label actor, issue author, issue state, open dependencies, and a maintainer-approved body snapshot. It must write untrusted text to a file rather than interpolate it into a shell command.
- The agent never receives production secrets, the `production` environment, a GitHub App token, or deployment access.

## Phased rollout

The first phase is a manually dispatched, read-only smoke workflow. It uses a disposable, redacted fixture in the runner's temporary directory and writes only the Actions step summary as a repository-visible result. It does not check out tanomu, read an issue, write an issue or pull request, create a branch, call Feishu, or contact the production server.

The smoke must be confirmed by the maintainer before a later pull request adds implementation, review, or rework workflows. Those workflows will be separate changes and will use a path allowlist, patch artifacts, independent review context, and human approval before merge.

## Smoke gates

The smoke stops rather than guessing when any of these are unknown: authentication, CI use authorization, data retention policy, or whether the run could incur paid usage. It requires a manually configured, isolated `OPENCODE_AUTH_JSON` secret and an explicit model ID; it never uses the production model key and never enables extra paid usage automatically.

The smoke is bounded by a ten-minute job timeout and runs one smoke at a time. It reports only non-sensitive status, duration, and model identifier in the Actions summary. It must fail on a non-zero command, timeout, missing credential, fixture mutation, or credential-shaped output. The first real smoke does not upload raw model output.

The OpenCode config denies all tools by default and allows only read-only file inspection (`read`, `glob`, and `grep`). Public session sharing is disabled by configuration. The CLI version is pinned; `@latest` is not allowed.

## Later task lifecycle

The planned lifecycle is:

```text
ready-for-agent -> agent:implement -> implementing -> draft PR -> reviewing
                                      -> rework (at most twice)
                                      -> ready-for-human / needs-human
```

A task is keyed by issue number and has one concurrency group. The implementation and review runs are independent. The maintainer reviews the draft PR and CI evidence, stops production before real Feishu testing, sends three rapid Private Conversation messages, confirms one ordered merged reply, restores production, and decides whether to merge.

## Human-only operations

The maintainer must configure GitHub rulesets, the `production` environment, secrets, the GitHub App, server SSH policy, and the model provider account. The maintainer must also confirm the deployment after setting `SESSION_SECRET`, review every factory PR, and perform real Feishu acceptance. No workflow in this phase performs those operations.

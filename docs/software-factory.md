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

The implementation lifecycle is:

```text
ready-for-agent + agent:implement -> implementing
  -> round: implement -> format + checks -> independent review
       check failure or review findings -> next round (four rounds in total)
  -> draft PR -> ready-for-human
  -> needs-human (authorization, scope, credential or infrastructure failure, or budget exhausted)
```

A task is keyed by issue number and has one concurrency group. The implementation and review runs are independent. The maintainer reviews the draft PR and CI evidence, stops production before real Feishu testing, sends three rapid Private Conversation messages, confirms one ordered merged reply, restores production, and decides whether to merge.

## Implementation controls

The trusted controls, task snapshots and prompts live in `.github/software-factory/`.
`control.py` runs from the dispatch revision, independently of the candidate tree.
Run its regression suite with `python3 -I -m unittest discover -s .github/software-factory -p 'test_*.py'`.
Task #6 permits only six core/server implementation and test files, with a 400-line
limit. Updating the specification requires a reviewed task snapshot change.

The only accepted model is `opencode/deepseek-v4.1-flash-free`; no paid fallback is
configured. OpenCode's [provider policy](https://opencode.ai/docs/zen/) states that
DeepSeek V4.1 Flash Free uses zero retention and does not train on submitted data.
Recheck this policy before changing models. The pinned CLI uses its tested legacy
`permission` configuration; migration to `permissions` needs separate verification.

## Implementation runbook

After both factory PRs are merged, the maintainer creates `agent:implement`,
`implementing`, `ready-for-human` and `needs-human`, enables Actions to create PRs,
and configures main protection and production approval. Review issue #6 and its
snapshot, then add `agent:implement` while `ready-for-agent` is present. The label
event starts **Software factory implement** on `main` with the free model above.
Manual dispatch remains available for re-running with the same validation. There is
no dry-run mode.

The gate checks the maintainer actors, issue author, latest authorization label
actor, body hash, dependencies and branch/PR uniqueness. Claim consumes the execution
label. Each round generates a patch, then a fresh runner without model credentials
applies `pnpm format`, rechecks scope, uploads that formatted patch, and only then
runs lint, typecheck, admin build and database tests. A failing check produces
`checks.json` (the command and a bounded, ANSI-stripped output tail) for the next
round; passing checks lead to a fresh read-only review, whose findings produce
`review.json`. Both kinds of repair share one budget of four rounds. Repair is not
a blind retry: every round is checked again, and only the patch that passed checks
and review is published.

Authorization, scope, credential-scan, implementer-error and infrastructure failures
are not repairable and stop the run, as does a repair round that leaves the patch
unchanged. Candidate code runs in the verify job after the checked patch is uploaded;
ordinary PR CI after Ready for review remains the authoritative check.

Only a passing candidate is committed and pushed to a draft PR, using `Refs #6`.
GitHub-token-created PRs do not trigger CI automatically; marking the draft ready
triggers ordinary CI through `ready_for_review`. Inspect that CI and the diff before
real Feishu acceptance. The factory never claims real Feishu acceptance passed.

Patch and structured feedback artifacts expire after three days. Exact credential
values and common credential patterns are checked before upload. Raw model events,
stderr and auth files are never uploaded. Workspace paths are explicitly pinned
with `PWD`; edit permission permits only the task's relative file paths, after a default deny rule. Shell,
network tools, external directories and subagents are denied.

Successful handoff adds `ready-for-human`; failures after the gate add `needs-human`
and remove `implementing`. Fixed reason codes include `claim-failed`, `round-failed`,
`checks-exhausted`, `rework-exhausted`, `handoff-failed` and `cancelled`. A gate rejection changes no
issue state. If GitHub cancels the entire run or its token/API is unavailable, the
report job may not execute: inspect the run, remove a stale `implementing` label,
and resolve any existing branch/PR before deliberately authorizing another run.
Never blindly rerun a claimed or partially published task.

## Human-only operations

The maintainer must configure GitHub rulesets, the `production` environment, secrets, the GitHub App, server SSH policy, and the model provider account. The maintainer must also confirm the deployment after setting `SESSION_SECRET`, review every factory PR, and perform real Feishu acceptance. No workflow in this phase performs those operations.

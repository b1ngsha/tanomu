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
  -> round: implement -> format + checks -> Standards review + Spec review
       check failure or blocking finding -> next round (four rounds in total)
  -> draft PR -> ready-for-human
       -> independent final PR review -> advisory comments
  -> needs-human (authorization, scope, credential or infrastructure failure, or budget exhausted)
  -> retro (read-only proposals) -> comment on the draft PR, or on the issue without one
```

A task is keyed by issue number and has one concurrency group. The implementation and review runs are independent. The maintainer reviews the draft PR and CI evidence, stops production before real Feishu testing, sends three rapid Private Conversation messages, confirms one ordered merged reply, restores production, and decides whether to merge.

## Implementation controls

The trusted controls, task snapshots and prompts live in `.github/software-factory/`.
`control.py` runs from the dispatch revision, independently of the candidate tree.
Run its regression suite with `python3 -I -m unittest discover -s .github/software-factory -p 'test_*.py'`.
Task #6 permits only six core/server implementation and test files, with a 400-line
limit. Updating the specification requires a reviewed task snapshot change.

The prompts and workflows are task-independent. Each `tasks/N.json` supplies the
commit/PR `title`, the `implement` and `review` requirements appended to the generic
prompts, and the human `acceptance` steps listed in the draft PR. A new task needs
only its snapshot; `control.py` rejects a snapshot missing any of these fields.

Review and retro follow skills vendored, unmodified, in `skills/` from one pinned
upstream commit (see `skills/README.md`). The factory never fetches skills at run
time. `control.py` inlines them into the prompts: the two sub-agent briefs and the
standards section from `code-review`, and for retro the `retro` skill together with
`writing-for-agents` and the `SKILL-MECHANICS.md` it links. The regression suite pins
the commit and every file's SHA-256, and fails if a vendored skill links a file or
names a skill that is not vendored. To update, replace all of them from one new
commit and update both pins; `control.py` rejects a `code-review` skill whose briefs
or standards section it can no longer find. The prompt builder removes only the
briefs' upstream "Under 400 words." instruction; vendored files stay unchanged.
Review and retro have no response word, character or finding-count cap, and their
prompts explicitly require supported judgement calls to be included. A provider finish
reason of `length` or `content-filter` fails with `incomplete-output`, rather than
accepting a partial review or retro as complete.

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
round. Passing checks lead to a read-only review along the two `code-review` axes,
each in its own fresh OpenCode session so neither sees the other's conversation:
Standards (documented repository standards plus the smell baseline) and Spec (the
issue and the task's review requirements). Each axis returns
`{"findings":[{"blocking":bool,"finding":str}]}`; `control.py review` validates both
and writes `review.json` with the verdict, the blocking findings and the advisory
ones, each labelled with its axis and never reranked. Only a blocking finding
requests changes. Smells are always advisory. Each round also saves `review.md`
with both axes' complete original JSON responses, preserving their order and all
blocking and advisory findings. These full reports are published as comments after
handoff, including earlier rounds that requested changes. Both kinds of repair share one budget of four
rounds. Repair is not a blind retry: every round is checked again, and only the
patch that passed checks and review is published.

Authorization, scope, credential-scan, implementer-error and infrastructure failures
are not repairable and stop the run, as does a repair round that leaves the patch
unchanged. Candidate code runs in the verify job after the checked patch is uploaded;
ordinary PR CI after Ready for review remains the authoritative check.

Only a passing candidate is committed and pushed to a draft PR, using `Refs #6`.
GitHub-token-created PRs do not trigger CI automatically; marking the draft ready
triggers ordinary CI through `ready_for_review`. Inspect that CI and the diff before
real Feishu acceptance. The factory never claims real Feishu acceptance passed.

Patch, structured feedback, session transcript and retro artifacts expire after
three days. Exact credential values and common credential patterns are checked
before upload. Raw event files, stderr and auth files are never uploaded; complete event
lines appear only inside the scanned transcript. Workspace
paths are explicitly pinned with `PWD`; edit permission permits only the task's
relative file paths, after a default deny rule. Network tools, external directories,
subagents and the Skill tool are denied in every session.

Shell is the one deliberate trust boundary. Only the implementation session gets
`bash`, so it can run typecheck and single test files as it works. With shell the
model can reach anything on that runner, including the trusted checkout and the model
key, and could bypass the edit allowlist. So nothing that runner produces is trusted
beyond its patch: the patch is scanned before upload, and the verify job reapplies it
on a fresh runner without model credentials and repeats the scope, file-type and
line-limit checks before any candidate code runs. This is an accepted limitation, not
a sandbox: running as the same user, the shell can still modify that runner's copy of
the trusted scanner and write to the Actions environment, output and step summary
files. Session uploads name only the exact files just scanned, which contains the
artifact path without closing that boundary. Review and retro sessions are
read-only: they may only read, glob, grep and list inside their workspace, with `.env`
and `auth.json` reads denied.

The implementation run has a 1500-second limit; each review axis and the retro run
have 600 seconds each. All have a 15-second
kill grace period. After success, timeout (exit 124) or any other nonzero exit, a trusted
`opencode-summary` line is written to the step log and job summary. It has the exit
status, elapsed seconds, event and tool-call counts by status, step finish reasons,
token totals and seconds until the last event. The original exit status is then
propagated, and nothing is retried. Only allowlisted names and numbers are printed.
Text, tool inputs and outputs, error messages, paths and stderr are never printed.
The summary shows what the run did, not why it stopped. For example, a tool error count
cannot tell a permission denial from another failure, and a gap after the last event
only means no further JSON was received.

Every session, including a failed or timed-out one, is also rendered by
`control.py transcript` into a readable record for retro: events in order with
seconds since the first timestamped event. Each readable entry includes the complete original JSON line, including unknown
metadata. Fields and the whole record are retained in full, without truncation. The safe CLI summary is also scanned and
saved beside the transcript, so retro can see timeout status and elapsed time. A step that always runs scans the
transcript with `scan-session` (the same credential checks, without a size cap) and only then uploads it as a `session-*` artifact kept for three days, naming only
the scanned files. A transcript that fails the scan is not uploaded.

After every claimed run that was not cancelled, whether or not it reached a PR, a
retro job runs the vendored `retro` skill on the whole run in a fresh read-only
session. It downloads the task, the `session-*`, `feedback-*` and `checked-*`
artifacts (one download per pattern, each allowed to be missing) and a record of each
job's outcome. It only proposes; it cannot edit, run shell, or write to GitHub. Its
reply is validated, scanned and uploaded as the `retro` artifact. A separate
`retro-publish` job, which holds no model secret, rescans all full review reports and
the retro, neutralizes `@` mentions and posts them on the open draft PR for the
task's branch, or on the issue when there is no PR. Review reports are still published
if retro fails. Retro is labelled "proposals only". Each report is split losslessly
into numbered comments of at most 60,000 UTF-8 bytes when necessary; no model
summary is substituted and no findings are dropped. The artifact scans for model
reports have no size cap, while credential checks still reject the entire report. Nothing is applied: the
maintainer decides which proposals to act on in an ordinary reviewed change.

Successful handoff adds `ready-for-human`; failures after the gate add `needs-human`
and remove `implementing`. Fixed reason codes include `claim-failed`, `round-failed`,
`checks-exhausted`, `rework-exhausted`, `handoff-failed` and `cancelled`. A gate rejection changes no
issue state. If GitHub cancels the entire run or its token/API is unavailable, the
report job may not execute: inspect the run, remove a stale `implementing` label,
and resolve any existing branch/PR before deliberately authorizing another run.
Never blindly rerun a claimed or partially published task.

## Final PR review

`final-review.yml` starts a fresh read-only review when a same-repository PR is
opened, reopened or marked Ready for review. Automatic entry skips Bot authors and
forks. The factory explicitly dispatches it after creating its draft PR, because
`GITHUB_TOKEN` creation does not fire PR workflows. Maintainers can force another
review with `gh workflow run final-review.yml --ref main -f pr=N`. Pushes alone do
not start another review.

Workflow code, prompts and `control.py` come from main. The candidate is checked
out at its exact head SHA only for inspection; no candidate code is executed.
Symlinks remain in the diff but are removed from the inspection tree so they
cannot redirect reads outside it. OpenCode project configuration and Claude
compatibility loading are disabled; repository standards are read as data. The review uses the merge-base-to-head diff,
so later unrelated main commits are excluded. Standards always runs. Spec uses
this repository's issues referenced by
`Closes`, `Fixes`, `Resolves` or `Refs #N` in the PR body, plus any task snapshot's
`review` requirements on main. Task path allowlists are not part of this review.
Without a linked issue, Spec is skipped and the report explains why.

The model job has no GitHub write token. A separate publisher with no model secret
posts blocking and advisory findings and the complete responses as new comments,
never editing previous reports. It neutralizes mentions, scans credentials and
splits losslessly at 60,000 UTF-8 bytes. Invisible first-line markers identify the
head, report digest and part number. Only markers authored by `github-actions[bot]`
count for deduplication: automatic entry skips a complete report for that head and
rerunning the publisher fills missing parts of the same report. A moved head makes the report
stale and prevents publication. Manual dispatch requests a fresh review.

This review is advisory: it submits no GitHub Review, changes no labels or PR
state, starts no repair, and is not a required merge check. The maintainer still
inspects CI and decides Ready for review and merge. Factory retro neither waits
for nor reads it; its scanned sessions stay in the separate review run's artifacts
for three days. See [ADR 0007](adr/0007-final-review-via-pull-request-target.md).
The automatic trigger can be validated live only after the workflow reaches main.

## Human-only operations

The maintainer must configure GitHub rulesets, the `production` environment, secrets, the GitHub App, server SSH policy, and the model provider account. The maintainer must also confirm the deployment after setting `SESSION_SECRET`, review every factory PR, and perform real Feishu acceptance. No workflow in this phase performs those operations.

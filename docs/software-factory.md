# Software factory

This repository is public, but the software factory treats repository text as untrusted input. The factory exists to test whether AFK implementation reduces maintainer coordination without reducing delivery quality.

## Trust boundaries

- `ready-for-agent` means that an issue is fully specified. It does not authorize execution.
- `agent:implement` is the explicit execution label. Only the maintainer adds it after checking the issue, its dependencies, and its acceptance criteria.
- External issues, comments, pull requests, and fork branches are not factory instructions. A maintainer must copy an accepted request into a maintainer-owned issue before it can enter the factory.
- The implementation workflow verifies the label actor, issue author, issue state and explicit `Blocked by #N` dependencies, then captures the issue body automatically for that run. It writes untrusted text to a file rather than interpolating it into a shell command.
- The agent never receives production secrets, the `production` environment, a GitHub App token, or deployment access.

## Provider Preflight

The initial manual smoke established Provider connectivity. Its disposable workflow
has been retired; Provider Preflight is an operational check, not a lifecycle stage.
Role-specific canaries and trusted workflow checks cover subsequent migrations.

## Task lifecycle

The implementation lifecycle is:

```text
ready-for-agent + agent:implement -> implementing
  -> round: implement -> format + checks -> Standards review + Spec review
       check failure or blocking finding -> next round (four rounds in total)
  -> draft PR -> ready-for-human
       -> independent final PR review -> advisory comments
  -> needs-human (authorization, patch validation, credential or infrastructure failure, or budget exhausted)
  -> retro (read-only proposals) -> comment on the draft PR, or on the issue without one
```

A task is keyed by issue number and has one concurrency group. The implementation and review runs are independent. The maintainer reviews the draft PR and CI evidence, performs the issue's human acceptance and decides whether to merge. Local real Feishu testing must avoid a competing production listener; acceptance against production itself does not require stopping it.

## Implementation controls

The trusted controls and prompts live in `.github/software-factory/`.
`control.py` runs from the dispatch revision, independently of the candidate tree.
Run its regression suite with `python3 -I -m unittest discover -s .github/software-factory -p 'test_*.py'`.

The issue body is the sole specification for implementation and Spec review. Gate captures it automatically for all rounds and reviews; no per-issue JSON or policy file is required.
Claim rejects a body changed since gate; later live edits do not change the run. Branch and Conventional Commit title are generated from the issue number.
Native GitHub dependencies and explicit same-repository `Blocked by #N` references are checked before claim; ordinary references do not block execution.

There is no task path allowlist: source, tests, docs, schema, new migrations, dependencies, environment declarations, `.env.example` and CI/deployment source may change.
The 600 changed-line limit excludes `pnpm-lock.yaml` and `apps/server/drizzle/meta/**`. Source edits do not authorize production operations, secret provisioning, merges or deployment. Real credential files remain private.

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

Implement, round review and retro accept only `opencode/deepseek-v4.1-flash-free`;
no paid fallback is configured. OpenCode's [provider policy](https://opencode.ai/docs/zen/) states that
DeepSeek V4.1 Flash Free uses zero retention and does not train on submitted data.
Recheck this policy before changing models. The pinned CLI uses its tested legacy
`permission` configuration; migration to `permissions` needs separate verification.

Final PR review instead runs a pinned Claude Code CLI against a provider's official
Anthropic-compatible endpoint, with paid usage on a dedicated key. Its configuration
lives in the `factory-review` environment, which has no required reviewers and
accepts deployments from `main` only: the variables `FACTORY_REVIEW_BASE_URL`
(`https://api.deepseek.com/anthropic`, or a verified Moonshot endpoint) and
`FACTORY_REVIEW_MODEL`, and the secret `FACTORY_REVIEW_API_KEY`, which should carry
a provider-side spend limit. Every model alias Claude Code uses is set to that one
model, so no hidden request goes to another model. DeepSeek `deepseek-flash` passed
the read-only tool loop, the structured findings schema and the canary in a manual
run against PR #62.

## Implementation runbook

The maintainer creates `agent:implement`, `implementing`, `ready-for-human` and
`needs-human`, enables Actions to create PRs, and configures main protection and
production approval. Review the issue body, then add `agent:implement` while
`ready-for-agent` is present. The label
event starts **Software factory implement** on `main` with the free model above.
Manual dispatch remains available for re-running with the same validation. There is
no dry-run mode.

The gate checks the maintainer actors, issue author, latest authorization label
actor, explicit dependencies and branch/PR uniqueness. Claim checks the captured body
and consumes the execution
label. Each round generates a patch, then a fresh runner without model credentials
installs candidate dependencies, applies `pnpm format`, rechecks the patch and
uploads the formatted patch before running lint, typecheck, admin build and database tests. A failing check produces
`checks.json` (the command and a bounded, ANSI-stripped output tail) for the next
round. Passing checks lead to a read-only review along the two `code-review` axes,
each in its own fresh OpenCode session so neither sees the other's conversation:
Standards (documented repository standards plus the smell baseline) and Spec (the
captured issue body). Each axis returns
`{"findings":[{"blocking":bool,"finding":str}]}`; `control.py review` validates both
and writes `review.json` with the verdict, the blocking findings and the advisory
ones, each labelled with its axis and never reranked. For streams with message IDs,
review parsing selects the final assistant message by `part.messageID` and joins
only its text parts; earlier progress remains in the session transcript. Mixed IDs
or a message ID reappearing after another message fail closed. Streams without IDs
retain whole-stream validation. No JSON substring extraction or earlier-answer
fallback is used. The pinned v2.1.0 CLI's `--format json` is an event transport,
not schema-constrained model output; the final message must still satisfy the
strict review schema. Only a blocking finding
requests changes. Smells are always advisory. Each round also saves `review.md`
with both axes' complete original JSON responses, preserving their order and all
blocking and advisory findings. These full reports are published as comments after
handoff, including earlier rounds that requested changes. Both kinds of repair share one budget of four
rounds. Repair is not a blind retry: every round is checked again, and only the
patch that passed checks and review is published.

Authorization, patch-validation, credential-scan, implementer-error and infrastructure failures
are not repairable and stop the run, as does a repair round that leaves the patch
unchanged. Candidate dependencies and checks run on the fresh verify runner without
model credentials; ordinary PR CI remains authoritative. Handoff validates from a
separate trusted checkout, never running candidate control scripts with its write token.

Only a passing candidate is committed and pushed to a draft PR, referencing its issue.
GitHub-token-created PRs do not trigger CI automatically; marking the draft ready
triggers ordinary CI through `ready_for_review`. Inspect that CI and the diff before
real Feishu acceptance. The factory never claims real Feishu acceptance passed.

Patch, structured feedback, session transcript and retro artifacts expire after
three days. Exact credential values and common credential patterns are checked
before upload. Raw event files, stderr and auth files are never uploaded; complete event
lines appear only inside the scanned transcript. Workspace
paths are pinned with `PWD`; implementation can edit repository files, with credential paths denied and `.env.example` allowed. External directories, subagents and the Skill tool remain denied.
Implementation may use shell for dependency installation, migration generation and checks; review and retro have no shell or network tools.

Shell is the one deliberate trust boundary. Only the implementation session gets
`bash`, so it can run typecheck and single test files as it works. With shell the
model can reach anything on that runner, including the trusted checkout and the model
key. So nothing that runner produces is trusted
beyond its patch: the patch is scanned before upload, and the verify job reapplies it
on a fresh runner without model credentials and repeats the patch, file-type and
line-limit checks before installing candidate dependencies and running checks. This is an accepted limitation, not
a sandbox: running as the same user, the shell can still modify that runner's copy of
the trusted scanner and write to the Actions environment, output and step summary
files. Session uploads name only the exact files just scanned, which contains the
artifact path without closing that boundary. Review and retro sessions are
read-only: they may only read, glob, grep and list inside their workspace, with `.env`
and `auth.json` reads denied.

The shared trusted `supervisor.py` owns process-group deadlines and cleanup for implementation,
review, retro, final review and smoke. Every 60 seconds it writes an allowlisted heartbeat
with phase/axis, elapsed time, event/tool counts and last observed event age. The age is
based on local file activity when event counts advance, not a provider diagnosis. Closed or
full log pipes may drop telemetry without blocking cleanup. Normal/nonzero exits retain their
status; deadlines return 124, signals return 128 + signal. Descendants receive TERM and,
after at most 15 seconds, KILL, even if the leader already exited. Hard runner termination
can still prevent cleanup or terminal reporting. Heartbeats stay in Actions logs; GitHub
comments change only when orchestration phases/outcomes change.

The implementation run has a 1500-second limit; each review axis and the retro run
have 600 seconds each (smoke has 420 seconds within its ten-minute job). All have a 15-second
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
issue state. Gate attempts write an allowlisted reason to the Actions summary. A separate
reporter can explain rejected maintainer triggers even when gate fails: it requires main,
both maintainer actors, an applicable event and a maintainer-owned issue. It upserts only
its own bot status comment for that run, with a reason, next action and run link; public
or unrelated events cannot authorize comments. Gate rejection never changes labels.

Each round records minimal orchestration outcomes in a `round-status-N` artifact kept
for three days, independently of candidate code and model credentials. Terminal status
preserves successful implementation and verification, identifies the failed check when
available, and distinguishes review axis timeout (124), runner error and invalid output.
An axis stopped by Standards failure is `not-started`; absent metadata is `unavailable`,
not proof that no events occurred. Review response validation runs before the next axis.
The status links to the run and available scanned artifacts and requests human inspection,
without guessing a provider/network root cause or starting retries. Status comments are
updated by run ID, and only bot-authored markers count. Final PR review publication and
its separate deduplication/resume markers are unchanged.

Diagnostics are best effort. Checkout failure, absent outputs/artifacts, API failures or
hard cancellation can prevent these reporters from completing. If GitHub cancels the
entire run or its token/API is unavailable, the report job may not execute: inspect the
run, remove a stale `implementing` label,
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
cannot redirect reads outside it. Claude Code runs with `--bare`, an isolated
`HOME` and settings, an empty strict MCP config, hooks disabled and only Read, Glob
and Grep. Before the review, a canary with a planted `CLAUDE.md`, hook and MCP
server must return a clean result without running either; repository standards
are read as data. The review uses the merge-base-to-head diff,
so later unrelated main commits are excluded. Standards always runs. Spec uses
this repository's issues referenced by
`Closes`, `Fixes`, `Resolves` or `Refs #N` in the PR body; their captured bodies supply this review's specification.
Without a linked issue, Spec is skipped and the report explains why. Each axis runs
in a fresh session under a 600-second budget and returns schema-validated structured
output. `control.py` reads the terminal result and validates it again; intermediate
stream events stay on the runner and are not uploaded. A timeout, provider error or
invalid result fails the job without publishing a partial review.

The model job has no GitHub write token. A separate publisher with no model secret
posts the structured blocking and advisory findings as new comments, never editing
previous reports. It neutralizes mentions, scans credentials and
splits losslessly at 60,000 UTF-8 bytes. Invisible first-line markers identify the
head, report digest and part number. Only markers authored by `github-actions[bot]`
count for deduplication: automatic entry skips a complete report for that head.
For a partial set it attempts to recover the original report from an earlier
trusted final-review run's artifacts, verifies its PR, head and digest, then posts
only missing parts. Expired or missing artifacts fall back to a fresh review.
Rerunning the publisher also fills missing parts from its existing report. A moved
head makes the report stale and prevents publication. Manual dispatch always
requests a fresh review.

Findings may carry a repository-relative path and a new-file line number. Only
locations that exist in the reviewed diff are kept; the rest stay in the summary
text. After posting the summary, the publisher submits all located findings as one
PR review with inline comments (`COMMENT`, never an approval or a change request),
so a rejected location fails the step rather than posting half of them. A marker
in that review's body deduplicates identical findings on reruns and during
recovery; only `github-actions[bot]` markers count. Findings too large for one
comment remain in the losslessly split summary.

This review is advisory: its PR review uses `COMMENT`, not an approval or change
request. It changes no labels or PR state, starts no repair, and is not a required
merge check. The maintainer still inspects CI and decides Ready for review and
merge. Factory retro neither waits for nor reads it. Only the structured report and
its identity are retained for three days. See [ADR 0007](adr/0007-final-review-via-pull-request-target.md).
The automatic trigger can be validated live only after the workflow reaches main.

## Execution observation and recovery

GitHub is the status store: bot-owned issue/PR comments are the durable entry point,
Actions summaries provide aggregate views, and safe metadata artifacts last 90 days.
Sensitive session/patch/review/retro artifacts retain their three-day lifetime and scans.
No database, external telemetry, secret or notification integration is needed.

`software-factory-observe.yml` runs trusted main code on implementation/final-review
`workflow_run` in-progress and completed events. It polls orchestration metadata once per
minute for at most five hours, updating its bot-owned comment only when phase/outcomes
change. This is STARTED and phase progress, not a model heartbeat notification. It writes
one schema-versioned execution manifest with repository, run/attempt, issue/PR, explicit
parent identity, branch/head/base when known, state/reason, phase/jobs, times, next action
and evidence links. Missing fields remain unavailable. Implementation delivery, independent
final-review publication, retro publication and ordinary PR CI are separate states.
The existing gate rejection/round diagnostics remain detailed evidence; observer comments
use their own marker and cannot overwrite those diagnostics or final-review report markers.

The observer verifies workflow ID/path, repository, main, event, owner actors, issue/PR
ownership and same-repository target before writes. Public/unrelated events are summary-only.
The observer never downloads model artifacts or executes candidate code. Final bot dispatch
must name its originating `run_id.run_attempt`; trusted parent metadata, successful handoff
and exact task PR branch bind that identity. The dispatch API returns no child run ID:
only an observed child supplies its own link/state. A standalone review has no parent.
The final-review dedupe/resume protocol remains unchanged. No automatic retry follows
failed dispatch, final review, retro, CI or observation.

`software-factory-reconcile.yml` runs every six hours or manually on main with read-only
permissions. Its Actions summary links recent trusted executions and reports stale running
implementation (>3 hours), completed tasks retaining `implementing`, final review not
observed >30 minutes after delivery, failed/missing publication and recorded expired
evidence. It links available PR/head CI and merged-head deployment metadata; pending and
unavailable remain explicit. It proposes concrete human inspection steps and never changes
labels, authorizes implementation, retries, merges or deploys. This schedule performs only
metadata reads; enabling it does not enable an automated implementation run.

Recovery bounds are 90 days, three pages of 100 runs per workflow, 20 detailed runs per
workflow, three pages of 100 jobs per run, one page of 100 artifact records and a hard
300-request budget. Partial failures and scan limits are shown. A recorded expired artifact
is distinct from absent/unknown evidence: deletion or API omission cannot prove it was
never produced. Arbitrary comments, titles, artifacts and candidate output cannot authorize
recovery writes; reconciliation makes no writes at all.

Comments survive artifact expiry, but observers are best effort: checkout/API/token failures,
GitHub scheduling delays, hard cancellation and a run exceeding the observation window may
leave a partial snapshot. Reruns share a source run marker and show the current attempt;
parent/child correlation retains the explicit originating attempt. Inspect the Actions run
and bounded recovery summary before removing stale labels, resolving existing branches/PRs
and deliberately authorizing a new task. A green implementation is not proof of final review,
retro delivery, ordinary CI, deployment or human acceptance.

## Human-only operations

The maintainer must configure GitHub rulesets, the `production` environment, secrets, the GitHub App, server SSH policy, and the model provider account. The maintainer must also confirm the deployment after setting `SESSION_SECRET`, review every factory PR, and perform real Feishu acceptance. No workflow in this phase performs those operations.

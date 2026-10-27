# Software factory

This repository is public, but the software factory treats repository text as untrusted input. The factory exists to test whether AFK implementation reduces maintainer coordination without reducing delivery quality.

## Trust boundaries

- `ready-for-agent` means that an issue is fully specified. It does not authorize execution.
- `agent:implement` is the explicit execution label. Only the maintainer adds it after checking the issue, its dependencies, and its acceptance criteria.
- External issues, comments, pull requests, and fork branches are not factory instructions. A maintainer must copy an accepted request into a maintainer-owned issue before it can enter the factory.
- The implementation workflow verifies the label actor, issue author, issue state and explicit `Blocked by #N` dependencies, then captures the issue body automatically for that run. It writes untrusted text to a file rather than interpolating it into a shell command.
- The agent never receives production secrets, the `production` environment, a GitHub App token, or deployment access.

## Task lifecycle

The implementation lifecycle is:

```text
ready-for-agent + agent:implement -> implementing
  -> round: implement -> format + checks -> Standards review + Spec review
       check failure or blocking finding -> next round (three rounds in total)
  -> draft PR -> ready-for-human
       -> independent agent PR review -> advisory comments
  -> needs-human (authorization, patch validation, credential or infrastructure failure, or budget exhausted)
  -> publish round-review findings on the draft PR, or on the issue without one
```

A task is keyed by issue number and has one concurrency group. The implementation and review runs are independent. The maintainer reviews the draft PR and CI evidence, performs the issue's human acceptance and decides whether to merge. Local real Feishu testing must avoid a competing production listener; acceptance against production itself does not require stopping it.

## Implementation controls

The trusted controls and prompts live in `.github/software-factory/`.
`control.py` is the compatibility CLI, loaded from the dispatch revision independently
of the candidate tree. `authorization.py` owns task snapshots and claims;
`publication.py` owns review markers and missing-part plans; `agent_runner.py` owns
supervised, sequential review execution; `execution.py` shares metadata vocabulary
and publication outcomes between observation and reconciliation. `artifacts.py`
owns patch scope checks and credential scanning. `verification.py`
executes candidate checks and binds them to the formatted source tree. Python entry
points retain isolated mode and resolve modules only from their trusted directory.
Run its regression suite with `python3 -I -m unittest discover -s .github/software-factory -p 'test_*.py'`.

The issue body is the sole specification for implementation and Spec review. Gate captures it automatically for all rounds and reviews; no per-issue JSON or policy file is required.
Claim rejects a body changed since gate; later live edits do not change the run. Branch and Conventional Commit title are generated from the issue number.
Native GitHub dependencies and explicit same-repository `Blocked by #N` references are checked before claim; ordinary references do not block execution.

There is no task path allowlist: source, tests, docs, schema, new migrations, dependencies, environment declarations, `.env.example` and CI/deployment source may change.
The 600 changed-line limit excludes `pnpm-lock.yaml` and `apps/server/drizzle/meta/**`. Source edits do not authorize production operations, secret provisioning, merges or deployment. Real credential files remain private.

Review follows the `code-review` skill vendored, unmodified, from one pinned
upstream commit (see `skills/README.md`). The factory never fetches skills at run
time. `control.py` inlines the two sub-agent briefs and standards section into the
prompts. The regression suite pins the commit and file SHA-256, and checks that
referenced files and skills are vendored. To update, replace the skill from one new
commit and update both pins. The prompt builder removes only the briefs' upstream
"Under 400 words." instruction; vendored files stay unchanged. Reviews have no
response word, character or finding-count cap and include supported judgement calls.
The pinned `pr/SKILL.md` supplies the same PR-body template used by an interactive
`/pr` session. Trusted handoff fills it with known run facts; the implementation
agent does not invoke the skill or receive PR permissions.
They require a successful native result with schema-validated `structured_output`;
partial results and automatic whole-role retries are not accepted.

All Factory Agents use the same pinned Claude Code CLI and one dedicated paid Provider configuration. Implement and both round-review jobs declare `environment: agent` directly because reusable-workflow callers cannot set a called job's environment; agent review does the same. The `agent` environment has no required reviewers, accepts deployments from `main` only, and defines `AGENT_BASE_URL` (initially `https://api.deepseek.com/anthropic`), `AGENT_MODEL` (initially `deepseek-flash`), and the secret `AGENT_API_KEY`. Keep this key separate from production chat credentials and give it a provider-side spend limit. Every model alias Claude Code uses is set to the selected model, so no hidden request goes to another model. DeepSeek `deepseek-flash` passed the agent-review read-only tool loop, structured findings schema and configuration canary in a manual run against PR #62; implement and round review also passed in [run 40102471987](https://github.com/b1ngsha/tanomu/actions/runs/40102471987), which created draft PR #77.

## Implementation runbook

The maintainer creates `agent:implement`, `implementing`, `ready-for-human` and
`needs-human`, enables Actions to create PRs, and configures main protection and
production approval. Review the issue body, then add `agent:implement` while
`ready-for-agent` is present. The label
event starts **Software factory implement** on `main` with the configured Factory Agent.
Manual dispatch remains available for re-running with the same validation. There is
no dry-run mode.

The gate checks the maintainer actors, issue author, latest authorization label
actor, explicit dependencies and branch/PR uniqueness. Claim checks the captured body
and consumes the execution
label. Each round generates a patch, then a fresh runner without model credentials
builds a trusted Node 24 / pnpm 11.20.0 container, installs candidate dependencies
without lifecycle scripts, applies `pnpm format`, rechecks the patch and uploads the
formatted patch before running lint, typecheck, admin build and database tests.
Candidate commands run inside disposable containers with only the candidate tree
mounted writable and its Git directory mounted read-only. Trusted controls, patch
evidence, Docker's socket and Actions command files are not mounted. Containers use
the host network to reach the disposable database. After formatting, the host records
the base SHA, patch SHA-256 and Git tree identity; after each later check it requires
the same identity, ignoring ordinary untracked build output covered by `.gitignore`.
A retained source mutation fails that check. This does not prove candidate tests are
honest, and does not detect a temporary source mutation restored within one command;
ordinary PR CI and human review remain authoritative. A failing check produces
`checks.json` (the command and a bounded, ANSI-stripped output tail) for the next
round. Passing checks lead to a read-only review along the two `code-review` axes,
each in its own fresh Claude Code session so neither sees the other's conversation:
Standards (documented repository standards plus the smell baseline) and Spec (the
captured issue body). Each axis returns native `structured_output` matching
`{"findings":[{"blocking":bool,"finding":str}]}`. `control.py claude-result` validates
both native result envelopes again and writes `review.json` with the verdict, the
blocking findings and the advisory ones, each labelled with its axis and never
reranked. Only a blocking finding requests changes. Smells are always advisory.
All findings from every completed round are rendered from `review.json` and published
as comments after handoff, including earlier rounds that requested changes; no
second review-Markdown response is generated. Both kinds of repair share one budget
of three rounds: the initial attempt and two repairs. Repair is not a blind retry: every round is checked again, and only
the patch bound to passing checks and review is published.

Authorization, patch-validation, credential-scan, implementer-error and infrastructure failures
are not repairable and stop the run, as does a repair round that leaves the patch
unchanged. Candidate dependencies and checks run on the fresh verify runner without
model credentials; ordinary PR CI remains authoritative. Handoff validates from a
separate trusted checkout, never running candidate control scripts with its write token.

Only a passing candidate is committed and pushed to a draft PR, referencing its issue.
GitHub-token-created PRs do not trigger CI automatically; marking the draft ready
triggers ordinary CI through `ready_for_review`. Inspect that CI and the diff before
real Feishu acceptance. The factory never claims real Feishu acceptance passed.

Patch, structured feedback and session transcript artifacts expire after
three days. Exact credential values and common credential patterns are checked
before upload. Native JSON result envelopes, stderr and auth files stay on the runner;
native Claude Code JSONL sessions are copied unchanged, scanned and uploaded as opaque
Run Evidence. Workspace
paths are pinned with `PWD`; implementation can edit repository files, with credential paths denied and `.env.example` allowed. External directories, subagents and the Skill tool remain denied.
Implementation may use shell for dependency installation, migration generation and checks; review has no shell or network tools.

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
artifact path without closing that boundary. Review sessions are
read-only: they may only read, glob, grep and list inside their workspace, with `.env`
and `auth.json` reads denied.

The shared trusted `supervisor.py` owns process-group deadlines and cleanup for implementation,
round review and agent review. Every 60 seconds it writes an allowlisted heartbeat
with phase/axis, elapsed time, native result/transcript byte counts and last observed
file-activity age. File activity is only a liveness observation, not a provider diagnosis.
Closed or full log pipes may drop telemetry without blocking cleanup. Normal/nonzero
exits retain their status; deadlines return 124, signals return 128 + signal. Descendants
receive TERM and, after at most 15 seconds, KILL, even if the leader already exited.
Hard runner termination can still prevent cleanup or terminal reporting. Heartbeats
stay in Actions logs; GitHub comments change only when orchestration phases/outcomes change.

The implementation run has a 1500-second limit; each review axis has 600 seconds. All have a 15-second kill grace period. After success, timeout
(exit 124) or any other nonzero exit, a trusted `agent-summary` line is written to the
step log and job summary. It has only the exit status, elapsed seconds and result/
transcript byte counts. The original exit status is then propagated, and nothing is
retried. Model text, tool inputs and outputs, error messages, paths and stderr are
never printed. The summary shows process activity, not why the run stopped.

Implement and round review retain their native session JSONL unchanged as Run
Evidence for human diagnosis. Claude Code's internal event schema is not a parsing
contract. A step
that always runs copies each explicitly named session, scans it with `scan-session`
(the same credential checks, without a size cap), and only then uploads it as a
`session-*` artifact kept for three days. Agent review uses `--no-session-persistence`
and retains only its structured report and identity. A transcript that is missing or
fails the scan is not uploaded; session recording is best effort after a failed run.

After every claimed run that was not cancelled, `publish-reviews` waits for the
rounds and handoff, then publishes all available round-review findings. It holds no
model secret, downloads only `feedback-*`, rescans the structured reports and
neutralizes `@` mentions. Reports go to the task's open draft PR, or to the issue
when there is no PR, including findings from earlier rounds that requested changes.
Missing feedback does not prevent other reports from publishing. Each report is
split losslessly into numbered comments of at most 60,000 UTF-8 bytes; no findings
are dropped. Report scans have no size cap and reject the whole report on a
credential match. The factory does not run an automatic retro or publish retro
proposals. Maintainers can inspect retained Run Evidence when diagnosis is needed.

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
updated by run ID, and only bot-authored markers count. Agent PR review publication and
its separate deduplication/resume markers are unchanged.

Diagnostics are best effort. Checkout failure, absent outputs/artifacts, API failures or
hard cancellation can prevent these reporters from completing. If GitHub cancels the
entire run or its token/API is unavailable, the report job may not execute: inspect the
run, remove a stale `implementing` label,
and resolve any existing branch/PR before deliberately authorizing another run.
Never blindly rerun a claimed or partially published task.

## Stacked PR management

Stacked PRs use GitHub's official `gh stack` extension. Read [the stacked PR runbook](agents/stacked-prs.md) before creating, linking, syncing, rebasing, submitting, or merging a stack. The Admin Console chain #103 → #104 → #106 → #107 → #109 → #111 → #113 is linked as GitHub stack #117.

The stack manager owns branch ancestry, PR base branches, rebases, pushes and stack merges. It does not grant Agent review any branch or PR mutation authority. Agent review remains an independent advisory workflow: it reads the current merge-base-to-head diff, records freshness for the current PR revision, and publishes comments without retargeting, rebasing, pushing, merging or closing PRs. A stack rebase can therefore require fresh CI and Agent review evidence even when the feature change itself is unchanged.

`/advance-pr-stack` is deprecated for normal operations and remains only as a recovery path for legacy stacks that cannot be imported into GitHub. Its regression test remains in CI until legacy stacks are migrated and one complete official stack synchronization and merge cycle has been accepted. Remove the skill and its test together after that cutover.

## Agent PR review

Agent review uses `agent-review.yml` and `agent-review-status.yml`. Historical
`final-review.yml` runs remain eligible for recovery; `final-*` CLI commands, receipt
markers, artifact names and metadata keys stay unchanged. New report identities freeze
the Agent review title; old identities retain their original title and digest when recovered.

`agent-review.yml` starts a fresh read-only review when a same-repository PR is
opened, reopened or marked Ready for review. Automatic entry skips Bot authors and
forks. The factory explicitly dispatches it after creating its draft PR, because
`GITHUB_TOKEN` creation does not fire PR workflows. Maintainers can force another
review with `gh workflow run agent-review.yml --ref main -f pr=N`. Pushes alone do
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
output. `control.py` reads the native single-result JSON envelope and validates its
`structured_output` again. Each native envelope is validated before starting the next axis. The result file stays on the runner and is not uploaded. A timeout, provider error or
invalid result fails the job without publishing a partial review.

The model job has no GitHub write token. A separate publisher with no model secret
posts the structured blocking and advisory findings as new comments, never editing
previous reports. It neutralizes mentions, scans credentials and
splits losslessly at 60,000 UTF-8 bytes. Invisible first-line markers identify the
head, report digest and part number. Only markers authored by `github-actions[bot]`
count for deduplication. New summary markers also record the expected inline digest
(or `none`); automatic entry skips only when every summary part and any expected
inline review are present. Legacy summaries have unknown inline status and are
checked through recovery. For an incomplete publication it attempts to recover the original report from an earlier
trusted agent-review run's artifacts, verifies its PR, head and digest, then posts
missing parts. Recovery of legacy markers also posts a modern first-part receipt so
completion remains detectable after the artifacts expire. Expired or missing
artifacts needed for recovery fall back to a fresh review.
Rerunning the publisher also fills missing parts from its existing report. A moved
head makes the report stale and prevents publication. Manual dispatch always
requests a fresh review.

`agent-review-status.yml` separately checks the current PR head on open, synchronize,
reopen and Ready for review. It reuses the bot-owned summary and inline receipts to
report `current`, `stale` (including incomplete publication) or `missing`; a public
comment cannot forge these receipts. A stale result updates one bot-owned advisory
comment with the current and reviewed heads and the manual rerun command. Initial `missing`
results stay silent; an existing status comment is refreshed even when receipts disappear. The
publisher dispatches a status refresh after posting a review, including inline
findings, so a completed manual rerun retires the stale status. Only the status
workflow writes this comment. Its separate cancelling group supersedes older status
runs without cancelling or replacing any paid review; every run reads live state.
The status job has no Provider secret, never invokes the model and rechecks the head
before writing. It does not make review a required check or start another paid review
on every push.

Findings may carry a repository-relative path and a new-file line number. Only
locations that exist in the reviewed diff are kept; the rest stay in the summary
text. New reviews post a brief summary with blocking/advisory counts and direct readers
to inline comments for located findings, without repeating their text. Findings
without a publishable location, including oversized inline comments, remain in full
in the summary. The presentation format is frozen in the review identity, so recovery
of earlier reports preserves their original rendering and digest. After posting the
summary, the publisher submits all located findings as one
PR review with inline comments (`COMMENT`, never an approval or a change request),
so a rejected location fails the step rather than posting half of them. A marker
in that review's body deduplicates identical findings on reruns and during
recovery; only `github-actions[bot]` markers count. Findings too large for one
comment remain in the losslessly split summary.

This review is advisory: its PR review uses `COMMENT`, not an approval or change
request. It changes no labels or PR state, starts no repair, and is not a required
merge check. The maintainer still inspects CI and decides Ready for review and
merge. Only the structured report and
its identity are retained for three days. See [ADR 0007](adr/0007-final-review-via-pull-request-target.md).
The automatic trigger can be validated live only after the workflow reaches main.

## Execution observation and recovery

GitHub is the status store: bot-owned issue/PR comments are the durable entry point,
Actions summaries provide aggregate views, and safe metadata artifacts last 90 days.
Sensitive session/patch/review artifacts retain their three-day lifetime and scans.
No database, external telemetry, secret or notification integration is needed.

`software-factory-observe.yml` runs trusted main code on implementation/agent-review
`workflow_run` in-progress and completed events. It polls orchestration metadata once per
minute for at most five hours, updating its bot-owned comment only when phase/outcomes
change. This is STARTED and phase progress, not a model heartbeat notification. It writes
one schema-versioned execution manifest (schema 2) with repository, run/attempt,
issue/PR, explicit parent identity, branch, current PR head/base, state/reason,
phase/jobs, times, next action
and evidence links. `current_head/current_base` describe the live PR, never the
reviewed revision. `reviewed_head/reviewed_base` remain unknown because observation
reads Actions metadata only; the frozen review identity stays in the review artifact.
Missing fields remain unavailable. Implementation delivery, independent
round-review comment publication, agent-review publication and ordinary PR CI are separate states.
Observer comment lookup follows all pages before creating a new comment; a failed lookup never authorizes a duplicate.
The existing gate rejection/round diagnostics remain detailed evidence; observer comments
use their own marker and cannot overwrite those diagnostics or agent-review report markers.

The observer verifies workflow ID/path, repository, main, event, owner actors, issue/PR
ownership and same-repository target before writes. Public/unrelated events are summary-only.
The observer never downloads model artifacts or executes candidate code. Final bot dispatch
must name its originating `run_id.run_attempt`; trusted parent metadata, successful handoff
and exact task PR branch bind that identity. The dispatch API returns no child run ID:
only an observed child supplies its own link/state. A standalone review has no parent.
The agent-review dedupe/resume protocol remains unchanged. No automatic retry follows
failed dispatch, review publication, CI or observation.

`software-factory-reconcile.yml` runs every six hours or manually on main with read-only
permissions. Its Actions summary links recent trusted executions and reports stale running
implementation (>3 hours), completed tasks retaining `implementing`, agent review not
observed >30 minutes after delivery, failed/missing final or claimed-round comment publication and recorded expired
evidence, including session, feedback and checked-patch artifacts. It links available PR/head CI and merged-head deployment metadata; pending and
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
and deliberately authorizing a new task. A green implementation is not proof of agent review,
round-review comment delivery, ordinary CI, deployment or human acceptance.

## Human-only operations

The maintainer must configure GitHub rulesets, the `production` environment, secrets, the GitHub App, server SSH policy, and the model provider account. The maintainer must also confirm the deployment after setting `SESSION_SECRET`, review every factory PR, and perform real Feishu acceptance. No workflow in this phase performs those operations.

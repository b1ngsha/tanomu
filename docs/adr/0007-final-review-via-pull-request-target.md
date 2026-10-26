---
status: accepted
---

# Review new PRs using trusted main code

Every new same-repository PR gets an independent Agent review published as plain
comments before the maintainer decides Ready for review or merge. This complements
the factory's round review, which drives repair, and ordinary PR CI. It has no
merge authority and does not run candidate code.

Use a separate `pull_request_target` workflow for opened, reopened and
ready_for_review events, with trusted controls and prompts from main. A
`pull_request` workflow can be rewritten by the candidate and is unsuitable for a
review job holding a model credential. The candidate's exact head is data for
read-only inspection; the diff starts at its merge base. Claude Code runs with `--bare --restricted`, an isolated configuration, hooks
disabled and an empty strict MCP configuration. A canary verifies candidate project
configuration stays inert; only Read, Glob and Grep are available.
Repository and issue text are untrusted, including instructions embedded in them.
The model job has only
read permissions; a separate publisher has GitHub write permissions and no model
secret. Neither job receives production access.

Skip forks and automatically triggered Bot-authored PRs. Factory PRs created with
`GITHUB_TOKEN` do not fire PR events, so handoff explicitly dispatches the workflow
on main. Manual dispatch also forces a new review. Pushes do not trigger it. Runs
are serialized per PR without cancelling the previous run; stale heads are not
published.

The independent review is named **Agent review** and its active workflows use
`agent-review*.yml` filenames. A separate advisory status workflow also listens to
synchronize events and cancels superseded status runs in its own group. It never calls
a model or cancels a paid review. Recovery accepts historical `final-review.yml` runs;
receipt markers, artifact names and metadata keys retain their `final-*` identifiers.

Standards always runs; Spec uses captured linked same-repository issues. Reports preserve
all structured findings, split into credential-scanned comments with
invisible head/digest/part markers. Only the Actions bot's markers count for
complete-report deduplication or filling missing parts. Completion includes any
inline review expected by the summary marker. Automatic recovery reuses
an earlier trusted workflow's report only after checking its PR, head and digest;
expired artifacts fall back to a fresh review. Manual dispatch always runs a new
review. Old reports remain visible.
Agent review does not persist native sessions; structured reports and identities
expire after three days. The cost is
an extra model review and an advisory report that can become outdated after a push;
the maintainer can explicitly request a fresh one.

---
status: accepted
---

# Run factory agents on Claude Code through an Anthropic-compatible provider

The factory previously reconstructed review results from OpenCode's event stream
and parsed them as strict JSON with no retry. Formatting noise from the free model
could fail whole runs, and the adapters also rendered provider-specific session
transcripts for retro. Automatic retro has since been removed; retained Run Evidence
serves human diagnosis. All remaining Factory Agent roles use one pinned Claude Code CLI:
implement produces the candidate patch, both round-review axes and final review
consume native `structured_output`. A provider failure, timeout or invalid result
fails the job without publishing a partial result; the job does not retry the whole role.

The default deployment connects each model job directly to one Provider's official
Anthropic-compatible endpoint. The `agent` GitHub environment defines
`AGENT_BASE_URL`, `AGENT_MODEL` and `AGENT_API_KEY`, initially DeepSeek's
`https://api.deepseek.com/anthropic` with `deepseek-flash`. It has no required
reviewers, accepts deployments from `main` only, and uses a factory-only,
spend-bounded key separate from production chat credentials. Reusable round jobs
declare this environment themselves because callers cannot select it for them.
There is no dynamic routing, alternate-model fallback or second agent harness.

A direct provider connection avoids operating a gateway and keeps the Provider's
spending controls and retention policy authoritative. Magpie remains an optional
later gateway, introduced only if the factory needs centralized credentials,
cross-provider accounting, routing, shared limits or audit logging. A gateway is
not automatically safer or more compatible than direct access. Non-Claude models
are permitted by this decision, although routing Claude Code to them is outside
Anthropic's support boundary; each selected role requires live Provider Preflight.

The official Claude Code Action is not used: it posts to GitHub itself and manages
its own permissions, which conflicts with the separate publisher. ADR 0007's
boundaries are unchanged: trusted main code, a read-only final-review model job,
a publisher without the model secret, and stale-head handling. Every role uses
`--bare --restricted`, isolated settings, an empty strict MCP configuration and
explicit tools. Review has only Read, Glob and Grep. Implement also has
Edit, Write and Bash. Configuration canaries check planted project instructions,
hooks and MCP servers; implement's canary also exercises its intended write/shell
path in a disposable directory.

Claude permissions are not a security sandbox. Implement's shell can read the
factory Provider key and alter anything on its runner, so only its scanned patch
crosses to a fresh verify runner without model credentials. The verify runner
repeats patch validation before installing candidate dependencies or running
checks. Native Claude sandboxing is a separate decision, not a substitute for this
handoff.

Implement and round review keep native session JSONL unchanged as
credential-scanned Run Evidence. Its internal schema is not an adapter contract.
Final review remains sessionless. The obsolete manual OpenCode smoke workflow is removed: Provider Preflight is an
operational check, not a task-lifecycle stage. Round findings are published from
`review.json`, eliminating the duplicate review-Markdown response.

This replaces the free-only model policy. The cost is paid usage and data sent to
the chosen upstream under its retention terms rather than zero retention.

---
status: accepted
---

# Run factory agents on Claude Code through an Anthropic-compatible provider

The factory reconstructed review results from OpenCode's event stream and parsed
them as strict JSON with no retry, so formatting noise from the free model (such as
a leading zero-width space) failed whole runs as `invalid-review`. Implement, round
review and final review therefore move to a pinned Claude Code CLI, one PR per
path, final review first as the spike. Review and retro use Claude Code's
schema-validated structured output with the existing findings schema. A provider
failure, timeout or invalid structured result fails the job without publishing a
partial review; the job does not retry the whole review.

The default deployment is direct from each job to one provider's official
Anthropic-compatible endpoint. DeepSeek's documented endpoint is
`https://api.deepseek.com/anthropic` and its Claude Code setup explicitly uses
`ANTHROPIC_BASE_URL` plus a provider key. Kimi/Moonshot also offers an
Anthropic-compatible endpoint, but its public compatibility documentation is less
complete; its endpoint, model, tool loop, streaming, and structured-output behavior
must be verified in the spike before it is selected. A direct provider connection
avoids operating a gateway and keeps the provider's own spending controls and
retention policy authoritative.

Magpie remains an optional later gateway, not a required part of this architecture.
Introduce it only if the factory needs provider switching without workflow changes,
centralized per-client credentials, cross-provider usage accounting, routing,
shared limits, or audit logging. If introduced, it must expose the Anthropic
Messages format and preserve Claude Code's headers, streaming events, request body
fields, and error responses; it is not automatically safer or more compatible than
direct access.

Each role uses one fixed provider/model from repository variables, with no route
selection or dynamic routing inside a run. The implement shell may read its
provider key, which is dedicated to the factory, separately revocable, and bounded
by a provider-side spending limit. A model is accepted only after the spike
repeatedly verifies its tool loop and structured output. Non-Claude models such as
DeepSeek or Kimi are permitted by this repository decision, although routing Claude
Code to them is outside Anthropic's support boundary.

The official Claude Code Action is not used: it posts to GitHub itself and manages
its own permissions, which conflicts with the separate publisher. ADR 0007's
boundaries are unchanged: trusted main code, a read-only model job, a publisher
without the model secret, and stale-head handling. Candidate configuration is
disabled in place of OpenCode's project-config switches: an isolated `HOME`,
user-only setting sources, an empty strict MCP config and, for review, only
read/glob/grep tools. A canary verifies that a planted `CLAUDE.md` and hook are
ignored. Implement starts from trusted main and may load `AGENTS.md`.

This replaces the free-only model policy in `docs/software-factory.md`. The cost is
paid usage and data sent to the chosen upstream under its retention terms rather
than zero retention. Each OpenCode path stays until its replacement merges.

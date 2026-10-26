# Implementing a ticket

The workflow for an agent picking up a `ready-for-agent` ticket. Read [AGENTS.md](../../AGENTS.md)
first for repository commands, conventions, and documentation entry points.

## Before writing code

1. Read the ticket body and comments in full (`gh issue view <n> --comments`). A `ready-for-agent`
   ticket needs Context, Design, PR plan, Tests, and Acceptance criteria; write up a `needs-triage`
   ticket before implementing it. Preserve recorded decisions; resolve ADR conflicts with the human.
   Factory runs use the issue body captured at gate as their specification; required decisions must
   be in that body before authorization.
2. Read [GLOSSARY.md](../../GLOSSARY.md), then the standards and architecture sections relevant to
   the change through AGENTS.md. Use the glossary's terms in code, tests, commits, and PRs.
3. Check the ticket's PR plan against AGENTS.md's size and independent-deployment requirements.
   Merging to `main` deploys to production. Create a branch per PR: `<type>/<ticket>-<slug>`.

## While writing code

1. Implement and test at the owning module's interface. Run `pnpm typecheck` and the focused test
   file often; use [coding standards](../../CODING_STANDARDS.md) for engineering and test rules.
2. For configuration, real Feishu listening, or deployment changes, follow the relevant procedure
   in [the deployment runbook](../deployment.md) before exercising or shipping the change.

## Finishing

1. Run `pnpm format && pnpm lint && pnpm test:db` before committing code changes; report skipped
   checks and missing prerequisites. For documentation-only changes, run `pnpm format:check` and
   `git diff --check`, and verify affected links and instructions.
2. In an interactive session, run `/simplify` on code changes, then `/code-review` against `main`
   with the ticket as spec, and fix what's worth fixing. In the factory, the orchestrator owns
   independent review and trusted publication; its implementation session does not invoke skills,
   commit, or open PRs. See [the factory runbook](../software-factory.md) for that handoff.
3. When authorized to publish, use AGENTS.md's commit conventions and ticket references, and the
   `pr` skill's template. Evidence must be observed output; list required human steps under Merge
   Danger. If Feishu console changes, server root access, or secrets need a human, state the exact
   action and wait for it before the dependent step.

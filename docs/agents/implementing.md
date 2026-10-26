# Implementing a ticket

The playbook for an agent picking up a `ready-for-agent` ticket. Read `AGENTS.md` first; this file adds the workflow and the traps that have already bitten this repo.

Only `ready-for-agent` tickets are detailed enough to implement directly (Context, Design, PR plan, Tests, Acceptance criteria). A `needs-triage` ticket must be written up first; don't start it from its one-paragraph summary.

## Before writing code

1. Read the ticket body and its comments in full (`gh issue view <n> --comments`). The **Context** section records decisions made in conversations you weren't part of; don't relitigate them. Factory runs use the issue body captured at gate as their task specification for implementation and review; put required decisions in that body before authorization. If the ticket contradicts an ADR, stop and ask.
2. Read `GLOSSARY.md` and use its terms in code, tests, commits, and PRs (Private Conversation, Capability, Provider, Digest Rule…).
3. Check the ticket's **PR plan**. Each PR changes at most 600 lines (CI `pr-size`) and must be mergeable and deployable alone: merging to `main` deploys to production immediately.
4. Create a branch per PR: `<type>/<ticket>-<slug>`, e.g. `feat/7-llm-call-log`.

## While writing code

- **Domain logic lives in `packages/core`** and takes its dependencies as interfaces (see `ConversationStore` and `ReplyDeps`). Feishu, Postgres, and Provider adapters live in `apps/server` and are wired in `apps/server/src/main.ts`.
- **Test first at the core seam**: unit tests in `packages/core/test/` with in-memory fakes and `MockLanguageModelV4` from `ai/test` (see `private-conversation.test.ts`). Postgres adapters get tests in `apps/server/test/` that are skipped without `TEST_DATABASE_URL`.
- **Verify third-party APIs instead of guessing.** For Feishu/Lark endpoints use the `lark-openapi-explorer` skill or the official docs; for the AI SDK read the installed types under `node_modules/ai/dist/index.d.ts` (the repo is on AI SDK v7, newer than most training data).
- Run `pnpm typecheck` and the single test file you're working on often; run `pnpm format && pnpm lint && pnpm test:db` before committing.

## Traps

- **Adding an environment variable** takes four edits, or production breaks:
  1. `apps/server/src/config.ts` (zod schema)
  2. `.env.example`
  3. the deploy step in `.github/workflows/ci.yml`: its `env:` block **and** the `app_vars` list
  4. the table in `docs/deployment.md`

  Then ask the human to add the value to the GitHub `production` environment **before** the PR merges. Never put secret values in code, commits, PR text, or chat.

- **Schema changes**: edit `apps/server/src/db/schema.ts`, run `pnpm db:generate`, commit the SQL and the `drizzle/meta` snapshot. Migrations run on server start. Never edit an applied migration.
- **Feishu long connection delivers each event to one client.** Local `pnpm dev` and production share the Feishu app, so ask the human to stop production (`docker compose stop server` in `/opt/tanomu`) before testing against real Feishu, and to start it afterwards.
- **Ack Feishu events fast.** The handler in `apps/server/src/feishu.ts` must not await slow work, or Feishu redelivers the event; dedupe relies on the unique Feishu message id.
- **The deploy health check greps for `tanomu is listening`** (logged in `main.ts`). Don't change that line without changing `.github/workflows/ci.yml`.
- **The server is in mainland China** and reaches the internet only through a proxy at build time. New runtime dependencies on overseas APIs may need a proxy; flag them in the PR.

## Finishing

1. In an interactive agent session, run `/simplify` on the change, then `/code-review` against `main` with the ticket as spec, and fix what's worth fixing. In the factory, the orchestrator runs independent review; its restricted implementation session does not invoke skills, commit or open PRs. The trusted handoff uses the pinned `pr` skill's template to create the draft PR without model-generated publication text.
2. Commit with Conventional Commits and a scope (`AGENTS.md`), body `Refs #N`, or `Closes #N` on the ticket's last PR.
3. Open the PR with the `pr` skill's template (Summary / Evidence / Merge Danger). Evidence must be real output: test names and results, or what you observed running it. List any human steps (Feishu console changes, new GitHub variables or secrets) under Merge Danger.
4. If a step needs a human (Feishu console, server root access, secrets), stop and say exactly what to do; don't work around it.

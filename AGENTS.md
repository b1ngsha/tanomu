# tanomu

A personal agent living in Feishu. Domain language: `GLOSSARY.md`. Decisions: `docs/adr/`.

## Layout

- `packages/core`: domain logic (Conversations, agent loop). No Feishu or database imports; dependencies come in as interfaces.
- `apps/server`: the single Node process. Adapters for Feishu (long connection), Postgres (Drizzle), and model Providers, wired together in `src/main.ts`.
- `apps/admin`: the web admin console (not created yet).

TypeScript runs directly on Node via type stripping, no build step. Use `.ts` extensions in relative imports and only erasable syntax (no enums, no parameter properties).

## Commands

- `cp .env.example .env` and fill it in (never commit `.env`, never print it)
- `docker compose up -d db`: local Postgres with pgvector on `localhost:54329`
- `pnpm dev`: run the server with watch mode (applies migrations on start)
- `pnpm test` / `pnpm test:db`: unit tests / unit tests plus Postgres-backed tests against the `tanomu_test` database in the local compose DB
- `pnpm lint` (oxlint, type-aware), `pnpm format` (oxfmt), `pnpm typecheck`
- `pnpm db:generate`: generate a migration after editing `apps/server/src/db/schema.ts`

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (b1ngsha/tanomu) via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

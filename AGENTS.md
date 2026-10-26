# tanomu

A personal agent living in Feishu. Domain language: `GLOSSARY.md`. Decisions: `docs/adr/`.

## Layout

- `packages/core`: domain logic (Conversations, agent loop). No Feishu or database imports; dependencies come in as interfaces.
- `apps/server`: the single Node process. Adapters for Feishu (long connection), Postgres (Drizzle), and model Providers, wired together in `src/main.ts`.
- `apps/admin`: React + Vite + shadcn/ui admin console; its production bundle is served by `apps/server`.
- `deploy/`: production compose file and backup script, copied to the server by the deploy job.

Server and core TypeScript run directly on Node via type stripping, no build step. `apps/admin` is the exception: Vite builds its browser bundle. Use `.ts` extensions in relative imports and only erasable syntax (no enums, no parameter properties).

## Commands

- `cp .env.example .env` and fill it in (never commit `.env`, never print it)
- `docker compose up -d db`: local Postgres with pgvector on `localhost:54329`
- `pnpm dev`: run the server with watch mode (applies migrations on start)
- `pnpm dev:admin`: run Vite on `localhost:3000`; set `HTTP_PORT=3001` in `.env` for the server and run both commands in separate terminals. Observe the Feishu listener warning in `docs/agents/implementing.md`.
- `pnpm build:admin`: build `apps/admin/dist`; Docker runs this during the image build
- `pnpm test` / `pnpm test:db`: unit tests / unit tests plus Postgres-backed tests against the `tanomu_test` database in the local compose DB
- `pnpm lint` (oxlint, type-aware), `pnpm format` (oxfmt), `pnpm typecheck`
- `pnpm db:generate`: generate a migration after editing `apps/server/src/db/schema.ts`

Deployment (Volcano Engine, deploy job in CI, backups, rollback): `docs/deployment.md`.

## Commits

Conventional Commits with a required scope: `type(scope): summary`, lowercase imperative summary.

- Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`
- Scopes: `core`, `server`, `admin` for the packages; `db` for schema and migrations; `infra` for Docker, Compose, and deployment; `repo` for root tooling, config, and repo-wide docs
- Reference the ticket in the body (`Closes #N`) when the commit completes it

## Pull requests

Small steps: each PR changes **at most 600 lines** (additions + deletions), excluding generated files (`pnpm-lock.yaml`, `apps/server/drizzle/meta/**`). CI's `pr-size` job enforces this.

- Plan the split before writing code. A ticket may span several PRs; each must be mergeable and deployable on its own (CI green, nothing half-wired in production).
- Earlier PRs reference the ticket with `Refs #N`; the PR that finishes it uses `Closes #N`.
- Prefer splitting along seams: a prefactor or schema migration first, then the behaviour, then its UI.
- After merging a PR with stacked children, run `/advance-pr-stack` for the direct child. Dry-run first; the tool retargets the child, recovers a deleted base and rebases descendants without merging or deleting branches.

## Implementing tickets

Follow `docs/agents/implementing.md`: workflow, test seams, and known traps (adding env vars, migrations, Feishu long connection).

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (b1ngsha/tanomu) via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

The software factory uses `agent:implement` as a separate, maintainer-only execution signal. `ready-for-agent` alone must never start an automated run. See `docs/software-factory.md` for the trust boundaries and phased rollout.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

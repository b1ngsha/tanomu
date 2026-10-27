# tanomu

A personal agent living in Feishu. Domain language: `GLOSSARY.md`. Decisions: `docs/adr/`.
Writing or reviewing code: read [CODING_STANDARDS.md](CODING_STANDARDS.md).
Adding or moving modules, changing dependencies, or locating extension seams: read [ARCHITECTURE.md](ARCHITECTURE.md).

## Commands

- `cp .env.example .env` and fill it in (never commit `.env`, never print it)
- `docker compose up -d db`: local Postgres with pgvector on `localhost:54329`
- `pnpm dev`: run the server with watch mode (applies migrations on start)
- `pnpm dev:admin`: run Vite on `localhost:3000`; set `HTTP_PORT=3001` in `.env` for the server and run both commands in separate terminals. Before starting a real Feishu listener, follow the [listener coordination procedure](docs/deployment.md#4-local-development-shares-the-production-feishu-app).
- `pnpm build:admin`: build `apps/admin/dist`; Docker runs this during the image build
- `pnpm test` / `pnpm test:db`: unit tests / unit tests plus Postgres-backed tests against the `tanomu_test` database in the local compose DB
- `pnpm test:factory`: software-factory controller and workflow tests
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
- Manage stacked PRs with GitHub's official `gh stack` extension. Read [docs/agents/stacked-prs.md](docs/agents/stacked-prs.md) when creating, linking, syncing, rebasing, submitting, or merging a stack. The deprecated `/advance-pr-stack` skill is reserved for legacy-stack recovery.

## Implementing tickets

Picking up a ticket: follow [docs/agents/implementing.md](docs/agents/implementing.md) for task preparation, verification, and handoff.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (b1ngsha/tanomu) via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

The software factory uses `agent:implement` as a separate, maintainer-only execution signal. `ready-for-agent` alone must never start an automated run. See `docs/software-factory.md` for the trust boundaries and phased rollout.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

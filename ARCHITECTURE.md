# Architecture

Module ownership, dependency direction, and extension seams for tanomu. Read this when placing or
moving code, changing dependencies, or designing an interface. Engineering rules live in
[CODING_STANDARDS.md](CODING_STANDARDS.md); task execution lives in
[the implementation workflow](docs/agents/implementing.md). Use [GLOSSARY.md](GLOSSARY.md) for domain
terms and [ADRs](docs/adr/) for decision rationale. Surface conflicts with an active ADR before
changing the design; this map does not replace those decisions.

## Module ownership

| Location                    | Owns                                                                                                                      |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `packages/core`             | Conversation behavior, model orchestration, batching, and interfaces for external effects.                                |
| `apps/server`               | Feishu, Postgres/Drizzle, Provider, OAuth, encryption, and HTTP adapters in one Node process.                             |
| `apps/admin`                | React browser interactions and presentation; Vite builds the production bundle served by server.                          |
| `deploy/`                   | Production Compose and backup operations.                                                                                 |
| `.github/software-factory/` | Trusted automation and candidate execution; consult its [runbook](docs/software-factory.md) when changing that interface. |

Place new behavior with the module that owns its decisions. Directory structure should express
that ownership; add internal grouping when related behavior needs it, rather than introducing a
layer for every technical role. Keep transport and persistence representation inside their adapters.

## Dependency direction

```text
apps/admin ──HTTP──> apps/server
                         │ imports
                         ▼
                    packages/core ──> ai (intentional)
```

The HTTP arrow is communication; the downward arrow is a source dependency. Core does not import
server or admin code, Feishu SDKs, database clients, or HTTP frameworks. Server adapters depend on
core interfaces and translate external representations into domain values. The browser uses the
server's HTTP interface; it does not import server adapters or access credentials or Postgres.

The AI SDK is an intentional core dependency ([ADR 0001](docs/adr/0001-typescript-vercel-ai-sdk.md)).
Core orchestrates model calls through its uniform model interface; server selects and constructs
the concrete Provider model. Preserve this distinction rather than adding an extra abstraction
solely to hide `ai`.

## Composition and extension seams

[apps/server/src/main.ts](apps/server/src/main.ts) is the composition root: it validates configuration,
initializes persistence, constructs adapters, supplies core dependencies, and starts HTTP and Feishu
listeners. Reusable modules receive dependencies through their interfaces; application startup owns
the concrete wiring.

- **Conversation behavior:** extend core's decisions behind its public interface. The existing
  `ConversationStore`, `LlmCallLog`, and `ReplyDeps` in
  [private-conversation.ts](packages/core/src/private-conversation.ts) connect production adapters
  and in-memory test adapters at the same seam.
- **Feishu, persistence, or Provider changes:** extend the owning server adapter, then wire it in
  `main.ts` if needed. Keep SDK envelopes, SQL rows, encryption, and protocol selection local to
  the implementation that understands them.
- **Admin changes:** keep authentication, validation, and configuration persistence on the server;
  place browser interaction in admin. The same HTTP interface serves development and production;
  the production bundle does not create a second backend.

New packages or dependency directions need a concrete ownership or variation requirement. Record
new architectural decisions in `docs/adr/` and update this map when module ownership changes.

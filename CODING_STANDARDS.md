# Coding standards

Engineering guidance for writing and reviewing tanomu. These standards combine the project's
architecture decisions with first-party guidance for its stack. Sources were reviewed on
2026-10-26; package manifests, installed types, and the deployment runtime determine API availability.

## Scope and authority

- Apply these standards to new or changed behavior and the surrounding contracts it affects.
  Existing code is not a claim of compliance; unrelated cleanup belongs in a separate change.
- **MUST** identifies a required correctness, privacy, or reliability boundary. **SHOULD** identifies
  a default that may be replaced by a documented, tested alternative appropriate to the change.
- Preserve [AGENTS.md](AGENTS.md), the [glossary](GLOSSARY.md), and accepted [ADRs](docs/adr/).
  Resolve conflicts explicitly rather than silently replacing a documented decision.
- Compiler, formatter, and lint configuration own mechanical rules. Use their results rather than
  debating whitespace, quotes, or import ordering in review. This document explains design choices
  and runtime consequences that those checks cannot establish.
- Review findings should identify an applicable rule, concrete consequence, and proportionate fix.
  Preferences without a material consequence are advisory. Improve code health without requiring
  speculative abstractions or perfection unrelated to the change. [Review guidance][review]

## Code style and TypeScript

- Use glossary terms for domain concepts. Name operations by their effect and predicates by the
  condition they test. Include units in values such as `timeoutMs` and `byteLength`.
- Follow surrounding naming and export conventions. Prefer explicit named exports for reusable
  application modules; preserve framework-required conventions and checked-in component idioms.
- Keep functions cohesive around a decision or operation. Extract helpers when they hide meaningful
  complexity or establish one owner for an invariant, rather than to meet a line-count target.
- Explain reasons, constraints, and non-obvious failure behavior in comments. Public contracts should
  clarify side effects, ownership, expected absence, and errors when types alone cannot express them.
- For server/core execution, honor Node's type-stripping constraints documented in AGENTS.md.
  Node does not type-check code, read TypeScript path aliases, or downlevel JavaScript. Verify APIs
  against the deployed Node version; newer `@types/node` declarations are not runtime evidence. [Node TS][node-ts]
- Treat external data and caught exceptions as `unknown` until validated or narrowed. A type assertion
  does not validate a network response, JSON document, or configuration value.
- Use discriminated unions for mutually exclusive states when independent booleans permit invalid
  combinations. Use exhaustive branching where adding a state must force callers to reconsider it.
  `satisfies` is useful for checking static configuration while retaining inference. [Narrowing][ts], [satisfies][ts-satisfies]
- Keep assertions and non-null assertions local to a demonstrated invariant. Explain non-obvious
  assumptions and exercise them in tests. Prefer narrowing to suppressing compiler diagnostics.
- Give empty, missing, and invalid data distinct meanings where callers need to react differently.
  Preserve the intended distinction between an omitted property, `undefined`, and `null`.

## Modules, interfaces, and dependencies

- Core owns domain decisions; server adapters translate Feishu, database, HTTP, and Provider details.
  Dependencies enter through contracts; `apps/server/src/main.ts` assembles the running application.
  The AI SDK abstraction in core is intentional: see [ADR 0001](docs/adr/0001-typescript-vercel-ai-sdk.md).
- Design interfaces around the caller's required behavior. Keep SQL rows, SDK response envelopes,
  transport status codes, and credentials inside the adapter that understands them.
- Use `ConversationStore`, `LlmCallLog`, and `ReplyDeps` in
  [private-conversation.ts](packages/core/src/private-conversation.ts) as existing boundary examples.
  Reuse an appropriate seam before introducing a parallel service or repository abstraction.
- Keep invariants with their owning module. A caller should not need to repeat internal lookup,
  validation, and state-transition steps to use a module correctly.
- Prefer explicit dependencies over hidden mutable globals. Read environment configuration at the
  application boundary; pass validated values or narrow interfaces into reusable code.
- Extract shared logic when its semantics are shared. Similar-looking code with different failure,
  security, or lifecycle requirements need not share an abstraction. [Design review][review]
- Before adding a library, compare native APIs, existing direct dependencies, maintenance activity,
  runtime compatibility, license, security exposure, and the complexity actually removed.
  A transitive package must become a declared direct dependency before application code imports it.
- Evaluate overseas runtime API access against the deployment network. A build-time proxy does not
  establish runtime connectivity. Record new configuration and operations requirements in the PR.

## Errors and failure boundaries

- MUST preserve the difference between expected absence, invalid input, dependency failure, and a
  programming defect. Return a sentinel for expected absence only when the contract defines it.
- Catch an error where the code can recover, translate it into a boundary response, or add useful
  context. Otherwise propagate it. Preserve the original cause when wrapping; avoid logging the
  same failure at every layer.
- Startup must stop on unusable required configuration, failed migrations, or initialization that
  prevents correct service. Do not advertise readiness before required initialization completes.
- Hono handlers should map expected input/authentication/conflict errors to appropriate responses.
  Unexpected failures need safe client messages and diagnostic context at the server boundary.
  Use Hono's error handling contract; errors in downstream middleware may be handled by `onError`
  instead of reaching a surrounding `try/catch` around `next()`. [Hono middleware][hono-errors]
- MUST handle rejections from intentionally detached work at its owning boundary. `void promise`
  expresses intent but does not catch failures. Define who observes completion and failure.
- Swallowing an error is acceptable only for a defined degradation policy. For example, the existing
  model-call log is best effort; its failure does not replace the model's result or original error.
  A failed primary write or send must not be reported as success.
- Cancellation should be distinguishable from a dependency outage when the caller can act on that
  distinction. Use stable error categories or codes at boundaries that need programmatic handling;
  preserve actionable causes without exposing credentials or user content.
- Test the failure policy: what the caller receives, what side effects already happened, and which
  safe diagnostic remains. No universal exception wrapper or `Result` dependency is required.

## Async work, retries, and resource ownership

- New or changed external I/O SHOULD have a deliberate deadline and cancellation policy. Propagate
  cancellation to APIs that support it; stopping the wait with `Promise.race` alone does not stop I/O.
- Set limits appropriate to the operation: request size, image bytes, batch size, concurrency, model
  output, and total execution budget. Bound collection before buffering the whole resource when
  the source is untrusted or potentially large. Avoid arbitrary limits copied from examples. [Resource limits][limits]
- Retry only when a failure is plausibly transient and repeating the operation is safe. Bound attempts
  and total duration, consider rate-limit guidance/backoff, and include SDK retries in the budget.
  Validation failures, rejected credentials, and caller cancellation need different handling.
- MUST treat a timeout or connection loss during a side effect as a potentially unknown outcome.
  The remote operation may have completed. Use an idempotency key, reconciliation, or an explicit
  recovery decision before repeating a send or write. Query cancellation is also best effort. [Postgres cancellation][pg-cancel]
- Keep independent work concurrent only when resource limits and ordering permit it. Identify which
  state must be serialized per Conversation and what happens when work overlaps or arrives late.
- An in-memory timer or detached Promise is not a durable queue. If delivery across process failure
  is required, design persistence and recovery explicitly; do not imply that fast acknowledgement
  alone provides reliable processing.
- Release timers, streams, connections, and subscriptions at the lifetime boundary that owns them.
  Use `finally` or the relevant cleanup hook without masking the original failure.
- When changing service lifecycle, define bounded shutdown: stop admitting work, drain or cancel
  owned tasks, then close adapters and pools. HTTP shutdown and WebSocket shutdown have different
  lifecycles; a signal handler alone is not a drain strategy. [Node HTTP][node-http]

## Logging, diagnostics, and sensitive data

- Separate **operational logs** from intentionally persisted **model-call records**. Operational logs
  diagnose events; model-call records contain conversation content and need restricted access.
- Operational events SHOULD use consistent structured fields: timestamp, level, operation/event,
  outcome, duration where relevant, a safe correlation identifier, and an error category. Prefer
  stable event names to interpolated prose that changes with each occurrence. [Log model][otel]
- Choose levels by outcome: debug for bounded diagnostics, info for meaningful lifecycle events,
  warn for recoverable degradation, error for failed operations. Keep routine events out of error.
- Correlate related work using request/run/message identifiers when needed. Raw User and Conversation
  identifiers may be sensitive; minimize their exposure and do not use them as unbounded metric labels.
- MUST exclude secrets from logs, exceptions returned to clients, and artifacts: API keys, tokens,
  cookies, authorization headers, credential-bearing URLs, and environment dumps. Select safe fields
  from SDK errors rather than assuming arbitrary error objects are safe. [OWASP logging][logging]
- Bound and sanitize untrusted diagnostic strings, including control characters/newlines where they
  could forge log entries. Stack traces belong in restricted diagnostics after reviewing their content.
- Preserve the current model-call contract: request/response text is stored for tuning and usage
  analysis; image data is represented by media type and byte count, not raw bytes or base64.
  See `ChatRequest.logged` in [core](packages/core/src/private-conversation.ts).
- New content-bearing telemetry or expanded logs require an explicit purpose, access boundary,
  retention/deletion policy, and tests for redaction. Retention is not currently guaranteed merely
  because records exist in Postgres. Backups are part of the same data-handling decision.
- Ordinary diagnostic logging failures should not break the primary operation or recursively use
  the failed logger. Mandatory audit requirements, if introduced, need their own explicit failure policy.
- These field conventions do not require adding OpenTelemetry, Pino, or another logging dependency.
  In factory jobs, preserve the stricter allowlisted diagnostics in [the factory runbook](docs/software-factory.md).

## HTTP, configuration, and trust boundaries

- MUST validate untrusted inputs before domain use: environment values, request parameters/bodies,
  cookie payloads, upstream responses, and persisted data when its shape is not otherwise guaranteed.
  Infer downstream types from validated schemas instead of maintaining conflicting copies.
- Use Zod `safeParse` when invalid input is an expected branch; `parse` is appropriate when throwing
  is the boundary's chosen failure policy. Pass the parsed value onward. [Zod basics][zod], [Hono validation][validation]
- Distinguish malformed JSON, schema errors, and upstream protocol failures. Respect content type
  and body-size limits; Hono JSON/form validation depends on the incoming content type.
- Define a consistent status/body contract for each API family. Preserve useful validation feedback
  without returning raw errors, SQL, provider payloads, or secrets. Keep API 404s outside SPA fallback.
- Authentication and authorization are separate decisions. Preserve the Feishu availability and
  tenant-login policy in [ADR 0004](docs/adr/0004-access-control-via-feishu-availability.md);
  a changed trust boundary requires an explicit design change.
- OAuth changes must preserve state validation, expiry, and rejection of malformed/tampered sessions.
  Signed cookies provide integrity, not confidentiality. Select cookie attributes and CSRF defenses
  for the actual origin/deployment model; public HTTPS needs a different assessment from loopback
  access through an SSH tunnel. [Session guidance][sessions]
- Client-controlled URLs, paths, identifiers, or model output must not expand network, filesystem,
  or data access authority. Constrain them at the adapter that performs the operation.
- Follow the existing [environment-variable procedure](docs/agents/implementing.md#traps) when changing
  configuration. Validate required values before admitting work; never log secret validation inputs.

## Persistence, transactions, and migrations

- MUST enforce uniqueness and idempotency invariants in Postgres, not just through a preceding
  application lookup. Select a conflict policy deliberately. Nullable unique columns permit multiple
  nulls by default; decide whether the business key may be absent. [Postgres constraints][pg-constraints]
- Keep multi-write invariants in a transaction and perform its queries through the transaction handle.
  Await all required work. Let failures reach the transaction boundary when rollback is required;
  catching and returning normally can accidentally commit partial work. [Drizzle transactions][transactions]
- Keep lock-holding transactions short. Database rollback cannot undo Feishu sends, model calls, or
  other remote effects; keep slow network work outside transactions unless the design justifies it.
- Choose lock/isolation strategies for an identified race. Retry deadlock/serialization failures only
  with a bounded policy for the complete transaction; external effects must remain safe to repeat.
  Advisory locks require a common protocol and correct connection/transaction scope. [Postgres locking][locking]
- MUST scope Conversation-owned data access to the intended Conversation. Enforce this in queries
  and interfaces rather than relying on the model to filter private data. Preserve
  [ADR 0002](docs/adr/0002-strict-memory-isolation.md), including future retrieval and summaries.
- Bound list queries, use stable ordering for pagination, and select only required data. Add indexes
  for demonstrated access patterns; measure a slow query before changing the storage design.
- Review generated migrations as executable changes: existing rows, locks, duration, compatibility
  with running code, and recovery matter as much as the target schema. Follow the existing migration
  generation procedure and preserve applied migration history.
- Coordinate migration execution against one database explicitly; do not assume a migrator serializes
  concurrent starters without verifying its implementation. Destructive changes need a staged rollout
  and an explicit data-recovery plan.

## Feishu and model integrations

- Keep the Feishu receiving path short. The SDK documents a three-second handler deadline and
  competing-consumer delivery for multiple clients. Normalize and validate the specific event
  shape, acknowledge promptly, and handle slow processing through an owned asynchronous path. [Feishu SDK][feishu]
- Preserve message-ID deduplication for incoming messages. Distinguish receiving a message from
  completing its reply; changing retry/recovery behavior must account for partial completion.
  Never claim exactly-once end-to-end delivery solely from an incoming unique constraint.
- Parse malformed or unsupported content at the adapter boundary and preserve the defined user-facing
  decline behavior. Check attachment size/media type and model vision capability before expensive work.
- Coordinate real local listening with production as documented in the implementation guide;
  sharing app credentials can divert production events into the local process.
- Verify SDK and Provider behavior against installed types and the selected protocol. In particular,
  OpenAI-compatible endpoints may implement Chat Completions without implementing Responses.
- Keep Capability/Binding/Provider decisions explicit and preserve how the current adapter resolves
  its configured model. Do not couple domain behavior to a Provider's wire envelope or assume all
  protocol adapters support the same media, parameters, or tools.
- Model calls SHOULD have explicit cost/timeout/cancellation/retry budgets appropriate to the feature.
  AI SDK exposes retry and cancellation controls, but version-sensitive examples must be checked
  against the installed SDK, not copied from older documentation. [AI settings][ai-settings]
- Treat generated text and structured model output as untrusted before it drives a business action.
  Validate structure and authority at the execution boundary; instructions in user/provider content
  do not grant new permissions.
- Inspect telemetry input/output capture settings before enabling an integration. The SDK can record
  prompts and responses; turning on telemetry is a data-handling change, not just a timing metric. [AI telemetry][ai-telemetry]

## React, Vite, and the admin console

- Keep one owner for shared state. Compute values derived from props/state during render; put
  interaction-specific effects in event handlers. Introduce memoization for a measured need. [React state][react-state]
- Effects synchronize external systems. Include reactive dependencies and pair setup with cleanup.
  Abort requests when appropriate and guard against stale results; an ignored result does not cancel
  network work. Components should tolerate StrictMode's setup/cleanup cycle. [React effects][react-effects]
- Make loading, empty, error, and submitting states intentional. Prevent unintended duplicate mutations
  and communicate failures without requiring the user to inspect the console.
- Browser/server contracts still need validation appropriate to their risk; a TypeScript type on
  `response.json()` does not make a response trustworthy. Preserve authentication-expiry behavior.
- Use native controls for actions and navigation, meaningful labels, visible focus, and keyboard access.
  Radix handles parts of focus and interaction, but composed controls still need application-provided
  names and correct semantics. Test the assembled behavior. [Radix accessibility][a11y]
- Reuse checked-in shadcn components, `cn`, CVA variants, and design tokens before introducing
  competing styling systems. Conditional complete classes are fine; interpolated fragments such as
  `bg-${color}-600` are not discoverable by Tailwind's source scanner. [Tailwind sources][tailwind]
- MUST treat browser-bundled configuration as public. `VITE_*` values are exposed in client code;
  Provider keys, session secrets, and database credentials belong on the server. [Vite env][vite]

## Tests and review evidence

- Test observable contracts at public seams. Use the existing core fakes and AI SDK test models for
  domain behavior; exercise real SQL/constraints in database adapter tests and Hono through requests.
- Cover the changed success path and meaningful failures: duplicate delivery, malformed input,
  privacy isolation, partial side effects, timing/order, cancellation, and concurrency when relevant.
  Tests should fail when the promised behavior breaks, not when harmless implementation details move. [Testing principles][testing]
- Choose database-test isolation explicitly. A rollback on one connection cannot undo commits from
  another connection. Use unique fixtures, cleanup, or an isolated database/schema as appropriate;
  serial execution alone does not clean accumulated data. [Postgres transactions][pg-transactions]
- Restore the kinds of state each test changes: spies, timers, globals, and environment variables need
  appropriate cleanup. Restoring spies does not restore all other state. Use asynchronous fake-timer
  advancement for asynchronous callbacks when appropriate. [Vitest utilities][vitest]
- Prefer controlled clocks, deferred promises, and in-memory fakes to real sleeps or live services in
  unit tests. Mock at external boundaries; do not mock away the integration being verified.
- Report exactly which checks ran, skipped tests, and missing integration prerequisites. A default
  unit run without `TEST_DATABASE_URL` does not demonstrate database-backed behavior.
- Use the commands and finishing workflow in [the implementation guide](docs/agents/implementing.md).
  Include focused regression evidence for a bug; choose verification based on affected contracts,
  without arbitrary coverage quotas or unrelated cleanup.

## Python, CI, and delivery boundaries

- Preserve the factory's trusted/candidate separation, schema and identity validation, publication
  receipts, credential scans, and allowlisted output. Treat repository/model/event text as data;
  read the [factory runbook](docs/software-factory.md) before changing these paths.
- Python subprocess calls should use argument sequences and an explicit nonzero-exit policy. Bound
  I/O and subprocess waits where the operation can hang; keep errors safe to publish. `shell=True`
  needs a specific reason and constrained inputs. [Python subprocess][subprocess]
- Process cancellation must match ownership: `subprocess.run(timeout=...)` handles the direct child,
  not arbitrary descendants. Preserve process-group TERM/KILL cleanup, deadlines, and exit status
  when changing the supervisor; verify it with real-process regression tests.
- Give GitHub jobs only required permissions. Prefer verified full commit SHAs for third-party
  actions; updates need source/provenance review. Pass untrusted event values through quoted data
  variables rather than interpolating them into executable shell code. [Actions security][actions]
- Workflows with production secrets or publication/write credentials must not execute untrusted
  candidate code. Preserve the factory runbook's documented implementation-stage exposure of its
  dedicated model credential; do not broaden that exposure. Keep verification separate and preserve
  isolated Python module loading and existing artifact/credential boundaries.
- Container changes should preserve signal delivery, runtime resource ownership, and minimal runtime
  dependencies. Prefer exec-form startup and non-root execution where permissions permit it; evaluate
  base-image pinning together with the update process. Readiness must represent the required service,
  not merely that an HTTP port opened. [Docker practices][docker]
- Delivery evidence must cover changed operations: configuration provisioning, migration compatibility,
  listener coordination, and recovery. Link the deployment runbook instead of duplicating its commands.

## Reviewer checklist

- Does the change preserve domain, dependency, trust, and Conversation-isolation boundaries?
- Are failure, partial success, duplicate execution, and async ownership clear and tested where relevant?
- Are new logs and model records useful without expanding secret/content exposure unintentionally?
- Do validation and database constraints enforce the intended contract at the actual boundary?
- Can the admin interaction be understood and operated during loading, failure, and keyboard use?
- Does the evidence exercise the changed contract, and are deployment/recovery requirements explicit?

## Sources

Source documents justify the relevant behavior; local choices remain governed by the repository's ADRs.
AI SDK documentation may describe a different major version: installed types remain the API reference.

- Design and language: [Google Engineering Practices][review], [Node TypeScript][node-ts],
  [TypeScript narrowing][ts], [satisfies][ts-satisfies].
- Boundaries and data: [Hono errors][hono-errors], [Hono validation][validation], [Zod][zod],
  [Drizzle transactions][transactions], [Postgres constraints][pg-constraints], [locking][locking],
  [transactions][pg-transactions], [cancellation][pg-cancel].
- Reliability and privacy: [OWASP resource limits][limits], [logging][logging], [sessions][sessions],
  [OpenTelemetry log model][otel], [Node HTTP lifecycle][node-http].
- Integrations: [Feishu SDK][feishu], [AI SDK settings][ai-settings], [telemetry][ai-telemetry].
- UI and tests: [React state][react-state], [effects][react-effects], [Radix][a11y], [Tailwind][tailwind],
  [Vite][vite], [Testing Library principles][testing], [Vitest][vitest].
- Delivery: [Python subprocess][subprocess], [GitHub Actions security][actions], [Docker][docker].

[review]: https://google.github.io/eng-practices/review/reviewer/looking-for.html
[node-ts]: https://nodejs.org/docs/latest-v24.x/api/typescript.html
[ts]: https://www.typescriptlang.org/docs/handbook/2/narrowing.html
[ts-satisfies]: https://www.typescriptlang.org/docs/handbook/release-notes/typescript-4-9.html
[hono-errors]: https://hono.dev/docs/guides/middleware
[limits]: https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption/
[pg-cancel]: https://www.postgresql.org/docs/18/libpq-cancel.html
[node-http]: https://nodejs.org/docs/latest-v24.x/api/http.html
[otel]: https://opentelemetry.io/docs/specs/otel/logs/data-model/
[logging]: https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
[validation]: https://hono.dev/docs/guides/validation
[zod]: https://zod.dev/basics
[sessions]: https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
[pg-constraints]: https://www.postgresql.org/docs/18/ddl-constraints.html
[transactions]: https://orm.drizzle.team/docs/transactions
[locking]: https://www.postgresql.org/docs/18/explicit-locking.html
[feishu]: https://github.com/larksuite/node-sdk/blob/main/README.zh.md
[ai-settings]: https://ai-sdk.dev/docs/ai-sdk-core/settings
[ai-telemetry]: https://ai-sdk.dev/docs/ai-sdk-core/telemetry
[react-state]: https://react.dev/learn/you-might-not-need-an-effect
[react-effects]: https://react.dev/reference/react/useEffect
[a11y]: https://www.radix-ui.com/primitives/docs/overview/accessibility
[tailwind]: https://tailwindcss.com/docs/detecting-classes-in-source-files
[vite]: https://vite.dev/guide/env-and-mode
[testing]: https://testing-library.com/docs/guiding-principles/
[pg-transactions]: https://www.postgresql.org/docs/18/tutorial-transactions.html
[vitest]: https://vitest.dev/api/vi
[subprocess]: https://docs.python.org/3/library/subprocess.html
[actions]: https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions
[docker]: https://docs.docker.com/develop/develop-images/dockerfile_best-practices/

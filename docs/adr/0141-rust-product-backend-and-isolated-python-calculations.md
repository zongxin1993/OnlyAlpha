# ADR 0141: Rust Product backend and isolated Python calculations

- Status: Accepted
- Date: 2026-10-21
- Decision maker: repository owner, explicitly requesting all Web backend calls and backend business implementations move to Rust, and explicitly retaining isolated Python Factor/Indicator execution.
- Related: PROJECT_CONSTITUTION.md; ADRs 0104, 0117, 0124, 0130, 0135, 0139, 0140.

## Decision

The maintained backend service and business implementation target is Rust. This includes the versioned Product HTTP/WebSocket service, Application admission/Commands/Queries, Research and trading orchestration, owning persistence, Runtime Generation lifecycle, recovery and provider/gateway implementations. Python remains an isolated algorithm implementation boundary for authored Factors/Indicators and their necessary mathematical helpers and authoring SDK. Python build/test tools are not backend services.

This extends ADR 0139 beyond the Trading Kernel and supersedes only its rejection of a separately authorized backend migration. It does not make Application, HTTP, database or provider-specific rules Trading Kernel responsibilities. Component placement now follows [ADR 0142](0142-library-product-boundaries-and-independent-releases.md): reusable libraries under `crates/`, Product business and worker roles inside `packages/backend`, Web inside `packages/frontend`, concrete plugins under `plugs/`. Semantic dependency boundaries remain. It preserves Python-authored private Factor assets and their exact stable API rather than translating arbitrary user source to Rust.

One formal Product API remains. Existing URLs, command identities, owner authorization, Source grants, error/UNKNOWN semantics, immutable inputs and Evidence remain governed by their existing Contracts. A Rust forwarding proxy, Rust wrapper around Python business objects, placeholder endpoint, or browser-side calculation does not establish a Rust implementation. Python algorithm workers cannot access Product stores, issue Product Commands, select Generations, grant promotion or own trading state.

## Migration and deletion

Migrate complete owning capabilities in their real dependency order, with a single official writer for each fact and exact implementation selection for each work identity. Shared Product Command Admission/Receipt and security/persistence boundaries precede dependent Product flows. Reuse audited Rust semantics; implement missing Application, provider and Research behavior at their proper boundaries. Do not move arbitrary backend code into the Kernel or create a service per type.

Each migrated Product flow must preserve its normal Shipping Web UI entry and pass the corresponding deterministic, persistence/recovery, compatibility, security and real browser tests. Retirement follows proof that all current callers use the replacement. Removed Python current source does not remove the exact archived artifacts/readers required for immutable history. Missing history never authorizes reset, identity translation, latest substitution or fallback. Development database rebuild permission does not substitute for these proofs.

Under ADR 0142, retirement assessment and eligible deletion are part of every migrated library/capability delivery, not optional cleanup after all migration. Audit remaining current callers and algorithm SDK dependencies first; R8 is the final aggregate gate, not permission to remove still-needed code or retain obsolete modules indefinitely.

Delete obsolete Python backend code, imports, entry points, dependencies, package/build/deployment consumers and obsolete implementation-only tests atomically after their replacement is admitted. Preserve independent semantic vectors, fault tests and assertions. Python algorithm workers and their minimal SDK keep only required algorithm responsibilities; retaining a broad Python Core distribution behind a worker label is not the final architecture.

This decision grants no LIVE activation, venue certification or data deletion authority. Existing R5-R8 semantic, recovery, historical artifact and human LIVE requirements remain. Any interim mixed implementation is a migration state, not the final maintained architecture or completion claim.

## Construction order

Follow the Product workflow dependency map in `docs/rust-product-backend.md`. That document describes future work and acceptance boundaries, not a progress ledger. Current source and executable evidence determine actual implementation.

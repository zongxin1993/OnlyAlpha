# Rust Execution Implementation Plan

Goal: deterministic Generic T0 Cash execution transactions and exact forward recovery using real components.
Spec: `docs/superpowers/specs/2026-10-19-rust-execution-design.md`.
Execution: owner-authorized inline implementation; final bounded independent review and mainline publication. No tracked progress/acceptance ledger.

## Global constraints

Constitution unchanged; no official Runtime activation, LIVE, Python retirement or data migration. Reuse admitted pinned dependencies and sole canonical dev verification. Freeze exact context, explicit time, source and identities. Store commit precedes mutation, Ready precedes business/outbox visibility. No fee defaults, guessed settlement, silent clipping, fallback or blind UNKNOWN retry.

## Task 1: pure planning and real component composition

Create `execution/{Cargo.toml,src/lib.rs,src/model.rs,src/components.rs,src/planning.rs,tests/lifecycle.rs,tests/support/mod.rs}` and `test-data/execution/`. Add independent expected economic vectors and missing-module/source-boundary RED proof in canonical dev. API: `Components::new(config:Value)`, `checkpoint()->Result<Value,Error>`, `prepare(&self,store:&impl Store,input:&Value)->Result<Prepared,Error>`; `Prepared` has private immutable identity/context/input/projection/event fields and exposes read-only record/encode. Order, Position, Account, Ledger and Risk restore their own exact canonical checkpoints. OPEN admission produces one exact Order/Request/Reservation relation. Explicit submission/acceptance, fill and terminal observations preserve UNKNOWN and aliases. Fees use cumulative explicit targets; settlement binds full trade/scope and T0 availability. Position supplies the single exact close-cost result consumed by cash and attribution. Test atomic denied/incomplete/conflicting cases, partial buys/sells, nonzero fees, final remainder and cancellation.

## Task 2: safety-capacity integration

Use deterministic saturation tests for Order/Position/Account/Ledger. Keep new-risk admission thresholds while allowing existing fills/observations/releases/controls and proved close to extend complete history. Fresh checkpoint readers must accept every emitted history. Avoid truncation, raising limits, bypassing conservation or exposing manager internals.

## Task 3: durable coordination and recovery

Create `execution/src/coordinator.rs` with Store commit/query/ready/delivery contracts and exact ordered component installation. Whole Prepared commits before any projection; recovery uses committed frozen payloads, never current queries or Planner. Missing applied index is reconstructed by exact result identity. Test-adapter actual file storage uses atomic durable replacement, reopen and ordered records; fail at commit, each target before/after install, Ready and acknowledgement. Stable Events are delivered at least once. Business queries are gated on Ready, and unready predecessor blocks later transactions. Prove corruption/conflict fail-closed and full restart.

## Task 4: engineering integration, verification and review

Update Cargo workspace/lock, version inventory, exact local dependency/source guards, isolated closure and canonical Rust lane; extend affected tests/impact selector without weakening guards or adding registry dependencies. Document owning Execution and source navigation boundaries. Run targeted Rust debug/release/Clippy/format and relevant Python execution/static/type/Constitution checks in canonical dev. Run nearest full Rust lane. Complete bounded Ponytail review and one fresh-context authority/recovery review, address High/Critical with RED regression and rerun impacted checks. Commit intended files only, verify immutable source/tree and remote base, `git merge --ff-only`, push/fetch equality. No Release for an isolated component.

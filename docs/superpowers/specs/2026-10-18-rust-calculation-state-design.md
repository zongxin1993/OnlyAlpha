# Rust Calculation state, snapshots and readiness

## Scope and authority

Extend the existing Calculation library, with no new crate/dependency. It owns one cursor per instance plus immutable result projections and explicit failure state. The Infrastructure client owns process exchange and binds checkpoint bytes. Algorithms and ready/warmup remain Python producer facts. This does not activate a Runtime, migrate history, add Factor execution or change Web/Release behavior. Constitution impact: NO.

Python `indicator.registry`, `indicator.pipeline` and `cluster.pipeline` are references, not templates. Their sequential updates are not an atomic multi-instance transaction, and checking a dependency's `ready` alone does not prove its input is current. Rust preserves per-instance committed results on failure, refuses implicit continuation after failure, and evaluates downstream eligibility against explicit expected positions. Python production correctness is not relabeled as full Rust parity.

## State and snapshots

`CalculationState` owns the existing `ExecutionCursor`, with no second mutable cursor. A prepared batch commits only a complete validated receipt matching exact binding/revision/samples/last event/input digest. The receipt stores generic tagged scalar outputs, producer `ready` and explicit quality flags. Warming is a successful producer result with `ready=false`, not an error. Unknown, failed and unavailable outcomes retain the last committed projection for diagnosis but never grant readiness. New updates after these outcomes require explicit reset or fresh exact restore; no hidden retry.

Snapshots are owned immutable copies. Their input position includes batch digest, event nanoseconds, cursor revision and total samples; identical timestamps alone are insufficient. Canonical records reject unknown/missing fields, wrong scalar families, noncanonical numbers, over-budget collections, invalid status/receipt relations and foreign bindings. Outputs use existing tagged scalar normalization; transport stays outside Calculation.

## Readiness

`ReadinessPlan` declares exact instance bindings, required/optional policy and dependencies. Reject duplicate instances/dependencies, missing dependencies, cycles, mixed generations and empty/no-required plans. Maximum 256 nodes, 64 outputs/quality flags per result. Evaluation consumes snapshots and an exact expected position for every declared instance; foreign snapshots or incomplete expected context are errors. Missing, stale, warming, failed, unavailable and UNKNOWN required nodes block. Every dependency of a required consumer must also be current and ready, irrespective of its own optional flag. Optional non-ready nodes degrade without independently blocking unrelated required nodes. Each timeframe may have its own explicitly expected event; no timestamp guessing or forward fill. Evaluation is pure and never invokes strategies.

## Worker pairing and lifecycle

The actual Rust client uses CalculationState instead of a parallel cursor. It validates every batch point before forming the last committed generic result. Any uncertain process exchange or invalid response marks all instances in that process UNKNOWN; structured known rejection marks the affected update failed. Locally rejected malformed input does not mutate state.

The Rust checkpoint bundle directly evolves to schema 2: exact worker checkpoint record plus Calculation state. Its external SHA-256 binds both; native worker protocol/checkpoint bytes remain unchanged. Bundle parsing validates scalar/state/cursor relations before a worker request; restore requires a fresh matching instance, validates both candidate states, restores the exact worker bytes and installs local state only on a matching response. Caller owns durable storage and expected digest. Missing/corrupt/mismatched state fails, never falls back to the old envelope. Real fresh-process continuation is technical proof, not service upgrade or formal Runtime checkpoint admission.

## Verification

Independent vectors cover primitive statuses/current-vs-stale and optional degradation; common warming/ready values are checked through Python registered SMA and Rust without using one implementation as oracle. Adversarial tests cover order, all nested identity/receipt relations, unknown fields, budgets, dependency omissions/cycles, failure preservation, atomic fresh restore and sample/position mismatch. Real worker proof includes warmup, required/optional dependencies, exact paired checkpoint/new process continuation, cancellation and poisoned-process snapshot withdrawal. Run affected tooling/static checks and the existing single-dev canonical Rust lane (debug/release, Clippy/format, independent dependency closures, real bridge). Existing indicator-provider golden failure must be diagnosed and reported separately, never silently rebaselined.

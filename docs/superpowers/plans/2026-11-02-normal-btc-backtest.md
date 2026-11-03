# Normal BTC Backtest Implementation Plan

> For agentic workers: use the existing executing-plans/subagent workflow. This document defines implementation order, not completion or acceptance status; evidence remains in the active task context.

**Goal:** Complete the normal single-instrument BTCUSDT Backtest path without a Research-report prerequisite.

**Architecture:** Reuse the original preparation, immutable Dataset, calculation workers, Freeze, Qualification, Promotion and Trading Kernel. Add a real manual validation origin under ADR 0148; no duplicate numerical or trading engine and no parsed-value grant.

**Tech stack:** Existing Rust crates/backend, isolated calculation SDK, PostgreSQL/immutable files, React/Ant Design/ECharts.

**Spec:** [Manual Backtest strategy validation](../../manual-backtest-strategy-validation.md).

## Global constraints

- Constitution remains unchanged; root `src/` remains frozen.
- Keep the approved BTC profile, original identities, exact inputs and current cost assumptions.
- No Research Run/Result, Target or Statistics in the manual path; no SIM/LIVE permission.
- All normal business steps use Shipping Web and the versioned Product API.
- Preserve current model settings, both original Factor reports and their exact referenced artifacts.
- Use the sole `onlyalpha-dev` verification/deployment topology and scoped checks; no larger timeout or weaker assertion to conceal a failure.

## Review focus

- Preparation may be cancelled after a valid immutable Freeze but before Run creation; UI and recovery must describe both facts accurately.
- Repeating the same Strategy must reuse its canonical admitted history without an invented same-stage Promotion.
- Changed current source/model availability must not prevent historical task/result reads or substitute a new exact revision.
- Browser reload/StrictMode and transport loss must recover original preparation/Run identities without automatic duplicate commands.
- An orphan validation file or false positive-child-exit claim must not become an opaque validation grant.

## Task 1: Shared executable validation and immutable publication

Files: `application/strategy_validation`, shared graph-validation primitive, `persistence/strategy_validation`, migration `0070_manual_backtest_strategy_validation.sql`, existing calculation-worker integration and directly affected tests.

Interface: `Origin::from_operation(&Operation)` consumes the original typed manual request. `ResolvedValidation::resolve` consumes actual authoring, Runtime and materialization; `observe` returns only a real joined producer. `Store::publish` consumes that producer and returns `VerifiedValidation`; original-preparation readers reopen the exact published proof. The proof exposes derived SourceRevision, exact authoring/Dataset/Runtime/preparation references, fingerprint, physical locks and cut/transaction verification.

First reproduce no manual validation path and rejected unregistered evidence. Implement the smallest shared graph/P9 execution extraction, positive-child ownership and guarded file/reference publication. Verify exact original sources, missing/mismatched implementations, restore/P9 failures, cancellation/cleanup, interruption and read-only tamper rejection through scoped canonical tests. Existing Research numerical behavior retains its own regression checks.

## Task 2: Same Freeze, Qualification and Promotion owners

Files: `frozen_strategy.rs`, `strategy_projection.rs`, Qualification/Decision/Promotion owners and source readers; migrations `0071_manual_backtest_qualification_promotion.sql` and `0072_manual_backtest_freeze_origin.sql`.

Interface: `FrozenStore::read_verified_manual(Arc<VerifiedValidation>, relation_id, max_work)` returns opaque `VerifiedManualBacktestEvidence`. The same evaluator consumes Research or manual typed evidence. Manual gate/policy and explicit Promotion origin follow the owning contract. Existing admitted Strategy lookup returns a fully verified original admission for reuse.

First demonstrate raw/changed validation cannot freeze or qualify, manual origin cannot pretend to be Research, and SIM/LIVE targets fail. Implement derivation, original-Command publication, exact source-lock/transaction checks, typed Qualification reevaluation and append-only Promotion. Verify first publication, repeated exact Strategy, existing Research records, source capture, tampering and deferred-constraint/UNKNOWN recovery.

## Task 3: Non-circular preparation and formal API

Files: Backtest input/wire, original preparation persistence and Host, manual strategy context, workflow queries, namespace bootstrap, Product contract/client generation and their tests.

Interface: input V2 has `MANUAL_STRATEGY` or `FROZEN_STRATEGY` origin plus existing source/release/Generation/future Command. View V2 keeps missing derived references nullable until READY. Existing workflow queries additionally expose durable `backtest_preparations`. The context query consumes an exact published Factor locator and optional existing private Strategy ID.

First test manual acceptance without Research, no Run before confirmation, complete proof requirements at READY, original identity after reply loss, blocked/cancelled recovery, and source-independent history. Implement materialization → real validation → Freeze/Q/Promotion → READY inside the same task; confirmation reopens all actual proofs. Extend bootstrap only for required owning storage. Regenerate and check the actual Product OpenAPI and typed consumers.

## Task 4: Normal Web path, economic execution and deployment

Files: existing strategies/backtest features, normal navigation/workspace entry, relevant tests and deployment integration.

Use existing Private Assets and source inventories. Select an exact Factor revision, save rules, choose the source, display sample/cash/size/cost assumptions, and submit “确认策略并准备回测”. READY separately enables “开始回测”. Browser performs no Qualification/Promotion itself. History recovers all preparations and Runs; results retain the existing metric → equity/drawdown → trade/position hierarchy. Model interpretation is optional.

Reproduce and test no-Study/no-Agent operation, stale selections, StrictMode, rejected/UNKNOWN submission, saved-but-not-prepared recovery, cancellation and result reads independent of model availability. Run actual complete native inputs with unchanged correctness guards, scoped static/build checks, bounded simplicity and independent reviews. Deploy through the canonical entry, then complete the entire normal path through real Shipping Web and verify original model/two reports before publication and permitted process-data cleanup.

# BTC Spot Research to Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking in the active context; this document is not completion authority.

**Goal:** Run the confirmed BTCUSDT momentum Factor through strategy research, Freeze and a real Web backtest.

**Architecture:** Rust Product Application owns authoring, immutable composition, Freeze, admission and job lifecycle. Reuse the existing native Strategy/Execution/Backtest and isolated calculation worker. Web is a client of versioned Product APIs.

**Tech Stack:** Rust, PostgreSQL, immutable filesystem evidence, existing calculation SDK, React/Ant Design, Lightweight Charts/ECharts.

**Spec:** `docs/superpowers/specs/2026-11-01-btc-spot-research-backtest.md`

## Global Constraints

- No additions to root `src/`; no Python backend authority or fallback.
- Preserve current model configuration, both Factor reports and protected holdout.
- Immutable Strategy identity excludes execution policy, fees and capital.
- Formal validation uses the current source through `scripts/dev_verification.py` and the single `onlyalpha-dev` topology.
- Business acceptance uses Shipping Web UI; no direct business API commands or database mutations.
- Use scoped tests, no full-workspace test escalation without impact evidence.

## Review Focus

- A missing/changed Factor revision must prevent draft composition and Freeze.
- A lost response must observe the same command and must not create a second run.
- Restart between a durable fill and progress update must recover that fill once.
- The final signal must not manufacture a same-bar or out-of-range fill.
- Fee rounding and open-position valuation must reconcile cash, positions and equity exactly.

### Task 1: Strict Rust strategy definition and authoring identity

**Files:** Create `packages/backend/src/application/private_strategy.rs`; modify `application/mod.rs`, `application/private_assets.rs`; tests in `private_strategy.rs`.

**Interfaces:** `Definition::from_record(&Value) -> Result<Definition, &'static str>`, `Definition::to_record() -> Value`, `Definition::fingerprint() -> Result<String, &'static str>`; later composition consumes exact published Strategy and Factor revisions, Research Context and Catalog through existing authorities.

- [ ] Add failing tests for the strict ADR 0133 definition format, fixed parameters, required entry/exit, exact Factor dependency closure and rejection of execution/account fields.
- [ ] Run affected backend tests through the formal dev entry and observe the new regression fail.
- [ ] Implement strict bounded definition parsing, canonicalization and identity using existing Calculation/domain types; call it from Strategy revision validation.
- [ ] Add strict Strategy Draft parsing and immutable authoring Revision creation; verify canonical identity, parent version binding and rejection of trading/account fields.
- [ ] Run affected tests and format/static checks; commit the coherent boundary.

### Task 2: Strategy research and sole Freeze publication

**Files:** Modify `application/research_run.rs`, `application/research_run_execution.rs`, `application/frozen_strategy.rs`, `persistence/research_submission.rs`, `persistence/research_execution.rs`, `persistence/research_evidence.rs`, `transport/host.rs`, `transport/routes.rs`; create focused `application/strategy_research.rs`, `transport/host_strategy.rs` and persistence owner as needed by existing schema.

**Interfaces:** Existing `POST /api/v2/research/runs/private-strategy`, `POST /api/v2/strategy-freezes`, `GET /api/v2/strategies/{strategy_fingerprint}`; retain exact command identity and public Strategy Revision contract.

- [ ] Add durable Strategy draft/publication commands using the existing private Strategy tables and global command receipts; expose them through strict versioned DTOs and Human ingress.
- [ ] Add failing tests for PRIVATE_STRATEGY origin, exact composition/runtime binding and refusal to Freeze a Factor-only statistical result.
- [ ] Add immutable composition derivation/verification following ADR 0133/0134 and existing storage schema; assert exact runtime/catalog/Factor bindings and rejection of missing or changed revisions.
- [ ] Execute strategy graph research with exact Factor implementation and sealed development inputs; produce vector/stream signal equivalence evidence.
- [ ] Publish Strategy only after verifying Dataset, calculation, Research and equivalence evidence. Use existing immutable Store layout and canonical FreezeRelation; reconcile PostgreSQL projection through its existing owner.
- [ ] Add exact evidence-backed experimental Qualification/Promotion through existing policy contract, without profitability claims.
- [ ] Test same-command replay, corruption, altered graph/implementation and crash boundaries; run scoped checks and commit.

### Task 3: Native next-open execution policy

**Files:** Modify `crates/onlyalpha-backtest/rust/trading.rs` and its tests; add provider-specific rule/fee implementation under `plugs/onlyalpha-plugin-binance/rust`; migrate the replaced replay-policy consumer closure out of Python authority.

**Interfaces:** Existing `Trading<C: NodePort>`/`Participants`/`RunLoop`; policy records explicitly bind quantity, capital, next-open price, slippage, fee and instrument rules, while Strategy continues to emit only eligibility/entry/exit.

- [ ] Add failing deterministic tests for thresholds, missing warmup, next-open timing, no duplicate order, insufficient funds and final pending signal.
- [ ] Replace prelisted request-only behavior for this supported policy using canonical Execution decisions, stable causal order identities and plugin rule validation; preserve explicit supported boundaries.
- [ ] Add ledger reconciliation tests for buy/sell fees, round-trip PnL, last-close valuation and same-size/cost buy-hold baseline.
- [ ] Test interruption before/after fill commit and deterministic recovery through existing durable RunLoop; require exhausted input plus drained execution before completion.
- [ ] Run affected package tests/checks, bounded simplification review, commit.

### Task 4: Product backtest lifecycle and immutable result

**Files:** Create focused `application/backtest_run.rs`, `persistence/backtest_run.rs`, `transport/host_backtest.rs`; modify owning module declarations, `transport/host.rs`, `transport/routes.rs` and `Cargo.toml`. Reuse existing schema and only add a checksummed migration for a demonstrated missing field/table.

**Interfaces:** Existing `/api/v2/backtest/creation-context`, `/runs`, `/runs/{id}`, `/cancellation`, `/evidence`, `/result`; production composition uses native `RunLoop<Trading<StrategyNodes>>` with exact admitted revision/runtime/input pins.

- [ ] Add failing tests for frozen/promoted revision admission and separate explicit execution configuration.
- [ ] Implement durable command admission, immutable input preparation and finite native execution with cancellation and restart observation.
- [ ] Publish verified equity, drawdown, orders, fills, costs, position and benchmark with trace links; model analysis reads only exact result evidence.
- [ ] Test lost response, duplicated submit, cancellation races, corrupt evidence and restart recovery without a second run.
- [ ] Run affected application/persistence/transport tests and checks, commit.

### Task 5: Shipping UI and model analysis

**Files:** Add `packages/frontend/src/features/strategies/` and `features/backtest/`; modify `app/router.tsx`, existing Factor preview actions and API clients; extend the existing Agent evidence-analysis path rather than introducing another model configuration.

**Interfaces:** Normal navigation from a confirmed Factor to exact strategy, research, Freeze and backtest; all commands use the formal API and server-owned receipt resolution.

- [ ] Add failing user-flow tests for creating/reviewing a strategy, research status, Freeze availability, backtest parameters, progress/cancel/reload and result navigation.
- [ ] Use installed Ant Design for forms/tabs/tables and existing charts for equity/drawdown; retain shared toolbar style and accessible navigation/focus.
- [ ] Render ordinary financial wording, causal order/fill detail on demand, and an exact-result model interpretation with exploration warning.
- [ ] Run targeted frontend tests, typecheck, lint/format and React quality review.

### Task 6: Real deployment and full workflow acceptance

- [ ] Build current source using the canonical native-workstation build, deploy into existing dev services preserving model/report volumes.
- [ ] Through the real Web UI, load both prior reports and model configuration; create the approved strategy, run strategy research, Freeze and run the fixed backtest.
- [ ] Inspect result arithmetic, trade sources, equity/drawdown, benchmark and current-model explanation through visible UI; reload and prove durable continuation.
- [ ] Conduct bounded independent review of the actual diff and impacted authority/correctness boundaries; resolve blocking findings and rerun affected verification.
- [ ] Verify Constitution unchanged and scope complete. Commit/push as authorized, fetch to prove alignment and clean unused process artifacts while preserving required exact artifacts and runtime facts.

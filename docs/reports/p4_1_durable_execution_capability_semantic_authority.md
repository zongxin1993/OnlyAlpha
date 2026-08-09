# P4.1 Durable Execution Capability Semantic Authority

## Baseline

- Prompt baseline: `7f11092bb5220fdbd35d2631682c03c50255cef0`.
- Actual implementation baseline: `7f11092bb5220fdbd35d2631682c03c50255cef0` (`master`).
- Baseline differences: none.
- Problems already solved ahead of P4.1: P4-0 had removed executable legacy Trade mutation and `LEGACY_UNMIGRATED`, but profile-based capability admission and duplicated resolver calls remained.
- Design adjustment for current code: Processor owns admission capture/routing, while Backtest Runtime callbacks finish the larger immutable planning context. The Processor therefore resolves once and passes the frozen decision into those callbacks; Runtime and planners never resolve again.
- The untracked user Prompt was preserved unchanged.

## Before architecture and root cause

`only_resolve_execution_capability()` accepted `market_profile_id`, granted permission only to `GENERIC_T0_CASH`, and returned an
unexplained enum. Processor Trade/Terminal routing, both Backtest planning-context builders, and both planners called it
independently. Trade Planner also had `_PROFILE_ID` and `UNSUPPORTED_MARKET_PROFILE`. Actual Reservation presence was checked
after admission, so the support decision did not describe the authority shape the kernel would consume.

The root cause was a category error: Market identity and Market capability are evidence about market rules, while durable
permission must describe the implementation semantics of the canonical transaction kernel.

## New support semantic model

`OnlyExecutionSupportContext` contains only operation kind, Account type, Order type/side/offset, Position side/effect/mode,
Margin presence, Account/aggregate-Strategy-Ledger parity, and `OnlyExecutionReservationShape`. It contains no profile, market,
venue, instrument, broker, Runtime, or product identity.

`only_execution_reservation_shape()` and `only_execution_support_context()` are the single pure projection path. Processor first
captures immutable Account, Order, Ledger, Position/Risk/Margin Reservation authority from Runtime-owned Managers, then passes
those captured values into the pure functions. The projection module imports no Manager, Runtime, Registry, Broker, Gateway, or
configuration authority.

`OnlyExecutionCapabilityResolver` is a stateless deterministic trusted-code policy. It returns an invariant-bearing
`OnlyExecutionSupportDecision(capability, typed reason, policy version, canonical SHA-256 fingerprint)`. Supported decisions
cannot have a reason; unsupported decisions must have one. Policy version is `1`.

## Reservation shape and support matrix

- BUY OPEN Trade: Account Cash + Strategy Cash + Risk; no Position or Margin.
- SELL CLOSE Trade: Position + Risk; no Account Cash, Strategy Cash, or Margin.
- SELL CLOSE Terminal: exact Position + Risk.
- BUY OPEN Terminal: explicitly `UNSUPPORTED / TERMINAL_SHAPE_UNSUPPORTED`.

Shapes are strict-exact. Missing or unexpected authority returns `RESERVATION_SHAPE_UNSUPPORTED`; Margin instruction or Margin
Reservation returns `MARGIN_UNSUPPORTED`. CASH + LIMIT + LONG + NETTING + no Margin + parity is required. Market/stop orders,
Margin Account, Short, Hedging, SELL OPEN, BUY CLOSE, unresolved effects, parity failure, and unsupported operation kinds fail
closed with typed reasons.

Settlement did not need a new capability DSL. The existing Trade Application Instruction already freezes a representable,
trading-day-based settlement schedule; the Planner continues to convert it into the immutable settlement instruction.

## Deleted interfaces and planner authority cleanup

Deleted without aliases or wrappers:

- `only_resolve_execution_capability()`;
- its `market_profile_id` argument and `generic_cash` predicate;
- Trade Planner `_PROFILE_ID` and `UNSUPPORTED_MARKET_PROFILE` gate/code;
- Processor boolean `_uses_prepared_trade_path()` / `_uses_prepared_terminal_path()` support projections;
- Runtime-builder resolver calls;
- Trade and Terminal planner resolver calls;
- terminal planning-context Market Profile permission state;
- obsolete Planner support error codes and Generic-profile capability tests.

Planning contexts now freeze `support_decision`. Planners only verify `DURABLE_TRADE` or `DURABLE_TERMINAL`; receiving any other
decision is an internal routing invariant failure. Concrete validation remains in planners: Fill/order sequence, Reservation
amount/state/scope, creation authority, fee accrual, close attribution, reducer invariants, preconditions, and projection order.

## Market identity audit boundary

Market identity remains in Trade Application Instruction, Settlement Instruction, committed Trade fact, result, artifact, and
recovery proof. Audit-only mapping lives in `market_evidence.py`, outside the support resolver and planners' permission logic.
Different real `GENERIC_T0_CASH` and `CN_A_SHARE_CASH` planning contexts with the same shape produce identical decisions; a
different Position side under the same A-share evidence produces a different decision.

This is kernel semantic reuse only. It does not certify the CN A-share durable product.

## Persistence, fact schema, and recovery impact

Trade draft schema advanced from 3 to 4, committed Trade fact from 4 to 5, and Terminal draft/committed fact from 1 to 2. Each
persists `execution_capability`, `execution_support_schema_version`, and `execution_support_fingerprint`. The generic Runtime
transaction envelope and Runtime persistence schema did not change.

Codec, Memory/SQLite store, committed facts, result projection, and recovery round trips preserve the proof. Recovery never calls
the Resolver for historical committed facts. The four immutable Recovery baselines were regenerated with the formal script
because their complete Trade projections intentionally gained the three proof fields; no comparator, economic assertion, or
recovery invariant was changed. The first Recovery run was 286 passed / 9 failed, and all nine first differences were exactly the
three new keys. After regeneration the complete lane passed 295/295.

## Architecture guards and tests

Source guards enforce:

- no Market Profile names/type/argument in capability, support projection, Trade Planner, or Terminal Planner;
- exactly one production Resolver invocation site;
- no Resolver imports/calls from planners or reducers;
- no old resolver wrapper or compatibility alias;
- support projection has no Manager/Runtime/Registry/Broker/Gateway query dependency.

Semantic tests cover both durable Trade shapes, every required Reservation omission, unexpected Reservations, Margin instruction
and authority, Account type, Order type, Short, Hedging, side/offset/effect combinations, parity, deterministic fingerprint,
SELL CLOSE Terminal, BUY OPEN Terminal denial, different-market/same-shape equality, same-market/different-shape inequality, and
proof persistence. A Processor test injects a fail-on-call Terminal Planner and proves BUY OPEN cancellation never enters it.

## Quality gates

Final local results:

```text
uv sync --frozen --all-packages --all-groups: PASS (67 packages audited)
ruff check src tests examples packages scripts: PASS
ruff format --check src tests examples packages scripts: PASS (1107 files)
core mypy: PASS (496 source files)
virtual Broker plugin mypy: PASS (14 source files)
Tushare provider mypy: PASS (15 source files)
MiniQMT provider mypy: PASS (36 source files)
version sync: PASS (0.3.5)

fast: 1035 passed, 1 skipped (1036 collected)
integration: 130 passed
core-full: 1165 passed, 1 skipped (1166 collected)
recovery: 295 passed
ashare: 5 passed
miniqmt-contract: 32 passed
exhaustive: 112 passed

uv build --all-packages: PASS
  onlyalpha sdist/wheel
  virtual Broker plugin sdist/wheel
  Tushare plugin sdist/wheel
  MiniQMT plugin sdist/wheel
```

The repository's full local `release` gate passed on the final source. Performance-budget messages remained advisory and did not
change lane status. GitHub Actions was not triggered because the implementation was not committed or pushed; therefore the
remote GitHub final Quality Gate is **NOT RUN**, while its local release-equivalent commands all pass.

No skip, xfail, assertion relaxation, generic fallback, profile mapping, compatibility wrapper, or premature BUY OPEN durable
terminal permission was introduced.

## NOT IMPLEMENTED IN P4.1

- BUY OPEN Durable Terminal;
- CN A-share full durable product conformance or complete BUY OPEN / SELL CLOSE + T+1 slices;
- A-share rule, Reference, matching, or Fee-kernel changes;
- partial/multi-fill production product certification or partial + terminal product closure;
- Market Product composition neutralization or Reference-provider neutralization;
- Paper checkpoint/restart, reconnect, realtime gap recovery, or Live Runtime;
- durable Broker outbound command or Broker account/order/trade/position synchronization;
- Margin, Short, Hedging, Futures, Crypto, multi-account, or vectorized/distributed Backtest products;
- dynamic capability DSL, Registry, configuration, or provider plugin.

## Next phases

P4.2 retains residual Planner semantic cleanup. P4.3 implements the complete BUY OPEN Terminal prepared transaction before policy
version evolution can admit that shape. P4.4 and later perform CN A-share end-to-end product slices and conformance rather than
inferring product readiness from this kernel-level decision.

# P4.1 Execution Capability Pre-Implementation Audit

## Baseline and scope

- Prompt baseline: `7f11092bb5220fdbd35d2631682c03c50255cef0`.
- Actual implementation baseline: `7f11092bb5220fdbd35d2631682c03c50255cef0` (`master`).
- Baseline difference: none. The only initial worktree item was the untracked user-provided P4.1 prompt.
- Product scope remains CASH, LIMIT, LONG, NETTING, BUY OPEN / SELL CLOSE durable fills and SELL CLOSE durable terminal operations. P4.1 does not certify a new market product.

## Current authority and call graph

The current pure function `only_resolve_execution_capability()` receives operation, market profile identity, account, order, position, margin, and Account/Ledger parity fields and returns only an enum. It is called independently by:

1. `OnlyExecutionProcessor._uses_prepared_trade_path()` and `_uses_prepared_terminal_path()` for routing;
2. `OnlyBacktestRuntime._build_trade_execution_planning_context()` and `_build_terminal_execution_planning_context()` before freezing planning authority;
3. `OnlyTradeExecutionTransactionPlanner._validate()`;
4. `OnlyTerminalExecutionTransactionPlanner._validate()`.

The Trade Planner additionally has its own `_PROFILE_ID = "GENERIC_T0_CASH"` gate. Capability is therefore not a unique authority even though the current resolver itself is stateless.

## Current inputs and consumers

Current inputs are `operation_kind`, `market_profile_id`, account type, order type/side/offset, position side/effect/mode, a margin boolean, and Account/Ledger parity. Current consumers use the result to select the prepared durable path or reject Planner input. The result has no typed unsupported reason, policy version, or deterministic proof.

`market_profile_id` is the permission gate: only `GENERIC_T0_CASH` can reach either durable planner. `CN_A_SHARE_CASH` is consequently rejected even when its compiled instruction and captured economic authority have the same supported semantic shape.

## Reservation and parity semantics

The actual immutable before-authority currently captured for BUY OPEN is Account Cash Reservation, Strategy Cash Reservation, and Risk Reservation, with no Position or Margin Reservation. SELL CLOSE captures Position Reservation and Risk Reservation, with no Account Cash, Strategy Cash, or Margin Reservation.

Reservation presence is currently validated late in Runtime context construction and again in the Trade Planner. It is absent from the capability input, so routing can approve a shape before discovering missing or unexpected authority.

SELL CLOSE terminal planning requires the exact Position + Risk Reservation shape. BUY OPEN terminal is handled outside the durable terminal planner because that planner cannot atomically project Account Cash, Strategy Cash, and Risk release. Account/Ledger parity compares the shared Account with the aggregate of all matching Strategy Ledgers; both trade and terminal durable admission require parity.

## Settlement instruction semantics

`OnlyTradeApplicationInstruction.settlement_schedule` already provides a market-neutral, trading-day-based schedule. The Trade Planner freezes asset and cash availability into an immutable `OnlySettlementInstruction`, and the settlement projection can represent immediate or delayed availability. No profile or T+N capability field is required for P4.1.

## Unsupported semantic shapes

The current kernel does not implement Margin Account, Market/stop orders, SHORT, HEDGING, SELL OPEN, BUY CLOSE, unresolved/AUTO effects, margin authority, Account/Ledger divergence, or incorrect reservation shapes. BUY OPEN terminal remains unsupported. These shapes must fail closed in the semantic resolver and must not be inferred from market capability flags.

## Generic naming and tests

Generic product identity leaks through `capability.py`, Trade Planner module/class documentation, `_PROFILE_ID`, terminal planning context `market_profile_id`, the Runtime builders, and tests named around Generic T0 permission. `tests/execution/test_execution_capability.py`, `tests/execution/test_trade_planner_failures.py`, and `tests/architecture/test_long_close_durable_transaction_architecture.py` explicitly encode the old profile-based authority.

## Interface disposition

Delete:

- `only_resolve_execution_capability()` and its `market_profile_id` argument;
- the `generic_cash` predicate;
- Trade Planner `_PROFILE_ID` and `UNSUPPORTED_MARKET_PROFILE` gate/code;
- Planner-side and Runtime-builder-side resolver calls;
- terminal planning context market-profile permission state;
- old Generic-profile-specific capability tests.

Introduce:

- immutable `OnlyExecutionReservationShape` and `OnlyExecutionSupportContext`;
- typed `OnlyExecutionSupportReason` and invariant-bearing `OnlyExecutionSupportDecision`;
- pure deterministic `OnlyExecutionCapabilityResolver` with policy version and canonical fingerprint;
- one pure support-context projection path at the Processor authority-capture boundary;
- frozen support decision in both planning contexts;
- support proof in committed Trade and Terminal facts;
- semantic matrix and source architecture guards.

Keep:

- compiled market identity, profile/version, market/venue, reference and rule fingerprints as audit/recovery evidence;
- existing Trade Application Instruction and settlement schedule authority;
- concrete economic validations in planners;
- current durable transaction, projection, persistence, and forward-recovery authorities.

## State ownership answers

- Runtime owns every mutable Order, Account, Position, Allocation, Ledger, Risk, Reservation, and transaction state.
- Managers mutate only through the existing Runtime services and ordered projection targets.
- The support resolver reads no Manager, Registry, Broker, or configuration; it receives an immutable projection captured at Processor routing.
- The Runtime Transaction Store remains durable authority. The support decision is admission proof, not a replacement transaction authority.
- Admission failure occurs before Planner entry. Post-commit failures remain forward-recovery projection failures.
- Recovery must reproduce the continuous-run committed transaction/projection result and must not re-authorize historical committed facts with the current resolver.

## Explicit P4.1 non-scope

P4.1 does not implement BUY OPEN durable terminal, A-share end-to-end product conformance, A-share rule or fee changes, margin, short, hedging, futures, crypto, Paper/Live recovery, broker outbound durability, multi-account products, or a dynamic capability DSL/registry/plugin.

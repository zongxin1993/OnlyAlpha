# Unified fee authority audit

Date: 2026-07-22

## Scope and method

The audit inspected the active Core fee, market-rule, virtual-broker, execution,
account, strategy-ledger, collector/result, configuration, scenario and plugin
paths.  Searches covered `fee`, `commission`, `fixed_commission`, `stamp_duty`,
`transfer_fee`, `exchange_fee`, `reported_fee`, `apply_fee`, `fee_instruction`
and `fee_manager`.

## Current call chains and authorities

* `OnlyMarketProfile.fee_model` contains market rules **and** a `commission`
  component. `OnlyMarketRuleEngine.build_trade_instruction()` calculates it and
  emits `market.runtime_rules.OnlyFeeInstruction`.
* `OnlyVirtualBrokerGateway` independently owns a `OnlyCommissionModel`
  (`OnlyFixedCommissionModel` by default) and writes its result into
  `OnlyOrderFill.fee`. This is a broker-side model, not an external report, but
  it is currently treated as the trade's final fee.
* `OnlyExecutionProcessor` builds a position trade from `fill.fee`, applies the
  market-rule instruction to `OnlyFeeManager`, then applies `trade.fee` to both
  `OnlyAccountManager.apply_trade_cash_flow()` and
  `OnlyStrategyLedgerManager.apply_trade()`. Thus account/ledger use the broker
  fill fee, while fee facts use the market-rule fee.
* `OnlyBacktestCollector` exports `runtime.fee_manager.records`, but builds
  execution records from `fill.fee` as `commission`. Result and account totals
  can therefore represent different authorities.

## Confirmed conflicts and risks

1. Market-profile `commission` and virtual-broker commission can charge the
   same economic fee twice, through separate state paths.
2. `OnlyFeeManager` holds facts calculated by market rules but account and
   ledger deduct `trade.fee`; the required equality is not enforced and is not
   generally true.
3. `OnlyOrderFill.fee` / `OnlyPositionTrade.fee` collapse a broker-originated
   reported fee and the locally resolved final fee into one mutable semantic.
4. The virtual broker maintains its own simulated account balances and applies
   its calculated commission there. It does not import Core managers, but its
   fee is still incorrectly promoted to Runtime truth by the execution path.
5. `OnlyFeeInstruction` is an unversioned market-rule DTO; it lacks runtime,
   account, cluster, status, source, idempotency and schedule provenance.
6. Existing `OnlyFeeBreakdown` is a Decimal/string shape with a permissive
   component mapping. It has no component authority/status and does not verify
   the stated total or unique component identity.
7. Fee configuration is implicit in `market.overrides` and virtual-broker
   `extensions.commission`; missing values default to `NONE`/zero in the
   virtual factory, conflating omission with an intentional zero model.
8. MiniQMT has no normalized reported-fee / reporting-mode contract. No live
   fee reconciliation or account-fee comparison exists. Account reconciliation
   cannot explain an external cash difference with an immutable fee adjustment.
9. Result facts/artifacts include only legacy fee records. They lack fee
   instructions, adjustments, reconciliation facts and schedule timeline;
   fingerprints consequently omit those facts.
10. Existing scenario/conformance tests exercise historical fee schedules,
    profile calculations and fixed virtual commission but do not assert the
    account = ledger = facts invariant, all-in prevention, or live reconciliation.

## State mutation points

* `OnlyAccountManager.apply_trade_cash_flow()` increments account fees and
  subtracts `OnlyAccountTradeCashFlow.fee`.
* `OnlyStrategyLedger` applies the same `trade.fee` as part of a trade.
* `OnlyFeeManager.apply()` appends market-rule fee records, idempotently only by
  trade id.
* `OnlyPositionManager` and allocation accounting also consume `trade.fee` for
  PnL. These must receive the resolved fee rather than a broker report.

## Migration decisions

The legacy `OnlyFeeInstruction` in `market.runtime_rules`, `OnlyFeeModel` as a
runtime final-fee authority, and virtual-broker `OnlyCommissionModel` cannot
remain on the Runtime truth path.  Broker-originated values will be represented
as explicit reports. A new fee package will own immutable domain facts,
versioned market/broker schedules, resolution, adjustment and reconciliation.
ExecutionProcessor will construct and apply one instruction per idempotency key;
account, ledger, position and collector consume that resolved instruction only.

## Implementation order and compatibility

1. Add immutable fee models, schedules, resolver/engine and reconciliation.
2. Add explicit configuration modes and reported-fee broker DTO fields.
3. Route execution through the new instruction and fee ledger; migrate virtual
   broker to report-only behaviour.
4. Move collector/artifact facts and assertions to the new ledger.
5. Remove legacy fee DTO/model/commission runtime paths after all call sites
   migrate, then add scenarios, architecture gates and documentation.

This is a breaking semantic migration: third-party broker plugins that populate
`fill.fee` need to populate the new reported-fee fields instead. It must be
released atomically with the associated plugin contract changes; a long-lived
compatibility path would preserve the double-authority defect.

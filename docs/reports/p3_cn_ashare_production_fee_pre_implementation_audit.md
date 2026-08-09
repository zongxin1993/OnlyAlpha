# P3 CN A-Share Production Fee Pre-Implementation Audit

## Baseline

- Prompt baseline: `0c0543765eeb124d3e87fdad5b3bfad2b38f69a1`
- Actual baseline after `git fetch origin master`: `0c0543765eeb124d3e87fdad5b3bfad2b38f69a1`
- Baseline differences and later pre-solved work: none.
- Pre-existing worktree item: only the user-supplied untracked Prompt.

## Audit

Runtime owns mutable fee accrual/application/ledger/reconciliation state. Transaction Store is durable trade authority;
restored Order Binding is historical fee authority proof. Packs and Contracts are immutable composition data.

The A-share path selected `CN_A_SHARE_TEST_MARKET_FEE_PACK@1`, a generic 0.001 rule from 1970 installed by production defaults.
Generic Cash/Futures/Crypto proved the same resolver, engine, accrual and application path.

Existing primitives already supported rate/per-unit/fixed terms, notional/quantity/contracts, minimum/maximum, explicit
rounding and pipeline, FILL/ORDER_CUMULATIVE, ORDER_FIXED/FILL_EFFECTIVE, side/offset/liquidity, exact Schedule families,
fingerprints, and zero/multiple-match failure. No new formula primitive was required.

`OnlyBrokerFeeContract` already carried identity/version, broker, typed account scope, schedules and fingerprint. Provisioning
existed through plugins only; configuration selected identity but could not define a strict data snapshot. Provenance was one
stable source string already persisted through policy, component, assessment, application, committed facts, Result and
Artifact, so a small source manifest suffices and persisted schemas need not change.

Partial/multi-fill was already correct: FILL adds targets; ORDER_CUMULATIVE applies cumulative target minus prior application,
rejects negative deltas and checkpoints component state. Reconciliation was already component-based.

Verified product scope is ordinary CNY `COMMON_STOCK` cash trading on XSHG/XSHE. A-share Reference supplies exchange/board and
rejects other security types; Fee code does not inspect symbol prefixes.

The only generic gap was side-only Schedule proof: Resolver included a Schedule identity when all its rules were excluded by
side, causing proof inconsistency. The market-neutral correction includes only Schedules contributing an applicable policy.

Required lanes: fast, integration, ashare, recovery, core-full, miniqmt-contract, exhaustive, static gates and build.

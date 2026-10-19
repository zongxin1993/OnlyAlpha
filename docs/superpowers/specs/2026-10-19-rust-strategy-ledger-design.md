# Rust Strategy Ledger

## Ownership

One non-deployed `onlyalpha-strategy-ledger` crate under `crates/onlyalpha-kernel/strategy_ledger/` owns fixed-capital Cluster cash, fees, reservations, equity and replay. Only Domain is a local dependency. It neither mutates Account/Position/Order nor computes fees, terminal Fill status or Position cost basis. Formal Runtime remains Python until integration/admission gates pass. Constitution remains unchanged.

A Manager owns exactly one Engine/Runtime/Account/Generation/canonical currency and an explicit map of Cluster capital. All capital is nonnegative and sums exactly to Account initial cash. No inferred equal shares. Inputs have closed schema version 1, exact scope, signed nanosecond time, runtime sequence, causal digest and stable command identity. Snapshots are immutable values.

## Transitions

Validate into a cloned candidate; rejection/conflict leaves state unchanged. Full canonical payload receipts distinguish equivalent decimal spelling, exact duplicates and conflicts. Trade/execution/venue Fill/fee/order/reservation identities bind globally to exact Cluster. Financial source IDs share one family. Standalone fee adjustments require an already accepted Trade and its exact Order/Cluster relation; unlinked account fees are outside this Cluster attribution input. Fresh duplicate command IDs are durably acknowledged without another financial occurrence or equity point.

BUY consumes gross notional plus charges from its own reservation; rebates credit cash separately. Partial Fill keeps positive authority; terminal comes only from explicit Order output. UNKNOWN/cancel request retain authority. A Fill proves sent even before STAGE; NOT_SENT release after a Fill is forbidden. SELL cannot consume BUY holds. Conservation and nonnegative available cash hold after each commit.

TRADE includes attributed Allocation before/after (quantity, exact cost, cumulative realized, version), instrument and evidence digest. Before equals this Cluster/instrument's last projection. BUY increases cost by notional and quantity; SELL decreases quantity/cost and satisfies realized delta = proceeds minus removed cost. Full close has zero quantity/cost. No average-price reconstruction or Account-cost attribution. These relation checks do not authenticate producers: later Execution proves provenance and commits authorities atomically.

TRADE values only its own Allocation line at explicit mark/multiplier; others remain. VALUATION requires exactly all owned lines, current economic version, exact Allocation versions/evidence and increasing valuation version. Linear market values round HALF_EVEN to currency precision; unrealized = rounded market minus attributed cost. No guessed margin/short/FX/provider rules.

Cash view = cash + market value. PnL view = initial + external flows + realized + unrealized - net fees. Mismatch is RECONCILING, blocking reserve/withdraw; matching valuation clears only mismatch, never sticky stale-Trade. Valid fills/observations/release continue. Charges/rebates support negative net fees and net-negative sale proceeds subject cash invariants.

Runtime calendar day and increasing day ordinal set day-start equity before a new day's first operation. Same ordinal cannot change identity; regression rejected. Simple return absent after any external flow or zero initial capital. Daily return is absent after any flow occurrence that day, including offsetting flows; only an explicit new calendar day resets that occurrence flag. HWM never falls; drawdown nonpositive, ratios precision 8 HALF_EVEN. Each applied mutation produces one equity point at globally increasing runtime sequence; equal timestamps across Clusters remain distinct, duplicates produce none. Stale trades retain receipts and Order ownership, block their Cluster, do not apply economics and cannot authorize fee adjustments. CREATED/ACTIVE/CLOSED lifecycle is explicit; close requires no open Allocation/holds, reactivation forbidden.

## Recovery and bounds

Canonical checkpoint includes config, complete journal and complete state, externally SHA-256 bound. Restore replays into fresh candidate, verifies normalized journal and full state including entries/flags/timeline, then replaces atomically. This is component recovery, not durable Runtime/service upgrade proof.

Reuse pinned Domain/BigDecimal/BigInt/serde_json/SHA-256; no new registry graph. No IO, clocks, random, bridge/provider imports. Bound commands 64KiB, journal4096/8MiB, checkpoint32MiB, Clusters64, instruments256/Cluster, reservations512/Cluster, aliases16384. Money canonical coefficient128 digits, derived1024.

## Reference audit and validation

Python Manager has ID-only Trade/Fee/valuation duplicate paths and consumes reservations before complete Trade validation. Rust does not copy these defects. Actual valuation uses cumulative exact Allocation cost; formal Trade reducer uses rounded average for unrealized. Rust uses exact attributed cost consistently. Avoid broad Python cleanup.

Independent vectors cover two Clusters/same instrument/different costs, partial/terminal, fee/rebate and valuation. Compare actual Python owning implementation on valid subset; literal expected values are independent. Test conflicts/source reuse/missing-extra-wrong Allocation lines/global ordering/calendar/UNKNOWN/stale/money bounds and altered checkpoint journal/state/config/digest. Formal Linux debug/release, isolated Domain+Ledger build, static/boundary checks, bounded simplicity review and one independent authority review are required. Durable cross-authority composition and business migration remain outside this component.

## Engineering evidence and derived protections

Curated `docs/engineering/failure_patterns/FP-STORAGE-001-trading-projection-without-durable-history.md` (RQAlpha issue479) motivates complete command/entry/equity history verification: matching current balances are insufficient. `FP-RUNTIME-001-generation-contamination-and-fallback.md` motivates exact generation/config restore rejection with no ambient fallback. Derived tests alter journal, owner/config, leaf cost and global equity sequence while recomputing an otherwise valid digest. Producer authenticity and real durable deployment proof are explicitly not inferred from a readable component checkpoint.

# ADR 0060: Fee Authority Integrity Closure

Status: Accepted

## Context

ADR 0059 established durable fee assessment and application, but its input model
still combined Market and Broker schedules in one policy pack. Schedule scope was
descriptive rather than a resolution condition, schedule IDs shared an implicit
namespace, and binding schema 1 could not prove the origin of resolved policies.
The resolver also interpreted contract quantity itself.

## Decision

Market fees and Broker fees are separate immutable authorities. A versioned
`OnlyMarketFeePack` owns only Market schedules. A versioned
`OnlyBrokerFeeContract` owns only Broker schedules and is explicitly selected by
an Account; its broker and typed account scope must match Runtime composition.
Missing authorities never imply zero fees. Simulation uses an explicit zero-fee
Broker contract.

Schedule identities and families include a MARKET or BROKER namespace. Market
schedules match effective date, profile market, venue and instrument class;
Broker schedules match effective date, broker and typed account scope. Resolution
requires exactly one applicable version per bound family. Zero or multiple matches
fail closed. Registry registration rejects scope drift across versions of a family.

Order fee binding schema 2 records the Market Pack identity, Broker Contract
identity, full applicability-scope identity, exact ORDER_FIXED schedule identities
and FILL_EFFECTIVE family identities. ORDER_FIXED always resolves the frozen exact
version. FILL_EFFECTIVE resolves the bound family for the Fill trading day while
proving that its scope has not changed.

`OnlyFeePolicyResolution` is the authority proof passed to `OnlyFeeEngine`. It
binds the binding fingerprint, pack/contract identities, scope fingerprint,
resolved schedule identities, policy fingerprint and trading day. The engine
remains pure: it imports no Runtime, Broker registry, Account manager or persistence
service and rejects cross-binding or inconsistent resolution requests.

Fee basis interpretation is outside the formula engine. Registered basis providers
convert instrument economics, price and quantity into notional, quantity and
contracts. Generic cash requires contract multiplier one and does not invent a
contracts value; Generic Futures explicitly defines quantity as contracts.
Unsupported economics fail with `FEE_BASIS_UNSUPPORTED`.

The duplicate `OnlyMarketProfile.market_fee_schedule_id` selector is removed.
Market profiles describe market rules, while Runtime configuration selects fee
authorities independently through `market.fee_pack` and
`accounts[].broker_fee_contract`.

## Persistence and recovery

Binding schema 1 is rejected without migration. Restored order state retains its
binding and is never rebound. ORDER_FIXED therefore survives registry additions;
FILL_EFFECTIVE may select a newly installed effective version only within the
already-bound family and scope. Authority fingerprints and sorted policy identity
make registration order irrelevant.

## Consequences

This is a breaking configuration and persistence change. The combined pack,
legacy schema, aliases and fallback resolution are deleted. Tests and fixtures
must use the same production authority model. This decision does not establish
production A-share fee rates, real Broker commission contracts or detailed
statement reconciliation; those remain separate product work.

## Rejected alternatives

- Keeping a combined pack or compatibility adapter preserves ambiguous ownership.
- Treating a missing Broker contract as zero fees destroys auditability.
- Resolving the first or latest arbitrary schedule makes registration order an
  economic input.
- Letting the fee engine query registries or infer instrument economics breaks
  purity and makes replay authority harder to prove.

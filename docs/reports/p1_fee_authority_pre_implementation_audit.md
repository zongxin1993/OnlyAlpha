# P1 Fee Authority Integrity Closure — Pre-Implementation Audit

Date: 2026-08-08

## Baseline and scope

The Prompt baseline and the actual local `master` baseline are identical:
`39272f9a7201222c83433ce9b1933f02b31985fc` (`Feat: Test Baseline & Feedback Loop Closure`).
The worktree contained only the untracked task Prompt before implementation.

The audit inspected the fee package and its public exports, market profiles and
compiled rules, configuration parsers and normalized payloads, Backtest/Paper
assembly, Runtime order integration, order/execution snapshots, checkpoint and
SQLite persistence, result/artifact projections, fee/order/runtime/recovery/
conformance/architecture tests, examples, fixtures, ADR 0031 and ADR 0059.

## Current type and authority relationships

`OnlyFeePolicyPack` owns both `market_schedules` and `broker_schedules` and is
registered by one `OnlyFeePolicyPackRegistry`. `OnlyFeeScheduleIdentity` contains
only schedule ID/version/fingerprint, so Market and Broker schedules have an
implicit shared namespace. `OnlyBrokerFeeSchedule.account_scope` is an arbitrary
string. Market profiles and compiled market rules additionally carry
`market_fee_schedule_id`, creating a second fee-authority selector.

The mutable fee state remains Runtime-owned. Fee assessment is converted by the
order accrual authority into an application, then enters the durable transaction
and ordered projections. Transaction Store remains the durable trade authority;
this P1 changes the authority input fact, not downstream accounting ownership.

## Current configuration and Runtime assembly

The public schema selects one combined pack at `market.fees.pack_id/version`.
Accounts contain account ID, gateway ID and initial cash only. Backtest and Paper
factories resolve the combined pack from `OnlyComponentFactoryRegistries` and
pass it to `OnlyRuntimeAssemblyConfig.fee_policy_pack`. No independent Broker
contract is selected or checked against the account/gateway relationship. Paper
uses the same combined-pack path despite shadow execution.

## Current binding and resolution flow

`OnlyFeeResolver.bind_order()` checks only pack/profile compatibility and the
effective date. It does not match schedule market, venue, instrument class,
broker or account scope. Binding schema 1 stores profile identity, exact
ORDER_FIXED schedules, bare `fill_effective_schedule_ids`, currency and one pack
fingerprint folded into the binding digest; it does not persist pack identity,
Broker contract identity or applicability scope.

At Fill time, exact and effective resolution first searches the Market registry
and catches `ValueError` before searching Broker. This is an implicit namespace
and can mask the real error. Resolution returns only `OnlyResolvedFeePolicySet`.
It does not prove that policies came from the binding's pack/contract/scope.
`OnlyFeeEngine._validate_request_authority()` explicitly deletes the supplied
binding fingerprint, allowing Binding A and policies B to be combined.

The resolver also computes notional itself and assigns `contracts = quantity`.
Thus fee resolution currently interprets instrument economics rather than
consuming an explicit basis authority.

## Persistence and recovery

Order and execution snapshots serialize the binding through `OnlyDomainModel`.
The order binding is restored as part of order state rather than normally rebound,
which is the correct ownership direction. Binding schema 1 is therefore a real
persistence contract and must become schema 2 with old payloads rejected.
Checkpoint and Runtime transaction containers embed changed snapshots/facts but
do not require a version bump unless their own payload contract changes; this
must be verified by focused round-trip and restart tests. Existing recovery
baselines contain binding-v1 payloads and must be regenerated, not adapted.

## Interfaces and vocabulary to remove

- `OnlyFeePolicyPack` and `OnlyFeePolicyPackRegistry`.
- Combined `market_schedules` / `broker_schedules` ownership.
- `market.fees` and `OnlyFeeConfig`.
- `OnlyRuntimeAssemblyConfig.fee_policy_pack`.
- Bare schedule namespace and `fill_effective_schedule_ids`.
- Market-to-Broker fallback resolution.
- Ignored `binding_fingerprint` validation.
- Resolver-owned `contracts = quantity` inference.
- `OnlyMarketProfile.market_fee_schedule_id` and the compiled-rule copy.
- `onlyalpha.market.models.OnlyFeeBasis`, which duplicates fee calculation
  vocabulary and has no active fee-formula authority.

## Required implementation and test migration

Introduce separate Market Pack and Broker Contract identities/registries,
typed account scopes, typed schedule authority/family identities, applicability
contexts with exactly-one matching and registry-time scope-drift rejection.
Binding schema 2 must freeze exact ORDER_FIXED identities and FILL_EFFECTIVE
families plus complete scope and authority identities. A formal policy resolution
must prove binding, pack, contract, scope and schedule membership before the pure
engine calculates an assessment. Generic cash/futures basis providers must make
instrument quantity semantics explicit and unsupported cases must fail closed.

All examples and valid fixtures must select `market.fee_pack` and an account-level
`broker_fee_contract`; the old `market.fees` schema must have an explicit rejection
test. Existing fee, assembly, persistence, recovery, deterministic-result and
architecture tests require migration. New tests must cover namespace coexistence,
0/>1 applicability matches, scope drift, cross-binding/tampering, ORDER_FIXED and
FILL_EFFECTIVE across restart, registry/config ordering determinism, basis support,
and absence of the deleted architecture.

## Authority answers before implementation

- Runtime owns mutable fee accrual/application and all account/order state.
- Runtime composition owns installed Market Pack and Broker Contract authorities.
- The order owns its immutable fee binding fact after acceptance.
- The resolver may select and prove policies but cannot mutate economic state.
- The basis provider interprets instrument economics; the engine only calculates.
- Transaction Store remains durable trade truth; restored orders must retain their
  binding and must not be rebound from current configuration.
- Failures occur at config/assembly, registry registration, binding, resolution,
  basis or engine proof boundaries and must fail closed before durable commit.
- Recovery must equal uninterrupted execution in binding JSON, resolution
  fingerprint, assessment ID and resulting fee application.

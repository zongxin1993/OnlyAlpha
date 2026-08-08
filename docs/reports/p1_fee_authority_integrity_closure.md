# P1 Fee Authority Integrity Closure — Implementation Report

Date: 2026-08-08  
Baseline: `39272f9a7201222c83433ce9b1933f02b31985fc`

## Before Architecture

One `OnlyFeePolicyPack` mixed Market and Broker schedules behind one registry.
Schedule IDs had no authority namespace, schedule scope did not participate in
resolution, Broker account scope was free text, and Market Profile carried a
second fee-schedule selector. Binding schema 1 did not persist Market Pack,
Broker Contract or applicability-scope identities. The fee engine accepted a
binding fingerprint but discarded it, and the resolver inferred contracts from
quantity.

## Root Problems

- Market rules and Broker commercial terms had no separate ownership.
- Missing or ambiguous schedules could be hidden by Market-to-Broker fallback.
- ORDER_FIXED and FILL_EFFECTIVE did not carry sufficient durable authority.
- Binding A could be combined with an economically equal policy set from B.
- Instrument quantity semantics were embedded in resolution rather than a typed
  basis provider.
- Artifact fee-authority tables existed as empty placeholders.

The detailed baseline audit is in
`docs/reports/p1_fee_authority_pre_implementation_audit.md`.

## Deleted Interfaces

- `OnlyFeePolicyPack` and `OnlyFeePolicyPackRegistry`.
- Combined `market_schedules` / `broker_schedules` ownership.
- `market.fees` and the old `OnlyFeeConfig` path.
- `OnlyRuntimeAssemblyConfig.fee_policy_pack`.
- Bare `fill_effective_schedule_ids` and implicit schedule namespace.
- Market-to-Broker fallback resolution.
- `OnlyMarketProfile.market_fee_schedule_id` and its compiled-rule copy.
- Duplicate `onlyalpha.market.models.OnlyFeeBasis` vocabulary.
- Ignored binding-fingerprint validation and resolver-owned
  `contracts = quantity` inference.

No alias, automatic migration, default Market Pack or default Broker Contract
was retained. Old config and Binding v1 fail closed.

## New Authority Model

`OnlyMarketFeePack` and `OnlyBrokerFeeContract` are independent immutable,
versioned authorities with independent registries and fingerprints. Broker
contracts bind a Broker ID and typed `ALL_ACCOUNTS` or `EXACT_ACCOUNT` scope.
Installed Broker plugins publish explicit fee contracts through
`onlyalpha.broker_fee_contracts`; zero fees exist only as named simulation or
shadow contracts supplied by the relevant plugin.

Market and Broker schedules have distinct namespaces. Their scope fingerprints
participate in family identity, registry registration rejects scope drift, and
resolution requires exactly one applicable version. Registration and config
ordering are normalized deterministically.

Binding schema 2 records both authority identities, the complete order
applicability scope, exact ORDER_FIXED schedule identities and FILL_EFFECTIVE
family identities. `OnlyFeePolicyResolution` proves the binding, authorities,
scope, schedules, policy set and trading day. `OnlyFeeEngine` consumes that proof
as a pure calculation boundary and rejects cross-binding requests.

Generic Cash and Futures providers now own basis interpretation. Unsupported
instrument economics fail with `FEE_BASIS_UNSUPPORTED`; the resolver no longer
invents contract counts.

## Config Changes

Formal configuration now requires:

```yaml
market:
  profile: GENERIC_T0_CASH
  fee_pack:
    pack_id: GENERIC_T0_MARKET_FEE_PACK_CONFORMANCE
    pack_version: "1"

accounts:
  - account_id: account
    gateway_id: virtual
    broker_fee_contract:
      contract_id: VIRTUAL_SIMULATION_ZERO_BROKER_FEES
      contract_version: "1"
```

Backtest and Paper assembly resolve both authorities, validate Market Profile,
Broker and Account compatibility, and include the selections in normalized
planning fingerprints. All valid examples, scenario configs and fixtures use the
new schema. `market.fees` is explicitly rejected.

## Schema Changes

- Order fee binding: schema 1 → 2.
- Fee assessment, estimate and application: schema 2 proof fields.
- Order snapshot: schema 2 → 3.
- Order execution state: schema 2 → 3.
- Trade draft: schema 2 → 3; committed fact: schema 3 → 4.
- Backtest Result: schema 3 → 4.
- Artifact payloads: schema 5 → 6.
- Market-rule checkpoint participant: schema 3 → 4.
- Order authority checkpoint participant: schema 1 → 2.

Committed facts and Result executions now carry Market Pack, full Broker Contract,
Binding, scope, Resolution and namespaced schedule proofs. Artifact tables for
Market Packs, Broker Contracts, schedules and order bindings are populated from
formal committed execution facts instead of remaining empty placeholders.

## Recovery Semantics

Restored orders deserialize Binding v2 from checkpoint and do not run binding
again. ORDER_FIXED resolves the frozen exact schedule identity after restart.
FILL_EFFECTIVE resolves the frozen family for the fill trading day, including a
newly installed effective version, but rejects any family scope drift. Binding,
policy, resolution and assessment fingerprints remain deterministic across
registration order. Recovery and Result baselines were regenerated through the
formal scripts because old Binding v1 payloads are intentionally unsupported.

## Test Matrix

Dedicated tests cover:

- Pack/Contract compatibility, unknown identities, duplicate and conflict
  semantics, and exact-account mismatch.
- Market/Broker same-name namespace coexistence and final assessment inclusion.
- Market, venue, instrument class, Broker and Account applicability.
- zero-match and multiple-match failure codes.
- Market, Broker and Account scope drift.
- ORDER_FIXED exact-version and FILL_EFFECTIVE family-version behavior across a
  serialized restart boundary and registry version addition.
- tampering of Pack, Contract, Account, Instrument, scope, namespace, exact
  version and family identity.
- cross-binding rejection even when calculated amounts are equal.
- cash, futures and unsupported basis providers.
- repeated registration-order determinism for Binding JSON, Binding,
  Resolution, Policy and Assessment identities.
- architecture scans for deleted vocabulary, forbidden dependencies and recovery
  rebinding.
- old config and old Binding schema rejection.
- real Engine artifact authority rows.

## Gate Results

Final recorded results:

- `uv sync --frozen --all-packages --all-groups`: PASS.
- Ruff check / format check: PASS.
- Core mypy strict: PASS, 483 source files.
- Virtual Broker, Tushare and MiniQMT plugin mypy: PASS.
- Fast: PASS, 949 passed / 1 skipped (the existing environment-dependent skip).
- Integration: PASS, 123 passed.
- Core Full: PASS, 1072 passed / 1 skipped.
- Recovery: PASS, 290 passed.
- A-share: PASS, 5 passed.
- MiniQMT Contract: PASS, 31 passed.
- Exhaustive: PASS, 112 passed, including the P1 authority permutation test.
- Build: PASS for all workspace packages.

Performance-budget warnings emitted by existing long-running tests are retained
as diagnostics; no assertion, marker, skip or threshold was weakened.

## Remaining Technical Debt

### NOT IMPLEMENTED IN P1

- Formal CN A-share production market fee pack.
- Real Broker commission contract.
- Detailed component fee reconciliation.
- Typed statement reconciliation period.
- Market-neutral reconciliation risk-reduction authority.
- Broker fee evidence port.
- Paper restart/reconnect.
- Live runtime.
- Durable outbound broker command.
- Multi-market production execution.
- Vectorized backtest.

P1 closes fee-authority integrity only. It does not upgrade experimental Market
Profiles or simulation contracts into production product capability. P2 Fee
Reconciliation Semantic Closure remains unfinished.

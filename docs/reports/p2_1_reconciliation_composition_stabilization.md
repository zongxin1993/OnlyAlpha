# P2.1 Reconciliation Composition Stabilization

## Baseline

- Prompt baseline: `f57664d9236cb97bbcf81f0e8a4a795f795c62f8`
- Actual implementation baseline: `f57664d9236cb97bbcf81f0e8a4a795f795c62f8`
- Baseline difference: none
- Work already completed by later commits: none
- Commit SHA at verification: `f57664d9236cb97bbcf81f0e8a4a795f795c62f8`
- Implementation state: verified working-tree changes; no implementation commit was
  created as part of this execution

## Why P2.1 exists

P2 completed reconciliation Domain and durable semantics, but Runtime factories
still installed their own reconciliation policies. Policy identity also omitted
currency, and the Broker fee-evidence Port had no explicit capability contract.
P2.1 closes those composition and provisioning inconsistencies without changing
P2 evidence, component reconciliation, forward correction, blocker, risk-change,
transaction, or recovery semantics.

## Policy registry ownership before and after

Before:

```text
Backtest factory ─┬─ creates registry
                  └─ creates/registers STANDARD policy

Paper factory ───┬─ creates registry
                 └─ creates/registers STANDARD policy
```

After:

```text
only_default_engine_services()
        └─ installs STANDARD_FEE_RECONCILIATION@1/CNY
                ↓
OnlyComponentFactoryRegistries.fee_reconciliation_policies
                ↓
Backtest/Paper exact require(id, version, Account currency)
```

Runtime factories no longer import the built-in policy constructor, create a
registry, register an authority, or provide fallback. Paper performs the exact
selection during validation, before creating the DataSource resource.

`OnlyEngineServices` exposes the same mutable composition registry used by the
assembler so an application composition root can install custom policies without
changing Runtime factory code. Integration tests prove both Backtest and Paper
select an injected `CUSTOM_STRICT@1/CNY` instance and both fail closed when the
configured policy is absent.

## Currency-aware authority identity

`OnlyFeeReconciliationPolicyIdentity` now contains:

```text
policy_id
policy_version
currency
fingerprint
```

The registry key is exactly `(policy_id, policy_version, OnlyCurrency)` and
`require()` accepts all three dimensions. CNY and USD policies with the same ID
and version are independent authorities. An uninstalled currency combination
raises `FEE_RECONCILIATION_POLICY_NOT_INSTALLED`; no currency fallback exists.
Same ID/version/currency with a changed payload still raises
`FEE_RECONCILIATION_POLICY_FINGERPRINT_CONFLICT`.

Configuration deliberately remains ID/version-only. The current single-currency
Account initial cash remains the sole resolution currency authority.

## Serialized contract changes

The generic Runtime transaction envelope remains schema 6 and is not upgraded.
The contracts whose serialized payloads directly changed advance as follows:

- policy identity: 1 → 2;
- reconciliation decision: 2 → 3;
- fee adjustment: 2 → 3;
- reconciliation fact draft and committed fact: 2 → 3;
- decision and adjustment projection states: 1 → 2;
- reconciliation authority checkpoint: 2 → 3;
- reconciliation blocker: 1 → 2;
- risk-gate state and checkpoint: 2 → 3;
- reconciliation, adjustment, and risk-gate projections: 1 → 2.

The generic domain codec rejects old currency-less identity payloads. Nested
decision, projection, committed fact, and checkpoint decoding therefore also
fails closed; Account currency is never inferred as a migration.

No Result or Artifact table structure changed. Existing reconciliation records
already contain their economic currency, which is equal to policy currency under
the enforced single-currency invariant, while full durable facts retain the new
typed policy identity. The generic artifact schema therefore was not advanced.

## Broker optional capability model

`OnlyBrokerCapability.QUERY_FEE_EVIDENCE` and the corresponding plugin descriptor
flag now represent the existing pull Port. The common
`only_require_broker_fee_evidence_port()` resolver requires both:

1. explicit gateway capability declaration; and
2. structural conformance to `OnlyBrokerFeeEvidencePort`.

A method without declaration raises `OnlyUnsupportedBrokerCapabilityError`. A
declaration without the Port raises `BROKER_CAPABILITY_CONTRACT_INVALID`. Product
code contains no `hasattr(..., "query_fee_evidence")` capability inference.

The Virtual Broker implements the optional Port for contract testing and returns
an empty tuple when it has no evidence. MiniQMT implements neither the capability
nor the query; its contract test freezes that accurate unsupported state.

## Architecture guards

New AST-based guards enforce:

- no reconciliation registry construction in Backtest, Paper, or Live factories;
- no built-in reconciliation policy constructor import/call in those factories;
- `runtime/defaults.py` is the sole Runtime package registry installer;
- product code does not reflectively infer fee-evidence capability.

Existing P2 semantic guards continue to pass unchanged.

## Documentation corrections

- README version is synchronized to `0.3.4`; `version_sync.py` now checks and
  updates the README Version row.
- README identifies the built-in A-share fee pack as test/conformance-only and
  explicitly states production commission, stamp duty, transfer fee, broker
  contract, and MiniQMT evidence work is not complete.
- Roadmap identifies Futures LONG/SHORT/HEDGING as Domain/Conformance foundations,
  not a formal durable product execution slice.
- Roadmap marks P2.1 complete and P3 as the next production-fee phase.
- ADR 0062 freezes composition ownership, currency identity, schema rejection,
  and Broker optional-Port decisions.

## Verification results

Dependency synchronization:

```text
uv sync --frozen --all-packages --all-groups
PASS — Audited 67 packages
```

Static and quality gates:

```text
ruff check src tests examples packages scripts
PASS

ruff format --check src tests examples packages scripts
PASS — 1092 files already formatted

mypy src/onlyalpha
PASS — 487 source files

provider/plugin mypy
PASS — 65 source files

python scripts/version_sync.py check
PASS — all packages synchronized at 0.3.4

python scripts/pre_commit_quality.py --all
PASS
```

Formal test lanes:

```text
fast:
972 passed, 1 skipped in 14.71s

integration:
129 passed in 60.38s

core-full:
1101 passed, 1 skipped in 70.55s

recovery:
294 passed in 168.63s

ashare:
5 passed in 2.12s

miniqmt-contract:
32 passed in 3.43s

exhaustive:
112 passed in 9.19s
```

Build:

```text
uv build --all-packages
PASS — source distributions and wheels built for Core, Virtual Broker, Tushare,
MiniQMT
```

No test was skipped or marked xfail by P2.1, no assertion was weakened, and no
fallback or test-only production branch was introduced. The reported skips are
pre-existing lane selections/environment contracts.

## NOT IMPLEMENTED IN P2.1

- Production CN A-share fee schedules;
- production stamp duty rules;
- production transfer fee rules;
- real Broker commission provisioning;
- real MiniQMT fee evidence query;
- Broker statement ingestion;
- fee debt or negative-cash handling;
- Paper streaming recovery;
- CN A-share durable execution product;
- Live Runtime;
- durable outbound Broker command;
- multi-account Runtime;
- multi-Broker Runtime;
- FX conversion;
- Futures durable product execution;
- Crypto production product;
- vectorized backtest.

P2.1 does not claim real broker fee integration. The next planned phase is P3 —
CN A-Share Production Fee Product.

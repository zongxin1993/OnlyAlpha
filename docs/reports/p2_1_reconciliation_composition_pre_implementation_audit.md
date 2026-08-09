# P2.1 Reconciliation Composition Pre-Implementation Audit

## Baseline

- Prompt baseline: `f57664d9236cb97bbcf81f0e8a4a795f795c62f8`
- Actual implementation baseline: `f57664d9236cb97bbcf81f0e8a4a795f795c62f8`
- Branch: `master`
- Local `origin/master`: `f57664d9236cb97bbcf81f0e8a4a795f795c62f8`
- Baseline difference: none
- Work already completed by later commits: none

The prompt itself is an untracked user file and is not modified by this work.

## Authority and ownership audit

`OnlyFeeReconciliationPolicy` is already a versioned, fingerprinted economic
authority. Its payload contains policy ID, version, currency, materiality
threshold, and the three reconciliation actions. The policy validates that its
threshold currency matches its own currency and that the supplied fingerprint
matches the complete authority payload.

The current registry is `OnlyFeeReconciliationPolicyRegistry` in
`src/onlyalpha/fee/reconciliation_policy.py`. It is Runtime-agnostic, but its key
is currently only `(policy_id, policy_version)`. Consequently, two policies with
the same ID and version but different currencies collide even though they are
different economic authorities.

The current identity model is `OnlyFeeReconciliationPolicyIdentity`. It contains
`policy_id`, `policy_version`, and `fingerprint`, but not currency. This identity
is nested in reconciliation decisions, adjustments, and active risk blockers.

The durable authority for reconciliation facts remains the Runtime transaction
store. Reconciliation authority, adjustment, ledger, and risk-gate components
own their respective projections and checkpoint state. P2.1 does not change
those ownership boundaries or the P2 planning, lineage, correction, blocker, or
recovery semantics.

## Current policy installation and selection paths

### Default composition root

`only_default_engine_services()` centrally installs Market Fee Packs, Broker Fee
Contracts, and Fee Basis Providers. It does not create or expose a reconciliation
policy registry in `OnlyComponentFactoryRegistries`.

### Backtest

`OnlyBacktestRuntimeFactory._plugin_plan()` currently creates a fresh
`OnlyFeeReconciliationPolicyRegistry`, constructs a standard policy using the
configured account currency, registers it, then resolves the configured ID and
version. This makes the Runtime factory both authority installer and selector.

### Paper

`OnlyPaperRuntimeFactory.create()` repeats the same local registry construction,
standard policy construction, registration, and ID/version lookup. It therefore
duplicates Backtest composition and cannot select a custom centrally installed
policy.

### Live

`OnlyLiveRuntimeFactory` is unavailable and does not currently install a policy.
It must remain free of reconciliation authority construction.

## Required composition deletion

The following factory-local behavior must be deleted from both Backtest and
Paper:

- construction of `OnlyFeeReconciliationPolicyRegistry`;
- registration of `only_standard_fee_reconciliation_policy(account currency)`;
- imports of the registry and built-in standard-policy constructor.

Factories must instead exact-resolve ID, version, and the account currency from
`components.fee_reconciliation_policies`.

## Configuration audit

`OnlyAccountConfig` requires `fee_reconciliation_policy`, whose configuration
contains only `policy_id` and `policy_version`. The account initial cash already
owns the single account currency. No policy currency should be added to config.
Runtime selection must use `(configured policy ID, configured version, account
initial cash currency)` and fail closed if that exact authority is not installed.

The normalized Engine payload persists only the configured ID/version, which is
correct: it records dependency selection while the selected authority identity
and fingerprint remain Runtime facts.

## Serialization and persistence audit

`OnlyFeeReconciliationPolicyIdentity` inherits the generic domain codec and is
serialized wherever it is nested in:

- `OnlyFeeReconciliationDecision` (schema 2);
- `OnlyFeeAdjustment` (schema 2);
- `OnlyFeeReconciliationBlocker` (nested by risk-gate state schema 2);
- reconciliation authority checkpoint schema 2;
- risk-gate checkpoint schema 2;
- durable `FEE_RECONCILIATION` projection payloads;
- Result/collector records and Artifacts through projected facts.

Adding currency changes the nested serialized identity. The identity schema and
the directly persisted reconciliation decision, adjustment, reconciliation
authority checkpoint, risk-gate state/checkpoint, and related committed fact
schemas must be reviewed and upgraded where their serialized contracts change.
Old identity payloads must be rejected; account currency must not be inferred as
an implicit migration. The generic Runtime transaction envelope has no structural
change and must not be upgraded solely for P2.1.

## Broker fee evidence audit

`OnlyBrokerFeeEvidencePort` already exists in `onlyalpha.broker.ports` and returns
normalized `tuple[OnlyExternalFeeEvidence, ...]`. It is not part of the mandatory
`OnlyBrokerGateway` protocol, which correctly leaves it optional.

`OnlyBrokerCapability` has no `QUERY_FEE_EVIDENCE` member and there is no single
optional-port resolver that verifies both declaration and structural Port
conformance. Product code currently has no fee-evidence query path and does not
use `hasattr()` for this purpose.

The Virtual Broker currently returns every `OnlyBrokerCapability` by enum
iteration, so adding the new enum value requires a real contract implementation
or an explicit capability set. Its plugin descriptor also has no fee-evidence
field. A supported fake query returning an empty tuple is valid when there is no
evidence; it is distinct from unsupported capability.

MiniQMT exposes no fee-evidence query and does not declare one in either its
gateway capabilities or plugin descriptor. It must continue to declare the
capability unsupported.

## Documentation audit

- `pyproject.toml` is version `0.3.4`; README says `0.3.3`.
- README lists base commission, stamp duty, and transfer fee as current A-share
  capability while the installed A-share pack is explicitly conformance/test
  only. Production schedules are not implemented.
- Roadmap says Futures LONG/SHORT open/close has a product vertical slice, while
  current formal durable execution is Generic T0 Cash LONG/NETTING only. Futures
  has domain/conformance foundations, not a durable product execution slice.
- P2 is correctly marked complete. P2.1 is absent and P3 is already identified as
  not complete.

## Planned narrow changes

1. Add the policy registry to `OnlyComponentFactoryRegistries` and install only
   `STANDARD_FEE_RECONCILIATION@1/CNY` in the default composition root.
2. Make policy identity and registry keys currency-aware, exact, deterministic,
   and fail closed; update affected serialized contracts without compatibility
   fallback.
3. Make Backtest and Paper select the installed policy using account currency;
   add custom-policy, missing-policy, parity, and architecture tests.
4. Add explicit broker fee-evidence capability and one typed optional-port
   resolver; make the Virtual Broker a valid supported fake and keep MiniQMT
   unsupported.
5. Correct README/roadmap wording and record the composition decisions in ADR and
   the final implementation report.

## Test lanes

The minimum acceptance remains the complete prompt gate: Ruff check and format,
Core and provider mypy, `fast`, `integration`, `core-full`, `recovery`, `ashare`,
`miniqmt-contract`, `exhaustive`, all-package build, and the repository quality
gate. No skip, xfail, assertion relaxation, fallback, or fake MiniQMT capability
is permitted.

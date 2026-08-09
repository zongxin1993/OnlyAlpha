# ADR 0062: Reconciliation Authority Composition and Broker Optional Ports

Status: Accepted

## Context

ADR 0061 established reconciliation policy as a versioned economic authority,
but Backtest and Paper each constructed a local policy registry and installed a
standard policy during Runtime assembly. Configuration therefore appeared able
to select arbitrary policy IDs and versions although factories could only create
their hard-coded standard policy.

The registry key and serialized policy identity also omitted currency. Policies
with the same ID/version but different currencies have different economic
meaning and fingerprints, so they cannot share one authority identity.

The normalized Broker fee-evidence Port existed without a corresponding explicit
Broker capability or a single contract-checked optional-Port resolver.

## Decision

Reconciliation policies are installed by the Engine composition root in one
`OnlyFeeReconciliationPolicyRegistry`, alongside the Market Fee Pack, Broker Fee
Contract, and Fee Basis Provider registries. Runtime factories only exact-select
an installed policy using configured policy ID, configured version, and the
single Account currency. They never construct, register, infer, or fall back to a
policy.

Currency is a required field of `OnlyFeeReconciliationPolicyIdentity` and a
dimension of the registry key. The default composition installs only the
currently verified `STANDARD_FEE_RECONCILIATION@1/CNY` authority. Other currency
or custom policies require explicit composition-root installation.

The serialized policy identity and directly containing reconciliation decision,
adjustment, fact, projection, authority checkpoint, blocker, and risk-gate
contracts advance their schema versions. Old currency-less identities are
rejected without migration. The generic Runtime transaction envelope remains
unchanged.

`QUERY_FEE_EVIDENCE` is an explicit optional Broker capability. Product code may
obtain `OnlyBrokerFeeEvidencePort` only through the common resolver, which first
requires the capability declaration and then validates structural Port
conformance. A method without declaration is unsupported; a declaration without
the Port is a capability contract error.

The Virtual Broker supports the optional query for contract testing and can
validly return no evidence. MiniQMT does not implement or declare the capability.

## Consequences

- Authority installation is Runtime-mode independent and custom policies require
  no Runtime factory changes.
- Account currency remains the sole current policy-resolution currency authority;
  configuration does not duplicate it.
- Missing policy/currency combinations fail closed.
- Broker capability discovery cannot be inferred with `hasattr()`.
- This ADR does not install production A-share fee schedules, real broker
  commission contracts, statement ingestion, or MiniQMT fee evidence queries.

## Rejected alternatives

- Factory-local registries preserve duplicated authority ownership and fake
  configurability.
- ID/version-only keys merge economically different currency authorities.
- Currency fallback or reconstruction silently changes configured governance.
- Making fee evidence mandatory on every Broker contradicts optional capability
  semantics.
- Treating method presence as capability bypasses the declared product contract.

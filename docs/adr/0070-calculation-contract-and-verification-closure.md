# ADR 0070: Calculation Contract and Verification Closure

Status: Accepted

Date: 2026-08-13

## Context

ADR 0069 established the Calculation Definition, DAG and plugin boundary, but its first implementation still admitted unsafe
interpretation: readers coerced scalar types and ignored unknown fields; DAG edges checked only data type/nullability; the Core
registration DTO required a Trading factory; product Indicator references could omit semantic version; and official plugin
algorithms had no package-owned characterization/coverage authority. Factor execution examples also continued to load by Python
path, which could be mistaken for semantic identity.

These gaps become irreversible once Definition and Graph identities are persisted by Dataset, Calculation Store, Result or
Artifact systems.

## Decision

Calculation Definition schema v2 and Calculation Graph schema v1 are exact, fail-closed persistence contracts. Definition v2
introduces tagged scalar persistence rather than silently changing the earlier v1 representation. Unknown, missing,
wrongly typed and unsupported-version data is rejected at every nested boundary. Calculation scalars use tagged persistence values
so Decimal and String never collapse during round-trip. Semantic fingerprints continue to use the single shared
`onlyalpha.canonical` authority; persistence tags do not create a second hash authority.

One pure compatibility authority validates data type, nullability, dimensions, semantic type and unit exactly. Implicit numeric
coercion, dimension conversion, unit conversion and missing-value normalization remain unsupported; future conversions require
explicit Calculation nodes.

`OnlyCalculationBackendRegistration.provider` is backend-neutral. The Registry owns exact
`kind + type_id + semantic_version + backend` availability only. `OnlyTradingCalculationBackendResolver` alone validates the
Trading `create` shape. A future real Research provider may register against the same Registry contract; no placeholder Research
backend exists today.

`OnlyCalculationTypeReference` is the immutable backend-independent type/version reference. Built-in legacy Indicator tokens are
normalized once through a fixed `TOKEN -> onlyalpha.indicator.name@1` mapping. Canonical third-party references must include
`@semantic_version`; no latest-version selection exists.

Formal Factor identity is `OnlyCalculationDefinition(kind=FACTOR, factor_kind=...)`. Trading product config carries an exact
`OnlyCalculationTypeReference`, and a loaded Factor implementation must declare the same reference before its config is created.
Python `class_path` remains an implementation loading detail and is excluded from Definition, Graph and fingerprint. The official
Factor plugin remains legitimately empty; examples are not promoted to built-ins.

Official Indicator verification is owned by its plugin package. All nine algorithms have fixed-output, ready/warmup, timestamp,
duplicate, out-of-order, reset, checkpoint/restore and continuation characterization. A dedicated calculation lane, plugin coverage
gate and explicit plugin mypy scope are release inputs.

## Consequences

Future schema readers fail closed instead of guessing. EMA@1 remains exact when EMA@2 is installed. Research can add a different
provider interface without changing Registry identity semantics. Indicator mathematics and checkpoint payload shapes are unchanged;
RSI restoration deterministically reconstructs its already-derived zone when reading the existing payload shape, closing a
previous continuous-versus-recovery mismatch.

Research Runtime, Dataset Snapshot, Calculation Store and Research backend remain future work.

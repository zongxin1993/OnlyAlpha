# ADR 0114: Canonical Decimal Execution Context Authority

- Status: Accepted
- Date: 2026-09-03
- Related: ADR 0069, 0070, 0073, 0113

## Context

ADR 0113 requires common-algebra calculations to execute with Decimal precision 28, `ROUND_HALF_EVEN`, and an output quantum of
`0.000000000001` inside an explicit context. Copying the caller's current Decimal context and overriding only precision and rounding
does not satisfy that requirement: exponent limits, clamp, traps, and flags remain caller-owned hidden inputs.

## Decision

OnlyAlpha Core owns one market-agnostic canonical Decimal execution policy. Caller Decimal contexts, Python `DefaultContext`, and
third-party Decimal mutations are not execution authorities. Policy `onlyalpha.decimal.execution@1` explicitly fixes `Emin=-999999`,
`Emax=999999`, `capitals=1`, `clamp=0`, clean entry flags, and the complete trap map. `InvalidOperation`, `DivisionByZero`, and
`Overflow` trap; `Underflow`, `Subnormal`, `Inexact`, `Rounded`, `Clamped`, and `FloatOperation` do not.

Per-Calculation precision, rounding, and output quantum continue to come from `OnlyNumericDefinition`; exponent, clamp, trap, and
flag-entry policy do not become authoring knobs or Calculation Definition identity. Core constructs every context from explicit values
and provides the canonical quantization helper. Internal flags are discarded on exit and caller flags remain unchanged.

The policy has one canonical payload and fingerprint. Every implementation whose behavior uses this policy binds that fingerprint via
the existing `OnlyCalculationImplementationManifest.semantic_dependencies` authority. A policy change therefore changes implementation
identity and, where admitted, the exact StrategyRevision implementation binding without changing Calculation semantic identity.

### Non-publishing legacy-CONTEXT invocation

ADR 0138 and its owner-approved fourteen-family extension permit separately admitted non-publishing W3 invocations whose exact legacy Definition declares
`CONTEXT`: versioned binding `CONTEXT_HALF_EVEN_V1` explicitly resolves it to `ROUND_HALF_EVEN` before constructing the existing
Core context. Precision and quantum still come from the exact Definition. Both declared and effective rounding and the resolution
policy are recorded without rewriting Definition fingerprints or copying caller context. The effective invocation's actual
implementation-manifest closure must bind the Core policy and resolution/invocation code; missing closure blocks support.

This does not create a second Decimal envelope, a Research publication exception or general permission to resolve unspecified
numerics. Provider-content changes require a new Provider version; actual Definition/algorithm semantic changes additionally
require a new Calculation version. Reuse of SMA@1 requires proof of unchanged declared semantics under the explicit contextual
input. No arbitrary historical ambient-context Research result is claimed equivalent or rewritten.

## Consequences

Identical Definitions and ordered inputs produce identical outputs or deterministic failures regardless of caller, thread, or process
Decimal state. L1 Operator and B1 L2 financial formulas share one numeric execution authority while their concrete mathematics remain in
their plugins. Unexpected Decimal envelope violations fail rather than becoming null, NaN, Infinity, or adjusted values.

## Rejected alternatives

- Adding Python runtime context fields to `OnlyNumericDefinition` and changing existing Definition fingerprints.
- Separate official Decimal policies in Operator and Indicator packages.
- Copying ambient contexts and overriding only selected fields.
- Omitting policy identity from implementation evidence.

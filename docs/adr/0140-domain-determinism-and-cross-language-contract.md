# ADR 0140 — Deterministic Domain and cross-language representation

- Status: Accepted (owner decisions, 2026-10-17)
- Scope: Python `src/onlyalpha/domain/` and Rust `crates/onlyalpha-kernel/domain/`
- Refines: ADR 0005, ADR 0006 and ADR 0139; subject to the Constitution

## Decision

Domain is a complete functional module, with isolated builds and no reverse dependency on Kernel orchestration, Runtime,
Application, storage, Web or concrete plugins. Both implementations consume one canonical Contract and independent test inputs.
Python is audited and corrected before its behavior becomes a comparison baseline. Neither implementation may normalize a
mismatch away or become a second official writer. Python and Rust coexist until the separate activation/retirement gates hold.

### Financial operations

The explicit policy identity is `domain-exact-28-half-even-v1`. Finite addition, subtraction and multiplication are exact.
Terminating division is exact; non-terminating division rounds to 28 significant digits with HALF_EVEN. Division by zero is
invalid. Division operates on coefficient ratios with a symbolic exponent; exact results remove fractional trailing zeros while
retaining compact integral exponents. A compact exponent must not trigger expansion into an enormous integer. Operations do not inherit mutable Python Decimal contexts, their traps or their rounding modes. Currency/tick/step
quantization occurs only at an explicit business boundary; its declared rounding overrides the generic default when required.
The existing 0–18 fractional-precision declarations remain; migration does not impose a new fixed integer-width ceiling.
Operational input/resource limits require separate explicit bounds and failure semantics, rather than silent overflow or rounding.

### Identity and serialization

Venue IDs cannot contain `.`. Symbols can; Instrument text splits at the last separator. Existing references must be inventoried
before any affected historical identity is migrated. No identifier is silently rewritten, guessed or aliased.

Financial Decimal fields are strings on the wire. Floating-point and JSON integer values are rejected at Decimal fields;
this does not change integer fields or user-facing numeric editors. Decode validates primitive field types, exact required fields
and fixed discriminants, and re-executes constructors. Concrete Instrument variants must retain all subtype fields recursively.
Instrument schema 2 includes an explicit `model_type`, separate from economic `instrument_type`; base Instrument remains an
explicit variant. Unknown model types and mismatched subtype tags fail closed. Explicit custom subclass readers validate their
own tag; the base reader does not dynamically import classes or silently invent plugin variants.

Owner selected direct development Contract evolution for Bar identity: BarSemantic schema 3 and Volume/Value formation
schema 2 use one exact canonical parameter representation for both records and fingerprints. Strip coefficient trailing zeros
and adjust the exponent without rounding or ambient Decimal context; equal values such as `1`, `1.0` and `1e0` serialize equally.
BarSemantic readers require that exact canonical record and reject noncanonical parameter spellings; constructors accept numerical inputs and canonicalize them.
This rule is restricted to numerical Bar parameters, not financial fields whose declared precision has meaning. Both languages
and repository consumers move atomically to the current Contract. No old reader, identity alias, fallback or version-family branch
is retained. Earlier immutable artifacts are not silently reinterpreted, rewritten or deleted; mismatched current inputs fail closed.
Actual business data disposal or reconstruction requires a separate explicit owner decision.

### Time and dependencies

Both languages must consume the same pinned timezone-rule dataset. Host timezone database discovery is not sufficient evidence
of deterministic parity. The exact dataset version/content belongs in implementation input closure and upgrade verification.
DST gaps fail; folds require the existing explicit disambiguation Contract. No custom DST rule table is introduced.
Owner confirmed strict temporal records: explicit UTC `YYYY-MM-DDTHH:MM:SS[.1..6 fractional digits]Z` or `+00:00`,
`YYYY-MM-DD` dates and timezone-free `HH:MM:SS[.1..6 fractional digits]` wall times. Alternate ISO spellings and
sub-microsecond datetime text are rejected, not truncated; exact nanoseconds remain in OnlyTimestamp.
Both languages preserve the full Python year 1..9999 range. Jiff is limited to civil calendar operations; tz-rs uses
explicit shared TZif bytes for absolute time and timezone conversion, with no OS discovery, clock input or fallback.
The strict input change requires explicit historical migration outside current readers; no business stores are mutated here.

Use stdlib/toolchain facilities first. Required third-party crates may be admitted after a specific review of maintenance, license,
security history, transitive dependencies, features, build scripts/native code and semantic fit. crates.io publication does not
mean Rust-project maintenance. Do not replace maintained numerical/JSON/time parsing with handwritten infrastructure merely to
avoid dependencies. Compiler/library defaults never define OnlyAlpha financial semantics.

## Historical data and rollout

New current-format readers reject old or malformed input; they do not contain an implicit legacy fallback. Before applying any
format/identity change to existing stores, identify their owning readers, exact historical artifacts, references and backups.
A migration must specify preconditions, deterministic transformation, transaction/atomicity, failure and restart semantics and
reference-integrity proof. Schema-1 Instrument values require an explicit source concrete type: an economic type alone cannot
distinguish a base model from a concrete/custom subclass. If an earlier reader has already discarded subtype fields, they cannot
be reconstructed by inference; migration requires authoritative original definitions or remains blocked.

Existing immutable facts and exact artifacts are preserved. No business database or user-data mutation is authorized by this ADR.
Fresh round-trip tests cannot substitute for history migration or deployment upgrade evidence. Full module parity, isolated
builds, affected consumer regression and bounded independent review remain necessary; this decision does not certify them.

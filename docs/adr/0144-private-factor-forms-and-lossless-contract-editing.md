# ADR 0144: Private Factor forms and lossless contract editing

- Status: Accepted
- Date: 2026-10-27
- Decision maker: repository owner, explicitly accepting the three forms, independent per-section advanced mode and independent required/default controls, then requesting documentation only.
- Related: PROJECT_CONSTITUTION.md; ADRs 0092, 0104, 0124, 0135, 0141, 0143.
- Owning architecture: [Private Factor authoring](../private-factor-authoring.md#structured-contract-editing-target).
- Construction order: [Repository work program](../repository-migration-work-program.md#private-factor-contract-form-follow-up).

## Decision

The Shipping Private Factor editor presents 所需数据, 可调参数 and 计算结果 as ordinary forms over the existing input, parameter
and output contract objects. Each section independently exposes advanced JSON. A complex section stays advanced without
forcing the other two out of forms. Backend Product/Command/Private Asset Authority, API DTOs, canonical fingerprints and
publication semantics remain unchanged. This is an editing projection, not a new contract language or durable form model.

Required and default are independent parameter controls. Read-time defaults never materialize absent fields. The existing
omitted-required rule depends on default presence; any coordinated edit needed to retain the independent selected behavior
must be explicit and confirmed. No implicit coercion, schema completion, unknown-field deletion or source rewrite is allowed.
Mode-only operations do not save/publish; a no-edit round trip and an edit/revert preserve original values and field presence.
Unrepresentable content remains intact in its section's advanced editor. Existing canonical object ordering governs identity;
JSON formatting is not a new identity, while arrays, exact strings, value types and absent/explicit fields remain significant.

Ordinary validation explains filling errors and advanced-mode limitations. Advanced storage follows existing authoring rules;
unsupported-for-form does not mean invalid-for-storage or admitted-for-execution. No browser execution validation, automatic
source parsing, data binding, Research/Generation/Backtest capability or new tools are introduced. Authoring acceptance does
not certify source execution or scientific correctness. ADR 0143's separate mutable names/usage and version-bound description
rules remain in force.

## Alternatives and consequences

JSON-only editing was rejected for ordinary usability. Rebuilding contracts from a restrictive form was rejected because it
could drop unknown fields, inject defaults and change identity. One global advanced-mode switch was rejected because one
complex contract would make unrelated sections unnecessarily technical. Independent lossless sections retain the existing
expressiveness with a smaller ordinary surface; a truthful advanced-only explanation is preferable to a lossy conversion.

Fields, exact defaults, errors, round-trip rules and required proof live in the owning architecture. Implementation follows
its bounded work-program sequence and AGENTS.md acceptance rules. This documentation approval does not implement the forms,
change current contracts/fingerprint algorithms, authorize data cleanup, commit/push, release or update the running dev app.

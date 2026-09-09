# FP-RUNTIME-001 — Historical generation contamination and ambient fallback

## Failure family

Historical work executes with current or mixed Python distribution bytes after a version change.

## External / internal evidence

- Python isolated-mode and subprocess documentation; specification-defined environment/import and pipe behavior.
- PyPA repeatable-install documentation; specification-defined risks of unpinned or implicitly resolved dependencies.
- OnlyAlpha PRE-E.A/PRE-E.B analysis; reproduced by contrasting differently built local Core/Provider wheels.

## Observed symptom

An old Search Experiment returns a result produced by current code, or two nominal historical generations share imported modules and
produce an order-dependent mixed result.

## Generalized root cause

Metadata identity was mistaken for executable isolation, or an unavailable historical dependency silently resolved from an ambient
interpreter/environment.

## Risk to OnlyAlpha

Determinism, exact Runtime Work binding, Research provenance, recovery and single Authority are violated. A plausible result can carry the
wrong implementation identity without an obvious process failure.

## OnlyAlpha invariant

All generation-sensitive executable code comes from the exact bound Runtime Generation. Different generations never share an interpreter,
and unavailability never falls forward to current code.

## Required protection

Content-addressed complete artifacts, clean no-network/no-dependency-resolution rebuild, hosted seal/RECORD/Provider/Catalog/Calculation
verification, exact worker handshake and a bounded versioned DTO protocol.

## Required tests

- G1/G2/current use observably different implementation bytes and return exact generation-specific evidence concurrently.
- Same Catalog plus different Core/support artifact still selects the exact Runtime Work binding.
- Historical plugin modules do not enter parent `sys.modules` and parent Catalog/Registry remain unchanged.
- Missing/corrupt artifacts, evidence, seal or RECORD fail closed.
- Deleted cache rebuilds the same handshake and deterministic result.

## Non-solutions / rejected shortcuts

`sys.path` mutation, `importlib.reload`, current/latest fallback, retry-until-success, sleeps, pickle/object proxying and a generic Python
RPC do not prove exact execution.

## Scope notes

This applies to generation-sensitive historical Search computation and later exact historical execution boundaries. Pure observation of
already durable facts does not require worker execution.

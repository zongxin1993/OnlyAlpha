# ADR 0083: Research Result Composition Authority

- Status: Accepted
- Date: 2026-08-15

## Context

P7.7 ends with immutable verified Statistics Results, but the platform has no stable machine-readable authority that states which
exact Statistics authorities constitute one complete research output. Sweep Outcomes describe an invocation and include
EXECUTED/REUSED evidence; Statistics Results own data rows. Neither is the final composition boundary required by future Artifact,
Query, API, or Web consumers.

## Decision

`onlyalpha.research.result` owns an immutable composition-only Research Result. A versioned Plan contains at least one canonical,
duplicate-free Statistics logical fingerprint. Identity is deliberately layered:

1. Plan fingerprint identifies the canonical requested Statistics identities.
2. Content fingerprint identifies canonical pairs of Statistics fingerprint and verified Statistics Result fingerprint.
3. Research Result fingerprint identifies Plan plus Content.

The assembler calls the Statistics Result Store's `load_verified()` for every Plan member, validates exact logical/result identity,
requires one exact Dataset Snapshot across all members, and stores references rather than Statistics rows. Created time and physical
root are provenance only; execution disposition, host/process/path, compression, JSON layout, display metadata, and Sweep ordering do
not enter semantic identity.

The JSON Store is keyed by Plan fingerprint. It stages one exact manifest, reads it back through full verification, atomically
publishes it, and performs upstream referential-integrity verification on every `load_verified()`. Equal recommit is REUSED;
different deterministic content conflicts; missing, corrupt, identity-mismatched, or cross-Dataset upstream authority fails closed.
Corrupt existing authority is never deleted, repaired, rebuilt over, or treated as missing.

Research Result may depend on the public Research Evaluation authority and neutral canonical helpers. It may not depend on Runtime,
Cluster, Strategy, Broker, Account, Order, Position, Risk, Reservation, Execution, Transaction, Settlement, Sweep invocation state,
Web, UI, or CLI presentation. Research and Live Runtime factories remain unsupported.

Impact propagation stops at the verified Statistics Result public contract while that producer contract remains unchanged. A future
Statistics public-contract change must propagate forward to the Research Result consumer.

## Rejected Alternatives

- Copying Statistics rows would create a second data authority.
- Treating Sweep Outcome as Research Result would put invocation evidence in semantic identity.
- A mutable Experiment DB would create a competing recovery and result authority.
- Including EXECUTED/REUSED, paths, timestamps, or display metadata would break retry and physical-location neutrality.
- Automatic cross-Dataset merge would introduce undeclared alignment semantics.
- Letting Web read internal stores directly would bypass a stable read boundary.
- Depending on Trading authorities would violate the Research/Trading firewall.

## Consequences

Future Research Artifact and read-only Query/API/Web layers can start from one verified immutable composition. P7.8 does not implement
those consumers, an optimizer, cross-Dataset comparison, a Research Runtime lifecycle, or a Trading product capability.

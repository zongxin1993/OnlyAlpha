# Calculation-publication compilation

Specification schema 3 expresses `CALCULATION_PUBLICATION` without Statistics, scientific Candidate or Signal facts.
Its exact payload contains one immutable Dataset Snapshot, one fixed Calculation template, one exact published-series selector,
and a publication selection. The selection requests `RESEARCH_CALCULATION_V2`, Calculation Result 2, Execution Evidence 2 and
readiness contract 1. It is separate from the unchanged Job execution publication contract.

The Specification resolver uses the existing canonical template materializer and selector resolution. The current capability
admits one TIME_SERIES node whose registered backend supports readiness V1 through the formal readiness backend resolver.
It produces one Job Plan 2 and Result Plan 4, with no Sweeps or Statistics plans. Result Plan 4 owns exact unowned Calculation,
Graph and series membership plus the publication selection; its wire payload omits scientific fields entirely.

Calculation semantic identity remains Dataset Snapshot plus Graph. Publication versions and artifact profile enter Specification
and Result Plan identities, not Calculation identity. Specification 1/2 and Result Plan 1/2/3 retain their original payloads and
fingerprints; old documents are never upgraded on read.

`OnlyResearchHostedRuntimeGenerationResolver.resolve_calculation_publication()` requests the separate
`RESOLVE_RESEARCH_CALCULATION_PUBLICATION` operation. The existing execution port verifies the exact hosted generation, artifacts
and capability handshake, including historical retired generations. The worker loads the verified Dataset and compiles using
that generation's installed Registry. Missing capability or authority fails closed; there is no current-process fallback.
Historical compilation uses a read-only generation verifier permitting exact validated RETIRED identity. Host cache reuse
revalidates eligibility for each acquisition: neither a cached compilation worker nor this verifier grants legacy operations
execution eligibility. Binding, release, activation and retirement state machines are unchanged.

`OnlyResearchCalculationRuntimeResolutionV1` checks Specification identity, complete template-node mapping, Job/Plan Dataset,
Graph and Calculation closure, published selector and exact RESEARCH implementation manifest/binding. Manifest hashes recompute
and nested fields are strict. Explicit input sources must agree with the requested template. Registered default inputs
and parameter normalization are proved by the hosted canonical compiler, not independently recompiled by the DTO reader. The
adapter additionally requires exact requested Specification, generation and operation equality.

A self-consistent DTO or manifest alone is not hosted provenance, execution evidence, observed readiness, a completed publication,
or permission to reuse outputs. Resolution executes no numeric backend. Generic Research admission remains restricted to its
existing Specification families; it cannot turn publication resolution into legacy admission evidence.

These contracts create no Chart database relation, Run, queue entry, Calculation output, Result or Artifact publication. Those
owning authorities must be integrated separately. Normal legacy Research imports keep the hosted DTO implementation lazy.

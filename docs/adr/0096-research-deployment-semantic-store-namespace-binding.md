# ADR 0096: Research Deployment Semantic-Store Namespace Binding

- Status: Accepted
- Date: 2026-08-22
- Related: ADR 0084, 0085, 0089, 0090, 0091

## Context

OnlyAlpha deliberately has two authority planes. PostgreSQL owns mutable Research Run, Attempt, lease, cancellation and Worker-presence
facts. Immutable stores under `USER_DATA_ROOT/research` own Dataset, Calculation Result, Statistics Result, Research Result and Artifact
facts. These authorities must remain separate, but the deployed service currently lacks one durable compatibility fact: which immutable
Research semantic-store namespace belongs to a given Research PostgreSQL deployment.

Consequently an API using database `D` and local root `A`, and a Worker using the same database `D` and local root `B`, can both pass their
local startup checks. The Worker can commit Result and Artifact under `B` and finalize the Run in `D`, while the API later reads the exact
completed reference from `D` and cannot find it under `A`. Artifact-not-found is too late: the deployment was incoherent before the Run
was admitted or claimed.

The missing fact is deployment operational compatibility, not Research semantic truth. It must not change Dataset, Calculation,
Specification, Candidate, Statistics, Research Result or Artifact identity.

## Decision

One Research PostgreSQL deployment is bound to exactly one compatible immutable Research semantic-store namespace:

```text
Research PostgreSQL deployment D
<->
Research semantic-store namespace S
```

The namespace owns a typed stable UUID identity. Root-level immutable metadata at
`USER_DATA_ROOT/research/.onlyalpha-semantic-store.json` stores only canonical schema version `1` and `store_id`. The ID denotes the
namespace, not its current contents: adding immutable objects does not change it. It is not a Result/Artifact index, catalog, latest
pointer, cache manifest or object registry.

The namespace ID is distinct from a local filesystem path. Two processes may expose the same shared filesystem namespace through
different mount paths and remain compatible because they load the same metadata identity. Path-string equality is neither required nor
accepted as proof.

Migration `0007_research_deployment_semantic_store_binding` creates one narrow singleton PostgreSQL table. It stores only the expected
semantic-store UUID and binding audit time. It contains no Dataset, Calculation, Statistics, Result or Artifact content and no generic
key/value metadata surface. PostgreSQL owns this durable deployment compatibility fact; existing semantic stores retain all scientific
authority.

## Explicit initialization and binding

Only the explicit operator command may initialize or bind a deployment. Migration creates schema only. API and Worker startup are
strictly read-only and never create, adopt, repair or rewrite either authority.

Operator initialization has these rules:

1. An absent or empty new `USER_DATA_ROOT/research` may receive a newly generated identity.
2. An existing valid identity may be loaded so an interrupted explicit initialization can be completed idempotently.
3. A non-empty semantic root without identity is refused. Existing contents are never silently adopted.
4. An absent PostgreSQL binding may be initialized to the local identity.
5. An existing equal binding is idempotent; an existing different binding fails closed.
6. Rebinding requires a future explicit, separately designed operator lifecycle and process restart. V1 provides no rebind command.

The identity file is published atomically and never overwritten. A crash after filesystem identity creation but before PostgreSQL bind
leaves an unbound namespace; rerunning the same explicit command can complete the same binding without changing the ID.

## Readiness and execution admission

API and Worker startup load and strictly validate the local namespace identity, load the PostgreSQL expected identity, and compare the
typed values. Missing binding, missing/corrupt/unsupported local identity and mismatch are stable secret-safe failures.

The API captures this check as a process-startup compatibility fact and cannot become READY when it fails. The Worker must pass it before
announcing readiness or entering the Scheduler claim loop. A Worker with the wrong namespace therefore cannot claim. Binding changes are
not dynamically adopted by a running process; operators restart services after any future authorized deployment change.

The check is deployment admission only. It is not repeated per semantic object, and its ID is never supplied to Research resolution,
execution or fingerprint computation.

## Restore semantics

A complete immutable semantic-store snapshot includes the namespace metadata. A coherent recovery pair has PostgreSQL expected ID `X`
and filesystem namespace ID `X`; fresh API and Worker startup pass. Pairing a database expecting `X` with a store identified as `Y`, or
with missing/corrupt identity metadata, fails before normal readiness or execution.

This complements, and does not replace, strict verified loading of exact Result and Artifact references. Correct identity proves the
namespace binding; it does not prove that every referenced immutable object is present or uncorrupted. Restore certification must prove
both namespace coherence and exact semantic evidence.

## Rejected alternatives

- Absolute-path binding is rejected because local mount paths are deployment presentation, not namespace identity.
- Hashing current store contents is rejected because a valid immutable store grows while retaining its namespace.
- Startup auto-initialization, silent adoption, repair and dynamic rebind are rejected because they can legitimize the wrong authority.
- Putting Result or Artifact content in PostgreSQL is rejected because the existing dual-plane authority is correct.
- A mutable central Artifact/Result registry is rejected because it would become a second semantic authority.
- Repeating `semantic_store_id` on every Run is rejected because the fact belongs to the deployment, not an individual semantic intent.

## Consequences

- Same PostgreSQL plus a different semantic namespace fails before API readiness or Worker execution.
- Different local paths to the same namespace remain valid.
- Backup/restore has an explicit durable pair-coherence proof in addition to exact semantic verified loads.
- One narrow forward migration and one explicit operator initialization step are required.
- Existing Research semantic identities, immutable stores, OnlyEngine/OnlyResearchRuntime execution and recovery behavior are unchanged.

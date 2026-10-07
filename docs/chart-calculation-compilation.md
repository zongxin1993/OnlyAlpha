# Chart calculation compilation relation

The compilation boundary consumes an admitted Chart operation and its verified immutable `INPUT_READY` preparation. It does
not select input, claim a worker lease, acquire market data, change preparation state or own Runtime Work lifecycle.

## Inputs and relation ownership

The operation owns normalized intent and the exact Catalog readiness witness. Preparation owns the input pin, ready revision
and fence, Dataset Snapshot/materialization references and original chart-owned Runtime binding reference. Verified readers
must prove the complete T1 admission/receipt/reservation relation and the append-only preparation chain, not just equal hashes.

Compilation verifies the pin against that operation, the exact Snapshot through its official physical/logical reader, and the
materialization's identity, Snapshot and pinned Revision lineage. The Runtime Authority supplies the original `NEW_WORK` binding
event, owner `CHART_CALCULATION_INPUT`, reserved work ID, generation, actor, sequence and event fingerprint. Missing or malformed
mandatory proof is an error, never permission to reselect latest or manufacture an absent occurrence.

The internal Specification uses fixed Calculation ID `chart_calculation` and template node ID `indicator`, the admitted type
reference and normalized parameters, one exact admitted output selector, and the readiness-bearing publication selection.
Template input bindings are omitted: the registered compiler in the exact hosted Generation owns canonical source derivation.
No application price-field switch or receiver Registry recompilation substitutes for that compiler.

One immutable operation-to-compilation relation binds this context to Specification V3, Job Plan V2, Result Plan V4, exact
Graph/Calculation membership and the Catalog's RESEARCH implementation manifest/binding. Its domain-separated canonical
fingerprint covers the complete relation without audit time. It is neither numeric execution evidence nor a completed
publication. Display style and browser incarnation are not compilation inputs.

## First compilation and historical replay

First compilation requires the original binding to be active, and the frozen Generation to match the admitted Catalog.
Only the exact hosted publication resolver may compile. Preparation and original active binding are verified again before
commit. Unavailability leaves `INPUT_READY` untouched; it does not mark failure, release work or allocate another identity.

A complete existing exact relation returns without hosted recompilation, consulting current Catalog, current activation,
latest Market Revision or a provider. The same original binding may be inactive for this historical replay; inactivity does
not rewrite the compilation and grants no future Run admission. Mandatory immutable inputs and owner references still require
verification. A corrupted stored relation cannot be rebuilt over. A complete different candidate is a conflict, not replay.

## Persistence, concurrency and ambiguity

Migration `0047_chart_calculation_compilation_relation` is additive after checksummed history through 0046. The control-catalog
table stores canonical compilation metadata and redundant identity columns, not numeric values, readiness rows, artifacts or
mutable progress. UPDATE, DELETE and TRUNCATE are prohibited. Existing operation and preparation history remains unchanged.

The adapter serializes on the global Product Command lock and uses the owning transactional T1/T2 verified readers before
insert or replay. Duplicate insert is successful only after proving complete equality. Every verified load checks canonical
JSON, fingerprint, redundant columns and contextual relations. DDL and the migration ledger commit atomically; interrupted
migration rolls back and retries the same checksummed migration. Rollback means disabling compilation writers while retaining
compatible readers/history, or forward-fixing—not deleting authority facts.

After an ambiguous commit acknowledgement, exact reload may return only a proved same relation. Missing proof, a different
relation or unavailable storage cannot become successful compilation or a definitive uncommitted outcome.

## Negative capability

Compilation creates no Research Run or queue entry, leaves the reserved Run ID unconsumed, and changes no Product receipt.
It executes no Calculation backend and publishes no Calculation Result, Execution Evidence, Research Result or Artifact.
Generic V3 admission and Plan4 execution fences remain closed. D3 alone may introduce separately authorized atomic reserved-ID
Run handoff; this boundary contains no D3, HTTP/OpenAPI/Web, cancellation or public operation-state projection.

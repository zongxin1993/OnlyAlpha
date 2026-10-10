# Native readiness-bearing Research publication

This contract extends ADR 0136/0137 for Research Result schema 4 and `RESEARCH_CALCULATION_V2` Artifact schema 2. It preserves
the Authority split in ADR 0074, 0083, 0084 and 0126. It defines publication foundations, not Chart Worker dispatch or a completed
Chart Run. Constitution Impact: NO.

## Ownership and version selection

| Fact | Owning Authority | Exact selection |
|---|---|---|
| Immutable input | Dataset Snapshot | Snapshot fingerprint, complete Definition/schema/content |
| Original sealed source and lineage | Integration / Market Data / Materialization owners | Original Integration Binding, Revision/Manifest/Seal/Segments and exact Materialization |
| Values and point readiness | Calculation Result V2 | Dataset + Graph + RESEARCH, Result2 content/result fingerprints |
| Sealed producer attestation | Execution Evidence V2 | Exact Result2, node/implementation bindings and Runtime provenance |
| Publication membership | Research Result V4 | Result Plan4 and exact Calculation logical/Result pairs |
| Portable copied facts | Research Artifact | Profile `RESEARCH_CALCULATION_V2`, schema 2, logical content fingerprint |
| Executable generation and eligibility | Infrastructure | Original Runtime Work relation, manifest and Validation Evidence |
| Run occurrence and terminal state | Research Run | Existing Run/Attempt/lease/fencing relations; not Artifact identity |

Specification3, Job Plan2, Result Plan4 and publication contract schema1 select Calculation Result2, Execution Evidence2 and
readiness1 explicitly. V1 caches cannot satisfy this selection. Existing Result1/2/3, Calculation/Evidence1 and existing Artifact
profiles retain their payloads, addresses and fingerprint semantics. No document is upgraded on read.

Result4 is calculation-only: exact Snapshot, nonempty canonical Calculation/Graph membership and published output selection,
with no Statistics, Candidate or Signal facts. Assembly and every verified load use the V2 Calculation Authority explicitly;
matching SHA text never determines a version. They prove Snapshot/Calculation/Result/Graph/node/output linkage.

Assembly, commit, verified load and durable acknowledgement additionally require complete Execution Evidence V2 through its
owning store. The scientific composition validates all applicable attestations without choosing a producer: multiple fully
verified producers of the same content do not change Result identity. Missing/corrupt/unavailable evidence cannot authorize
publication or reuse. Publication acknowledgement synchronizes the verified Evidence predecessors as well as Calculation2.
Artifact selection and exact generation-bound reuse retain their separate, explicit producer requirements.

Result4 content hashes schema4 and canonical Calculation logical/Result pairs with the empty Statistics set. Its Result identity
hashes schema4, Plan4 and content. Runtime generation, Evidence selection, execution disposition, audit time, paths, style and
browser identity are not scientific Result identity. Multiple valid producers may attest the same scientific Result.

## Native producer and Runtime provenance

Only an actual issued `_execute_verified_v2` capability can publish values/readiness. A public execution DTO, copied/replaced
seal, parsed E1 `EXECUTED_UNPUBLISHED` response or self-consistent caller-authored rows cannot publish or mint Evidence.

The native adapter verifies the exact manifest and Validation Evidence through Infrastructure's owning readers, their complete
relation and the current isolated installed process through hosted verification. It uses that process's installed compiler and
Registry, comparing the complete frozen compilation and implementation bindings. Current-process fallback and in-place reload
are forbidden. New executable bytes require a new Runtime Generation; an existing Work is never rebound or implicitly upgraded.

Before backend execution, trusted Infrastructure composition issues a process-local context binding Graph, complete expected
node-to-implementation bindings and Runtime provenance. Structural parsing does not issue this context. The executor verifies
actual issuance and exact context, compares atomic producer bindings, and binds the context into its native execution seal.
Evidence minting consumes that same seal; provenance cannot be attached after execution. Independent immutable issuance records
must detect in-place mutation as well as copied/replaced contexts and changed context inside an issued execution.

The narrowly internal issuer has one production composition caller: the native adapter in the existing generation-manager
component, after owning-reader and current-process hosted verification. Public DTO constructors/parsers, raw fingerprint
arguments and public re-exports cannot invoke issuance. Calculation publication modules do not import Infrastructure/runtime
implementations. This is the trusted in-process composition boundary, not protection against arbitrary malicious Python already
executing inside that process.

Execution Evidence2 adds an optional `runtime_execution_provenance` record. Its exact schema1 fields are:

- `schema_version` = 1;
- `runtime_generation_fingerprint`;
- `validation_evidence_fingerprint`;
- `core_execution_fingerprint`;
- `catalog_generation_fingerprint`.

All fingerprints are canonical lowercase SHA256. The record participates in Evidence identity when present. Omission preserves
existing Evidence2 payloads/fingerprints exactly; explicit null, coercions, unknown fields and unsupported versions reject.
Generation-bound publication requires this record. `authoring_generation_fingerprint` remains a separate dimension and cannot
stand for actual executable Runtime Generation. Old readers must reject unsupported payloads, not discard provenance.

Generation-bound reuse selects exact Result2, full implementation bindings, full Runtime provenance and exact authoring
provenance when applicable. Finding one numerically equal Result or one otherwise matching Evidence is insufficient. Evidence
without mandatory generation proof is incomplete for this path, not a proved different producer or permission to overwrite.

`ExecutionEvidenceStoreV2.load_exact_for_result` is the non-mutating exact-producer
read: full Result2, implementation, Runtime and authoring expectations remain
mandatory, with no publication or durability acknowledgement. The existing
`require_exact_for_result` delegates that verification and still acknowledges the
selected predecessor for publication/re-entry. Neither path accepts a missing
Runtime expectation for generation-bound selection. Local NOT_FOUND is not a
scientific-absence witness.
An unavailable owning semantic anchor or permission/device/read failure reports
`RESEARCH_EXECUTION_EVIDENCE_STORE_UNAVAILABLE`, not local NOT_FOUND or corruption.
An available anchor with an unpublished optional namespace can report local
NOT_FOUND. Existing malformed packages and missing mandatory files remain corrupt.
Evidence bindings stay open through the owning Calculation Result read and linkage
check, followed by the final namespace recheck. Exact-miss fallback and dangling
Evidence inspection enumerate bound directories and read bound regular manifests,
not unbound pathname text. All visited directory memberships and opened inodes are
rechecked before returning a local scan snapshot; anchor loss or substitution
cannot turn relevant incomplete provenance into an empty scan. The snapshot is
still not a historical/cancellation absence witness and mints no producer authority.

Hosted verification proves execution location, not Chart Work permission. This foundation grants no production Chart dispatch,
Search-worker durable writes, Claim, Attempt, lease or Run transition. A future Chart caller must independently prove original
Work eligibility and owning compilation relations through the formal Run boundary.
Verification of this foundation must run inside exact installed-generation tests. This contract adds no production dispatch,
IPC capability or HTTP/Product API entry point.

## Artifact address and retained content

For this new profile only, the exact read selection is
`(RESEARCH_CALCULATION_V2, 2, research_result_fingerprint, artifact_content_fingerprint)`. Storage is under
the existing Artifact root at `research-calculation-v2/sha256/<first-two-hex>/<artifact_content_fingerprint>`. This is a versioned
extension to the Result-addressed older profiles, whose addresses and readers remain unchanged. There is no Result-SHA fallback,
latest producer selection or new Artifact Plan/Artifact Result authority. V2 readers require both explicit identities and reject
a Result/Artifact mismatch; they do not derive a missing Result expectation from the package being queried.

For receipt-less lookup, `ArtifactStoreV2.load_exact_for_publication` derives the
same existing Manifest2 logical identity from complete verified Result4, Dataset,
Calculation2, selected Evidence2, retained Generation and sealed Source references.
It reads the resulting exact Result/Artifact pair using bound no-follow descriptors,
rechecks the complete package and namespace bindings, and performs no scan, write,
fsync, acknowledgement or repair. Physical encoding and audit-time differences
remain excluded by the canonical Manifest identity; no duplicate hash formula or
new index is introduced. The caller must obtain expectations through owning
verified readers: parsed copies grant no live Source, producer or Attempt authority.
Unavailable roots, incomplete context, corruption and substitution fail closed;
even an exact local NOT_FOUND cannot authorize cancellation or certify scientific
or historical absence. Stable semantic-absence inspection remains a separate
reconciliation obligation, not implemented by this lookup.
`ARTIFACT_STORE_UNAVAILABLE` distinguishes an unavailable owning anchor and
permission/device/read failures. Local NOT_FOUND is returned only after no-follow
descriptor traversal and rechecking the opened existing ancestors. Malformed
namespace links, incomplete retained packages and inode substitutions remain
`ARTIFACT_CORRUPT`. These failures cannot be interchanged by a reconciliation caller.

Artifact logical identity binds profile/schema, exact Result4 identity, complete copied logical sections and exact selected
Evidence/provenance. Artifact encoding byte hashes, compression, relative storage paths and audit time are excluded. Executable
artifact byte identities inside Runtime provenance remain mandatory provenance inputs, not Artifact encoding choices. Different
valid generations can therefore share Result4 while having different Artifact locators without a false deterministic conflict.

Publication starts with verified Result intent and explicit exact Evidence selection through the canonical materializer, never
a public raw commit of caller-authored derived rows. Every reload rechecks exact references; a previous Result read does not
authorize a later different upstream Result. Evidence selection is a nonempty canonical bijection from Result4 Calculation
references to exactly one explicitly selected Evidence2 per reference. Missing, extra or duplicate selections reject. Each
Evidence must match the complete referenced Calculation2 identity and explicitly expected Runtime provenance, plus exact
authoring provenance when applicable. For this generation-bound publication path, all selections agree with the single exact
generation of the verified frozen compilation; publication obtains that expectation from verified native composition, not raw
caller hashes. No producer is inferred from Result identity or discovered by scanning. Offline verification proves this same
complete coverage and single-generation relation from the retained facts; any supplied read expectation must also match them.
The portable package retains:

- complete Result4/Plan4 and canonical membership;
- complete Dataset Snapshot manifest, Definition, schema and all canonical Dataset partition content needed to recompute its
  content and Snapshot fingerprints;
- every referenced Calculation2 manifest/Graph and all value/readiness partitions, including unselected Definition outputs,
  instruments and rows;
- each explicitly selected Execution Evidence2 and its complete Runtime provenance;
- exact Runtime manifest, Validation Evidence, all referenced distribution manifests, selected Calculation implementation
  manifests and the complete canonical Catalog descriptor needed for their retained identity relationships.
- mandatory `OnlyRetainedSealedChartInputEvidenceV1`, including original Integration Runtime Binding payload, source reference
  and selection, exact scope/construction, complete Revision/Manifest/Seal, all ordered Segment metadata and physical proofs,
  exact Materialization semantic payload/ID and its relation to this same Dataset Snapshot.

Publication additionally requires the reader-issued input capability from the
[verified sealed Chart input export](chart-calculation-input-export.md). Its Result Plan, Graph, Generation and Dataset must
match the native publication, and its callback repeats the original owning reads before staging, writes or successful reuse,
and again before rename. A parsed retained DTO, E1 JSON or self-consistent source hashes cannot issue this capability.
Original Source loss blocks live publication/reuse; an independently retained package does not restore the missing owner.

Schema 2 with missing source proof is intentionally unsupported. Such existing immutable packages fail closed without
upgrade, overwrite, legacy loader, inferred proof or compatibility shim. Existing Calculation1, Result1/2/3, Evidence2 without
Runtime provenance and the older Scientific/Calculation Artifact profiles are unchanged. The new required source exporter
currently covers the admitted one-instrument native 15-minute Chart input; it does not admit arbitrary multi-source inputs.
That bounded capability does not redefine long-term Research or Source scope.

### Current owning Artifact inventory

`ArtifactStoreV2.inspect_retained_for_calculation(calculation_fingerprint)` is a
scoped read-only session, separate from exact pair lookup. It holds the existing
owning exclusive publication lock until successful context exit and returns all
fully verified V2 packages containing that canonical Calculation. It verifies each
published candidate before applying membership selection, regardless of Result
Plan, Generation, Source or selected Evidence. It performs no live predecessor
read, reconstruction, Source issuance, execution, acknowledgement or fsync. It
does not add an index, identity, historical cut or negative witness.

The root and regular lock must already exist; missing/permission/device failures
are `ARTIFACT_STORE_UNAVAILABLE`, not an empty inventory. Malformed V2 namespace,
packages, applicable proof, addresses, or any binding/membership substitution are
`ARTIFACT_CORRUPT`. Other Artifact profiles are not inspected. Within the optional
V2 namespace only `sha256`, canonical two-hex prefixes and exact content-addressed
directories are published locators. A `.stage-<canonical UUID4 hex>` directory in
its writer-defined prefix position is an unpublished crash staging area, not a
retained publication; noncanonical staging names, non-directories and symlinks
reject. Empty optional namespace links remain a current view, not history.

Inventory membership and all package/ancestor/file inode bindings are retained and
rechecked before yielding and before successful exit. Consumers retain this same
Artifact exclusion while acquiring any other necessary owners in the documented
downstream-to-predecessor order, without reopening the Artifact read session. They
must not publish/acknowledge under EX or use the snapshot before successful exit.
The snapshot's linearization is its final owning checks, not its first directory
read. Consumer exceptions propagate unchanged rather than being reclassified as
Artifact corruption/unavailability; lock release and descriptor cleanup still run.
An empty tuple cannot authorize cancellation or certify historical absence;
readable retained copies do not prove durable ACK, live Source/predecessor closure,
Run/Attempt occurrence or terminal outcome. Native forward guarding and complete
multi-owner cancellation/recovery inspection remain separate consumer obligations.

### Native forward re-entry inspection

Both native publication entry points require the approved Artifact root in addition
to their live predecessor roots. Before native context issuance, Job/backend work
or semantic publication they inspect all retained V2 packages containing the exact
Calculation, not just the current Result Plan. Complete different Plan, Generation
or Source packages remain relevant to protecting their shared live predecessors.
Every related package must have its original live Result4, all referenced
Calculation2/Datasets and every exact selected Evidence2; a readable portable copy
never repairs a missing live owner or grants Source/execution permission.

The inspection prebinds four existing roots and regular locks and acquires EX in
Artifact → Result → Evidence → Calculation order. Actual lock inodes are deduplicated;
only contiguous alias classes preserve this order. Non-contiguous aliases form an
order cycle and reject before lock acquisition. The Artifact inventory continues
the same retained owner binding instead of re-locking itself. Owning scoped
Dataset/Calculation/Evidence/Result readers retain full package/file bindings and
Evidence inventory membership through common relation checks. No ACK, mkdir,
coordination creation, Source issuance or fsync occurs in this inspection.

An available zero/partial prefix may continue the original authorized producer
path. Missing anchors/locks and I/O remain unavailable; incomplete/corrupt relations
reject rather than become non-match. Exact query refs derived from verified reads
only restrict later work: any observed Calculation, selected current Evidence or
current Result must still exist for exact reuse/ACK after inspection. Job result-only
recovery can produce a new attestation but cannot recreate an observed Calculation
that disappears during numerical execution, and must prove equal values/readiness
before reusing it. Existing Result ACK does not recreate a lost owning root.

The inspection's final relation checks are its current-view linearization, not a
cross-filesystem transaction covering later numerical work. Locks are released
before that work; subsequent owning operations must refuse missing protected refs.
This is not historical absence, no-ACTIVE cancellation certification, lease/Work
permission or a durable ACK witness. Those Controller/reconciliation obligations
remain separate, and no SQL Claim capability follows from this guard.

### Physical section contract

The original physical baseline is mandatory; it is not waived in favor of embedded or partitioned equivalents. Full owning
partitions remain additionally retained to prove all outputs, not only published projections. Required projection files are
derived mechanically from those full facts and verified equal on every read; they are not parallel Authorities.

| Required physical section | Exact carrier and derivation | Identity / completeness checks |
|---|---|---|
| `artifact_manifest.json` | Strict Manifest2 with Result4, Dataset, Calculation2, selected Evidence2, Runtime and source proof | Full schema, logical Artifact identity, explicit Result/Artifact pair |
| `market.parquet` | Existing Scientific market schema; OHLCV projection of the complete Dataset | Exact Arrow schema/count, decimal strings and full table equality to verified Dataset |
| `graphs.json` | Canonical ordered Calculation identity/Graph pairs | Exact bytes equal owning Graph serialization |
| `variables.parquet` | Existing Scientific variable schema; exact published-series values | Candidate null, exact Calculation/node/output/instrument/axis, typed value and lossless full table equality |
| `readiness.parquet` | Non-null Calculation/node/output/instrument/time/readiness/reason schema | Exact published-series projection of actual complete Calculation2 readiness, never reconstructed warmup |
| `calculation_evidence.json` | Canonical ordered exact selected Evidence2 payloads | Exact bytes, original Evidence identity and Runtime/Result relation |
| `sealed_input_evidence.json` | Complete canonical retained source proof also bound by Manifest2 | Exact bytes, strict nested lineage, source family/count/coverage and Materialization/Snapshot relations |
| `signals.parquet` | Existing Scientific Signal schema, zero rows | Required file, exact schema and typed-empty table |
| `statistics.parquet` | Existing Scientific Statistics schema, zero rows | Required file, exact schema and typed-empty table |

`dataset/<partition>` and `calculations/<fingerprint>/<partition>` retain the complete source-independent Dataset and
Calculation facts. Their hashes and logical manifests still prove unselected outputs and exact input membership. Every
required file, including JSON and typed-empty sections, participates in the exact file set and has an exact byte hash/size.
Projection logical identities are derived from the already bound owning facts and fixed schema2 section semantics; encoding
and audit time do not enter logical identity. No required section is missing or replaced by an unapproved equivalent layout.

Every retained file has an exact byte hash; partition descriptors retain exact Arrow schema, row count and logical fingerprint.
Physical hashes describe the retained bytes. Re-encoded partitions must not claim the original encoding's byte hash. Logical
identity projections exclude upstream audit times and physical encoding fields while retaining complete canonical fact identities.
Allowed relative paths and the complete file set are derived from strict canonical manifests, never caller-selected file reads.

The V2 portable reader admits at most 16 MiB of manifest bytes, 512 MiB of total encoded partition bytes, 512 MiB of declared
uncompressed and incrementally observed logical partition content, and 2,000,000 rows per partition. These are profile-local
read bounds, not E1 execution limits or permission to decode unverified bytes. Physical size/hash and declared schema/count/bounds
are checked before partition decoding. Over-budget or malformed content fails closed without fallback.

OHLCV/chart rows are mechanical projections of the retained full Dataset, not independent caller-authored sections. Axes alone
do not prove market-value linkage. A published subset does not reduce complete Calculation2 fingerprint proof requirements.
Original Revision/Seal/materialization references retain their canonical lineage; a package without upstream venue history does
not claim independent verification of unretained venue facts.

## Neutral retained-proof verification

Offline reads use shared pure identity/read contracts, not Runtime, Application, generation-manager, Registry construction,
Provider discovery, entry-point loading or numeric execution. Infrastructure remains the sole executable validation and lifecycle
Authority. Moving pure contracts does not move this Authority or create another Runtime parser.

The same canonical generation identity classes and serialization/fingerprint methods serve Runtime and portable verification.
Pure private-factor snapshot entry **and snapshot** contracts must be shared without eagerly importing their executable producer,
including through package initializers. Existing public exports refer to the same class objects, not duplicated legacy types.
Reuse the Exact Catalog descriptor/type validator and Calculation implementation-manifest reader through neutral shared boundaries.

Retained-proof parsing rejects duplicate JSON keys, unknown/missing nested fields, boolean versions, malformed identities and
noncanonical collections; constructor normalization alone is insufficient. Verification proves:

1. Snapshot Definition/schema/content/count and identity from full retained Dataset facts.
   Original sealed source proof additionally verifies Integration Binding, ordered complete Segment/physical proof membership,
   BAR-only canonical partition family, sufficient physical Bar occurrence count for native unique grid coverage (duplicates
   are allowed), Revision/Manifest/Seal identities and exact Materialization request/construction/Definition/provenance.
2. Complete Calculation2 value/readiness partitions, Graph/output membership, types/nullability and exact instrument/time axes.
3. Selected Evidence2's exact Calculation2 content/Result and Graph/node/implementation relation.
4. Runtime provenance's exact manifest/Validation Evidence/Core/Catalog relationship.
5. Exact distribution manifest fingerprints and unambiguous manifest-to-byte relationships, not coincidence of sorted sets.
6. Selected Graph type, Catalog registration, implementation manifest and distribution inventory relationships, including owning
   provider content, asset type descriptors and tested Core identity where required.
7. Catalog provider/registration uniqueness, same type across backends, state/checkpoint compatibility, private snapshot identity,
   unique entries, source references and backend binding relations without constructing executable registrations.

Dataset tables must equal their canonical Arrow-to-Bar-to-Arrow representation exactly; declared price/quantity precision cannot
hide subprecision values in copied Arrow tables or market projections. The complete Dataset must satisfy the owning Definition
validator, including instrument, Bar semantics, closedness, requested range and logical-Bar uniqueness. Coherently rehashing
downstream identities does not excuse a contradiction between retained Definition and content.

Runtime inventories may include native-factor bindings and predicate primitives outside Catalog registrations. Verify each owning
family relationship, not blanket inventory equality. Catalog descriptors do not advertise readiness versions; native execution
and its Evidence establish readiness capability, never a guessed Catalog inference.

Offline hashes prove internal coherence of retained canonical attestations, not cryptographic authenticity, fresh execution
permission, Run ownership or terminal success. No reverse restore/import authority is granted by a portable copy.

## Point readiness and exact predicates

Values and readiness come from one registered atomic execution. Apply the complete ADR 0137 state/reason/value/nullability
matrix to every Definition output and row. Period3 has two initial `PARTIAL/WARMUP_INCOMPLETE` points then `READY/NONE`;
period1 is immediately READY. Exact zero is valid. Missing/malformed readiness is an error, not invented UNAVAILABLE or READY.

Exact producer predicates distinguish applicability, completeness and equality:

| Proof | Conclusion |
|---|---|
| Complete applicable proof, all exact dimensions equal | Proved match |
| Complete applicable proof, an exact dimension differs | Proved non-match |
| Relevant mandatory proof missing | Incomplete; never certified non-match/absence |
| Relevant proof malformed/corrupt | Fail closed; never missing |
| Required owning source inaccessible | Unavailable; never missing |
| Exact leaf absent under a verified local namespace | Local NOT_FOUND, not historical absence |

Historical certified absence requires a closed owning source cut and complete evaluation of relevant records. `exists()`, partial
scans, row counts and absent optional downstream facts do not provide this proof. No new historical absence facility is implied.

## Durability, concurrency and recovery

Publication retains valid prefixes: Calculation2, selected Evidence2, Result4, then Artifact2. Run terminal publication is a
separate owning transition. Failure/cancellation may leave any valid prefix; these facts do not imply COMPLETED or rejection.

New Result4/Artifact2 publication fully verifies staging, syncs every retained file/directory, uses native exclusive rename,
verified-loads the exact winner and acknowledges all owned namespace links through a defined preprovisioned anchor. Equal race
losers and exact re-entry perform durability acknowledgement themselves. Readability is insufficient. Existing empty directories,
files, symlinks and corrupt/incomplete targets are not replaceable absence.

Each predecessor is exactly verified and durably acknowledged before the next publication reports success. Result remains under
its existing Plan-keyed address and source-owned publication barrier; no second Result inventory or migration is introduced.
Ordinary readers remain read-only. Explicit owning-store publication/reuse paths perform acknowledgement.

### Read-only publication exclusion

Calculation2, Evidence2 and Artifact2 publication and durability re-entry hold their
owning shared publication barrier through staging, exclusive rename, verification,
acknowledgement and staging cleanup. Result4 retains its existing barrier. The
barriers add no scientific identity, producer attestation, persistent inventory or
historical cut. Native seals, exact selected Evidence and all existing Source and
predecessor acknowledgement requirements remain mandatory.

`OnlySourcePublicationBarrier.inspect_readonly()` opens the already provisioned
owner root and regular `.source-cut.lock` through bound no-follow descriptors and
takes the exclusive lock. It creates no directories/lock/cut, performs no fsync,
and rechecks every opened ancestor and the lock inode after acquisition and before
successful return. Initial missing root/lock or I/O/permission failure is
`SOURCE_PUBLICATION_UNAVAILABLE`; malformed lock/path or substitution of an opened
binding is `SOURCE_PUBLICATION_BARRIER_INVALID`. Neither is an empty inventory.
The existing `capture_closed_cut()` still writes retained cut metadata and is not
a substitute for this read-only primitive. Owning write paths may initialize
coordination metadata; V2 acknowledgement never recreates a missing semantic root.
Calculation commit retains its existing permission to create its root only under
the preprovisioned parent, after sealed input/Graph validation.
Its parent descriptor is retained across validation and root creation; creation
uses that directory descriptor, not a pathname that a Source/audit hook can replace.
`publication_bound()` continues that same root/ancestor binding when creating and
locking the regular coordination file. It does not reopen and select another owner
between root creation and lock acquisition. The locked descriptor is the one
retained and verified by the tree; successful return rechecks that same relation.
Artifact similarly retains its original root across the initial full table
verification and predecessor acknowledgement, before creating a coordination file.
It repeats predecessor acknowledgement under exclusion and immediately before
rename. Internal post-publication acknowledgement remains inside that same owner
lock; it does not open another coordination lock or select another owner. These
preflight checks grant no reuse, absence or publication permission on their own.
Legacy publication/capture may still initialize their configured directory chain,
but bind every existing ancestor before creating each missing child via its bound
parent descriptor. Initial or later symlink substitution cannot redirect that
creation into an unrelated directory. Acquisition/unlock I/O failures remain
unavailable and always close the owned descriptors, including when unlock fails.

All publishers and retained-cut captures also bind/recheck this regular lock and
their owning ancestors. Locks are advisory, not protection against an administrator
writing outside the owner. This contract requires local filesystem flock semantics;
unsupported locking/error outcomes fail closed, with no pathname or network-lock
fallback. Acquiring a shared publication lock while holding an exclusive inspection
lock for the same owner is prohibited, not a read-to-write permission upgrade.

A multi-owner read must use the downstream-to-predecessor order
`Artifact → Result → Evidence → Calculation`, acquire each owning lock once, and
retain exclusion until its final namespace/relation verification. This matches the
publication acknowledgement direction. Exclusion alone certifies no semantic
absence, durable acknowledgement, Run/Attempt occurrence or terminal outcome.
Complete owning namespace inventory and exact predicate evaluation remain separate
requirements of cancellation/recovery inspection; a local NOT_FOUND cannot satisfy
them. No Run mutation, Attempt or Work release is added by this primitive.

Calculation2, Evidence2, Result4 and Artifact2 acknowledgements bind their canonical directory tree and retained files to no-follow
descriptors before verification and synchronization. They check inode/type relations and exact leaf sets before and after syncing
and rereading the same descriptors. A prefix symlink, an additional retained entry, or even a byte-identical replacement inode must
fail closed rather than return an object verified before substitution. Result source-cut lock and Evidence staging links remain
inside their respective owning anchors and are synchronized without moving their Authority. Result acknowledgement uses the
actual held publication-barrier descriptor, not a reopened lock pathname, and checks every enclosing publication lock binding.
Replacement before acknowledgement binds its tree is therefore also an error. Shared descriptor bookkeeping is an
internal filesystem primitive; each store remains the sole parser, linkage validator and semantic acknowledgement Authority.

The Dataset store's explicit `acknowledge_exact(snapshot_fingerprint)` verifies the exact canonical snapshot tree, syncs its retained
files and data directory, and acknowledges snapshot/prefix/sha256/root and every ancestor link through the fixed preprovisioned
filesystem root anchor. Existing Dataset commit directory-creation behavior is unchanged; existence of an intermediate parent is
not substituted for durability of its link. Acknowledgement binds traversal, verification and sync to
opened no-follow directory/file descriptors, then rechecks exact inode/type bindings and complete file sets; concurrent symlink or
byte-identical inode substitution is not accepted as the acknowledged tree. Calculation V2
publication and exact reuse require this owning acknowledgement; Result4 and selected Evidence acknowledgement transitively retain
that requirement. Artifact publication also requires exact Dataset acknowledgement before acknowledging the remaining predecessors.
An ordinary `load_verified_table` is never substituted for that durability proof and never performs fsync.

| Interruption/state | Re-entry semantics |
|---|---|
| Before exclusive rename | Staging is not published Authority |
| After rename, before durability acknowledgement | Unknown acknowledgement; same identity is reread and resynced |
| Valid Result2, expected exact Evidence leaf NOT_FOUND under a verified owning namespace, with no broken relevant retained relation | Fresh eligible native execution may attest equal complete content; no Result rewrite or historical absence claim |
| Result2 absent but relevant retained Evidence present | Broken relation; refuse recomputation/overwrite |
| Complete different producer proof | Not exact reuse; separately eligible native execution may create its own attestation |
| Complete Result4, Artifact publication fails | Preserve Result; re-enter exact Artifact selection, not Run success |
| Artifact published before Run update | Preserve Artifact; only Run Authority can recover occurrence/terminal relations |
| Same canonical identity, different scientific content | Deterministic conflict; preserve winner |
| Required proof corrupt/incomplete/unavailable | Fail closed; no repair, fallback or invented seal |

A missing live upstream fact does not erase a retained downstream publication or authorize restoration/recalculation. Portable
copies remain independently readable without implying live upstream availability. No fsync failure may be hidden by a later
read-only reuse path.

## Required verification properties

Verification covers forged/copied/in-place-mutated seals and contexts, wrong Graph/implementation/Generation, post-execution
provenance attachment, all readiness/nullability combinations and zero, complete-different versus incomplete proof, rehashed
Dataset and nested provenance mutations, duplicate owners/registrations/relations, wrong families, unselected output retention,
offline copy with every upstream/executable access prohibited, canonical legacy identity/import parity, and barrier/fault-driven
equal/conflicting races and every publication acknowledgement failure. Two actual installed generations with equal scientific
outputs must yield the same Result4 and independently selectable producer-specific Artifacts.

FP-RUNTIME-001 derives exact installed-byte/isolation tests and rejects ambient fallback. Arrow issue 47666 motivates checking
frozen physical bytes and bounded metadata before Parquet decoding; exception handling after native decoding is not integrity
proof. No upstream patch, retry, sleep, timeout enlargement or relaxed quality rule is adopted as publication semantics.

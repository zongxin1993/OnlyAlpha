# Chart native publication worker contract

Constitution Impact: NO. This boundary extends the typed Chart Run and native
publication contracts, not Search Generation Execution V1. It grants no HTTP,
Query, Web, Agent, SIM or LIVE Authority.

## Versioned structural protocol

`ONLYALPHA_CHART_NATIVE_PUBLICATION_V1` names a separate Chart-only contract.
`OnlyChartCalculationNativePublicationProfileV1` fixes Chart origin, Specification3,
JobPlan2, ResultPlan4, ResearchResult4, Artifact schema2 and the existing
Calculation2/Evidence2/readiness1 publication selection. Older Search/E1 hosts do
not advertise or dispatch it. Defining or parsing a profile does not make a host
ready or a worker eligible.

The native request contains only canonical Operation, original reserved Run,
Attempt and Worker IDs, positive Attempt number/Run revision, original Compilation
and Generation fingerprints, and the exact version profile. The Run ID locates
the same original Runtime Work; a separate caller-supplied Work cannot replace it.
Graphs, values, readiness, storage roots, credentials, arbitrary module/function
names and serialized issued capabilities are not request fields. Constructors
and structural parsers reject wrong types, boolean versions/counters, unsupported
versions, missing/unknown fields and malformed canonical identities. The complete
frozen compilation comparison is structural equality, never owning-read issuance.
The Chart-only wire decoder accepts one bounded UTF-8 JSON object followed by LF,
rejects duplicate keys at every depth and non-finite JSON numbers, and applies the
same exact structural parsers. It accepts no bootstrap/configuration fields.
Decoding still neither verifies owning facts nor grants execution permission.

A publication receipt binds the complete original request, Runtime provenance,
frozen Result Plan and Calculation identities, and exact Calculation Result2,
Evidence2, Research Result4 and Artifact2 fingerprints. Result4 may be shared;
Artifact2 is selected by the full `(research_result_fingerprint,
artifact_content_fingerprint)` pair and Evidence2 is separately mandatory.
Receipt comparison is structural, not a native seal or independent verified-load.
The Controller must verify these references through the owning Stores before any
terminal transaction; a self-consistent receipt is not proof of publication.

The separate native handshake carries the exact existing Runtime execution
provenance (Generation, Validation Evidence, Core and Catalog) and version profile.
A parsed handshake is a declaration, not hosted verification, Source readiness,
Attempt ownership or permission to produce a seal. Only a host with the actual
configured owning readers, publishing stores and installed-byte verification may
eventually advertise it. No current host does so.

## Database privilege boundary

Migration `0049_chart_native_publication_permissions` introduces two cluster-scoped
NOLOGIN, non-superuser, non-role-creating privilege groups. The operator owns schema
rollout and deployment login provisioning; migrations contain no passwords and do
not change existing application credentials or deployment topology.

| Group | Allowed now | Forbidden now |
|---|---|---|
| `onlyalpha_chart_input_reader` | SELECT on the exact existing original-input metadata tables and Run/Attempt locators; public-schema USAGE | business INSERT/UPDATE/DELETE, credential values, Integration Drafts, acquisition, role escalation, Run lifecycle mutation |
| `onlyalpha_chart_execution_controller` | No business write or execution-function grant | Claim, Heartbeat, Expiry, Finalize or raw Chart Attempt insertion |

The Source reader reuses existing owning readers. `integration_revision_secret_binding`
contains immutable credential **references** required by the Integration Revision
parser; access to those references grants neither `product_credential` access nor
provider execution. Dataset/Runtime/physical Fact filesystem/network permissions
are separate deployment capabilities. PostgreSQL SELECT permission is not an
issued input, registered native execution context or Artifact publisher.

Existing groups must have the exact safe attributes, inherit no other role, and
have no preexisting owned objects, direct ACLs or default grants in the installing
database, nor shared parameter privileges or other shared-object authority. Native
`pg_shdepend` relations cover all object families, including types and large
objects, rather than a hand-selected catalog list. Groups must have no stored
password; operator-only `pg_authid` visibility is necessary to prove this without
returning password material. A finite password-expiry policy is not an accepted
group attribute (NULL/infinity both mean no expiry). An unsafe/unrelated role fails
migration without sanitization or silent adoption. Deployment principals must themselves be non-owner/non-superuser and
receive no additional broad permissions. An administrator can change guards or
grants; malicious schema-owner/superuser administration is outside the runtime
bypass threat model, not something CHECK/trigger constraints claim to prevent.

The published `0048` Chart Run CHECK accepts only QUEUED0 or direct
CANCELLED1, without execution timestamps/refs. Its `0049` insert/update trigger rejects
any Chart Attempt, including writes through a trusted controller account, until
a separately implemented and verified native execution consumer replaces that
closed boundary through an explicit forward schema evolution. There is no switch,
GUC, token, caller DTO or role membership that enables Claim. Existing Chart
Attempts at migration time are unsupported and fail closed; history is not deleted
to make migration pass. Legacy GENERAL/PRIVATE_STRATEGY execution SQL, ownership,
state transitions and negative Chart capability remain unchanged.

## Rollout and failure semantics

Migration precondition is checksummed history through 0048 and operator role/schema
authority, ownership/write-lock authority over Run/Attempt tables, and permission
to inspect `pg_authid`. Missing operator visibility fails closed; no runtime reader
is granted that visibility. Under the existing migration advisory lock, table
write exclusion is acquired in Run → Attempt order **before** inspecting existing
Chart Attempts and is held through guard installation and ledger COMMIT. A writer
that committed earlier is retained and rejects rollout; a later writer cannot slip
between the history check and installation. Source-history/frontier writes remain
the existing writer transaction, not a new migration rewrite. Group creation,
validation, ACLs, guard DDL and ledger commit are one PostgreSQL transaction under
the existing migration lock. DDL or ledger failure
rolls the whole change back; retry applies the same canonical migration. Existing
Run/Attempt/source/receipt facts are not updated. Published 0001–0048 bytes and
checksums stay immutable.

Schema verifiers with a 0048 reference report AHEAD after rollout, rather than
silently accepting unknown history. Deploy compatible readers/reference assets
together; this is not authorization to migrate/restart the development Runtime.
Rollback means retaining history/readers, stopping incompatible writers, and using
a verified snapshot or forward-fix. Do not drop shared privilege groups underneath
other databases or running consumers.

## Required execution connection before enabling Claim

The controlled installed host must obtain original Source proof through formal
Application owning readers in its own process. Its confidential deployment
bootstrap supplies least-privilege read credentials and approved storage locators,
not caller operation fields, inherited plugin state or test-only `runpy` readers.
It receives no Run/Attempt/receipt/lifecycle mutation credentials. Search/E1's
compute-only bootstrap remains unchanged.

`only_chart_native_input_export` in the Runtime Generation Manager composes the
existing PostgreSQL Operation/Preparation/Compilation/Integration/catalog readers,
the physical ClickHouse reader and the Dataset/Runtime owning readers in the
calling process. Its infrastructure-supplied configuration is separate from the
Chart request. It does not deserialize an issued input or use a test loader.
PostgreSQL admission checks the real authenticated non-owner reader principal,
column/table mutation and extra read privileges, inherited roles, ownership and
callable privileged functions. The ClickHouse credential must have immutable
`readonly=1` (not mutable `readonly=2`); deployment must grant only the physical
Fact SELECT surface. Missing roots or schema reference, unsafe credentials and
unavailable readers fail closed, without provisioning or Source repair.
Effective PostgreSQL checks include PUBLIC grants on restricted PG18 filesystem,
maintenance, replication, configuration and memory-diagnostic functions (all
overloads, including the functions underlying restricted system views), and secret-bearing
`pg_authid.rolpassword`, `pg_user_mapping.umoptions` and
`pg_subscription.subconninfo` columns. Role dependency inspection alone cannot
prove these absent: PUBLIC has no dependency on the admitted login/group.
The trusted `schema_reference_root` is handed to
`OnlyPostgresMarketDataCatalog(migration_root=...)` and its existing exact-ledger
verifier. An installed interpreter therefore needs no repository loader, copied
module, or mutation of its site-packages tree to locate the schema reference.
Changed checksums, missing history and AHEAD/BEHIND remain incompatibility, not
permission to skip schema verification. The default catalog composition is
unchanged for existing consumers.
The Registry's existing lock-file permission is distinct from permission to
append Generation events. Calling this composition is not installed-byte
verification, Host readiness, native producer registration or Attempt permission.

The trusted controller retains operational Authority: complete pre-Claim
Operation/Receipt/Preparation/Pin/Source/physical Dataset/Materialization/Compilation
verification, exact installed-host capability, and original active Work/Generation.
It must hold a bounded Runtime shared lifecycle proof through actual atomic
PostgreSQL Claim COMMIT, without retaining a PG transaction during numerical work.
Selected immutable Result2/Evidence2/Result4/Artifact2 facts are independently
verified before fenced terminal commit. PostgreSQL proves operational relations,
lease and CAS, not external scientific file authenticity. It must not store a
parallel scientific proof Authority or trust a caller hash/session flag.

The Runtime Generation Manager's `only_verify_chart_native_publication` performs
that scientific verified-load independently of the installed producer. It compares
the full original request, original owning non-issuing Source verification, whole frozen Compilation,
live Dataset/Calculation2/Evidence2/Result4 and the explicitly selected Artifact2
pair against the original Registry Manifest/Validation/Core/Catalog. It issues no
native seal and performs no SQL mutation or Work release. Missing live
predecessors refuse current completion even if the offline Artifact is readable.
The operational Attempt/lease/revision proof remains a separate mandatory
Controller responsibility; passing a structural request with nonexistent Attempt
IDs does not satisfy that responsibility.
Source verification repeats after the scientific reads and does not issue a
publication input or native context. It propagates missing/corrupt/unavailable
owning proof and cannot certify absence or replace retained inspection/PG fencing.

Human cancellation serializes its Command, acquires Run table ROW EXCLUSIVE write
intent and the original Run row, and only then writes Admission/history frontier.
The table lock is necessary because T1 takes SHARE: a row's FOR UPDATE alone holds
ROW SHARE and could otherwise upgrade behind a SHARE holder waiting on frontier.
Receipt replay remains read-only; Command conflicts and rollback remain atomic.

Ordinary finalization requires the exact ACTIVE Attempt and valid PG lease.
No-ACTIVE cancellation reconciliation is a distinct read-only semantic-inspection
port under ADR0090; it cannot create an execution Attempt or treat incomplete,
corrupt or unavailable proof as certified absence. Terminal ACK precedes original
Work release, with exact unknown-ACK/release reconciliation and no rebind.

Until this complete connection and its PostgreSQL/installed-host failure seams
exist, parsing these DTOs, acquiring an exact compute-only host or reading original
input still cannot start a Chart Attempt or mark its Run COMPLETED.
Chart Domain lifecycle values and immutable admission validation are likewise not
SQL execution permission. A deployment through 0049 prohibits durable execution
states/Attempts; the forward SQL entry below grants no runtime execution permission.
Current historical readers retain their closed-first fence.

## Narrow operational SQL entry

`0050_chart_native_execution_entry` introduces version-1 Claim and Heartbeat
operations, not a deployed native consumer. It does not grant EXECUTE to PUBLIC,
the Controller group, the reader group or a deployment login. No production
launcher provisions that grant. Test-local operator grants exercise the real
entry without disabling triggers; they are not consumer-readiness evidence.
Finalization, expiry, no-ACTIVE recovery and Work release are not SQL entry points
in this schema. They must be connected and verified before deployment provisioning.

| Actor / Authority | Permitted responsibility | Not granted |
|---|---|---|
| Legacy Worker | Existing GENERAL/PRIVATE_STRATEGY Spec1/2 execution | Chart Claim/Heartbeat/terminal |
| Controller | Independent owning preflight; short SQL transaction and committed ACK | Raw DML, Source issuance, scientific authoring |
| Source reader | Original PG metadata and exact read-only physical inputs | Lifecycle mutation, native seal, credentials |
| Installed Native Host | Exact installed-process Source issuance and native publication, after separate authorization | PG lifecycle mutation or wire-supplied bootstrap |
| Runtime Work owner | Original active Work/G eligibility and shared lifecycle proof | Rebinding released Work from equal fingerprints |
| Scientific owners | Calculation2/Evidence2/Result4/Artifact2 verification and durable ACK | Run state or historical absence inferred from local missing files |
| Web/Agent/SIM/LIVE | Existing contracts | Any new operational Authority |

The SQL executor is a separate NOLOGIN, NOINHERIT, non-superuser role with no
members or inherited roles. It owns only the narrow functions. Runtime principals
cannot SET ROLE to it. The operator temporarily grants membership and schema CREATE
solely to transfer ownership, revoking both before atomic migration COMMIT. Unsafe
preexisting role attributes, memberships, local/shared dependencies or settings
reject migration without sanitization. Other databases' local dependencies remain
unchanged. Schema evolution retains original rows and checksums; DDL/ledger failure
rolls back role creation, grants, guard replacement and constraints together.
Any resulting non-owner EXECUTE ACL from operator function defaults rejects the
transaction, including named-role defaults which PUBLIC revocation and ownership
transfer do not remove. Unrelated operator defaults are never sanitized.

The Run mutation guard and Attempt guard are SECURITY INVOKER: the effective
executor identity comes from a fixed-search-path SECURITY DEFINER entry, not a
guard's owner, caller boolean, GUC, token, temporary table or role membership.
Broad legacy table privileges still cannot claim Chart work. Human queued cancel
and running cancel intent remain separate permitted transitions. Immutable Run
admission fields and terminal Attempt history cannot be rewritten by an entry.

The forward constraint admits QUEUED0, direct CANCELLED1, RUNNING1 and
CANCEL_REQUESTED2, with the Domain's timestamps and no finalized scientific refs.
It admits no execution terminal projection yet. Claim allocates a fresh ACTIVE
Attempt under the original Run row lock, checks contiguous Attempt numbers,
retryable history and budget, and atomically transitions the first QUEUED Run.
Retries retain RUNNING1 and the same immutable specification/Compilation/G.
Heartbeat checks exact Run revision, Attempt/Worker/number, ACTIVE state and lease,
sampling `clock_timestamp()` only after row-lock waits. Lease intervals must be
finite and strictly positive; PG18 interval infinity cannot create unbounded
ownership or an unreadable Attempt. Heartbeat cannot shorten a lease
or renew an expired one. Neither routine acknowledges scientific publication.

SQL checks original Operation/reserved Run, Admission/Receipt, INPUT_READY revision,
consumed reservation, immutable admission/Compilation references, whole exact stored
Compilation JSON and original Work/G references. Application owning readers remain
responsible for canonical nested parsing, hashes, complete preparation/source proof,
installed bytes and filesystem authenticity; SQL does not duplicate those owners.
`OnlyPostgresChartNativeExecutionStore` connects this SQL seam with original Work
proof through actual explicit COMMIT and independent fresh Run/Compilation/Attempt
reads. Lost ACK is observation of that exact Attempt only, never a second Claim.
It is not a scheduler, Host capability check, complete Controller or Work releaser.

### Lock and privilege closure

```text
expensive Source / Compilation / installed-host preflight (no PG writer transaction)
  → original Runtime shared Work proof (no PG row/frontier held while waiting)
  → Run TABLE ROW EXCLUSIVE → Attempt TABLE ROW EXCLUSIVE
  → original Run row (SKIP LOCKED for Claim) → exact Attempt row for Heartbeat
  → original source-history frontier during owning triggers
  → actual PG COMMIT → release shared Work proof → fresh committed ACK
```

Runtime lifecycle writers acquire EX and must never acquire PostgreSQL locks while
holding it. No PG row/frontier is retained during numerical work or while waiting
for a Host/filesystem owner. Human cancellation keeps its Command advisory → Run
write-intent → Run row → Admission/frontier sequence. T1's SHARE table lock precedes
its frontier writes, so operational write intent must precede row/frontier access.
Migration uses Run → Attempt write exclusion under the existing migration advisory
lock and holds it through DDL/ledger COMMIT. Legacy positive execution remains
separated by its unchanged origin/Specification allowlist.

The existing journal trigger callees now qualify their unchanged public owning
tables and function call and fix search_path to pg_catalog. They remain invokers,
not generic privileged journal writers. A caller's pg_temp shadow cannot redirect
the journal of a definer transaction. This applies the failure pattern from
[PostgreSQL CVE-2018-1058](https://www.postgresql.org/support/security/CVE-2018-1058/),
not an upstream permission/retry model. Database relation/lease proof, Runtime
eligibility proof and immutable scientific verified-load remain three distinct
layers; none can stand for the other two.

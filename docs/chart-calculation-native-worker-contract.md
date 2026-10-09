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
Duplicate-key rejection and bounded confidential transport are responsibilities
of a future actual wire decoder; there is no JSON transport entry here.

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

The prior `0048` Chart Run CHECK remains unchanged: only QUEUED0 or direct
CANCELLED1, without execution timestamps/refs. A new insert/update trigger rejects
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

The trusted controller retains operational Authority: complete pre-Claim
Operation/Receipt/Preparation/Pin/Source/physical Dataset/Materialization/Compilation
verification, exact installed-host capability, and original active Work/Generation.
It must hold a bounded Runtime shared lifecycle proof through actual atomic
PostgreSQL Claim COMMIT, without retaining a PG transaction during numerical work.
Selected immutable Result2/Evidence2/Result4/Artifact2 facts are independently
verified before fenced terminal commit. PostgreSQL proves operational relations,
lease and CAS, not external scientific file authenticity. It must not store a
parallel scientific proof Authority or trust a caller hash/session flag.

Ordinary finalization requires the exact ACTIVE Attempt and valid PG lease.
No-ACTIVE cancellation reconciliation is a distinct read-only semantic-inspection
port under ADR0090; it cannot create an execution Attempt or treat incomplete,
corrupt or unavailable proof as certified absence. Terminal ACK precedes original
Work release, with exact unknown-ACK/release reconciliation and no rebind.

Until this complete connection and its PostgreSQL/installed-host failure seams
exist, parsing these DTOs, acquiring an exact compute-only host or reading original
input still cannot start a Chart Attempt or mark its Run COMPLETED.

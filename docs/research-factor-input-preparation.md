# Exact conversational Factor input preparation

This backend Research capability refines ADRs 0116, 0139, 0141, 0145 and 0146. It compiles the already
selected bounded conversational grammar into the existing Product Definition V2 / Graph V1 values.
It does not introduce a second Calculation graph, translate arbitrary Python programs, interpret
Factor arithmetic in Rust, select an executable implementation or grant Research permission.

## Content relation

Compilation takes the candidate, the exact saved Draft selected by Human acceptance, and its exact
published Revision. The owning Product path must obtain these through the existing authoring/proposal
Authority and verify acceptance/ownership/current approval itself. Supplied JSON is not proof of Human
consent. The pure compiler is not a public Command or a substitute for that relation proof.

The backend regenerates readable formula, bounded API V1 source and contracts together using the
existing canonical preview producer. Every Draft content field must match that producer, retaining
the exact already-selected base Revision. The published Revision must equal the authoring owner's
canonical Revision of that Draft, including parent, source/API fingerprints and version annotations.
Missing publication, a valid but different Revision, unseen code, changed hypotheses/contracts or
unsupported grammar is an explicit error. Compilation neither publishes nor silently rebases a Draft.
Names and purpose are validated presentation metadata; changing only them does not change compilation
identity. There is no `latest` lookup or normalization of another accepted source into this one.

## Graph and algorithm ownership

Plain OHLCV leaves bind explicit external Dataset field names. A `lag:p` leaf becomes the exact
`onlyalpha.operator.delay@1` node, and a `mean:p` leaf becomes `onlyalpha.operator.rolling_mean@1`.
Identical declared dependencies share one node. The root retains the selected private Factor ID,
its original stateless API V1 source, nullable decimal inputs, `FACTOR_VALUE` output and numeric
policy. Integer literals and arithmetic remain in that reviewed source, not invented graph nodes.

The Definition V2 metadata materialization matches the frozen existing SDK contracts, including
the operators' Decimal(28) versus private API V1 Decimal(38), quantum, ports and exact warmup text.
An independently SDK-produced vector and regeneration check pin those original Definition/Graph
fingerprints. A changed plugin contract requires explicit review/version handling, not adapting a
golden vector to a conflicting Rust implementation. Actual mathematics stays in the Python algorithm
boundary; these values do not assert that an installed factory supports them.

The compiler reuses the existing Product Graph validator for canonical ordering, exact node/port
references and Feature/Target separation. `delay(p)` requires `p+1` observations, `rolling_mean(p)`
requires `p`; the first supported grammar has parallel raw-field history dependencies, so required
history before the first observation is the maximum dependency requirement minus one. Root pointwise
arithmetic needs no additional history. This is not a general nested rolling-graph readiness rule.
Constant-only Factors bind `close` solely to define their observation axis and require no preceding
history; a constant without an input axis cannot emit one value per observed bar. The reviewed source
still returns the declared constant, independently of the price value.

Preparation identity binds exact Draft, Revision/source/API, original graph/root identities, raw
columns and history requirement under `ONLYALPHA_RESEARCH_FACTOR_PREPARATION_V1`. A graph fingerprint
alone is insufficient: different private source implementations can have identical type/port graphs.
Before execution, the owning admission must rematerialize those exact definitions using the selected
immutable executable closure and verify implementation, source artifact, validation and Generation
bindings. This compiler does not certify static/security validation, Research/TRADING equivalence,
runtime readiness, source access, Dataset availability or scientific quality.

## Explicit input window

The first window planner uses nonnegative UTC event nanoseconds and a fixed bar duration, consistent
with the supported single-instrument Statistics slice. The observation interval is `[start,end)`;
its width must be a positive exact number of bars. Forecast horizon `h` is positive and smaller than
the observation capacity. Calendar/nonuniform bar planning needs its own admitted contract; a fixed
duration here does not certify compatibility with a selected source's calendar/alignment.

Dataset event coverage requested for this Factor is `[start-history*bar,end)`. It includes exactly
the preceding history, without future data beyond the agreed observation end. The first planned
Target is declared close-to-future-close return, so Dataset columns include `close` even for a
constant or volume-only Factor. Target calculation remains a separate Research Evaluation graph;
this requirement does not create a Target Definition, compute returns or feed Target into Feature.

Eligible observation times are strictly before `end-h*bar`; crossing-boundary labels are excluded
as in ADR 0147. The resulting `observation_capacity` and `pair_capacity` are grid capacities, not
actual available rows, complete samples or independent observations. Missingness/quality and actual
statistics are determined later from verified inputs. Boundary overflow/underflow, zero/nonintegral
duration or an impossible horizon fails explicitly; no truncation, clamping, implicit acquisition or
scope widening occurs. Warmup coverage is part of the visible Research proposal requiring the separate
Human authorization before data access/preparation.

The input-window identity binds the exact Factor preparation, Revision, all boundaries, bar spacing,
horizon, columns and capacities under `ONLYALPHA_RESEARCH_FACTOR_INPUT_WINDOW_V1`. It is **not** a
Dataset Snapshot identity, native Source Scope or immutable source proof. Dataset `[start,end)` event
membership and market Source interval-ownership rules must be related explicitly by the materializer;
equal endpoint numbers alone never prove that relation. No DataFrame/query/chart window substitutes
for the owning immutable Dataset, full source lineage and physical proof.

Dataset materialization must preserve exact UTC event timestamps with integer/timedelta arithmetic,
not floating-point `timestamp()*1e9`. The existing Arrow/Domain round-trip contract is the authority;
a Python reference that loses microseconds is a known semantic defect, not a Rust parity target.

## Integration and acceptance

This pure module is an input to the minimum native Dataset/admission flow in the migration program.
It adds no route, alternate database, worker service, model call, Generation activation, Research Run
or publication. The normal Shipping UI must eventually obtain these values from the backend-owned
proposal flow and then separately authorize one Research; pure tests cannot claim that Product closure.
Existing Python authoring/Calculation/Dataset consumers remain until their actual replacement gates
pass. Retain the admitted algorithm SDK rather than treating it as retired backend business code.

Acceptance includes original SDK Graph/Revision vectors, changed valid source and whole-context
substitution, parent binding, presentation-only stability, unique dependency reuse, one-bar boundaries,
explicit Target column requirements, exact forecast exclusion, overflow denial and fresh-process replay.
Only modified modules and direct consumers are verified; existing unrelated results are reused.

## Native immutable Dataset boundary

The backend materializer consumes an exact sealed Source Revision through the existing market-data
Storage owner, after validating the requested Definition, source scope and construction. The first
slice accepts one instrument and provider-native fixed bars with equal window/stride. Source interval
ownership `(s,e]` maps explicitly to Dataset event membership `[s+bar,e+bar)`; grid alignment, warmup,
forecast end and budgets are checked before physical reads. Unsupported construction requires an
explicit future implementation, not scope widening or a latest-revision substitution.

Dataset V2 retains the original 27-column Arrow/Decimal(38,18) schema, length-framed canonical row
content hash, Snapshot fingerprint and materialization-lineage identity. Semantic identity does not
depend on compressed Parquet bytes. Those bytes receive separate physical hashes. Publication uses
protected descriptor-relative paths, a fully synced exclusive staging directory and no-replace
atomic publication. Existing exact content is verified and reused; corrupt or rebound objects are
refused. A crash after publication and before acknowledgement can re-read the same Snapshot and
lineage, without generating another semantic identity. Reads validate schema, row/content identities,
partition bytes, row counts and compressed/logical byte budgets. Native source proof and original
Revision/Manifest/Seal/segment/physical evidence remain in retained provenance.

Exact time conversion uses integer UTC arithmetic. Decimal scale/precision checks use an explicit
38-digit context and reject inexact values, independently of a caller's Decimal context. These are
correctness requirements for both readers, not historical Python defects to reproduce.

## Guarded executable-input preflight and remaining execution gate

The internal preflight retains the existing Generation ledger's shared lifecycle lock, verifies its
hash chain and eligible exact Generation/validation record, and requires the original active
owner-tagged NEW_WORK binding for the same work identity. It never writes a second registry, selects
a new active Generation, binds a missing work identity or releases/retries an uncertain operation.
The hold lasts through the consumer's bounded durable handoff; a portable JSON record is not a hold.

The selected immutable runtime/source artifacts and their physical bytes are checked separately from
the managed algorithm installation. A dedicated one-shot source resolver rematerializes each original
Definition using actual installed registrations and returns their actual implementation records.
It performs static source validation, never Factor observation evaluation, equivalence certification,
Research or trading. The backend requires exact private source, published Revision metadata, retained
Research/TRADING equivalence, provider snapshot and Generation implementation relations, plus the
same verified Dataset and authorized input window. Source/API/operator/implementation substitutions,
missing facts and released/mismatched work bindings fail closed.

Pure Factor adapters and source validation belong to
`packages/backend/python/algorithms/src/onlyalpha_backend_algorithms/sdk/`. The executable source DTO
is an opaque input, not publication or consent proof. The original pure provider-snapshot DTO remains
at its existing source location while legacy consumers still require its single canonical type; the
minimal installed algorithm SDK projects only that DTO and an empty namespace, not Product services.
Retire it after those real consumers migrate, without a second implementation or compatibility alias.
The old Python private Factor execution module is replaced by the algorithm constituent. Authoring
publication/permission, Runtime lifecycle and Research Run business remain outside the minimal SDK.
Artifact wire DTOs live in the gateway-protocol constituent and use canonical primitive JSON without
importing the legacy backend. Existing build/lifecycle consumers declare that protocol dependency;
actual algorithm consumers declare their algorithm dependency. Root `src/` must not depend on the
algorithm worker at runtime. Still-used Python business consumers are not retired merely because a
Rust reader now exists.

`PreparedInputs` is input eligibility, **not Human Research authorization**. It requires the exact
`RESEARCH_RUNTIME` artifact in the existing Generation and its mandatory tested-Core relation, with
native byte identity and the builder's actual executable descriptor. Rust binds the selected executor's
exact distribution version as well as its SHA and protocol; execution and retained Evidence must match
that same version, rather than accepting a caller-supplied label. The managed process checks the
selected Core wheel's real pure SDK resources, including bounded uncompressed metadata, against the
actual installation. This is compatibility for the declared Factor/input/algorithm ABI; it does not
assert whole Python Trading Kernel equivalence. Installation bootstrap and AST/decimal runtime
resources retain their separate exact installation binding.

The observer validates the original nested Generation, event, equivalence and provider/snapshot DTO
relations. Event timestamps use the owning canonical UTC representation before fingerprint checks.
Missing outputs cannot match by both being null; vector identities and canonical snapshot/provider
content are mandatory. UNKNOWN algorithm outcomes preserve the original cancellation/drain owner
and lifecycle hold, rather than becoming unavailable or permitting replacement work.

The owning backend still closes the separate Human Research permission, original Command/Run
identity, Authoring publication/consent, budget, trial/comparison and protected-sample transaction.
Those checks cannot be inferred from a valid Dataset, a matching resolver report or a READY
Generation. No Research endpoint is enabled by this preflight, and technical fixture evidence does
not claim the later Shipping UI/Run closure. Execution must consume the same selected runtime
artifact through its original bounded handoff and retain the required recovery/cancellation gates.

## Native one-run execution boundary

The internal Rust submission owner binds the separately confirmed Study and original Factor approval
to the global Command receipt, existing Novelty Admission and one Run. The grant retains exact prepared
inputs, immutable Dataset, source/revision, runtime, comparison family and trial prefix. Replaying the
same accepted Command observes that original receipt; source withdrawal cannot authorize a new Run.
An unacknowledged submission remains UNKNOWN until its original outcome can be established.

The native time-series profile uses Specification V4, Calculation Result V3, Statistics Result V2 and
Research Result V5. Feature arithmetic runs only in the selected isolated authored-algorithm closure.
Rust owns fixed-grid pairing, close-to-future-close Target returns, forecast exclusion and Statistics.
Target division uses exact decimal/rational inputs and half-even rounding at quantum `0.000000000001`;
it is distinct from the old Target plugin ABI and cannot feed Target values back into Feature.
Result/Artifact readers verify physical and semantic relations and the exact completed Run references;
they do not recompute statistics or silently accept another self-consistent report chain.

Execution reuses the existing Run/Attempt owner, with three attempts, a 120-second lease and 30-second
heartbeats. Semantic publication precedes fenced operational completion and never runs inside a
database transaction. Lost ownership forbids operational finalization. Cancellation recovery waits
until no ACTIVE attempt remains and holds the immutable publication cut through reconciliation:
verified complete evidence wins, certified absence cancels, corruption fails, unavailable proof stays
unresolved. Exhausted RUNNING attempts fail without deleting retained immutable facts or starting a
fourth attempt. A late stale worker may only make the contract's idempotent immutable writes; it
cannot rewrite terminal operational state. UNKNOWN child shutdown retains the original drain owner.

These internal capabilities and controlled authority tests are not the Shipping Web acceptance path.
The Product composition must expose separate Human environment preparation and Research confirmation,
observation/cancellation and report through the ordinary UI before conversational Research closure.

## Product preparation and deployment owners

`factor-study-grants`, `factor-studies` and `factor-study-context` retain the distinction between a
Human registration permission and an Agent's unadmitted recommendation. The Human-only
`factor-study-preparation-context` and `factor-study-preparations` APIs expose the selected inputs,
original preparation operations, explicit resume/cancellation and separate Research confirmation.
They compose the existing Authoring, Generation journal, Source acquisition, Dataset, Novelty and
global Command owners; they do not create another Run, queue, registry or scientific assessment.
The actual Run and its cancellation remain under `research/runs/{run_id}`.

The deployment owner initializes the complete fresh Research namespace atomically through the
existing `initialize-deployment` entry and an explicitly selected native backend. Owner profile
`ONLYALPHA_FACTOR_RESEARCH_OWNER_PROFILE_V1` binds the seven file Source families to their five
physical owners, the four existing PostgreSQL families and exact policy `onlyalpha.factor-research@1`.
Its rules retain the existing ADMIT/REUSE/SUPPRESS/REVIEW/FAIL_CLOSED meanings. A fixture policy does
not grant installation authority. Ordinary startup and Product preparation only open and verify
this profile; missing roots, locks, policy or history cannot be repaired into an empty experiment
history. Reentry verifies the same complete semantic-store ID before binding the existing database.

Run status, original receipt recovery and Human cancellation consume the original committed Run
grant and operational facts; they must remain available independently of current Agent/Source
availability. A complete historical Decision explanation additionally reads the original retained
Novelty Group/witness and original cuts. Missing historical proof is explicitly unavailable, not a
replacement current projection, a scientific failure or certified absence. Original numeric artifacts
remain immutable. Neither operational completion nor a readable metric alone is Qualification.

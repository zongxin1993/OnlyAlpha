# ADR 0123: Agent Orchestration Authority and Model/Tool Provenance Contract

- Status: Accepted
- Date: 2026-09-08 (amended 2026-09-10 for Agent Launch Tool Result identity closure)
- Decision maker: repository owner through the B3.4.0 design authorization
- Related: ADR 0091, 0103, 0108, 0118, 0119, 0120, 0121, 0122

## Context

OnlyAlpha already exposes Product API v2 operations for Calculation/Dataset/Universe/Statistics discovery, Research Definition
resolution, Research Run submission/query, and exact Research Artifact, Candidate, Statistics, and scientific-series queries. ADR
0120 records deterministic, human, and model-assisted Search decision provenance. ADR 0121 owns deterministic Symbolic Search, and
ADR 0122 owns deterministic Evidence-driven Parameter Search and its recovery path.

Those authorities do not yet define how a probabilistic model may choose research direction, which model and tool occurrences must
be durable before they cause work, how a crash with an unknown model outcome behaves, or which narrow Product API is needed by an
independently deployable Agent Orchestrator. The current Product API also exposes no Search operations and its discovery projections
do not prove one exact Catalog Generation context seen by a model.

The missing contract must let a model influence research direction without making the model or Agent a second Catalog, Search,
Research, Evidence, Qualification, Admission, Promotion, Strategy, or LIVE Authority.

The permanent relationship is:

```text
Agent proposes and orchestrates.
OnlyAlpha proves and executes.
```

The replay target is not equivalent model generation. It is:

```text
same recorded Model Call Result
+ same exact Tool Results
+ same immutable Agent Context
+ same Agent Workflow implementation
= same downstream OnlyAlpha command/proposal
```

## Decision

### Scope and authority boundary

OnlyAlpha introduces a stable Agent Orchestration Provenance contract. It owns only immutable Research Brief, Session, model-call,
tool-call, Agent decision, and Agent-to-child-Experiment launch provenance. It does not own the facts produced by any referenced
Product API operation.

The formal flow is:

```text
Probabilistic Model Decision
        ↓ immutable recorded Model Call Result
strict structured validation
        ↓ deterministic Agent Workflow transformation
durable Agent Decision and Tool Call Plan
        ↓ versioned OnlyAlpha Product API
deterministic Search / Research
        ↓
authoritative Evidence
```

An Agent explanation is commentary. Natural-language prose, confidence, a model-produced number, or a model's hidden reasoning never
authorizes formal work and never becomes Research truth.

### Identity domains

The following identities are permanently distinct:

```text
Agent Research Brief
!= Agent Session
!= Agent Model Call
!= Agent Tool Call
!= Agent Decision
!= Agent Experiment Launch
!= Search Experiment
!= Search Iteration
!= Search Proposal
!= Candidate
!= Calculation
!= Research Run
!= Research Result
!= Qualification Decision
!= Factor
!= StrategyRevision
```

References connect identities; they never transfer identity or Authority. In particular:

- a Model Call Result is not an Agent Decision;
- an Agent Decision is not an ADR 0120 Search Iteration decision;
- an Agent Experiment Launch Record is not a Search Experiment;
- a Search Proposal is not a Candidate or Calculation;
- a Next Experiment Proposal is not an executable command and not a child Experiment;
- a Session completion projection is not a mutable workflow truth.

All new immutable objects use the existing canonical JSON and lower-case SHA-256 conventions. Identity includes every
decision-affecting semantic field and excludes wall-clock time, host, PID, path, HTTP metadata, display state, logs, secret material,
and operational cost telemetry.

#### Amendment: typed exact Authority locators (2026-09-11)

The SHA-256 convention above governs immutable Agent fact fingerprints; it does not redefine every owning Authority's locator domain.
An Agent exact reference binds the referenced Authority's canonical typed locator. Initial admitted locator kinds are exactly
`SHA256` and `UUID4`. Reference kind, reference schema version, locator kind, and canonical locator value all participate in the
serialized reference and therefore in every containing new Agent fact's identity.

Historical `OnlyAgentContextReferenceV1` remains the immutable three-field SHA-only representation. Its bytes, fingerprints, parsing,
and meaning are unchanged. New typed references use a discriminated V2 nested representation; they never store a UUID in
`reference_fingerprint` and never rewrite V1 facts. New SHA references may use V2 when required by their owning contract.

`RESEARCH_RUN` accepts only `UUID4` and preserves `OnlyResearchRunId` as its sole canonical entity identity. Other currently admitted
Agent reference kinds remain SHA-owned. A Research Run reference is verified by passing its UUID4 locator to the canonical Research
Run Query Authority and requiring the returned Run ID to equal it. No Run digest, UUID-to-SHA conversion, mapping store, or second Run
identity is introduced.

Research Run mutability does not alter this locator: a later revision is a new observation under a new Tool Call Plan using the same
Run UUID. Each Tool Result preserves its exact validated historical projection and revision/reference bindings; historical validation
does not compare that projection with the current latest Run state.

### Final contract closure: immutable orchestration resource Authority

The first design used workflow, prompt, schema, tool-policy, role-policy, and model-execution-policy fingerprints as bindings but did
not require each fingerprint to resolve exact historical content. A bare digest cannot prove replay. This amendment introduces one
conceptual authority:

```text
Agent Orchestration Immutable Resource Authority
```

It is the sole Authority for every immutable Agent orchestration resource. It does not create one Authority per resource kind and does
not own any Catalog, Dataset, Search, Research, Evidence, Qualification, Admission, Promotion, Strategy, or LIVE fact.

`OnlyAgentOrchestrationResourceV1` is a strict discriminated envelope containing:

```text
schema_version = 1
resource_kind
resource_schema_version
resource_semantic_version
canonical_payload
resource_fingerprint
```

`resource_kind` is exactly one of:

```text
AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST
PROMPT_TEMPLATE
STRUCTURED_OUTPUT_SCHEMA
TOOL_POLICY
ROLE_POLICY
MODEL_EXECUTION_POLICY
```

The Authority computes `resource_fingerprint` from the resource kind, both versions, and complete canonical payload; it never accepts
a caller-trusted digest as proof. Its one typed Store is content-addressed, put-once, canonical-byte verified, and exposes exact commit
and `load_resource_verified(resource_kind, resource_fingerprint)` semantics. A reader requires the expected kind and schema, recomputes
the fingerprint, validates the complete type-specific payload, and returns exact immutable content. Missing content, a kind/schema or
fingerprint mismatch, non-canonical bytes, conflicting content, unsafe path, or unknown version fails closed as
`AGENT_ORCHESTRATION_RESOURCE_MISSING` or `AGENT_ORCHESTRATION_RESOURCE_MISMATCH`.

There is no latest, current, nearest, equivalent, fallback, Store scan, caller-supplied SHA admission, or reconstruction from the
currently installed package. Identical recommit returns `REUSED`; history is never overwritten.

Type-specific payloads freeze:

- `PROMPT_TEMPLATE`: exact canonical template text/bytes, template format/version, declared ordered variables, and rendering semantics,
  sufficient to answer which template a historical Model Call bound without current package code;
- `STRUCTURED_OUTPUT_SCHEMA`: exact canonical strict schema, schema dialect/version, root type, unknown-field rejection, enums, and
  reference-field rules used to validate the historical response;
- `TOOL_POLICY`: complete ordered allowed tool classes, operation constraints, query/command classification, identity requirements,
  and explicit forbidden capabilities;
- `ROLE_POLICY`: exact role identity, responsibility boundary, permitted prompt/schema/model-policy bindings, tool subset, input/output
  contracts, and terminal behavior;
- `MODEL_EXECUTION_POLICY`: exact setting names and semantics, supported/required/absent provider settings, retry rules, no-fallback
  rule, output handling, and secret exclusion;
- `AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST`: the executable resource closure defined below.

Every resource fingerprint already named by Brief, Session, Model Call Plan, Tool Call Plan, or Agent Decision is henceforth an exact
typed reference into this single Authority. A syntactically valid SHA without exact verified resolution is invalid provenance.

### Agent Workflow Implementation Manifest and runtime admission

`OnlyAgentWorkflowImplementationManifestV1` is the payload of the workflow resource and binds:

```text
workflow_id
workflow_semantic_version
source_revision
ordered logical executable/source/package resources with byte SHA-256
distribution/package provenance when applicable
implementation_fingerprint
```

The ordered closure includes every executable resource capable of changing Brief admission, role sequencing, resource resolution,
Model/Tool Plan construction, structured validation, Agent Decision transformation, budget accounting, recovery classification, and
the one-cycle terminal outcome. `implementation_fingerprint` is derived from the complete ordered semantic manifest fields preceding
it—workflow ID/version, source revision, resource closure, and distribution/package provenance—and explicitly excludes the
`implementation_fingerprint` field itself. The outer orchestration `resource_fingerprint` then covers the complete canonical payload,
including that computed implementation fingerprint. Neither fingerprint is an arbitrary constructor argument or a digest of only a
package version.

Historical exact-load and current execution admission are separate:

```text
Session → exact stored historical workflow resource A → historical verification PASS

current runtime derives workflow resource B
B == A → continuation/reproduction eligible
B != A → AGENT_WORKFLOW_RUNTIME_MISMATCH
```

Historical Briefs, Sessions, resources, Plans, Results, Decisions, and observed responses exact-load without importing or comparing the
currently installed workflow. A code upgrade therefore cannot invalidate history. Before current code may continue a Session, rebuild
a missing downstream Decision, reproduce a historical transformation, invoke another Tool, or publish a new Session fact, it derives
its manifest from actual explicit runtime resources and must equal the Session-bound historical manifest in full. A mismatch blocks
execution but does not mutate or invalidate any historical fact.

### Agent Research Brief V1

`OnlyAgentResearchBriefV1` is the immutable, structured entry point. It binds exactly:

```text
schema_version = 1
hypothesis
catalog_generation_fingerprint
dataset_snapshot_fingerprint
evaluation_context_reference
allowed_search_methods
agent_budget
research_brief_fingerprint
```

`hypothesis` is a structured hypothesis value or an exact reference to an existing compatible hypothesis authority, not free-form
chat history. `evaluation_context_reference` names an exact versioned Target/Evaluation contract through its canonical verified
reader. The allowed executable methods are a non-empty subset of exactly:

```text
REUSE_EXISTING
SYMBOLIC_SEARCH
PARAMETER_SEARCH
```

`CAPABILITY_GAP` is a router outcome, not an executable search method. Catalog Generation, Dataset Snapshot, and Evaluation/Target
Context are frozen for the complete Session. Changing any of them requires a new Brief and Session; no `latest`, current, nearest, or
silent mid-Session rebinding is permitted.

The Agent budget is separate from ADR 0120 Search budget:

```text
OnlyAgentBudgetV1:
    model_call_limit: positive integer
    tool_call_limit: positive integer
    child_experiment_limit: exactly 1
```

Consumption is derived from committed Model Call Plans, Tool Call Plans, and Experiment Launch Records. Process-local counters are
not Authority. Provider token counts, latency, and monetary cost may be operational telemetry but are not Research Authority and do
not enter V1 decision identity unless a later policy explicitly makes a bounded setting decision-affecting.

### Agent Session Manifest V1

`OnlyAgentSessionManifestV1` binds:

```text
schema_version = 1
research_brief_fingerprint
agent_workflow_id
agent_workflow_semantic_version
agent_workflow_implementation_fingerprint
agent_workflow_source_revision
workflow_implementation_resource_fingerprint
tool_policy_fingerprint
ordered_role_policy_fingerprints
session_fingerprint
```

The first implementation has one Orchestrator with logical Research Planner, Search Router, Factor Designer, and Evidence Analyst
roles. These roles are not independent Authorities or services. The exact workflow implementation binding is required for
deterministic downstream replay. A package upgrade does not invalidate historical facts, but a different implementation cannot claim
to reproduce or continue a historical Session unless its complete binding matches.

`workflow_implementation_resource_fingerprint` exact-loads one workflow resource whose ID, semantic version, implementation fingerprint,
and source revision must equal the duplicated searchable bindings above; disagreement fails closed. `tool_policy_fingerprint` and every
ordered role-policy fingerprint exact-load the matching typed resource. The Session-level Tool Policy freezes the complete V1 allowlist
and every Model/Tool Call Plan must bind that same exact resource. Session progress and terminal state are derived from its immutable
occurrence facts. A mutable `session.status` field, in-memory conversation, or provider thread is never the sole truth.

### Catalog-first Search Router V1

The Search Router action space is exactly:

```text
REUSE_EXISTING
SYMBOLIC_SEARCH
PARAMETER_SEARCH
CAPABILITY_GAP
```

Semantics are:

- `REUSE_EXISTING`: the exact required registered Calculation/Factor already exists in the bound Catalog Generation;
- `SYMBOLIC_SEARCH`: the hypothesis can be represented with admitted L1/L2 components and an admitted L3 Factor bridge through the
  existing ADR 0121 contract;
- `PARAMETER_SEARCH`: semantic graph structure is fixed and bounded parameter adaptation uses ADR 0122;
- `CAPABILITY_GAP`: the bound Catalog cannot express the hypothesis; the Session records the gap and stops without generating code.

The router cannot relabel an Indicator as a Factor, synthesize Python, refresh or activate a Catalog, select an approximate identity,
or change the internal decision mode of a child Search Experiment. A B3.2 child remains `DETERMINISTIC`; B3.3 remains governed by its
immutable Search Policy and deterministic Feedback Decisions.

### Agent Decision V1

`OnlyAgentDecisionV1` is the sole Agent orchestration-decision occurrence. Its `decision_kind` is exactly one of:

```text
RESEARCH_PLAN
SEARCH_DIRECTIVE
NEXT_EXPERIMENT_PROPOSAL
```

The structured payload schemas are conceptually:

```text
OnlyAgentResearchPlanV1
OnlyAgentSearchDirectiveV1
OnlyAgentNextExperimentProposalV1
```

`OnlyAgentResearchPlanV1` binds the exact Brief, ordered logical role sequence, permitted Router action set, exact Agent budget, and
the expected single-cycle terminal boundary. It is planning provenance, not a Research Specification or execution command.

`OnlyAgentSearchDirectiveV1` binds one exact Router action, the exact Catalog-context projection seen by the decision, and either the
exact reused capability references, the complete child Symbolic/Parameter Search configuration references, or the structured
capability-gap references required by that action. Contradictory or extra action payload fields are invalid.

`OnlyAgentNextExperimentProposalV1` binds the exact completed evaluation path: either the child Search terminal fact or the direct
REUSE Research Run/Result references, plus exact Research Statistics references consumed by the Evidence Analyst,
`OnlyAgentEvidenceObservationV1` categorical observations whose closed code and mandatory supporting Research Statistics references
make no new numeric claim, and one proposed follow-up Brief delta. Free prose and Agent-owned metric values are not formal observation
identity. The delta is advisory data only and cannot mutate
the current Brief or become a command.

Each Decision binds the Session, role, ordinal, exact ordered Model Call Result and Tool Call Result inputs, exact immutable context
references, decision schema/version, structured payload fingerprint, workflow implementation fingerprint, and decision fingerprint.
Unknown fields, unknown enum values, approximate references, or inputs outside the Session fail closed.

`OnlyAgentSearchDirectiveV1` contains one router action and the exact configuration/reference needed by that action. Symbolic and
Parameter actions may configure only a bounded child ADR 0121 or ADR 0122 Experiment whose Catalog, Dataset, and Evaluation bindings
equal the Brief. `REUSE_EXISTING` names an exact admitted capability or exact already-resolved graph from the bound Catalog and proceeds
through normal Research without a Search Experiment. `CAPABILITY_GAP` carries structured missing-capability references and causes no
formal evaluation.

The earlier singleton ADR 0121 mapping for `REUSE_EXISTING` is superseded and rejected. REUSE never constructs a Symbolic Search Space,
Proposal, Enumeration, Iteration, or Search Experiment and never invokes the `SYMBOLIC_SEARCH` tool class. A Brief whose allowed methods
are exactly `{REUSE_EXISTING}` can complete with only Catalog, Definition Resolve, Research Run, and Research Evidence tool permissions.
If the exact capability/graph cannot be verified and the frozen Router semantics permit `CAPABILITY_GAP`, the Session records that
terminal outcome; otherwise it fails closed. It never silently falls through to Symbolic or Parameter Search.

`OnlyAgentNextExperimentProposalV1` is advisory, immutable authoring output. B3.4 V1 persists it and ends the Session. It has no
automatic execution transition, command identity, Search Experiment identity, Qualification effect, Promotion effect, or LIVE
permission.

### Model Call Plan V1

`OnlyAgentModelCallPlanV1` is the sole model-request occurrence Authority and is committed before an external invocation. It binds:

```text
schema_version = 1
agent_session_fingerprint
call_ordinal
logical_role
role_policy_fingerprint
provider_id
model_id
model_version
prompt_template_fingerprint
structured_output_schema_fingerprint
tool_policy_fingerprint
model_execution_policy_fingerprint
response_affecting_settings
ordered_context_references
parent_agent_decision_fingerprint | null
retry_of_plan_fingerprint | null
model_call_plan_fingerprint
```

The role, prompt-template, structured-output-schema, Tool Policy, and model-execution-policy fingerprints must exact-load their matching
typed resources through the Agent Orchestration Immutable Resource Authority before the Plan may be committed or invoked. The role
policy must belong to the Session's ordered role-policy set and all cross-resource bindings must agree. A bare or unresolved fingerprint
fails closed before external I/O.

`response_affecting_settings` is a strict, versioned structure containing every applicable provider setting, including temperature,
top-p, maximum output tokens, provider-supported seed, and any other response-affecting provider option. Unsupported or absent values
are represented explicitly according to the model execution policy. Provider/model fallback is forbidden in V1. A different provider,
model, model version, prompt, output schema, tool policy, execution policy, setting, context, role, ordinal, or retry lineage creates a
different Plan. `retry_of_plan_fingerprint` must name an exact terminal prior Plan occurrence and may not form a cycle.

API keys, tokens, credentials, secret locators, and secret values are never semantic identity or persisted provenance. The invocation
adapter obtains secrets operationally outside the formal record.

### Structured model result and validation

`OnlyAgentModelCallResultV1` is the sole returned structured-output occurrence Authority. It binds:

```text
schema_version = 1
model_call_plan_fingerprint
outcome
structured_output_fingerprint | null
validated_structured_output | null
failure_code | null
response_digest | null
model_call_result_fingerprint
```

`outcome` is exactly `RETURNED`, `FAILED`, `OUTCOME_UNKNOWN`, or `RESPONSE_INVALID`. A `RETURNED` result exists only after the response:

1. parses against the Plan's exact versioned structured-output schema;
2. rejects unknown fields;
3. uses only the allowed action enums;
4. references only identities supplied in and verified for that exact Plan context; and
5. has a canonical output fingerprint matching the persisted payload.

No heuristic extraction from prose, repair prompt, retry-until-valid loop, permissive extra-field mode, or best-effort coercion is
allowed. Invalid responses commit only stable failure classification and non-reversible response digest if useful for audit; arbitrary
prose and hidden reasoning are not formal payload. Formal persistence never contains chain-of-thought, scratchpad, hidden reasoning,
or provider-internal reasoning transcripts.

`RETURNED` requires the validated payload and output fingerprint and forbids a failure code. `FAILED`, `OUTCOME_UNKNOWN`, and
`RESPONSE_INVALID` require their matching stable failure code and forbid a validated payload. A response digest, when present, is an
audit-only digest of otherwise non-authoritative bytes; it cannot authorize replay, parsing, or downstream action.

A Model Call Result must be committed and exact-loaded before any downstream Agent Decision or Tool Call Plan may reference it. The
forbidden order is:

```text
model response → Search/Research execution → persist model fact later
```

### Model UNKNOWN and retry semantics

The required call lifecycle is:

```text
commit Model Call Plan
→ invoke external model
→ strictly validate response
→ commit Model Call Result
→ derive downstream Agent Decision
```

If a committed Plan may have been sent but the exact response is unavailable after crash/restart, recovery commits or resolves the
terminal outcome `OUTCOME_UNKNOWN` with stable failure code `AGENT_MODEL_CALL_OUTCOME_UNKNOWN`. It must not call the model again for
that occurrence and must not infer whether the provider completed it.

A human-authorized or explicitly bounded policy-authorized retry is a new Model Call Plan with a new ordinal and exact
`retry_of_plan_fingerprint` lineage. It is never a mutation or re-use of the unknown occurrence. B3.4 V1 defines no blind automatic
retry and no automatic provider/model fallback.

Historical validity requires no current provider, model, prompt implementation, or Agent package. Historical replay exact-loads the
Plan, recorded Result, exact Tool Results, Brief, Session, and workflow implementation resources, then re-runs only the deterministic
downstream transformation. It never invokes the model again.

### Tool policy and Tool Call Plan V1

Every Session binds an exact allowlist policy. B3.4 V1 permits only these tool classes:

```text
EXACT_CATALOG_CONTEXT_QUERY
RESEARCH_DEFINITION_RESOLVE
RESEARCH_RUN_SUBMIT
RESEARCH_RUN_QUERY
RESEARCH_EVIDENCE_QUERY
SYMBOLIC_SEARCH
PARAMETER_SEARCH
SEARCH_QUERY
```

It explicitly forbids:

```text
SHELL
PYTHON_EXEC
ARBITRARY_FILESYSTEM
DIRECT_DATABASE
ARBITRARY_HTTP
GIT
PACKAGE_INSTALL
BROKER
LIVE
PROMOTION
ASSET_ADMISSION
```

`OnlyAgentToolCallPlanV1` is the sole tool-invocation occurrence Authority. It must be committed before every Agent-visible invocation,
including exact queries, pure resolve calls, Search commands, Research commands, and Evidence queries. Read-only I/O is not exempt. It
binds:

```text
schema_version = 1
agent_session_fingerprint
tool_call_ordinal
authorizing_agent_decision_fingerprint
tool_class
product_api_major
product_api_contract_fingerprint
operation_identity
canonical_validated_request
canonical_request_fingerprint
exact_identity_inputs
product_command_id_or_idempotency_key | null
tool_policy_fingerprint
tool_call_plan_fingerprint
```

`canonical_validated_request` or an exact immutable request-object reference preserves enough content to reconstruct the identical
request; its complete canonical bytes must match `canonical_request_fingerprint`. The Plan's Tool Policy fingerprint exact-loads the
Session-bound Tool Policy resource, admits the tool class and operation, and verifies the query/command classification before commit.
`exact_identity_inputs` is a strictly discriminated union of historical V1 SHA references and new V2 typed-locator references. The
outer Tool Call Plan V1 format remains unchanged; historical V1 nested payloads produce byte-identical Plan identities.

`operation_identity` is a stable Product API operation identity. A Tool Plan can address only the canonical versioned Product API;
it cannot contain a database operation, Store path, internal Python callable, Engine object, Worker lease, arbitrary URL, shell, or
Broker credential. Command operations must freeze the owning Product API's required command/idempotency identity before dispatch.

The universal occurrence order is:

```text
commit Tool Call Plan
→ invoke exact Product API operation
→ validate exact response
→ commit Tool Call Result
```

No response may enter a Model Call context or Agent Decision unless this complete occurrence chain exists. `tool_call_limit` counts all
committed Tool Call Plans, Query and Command alike. Re-executing the same eligible Plan during type-specific recovery is the same
occurrence and consumes no second Tool budget unit; a genuinely new Plan consumes one.

### Tool Call Result V1 and Product-command recovery

`OnlyAgentToolCallResultV1` binds:

```text
schema_version = 1
tool_call_plan_fingerprint
outcome
observed_response_storage_kind | null
canonical_validated_response | null
exact_immutable_response_reference | null
canonical_response_fingerprint | null
owning_authority_references
failure_code | null
tool_call_result_fingerprint
```

Tool Result outcome is exactly `SUCCEEDED`, `FAILED`, or `RESULT_INVALID`. `SUCCEEDED` requires either the complete canonical validated
response or an exact immutable response-object reference, never both; `observed_response_storage_kind` discriminates that one-of choice.
It also requires the matching canonical response fingerprint and the operation's complete exact owning-authority references. The Result
reader exact-loads the chosen content and recomputes and verifies the response fingerprint before use. Failure/invalid
outcomes require the matching stable failure and cannot authorize a downstream Decision. An ambiguous command transport outcome remains
an unresolved Plan while reconciliation uses its same Product Command identity; it is not converted into a false terminal Result.
The two reference-bearing Result fields use the same strictly discriminated V1/V2 nested union; this evolution does not reinterpret or
rewrite any historical Tool Result V1 payload.

The Result preserves the exact historical response projection that entered a later Model Call or Agent Decision, including exact
receipt/resource/revision identities returned by the owning API. For a response backed by mutable operational state, this is the
validated commit-time projection and its exact revision, receipt, or immutable owning reference; historical loading verifies the
stored projection and those references and never compares it blindly with the owning API's latest mutable projection.

This projection is occurrence provenance, not a second Catalog, Search, Research, Evidence, Qualification, or Run Authority. It does
not silently copy an owning ledger or metric into Agent ownership. Exact references remain governed by their canonical readers, and
the response identities must agree with the Tool Plan and owning Product API. Invalid, ambiguous, missing, corrupt, mismatched, or
policy-disallowed results fail closed as `AGENT_TOOL_RESULT_INVALID` or `AGENT_POLICY_VIOLATION`.

Recovery is frozen by occurrence type:

1. A probabilistic Model Plan with unknown outcome is terminal `AGENT_MODEL_CALL_OUTCOME_UNKNOWN`; retry requires a new Model Plan and
   is not historical replay.
2. An exact immutable, side-effect-free query with no terminal Result may re-execute the same Tool Plan and byte-identical validated
   request. It remains one occurrence, consumes no additional Tool budget, and must converge on the same exact-addressed authority
   content. A query whose contract can observe changing state cannot use same-Plan replay; ambiguity fails closed, and any later fresh
   observation requires a new Tool Plan.
3. An idempotent command with an ambiguous transport outcome reuses the same Tool Plan and the same Product Command ID/idempotency key
   to query or replay the owning API's idempotent admission path. This reconciles one occurrence and never authorizes a new work identity.

Conflicting response, receipt, or resource identity fails closed. No process-local assumption, blind retry, or fabricated prior result
is permitted.

### Agent Session and optional child Search Experiment

An Agent Session chooses exactly one mutually exclusive Router path. `SYMBOLIC_SEARCH` or `PARAMETER_SEARCH` may launch at most one
child Search Experiment in V1. `REUSE_EXISTING` launches none and instead performs one direct normal Research evaluation through the
existing Product API. `CAPABILITY_GAP` launches and evaluates nothing. Invalid model/tool result, policy violation, or exhausted budget
terminates fail closed without pretending the cycle completed. Before any Search launch or direct Research submission, the Model
Result, Agent Search Directive, and corresponding Tool Call Plan are durable.

`OnlyAgentExperimentLaunchRecordV1` binds:

```text
schema_version = 1
agent_session_fingerprint
agent_decision_fingerprint
tool_call_result_fingerprint
child_search_experiment_fingerprint
experiment_launch_record_fingerprint
```

The Launch Record exists only for an actual Symbolic or Parameter child Search and is the exclusive Agent-to-child lineage Authority.
`tool_call_result_fingerprint` is the exact successful Tool Call Result occurrence whose verified owning-Authority response proves the
child Search Experiment identity. A Tool Call Plan records intent only and is insufficient to prove that the child exists. Historical
Launch verification therefore exact-loads the Result, requires `outcome = SUCCEEDED`, exact-loads its Plan, verifies that the Plan was
authorized by the bound Search Directive, and requires the Result's owning Search reference to equal
`child_search_experiment_fingerprint`.
It neither changes nor enters the child Search Experiment's own identity. Agent Decision, Model Call, and Tool Call fingerprints must
not be injected into B3.2/B3.3 internal Plan, Feedback Decision, algorithm, Proposal, or decision-input/tool-result context. The child
preserves its own Search hypothesis, Search Space, Evaluation, Catalog, Dataset, algorithm, budget, and internal decision Authority.

REUSE has no Launch Record and no new direct-Research launch Authority. Its durable causality is:

```text
Agent Decision
→ Tool Call Plan(RESEARCH_RUN_SUBMIT, exact Specification, Product Command ID/idempotency key)
→ Tool Call Result(exact receipt/Run references)
→ exact Research Run/Result/Evidence references
```

Correct authority direction is:

```text
Agent Decision → chooses/configures one child Search Experiment
ADR 0121/0122 → own deterministic internal Proposal/Feedback/Iteration semantics
```

The Agent cannot make a B3.2 Experiment `MODEL_ASSISTED`, change a B3.3 Feedback Decision, inject a model score into an algorithm, or
replace an ADR 0120 Plan/Result occurrence.

For B3.2, every child Plan continues to have no parent Result, no decision-input context, no tool-result context, and
`decision_output_fingerprint == proposal_fingerprint` exactly as ADR 0121 requires. For B3.3, Plan decision inputs and Feedback Decision
inputs remain only the exact durable Result/Evidence prefix admitted by ADR 0122. Agent provenance is never an internal Search input.

### Immutable persistence contract

Every orchestration resource, Brief, Session Manifest, Model Call Plan/Result, Tool Call Plan/Result, Agent Decision, and applicable
Experiment Launch Record is canonical, content-addressed, put-once, exact-load verified, and append-only. Identical recommit returns
`REUSED`; different content under an occupied identity, a second different terminal Result for one Plan, a conflicting ordinal, unsafe
path, non-canonical bytes, unknown schema, or fingerprint mismatch fails closed and never overwrites history.

One Model Call Plan has at most one terminal Model Call Result. One Tool Call Plan has at most one terminal Tool Call Result. Session
model/tool/decision ordinals are contiguous per occurrence kind, and recovery derives the next ordinal from the verified immutable
prefix. Stores expose no update, delete/recreate, latest, nearest, fuzzy, best, mutable cursor, or general conversation-memory API.

### One-cycle B3.4 V1

The complete successful V1 cycle follows exactly one bounded formal evaluation path:

```text
Structured Research Brief
→ Research Planner
→ Catalog-first Search Router
→ Factor Designer
→ exactly one of:
   REUSE_EXISTING: zero child Search Experiments + one direct Research evaluation
   SYMBOLIC_SEARCH: one bounded ADR 0121 child Search Experiment
   PARAMETER_SEARCH: one bounded ADR 0122 child Search Experiment
→ authoritative Evidence
→ Evidence Analyst
→ persisted Next Experiment Proposal
→ Session COMPLETE
```

The three successful branches are mutually exclusive as derived from the durable Router Decision, Tool Plans/Results, optional Launch
Record, and owning Search/Research facts. A child Experiment uses its own ADR 0120 Search budget. The Session's separate
`child_experiment_limit = 1` bounds only the Symbolic/Parameter branches and remains zero-consumed for REUSE. The Next Experiment
Proposal is not automatically executed. Continuing research requires a new explicitly admitted Session/Brief occurrence under a future
contract; V1 has no autonomous loop.

Tool-class and Product-operation permission is only a coarse gate. Before a Tool Plan is committed, the exact canonical request and its
identity-reference closure must additionally be verified against the authorizing Decision's immutable semantic scope and, for an
advance/reconcile or mutable observation, the owning Search/Research Authority's exact current projection. The reducer knows the Agent
grammar but never derives Search terminal/frontier state or Research Run progress from Tool ordinals. It composes those owning projections
into one transient next action; it does not persist a cursor or copy domain state.

`AGENT_CAPABILITY_GAP` is the one Router-defined pre-launch terminal exception. It persists the structured `CAPABILITY_GAP` Decision,
creates no Tool Call Plan for formal work and no Launch Record, and terminates the Session fail closed. It is not `Session COMPLETE`,
does not satisfy the successful-cycle gate, and cannot generate code. Other invalid/policy/budget failures likewise terminate before
launch and never consume or fabricate a child identity.

### Evidence Analyst boundary

The Evidence Analyst may consume only exact Product API projections of:

```text
Research Result
Research Statistics
Search terminal Result/STOP
Qualification Decision, if formally available
```

It may summarize and propose. It may not download raw Dataset data to recompute IC, RankIC, Sharpe, coverage, stability, correlation,
or any other official metric; invent substitute metrics; copy metrics into an Agent truth store; declare Qualification PASS/FAIL;
admit a Factor; promote a Strategy; or authorize LIVE. Scientific values remain owned by Research Statistics, Evidence membership by
Research Result, and qualification outcomes by QualificationDecision.

### Authority matrix

| Fact | Sole Authority |
|---|---|
| Structured Research Brief | Agent Research Brief |
| Agent orchestration identity/configuration | Agent Session Manifest |
| Model request occurrence | Agent Model Call Plan |
| Model returned validated structured output | Agent Model Call Result |
| Tool invocation occurrence | Agent Tool Call Plan |
| Tool exact result/reference | Agent Tool Call Result |
| Agent orchestration decision | Agent Decision provenance |
| Immutable workflow/prompt/schema/policy resources | Agent Orchestration Immutable Resource Authority |
| Agent-to-Search launch linkage, when a Search child exists | Agent Experiment Launch Record |
| Search hypothesis/iteration/proposal provenance | ADR 0120 Search Provenance |
| Symbolic Search semantics and ordered output | ADR 0121 |
| Parameter adaptive Search semantics and STOP | ADR 0122 |
| Catalog contents | Catalog Generation |
| Dataset | Dataset Snapshot |
| Candidate identity | Calculation / Research Resolver |
| Research Run identity, admission, and state | Research Product Command / Run Authority |
| Scientific numeric facts | Research Statistics |
| Evidence membership | Research Result |
| Qualification PASS/FAIL | QualificationDecision |
| Factor Admission | Quant Asset Admission |
| Promotion | Promotion Authority |
| LIVE activation/change/material risk authorization | Explicit Human LIVE Authority |

No Agent fact changes the meaning or content of a referenced Authority. There is no REUSE Authority: REUSE is a Router action whose
direct Research work and results remain owned by the existing Research Product Command, Run, Result, and Statistics authorities. The
orchestration resource Authority owns only immutable orchestration resources and no Product fact.

### Exact Catalog Context projection

A model-assisted decision must prove exactly which Catalog context it saw. A future
`OnlyExactCatalogContextProjectionV1` is a verified, immutable-response projection over existing Authorities and contains:

```text
schema_version = 1
catalog_generation_fingerprint
ordered_calculation_capabilities
ordered_registered_universes, when applicable
ordered_dataset_field_contracts
ordered_statistics_capabilities
projection_schema_fingerprint
projection_fingerprint
```

The query requires an exact `catalog_generation_fingerprint`. The server exact-loads that Catalog Generation and reconstructs every
projected capability through existing registries/contracts. `projection_fingerprint` canonically covers the complete ordered response;
`projection_schema_fingerprint` binds its versioned schema. The projection is not a second Catalog, Dataset-field, Universe, or
Statistics Authority. It has no current/latest fallback and cannot silently use the process's active generation for a historical query.

The current discovery routes remain useful human/current-context projections but are insufficient as historical model provenance
because they neither accept an exact Catalog Generation identity nor return one complete projection fingerprint.

### Existing Product API surfaces and missing Search surface

The existing Product API v2 surfaces to reuse are:

```text
Catalog / Discovery Query
Research Definition Resolve
Research Run Submit
Research Run Query
Research Artifact / Candidate / Statistics / Scientific Series Query
Qualification Decision Query, when needed
```

The missing surface is a Product adapter over existing Search authorities. It must not introduce an Agent-specific Search engine,
Research runtime, Store, Candidate, or result identity.

### Future Product API design

The table freezes semantic operations, not HTTP paths or DTO implementation. `B3.4.1` denotes Search/API foundation;
`B3.4.2` denotes Agent provenance/application services; `B3.4.3` denotes the independently deployable Orchestrator MVP. None is
implemented by this decision.

| Operation | Kind / current state | Owning Authority | Exact identity/reference inputs | Output identity/reference | Idempotency | Failure and recovery | Future phase |
|---|---|---|---|---|---|---|---|
| Exact Catalog Context Query | Query / missing | Existing Catalog Generation plus existing capability authorities; projection owns no source fact | exact Catalog Generation fingerprint and projection schema version | exact generation plus ordered verified projection and projection fingerprint | same exact inputs return byte-equivalent canonical projection | missing/corrupt/mismatched generation or capability fails closed; re-query exact generation, never latest | B3.4.1 |
| Research Definition Resolve | Command-like pure resolve / existing | Existing Research Definition/Specification Resolver | exact authoring Definition and frozen Dataset/Catalog-relevant references | resolved Definition, exact Specification and Candidate fingerprints | deterministic same input; creates no Run | schema/semantic/reference failure is final; correct input creates a new request | existing, reused in B3.4.3 |
| Research Run Submit | Command / existing | Existing Research Product Command / Run Authority | UUID4 Idempotency-Key plus exact resolved Research Specification and required execution bindings | durable command receipt and exact canonical Run ID/reference | same key plus same canonical intent converges; conflicting intent fails closed | reconcile/query or replay admission with the same key; never create a second Run identity | existing, required by REUSE in B3.4.3 |
| Symbolic Search Submit | Command / missing | ADR 0120 Experiment plus ADR 0121 Space/Evaluation/Algorithm/Enumeration authorities | Product Command ID, exact Brief-derived Catalog/Dataset/Evaluation, Search Space, algorithm and Search budgets, deterministic decision binding | Product receipt and exact Search Experiment fingerprint | same command ID plus same canonical intent converges; conflicting intent fails closed | reconcile receipt/Experiment by same command ID; no duplicate Experiment or Agent-specific store | B3.4.1 |
| Parameter Search Submit | Command / missing | ADR 0120 Experiment plus ADR 0122 Space/Policy/Algorithm authorities | Product Command ID, exact Brief-derived Catalog/Dataset/Evaluation, Search Space, Search Policy, algorithm and budgets | Product receipt and exact Search Experiment fingerprint | same command ID plus same canonical intent converges; conflict fails closed | reconcile receipt/Experiment by same command ID; no duplicate Experiment | B3.4.1 |
| Search Advance/Reconcile | Command / missing | ADR 0121 execution or ADR 0122 Controller plus existing Product Command/Research Run authorities | Product Command ID, exact Experiment fingerprint, expected durable frontier/ledger references and requested bounded action | receipt plus exact created/reused Plan, Result, Feedback Decision, STOP, or owning Run references | expected-frontier CAS and same command ID/intent converge; stale/conflicting frontier fails | reconstruct eligibility from exact durable authorities; reconcile existing Run receipt; never blind resubmit or skip barrier | B3.4.1 |
| Search Experiment Query | Query / missing | ADR 0120 Search Provenance with method-specific authorities | exact Search Experiment fingerprint | verified Experiment manifest and exact method-specific authority references | exact-addressed read | missing/corrupt/mismatched facts fail closed; fresh process exact-loads without current/latest selection | B3.4.1 |
| Search Iteration Ledger Query | Query / missing | ADR 0120 Plans/Results; ADR 0121 enumeration or ADR 0122 feedback occurrence | exact Search Experiment fingerprint and versioned exact cursor, if paged | ordered exact Plan/Result references and method occurrence references | stable ordering and canonical cursor | gap, duplicate, corruption, ambiguous terminal state, or cursor mismatch fails closed; rebuild only from durable facts | B3.4.1 |
| Search Terminal Decision/STOP Query | Query / missing | ADR 0121 terminal completion facts or ADR 0122 durable Feedback STOP | exact Search Experiment fingerprint | exact Enumeration completion/terminal Result or Feedback Decision/STOP fingerprint and reason | exact-addressed read | absence means non-terminal, not success; mismatch/corruption fails closed; reconcile through Search Advance | B3.4.1 |
| Research Run Query | Query / existing | Research Run operational Authority | exact canonical Run ID | Run state and exact Result/Artifact/execution-evidence references when available | exact read; list cursor remains versioned | missing/conflicting/corrupt Run fails closed; owning Run recovery/reconciliation applies | existing, reused in B3.4.3 |
| Research Evidence Query | Query / existing | Research Result, Artifact, and Research Statistics authorities | exact Research Result/Artifact locator and exact Candidate/Statistics/series references | verified Artifact summary, Candidate, Statistics, and scientific Evidence projections | exact-addressed read and deterministic page cursor | missing/corrupt/unsupported Evidence fails closed; projection may be retried but never recomputed by Agent | existing, reused in B3.4.3 |

Commands must return only after their durable owning intent/receipt boundary. HTTP transport owns no Search transition. Advance does not
mean an Agent can mutate a ledger; it asks the canonical method controller to perform the one transition admitted by exact current
facts. Query operations expose exact existing Authorities and no mutable generic Search status.

The REUSE branch uses `Exact Catalog Context Query → Research Definition Resolve → Research Run Submit → Research Run Query → Research
Evidence Query`; only the first exact historical Catalog projection is a future B3.4.1 surface, while the remaining Product operations
already exist. REUSE does not require or permit `Symbolic Search Submit`. Symbolic and Parameter branches alone use their corresponding
Search submission and launch linkage.

### Product API and security boundary

The future Agent consumes only the versioned Product API. It must not directly access:

```text
PostgreSQL
semantic or Search JSON Stores
Parquet paths
Scheduler leases
Worker internals
Trading Kernel mutable managers
Broker credentials
```

Its authorization surface excludes LIVE activation, LIVE strategy change, material LIVE risk authorization, Promotion, Asset
Admission, direct database mutation, and arbitrary command execution. Authentication/RBAC mechanics are future infrastructure work,
but an implementation that cannot express this least-privilege surface must fail closed rather than broaden Agent authority.

### Repository placement

Future stable, market-agnostic Agent provenance values, verification protocols, and application-facing ports belong at the nearest
accepted Core boundary, expected as:

```text
src/onlyalpha/research/agent/
```

The independently buildable, versioned, deployable high-change Orchestrator belongs at:

```text
packages/onlyalpha-agent-orchestrator/
```

Concrete model provider SDK integrations belong behind the Orchestrator's provider adapter boundary. They do not belong in stable Core
and are not OnlyAlpha market/provider Plugins. If later split into independently deployable components, each must follow the component
naming rule and a separately accepted boundary decision. No path is created by B3.4.0.

### Stable workflow failure taxonomy

B3.4 workflow failures are:

```text
AGENT_ORCHESTRATION_RESOURCE_MISSING
AGENT_ORCHESTRATION_RESOURCE_MISMATCH
AGENT_WORKFLOW_RUNTIME_MISMATCH
AGENT_MODEL_CALL_FAILED
AGENT_MODEL_CALL_OUTCOME_UNKNOWN
AGENT_MODEL_RESPONSE_INVALID
AGENT_TOOL_CALL_FAILED
AGENT_TOOL_RESULT_INVALID
AGENT_CAPABILITY_GAP
AGENT_SEARCH_FAILED
AGENT_EVIDENCE_UNAVAILABLE
AGENT_BUDGET_EXHAUSTED
AGENT_POLICY_VIOLATION
```

They classify workflow outcomes only and do not replace owning API/domain error codes. Free-form diagnostics are non-authoritative and
excluded from semantic identity. Unknown codes, contradictory outcome/code combinations, and unsupported schema versions fail closed.

### Recovery and deterministic continuation

Fresh-process recovery derives the next legal action from exact durable facts:

```text
Research Brief + Session Manifest
+ exact immutable orchestration resources
+ committed Model Call Plans/Results
+ committed Tool Call Plans/Results
+ Agent Decisions
+ optional Experiment Launch Record
+ exact direct Research or child Search/Research facts
→ one legal next action or terminal failure
```

Rules:

1. Historical verification exact-loads the Session-bound workflow, prompt, schema, Tool, Role, and model-policy resources without
   importing or comparing current code. Before continuation or deterministic reproduction, the current runtime must derive and pass
   exact workflow-manifest admission; mismatch is `AGENT_WORKFLOW_RUNTIME_MISMATCH`.
2. A Model Plan without a known exact response terminates as `AGENT_MODEL_CALL_OUTCOME_UNKNOWN`; historical replay never re-calls the
   model. A retry, if a later contract permits one, is a new Model Plan.
3. A valid Result without its downstream Decision permits deterministic Decision reconstruction only after runtime admission against
   the exact historical workflow implementation and exact resource closure.
4. An eligible exact immutable, side-effect-free query without a Result may re-execute the same Tool Plan and request as one occurrence;
   a non-immutable query ambiguity fails closed and a later observation requires a new Tool Plan.
5. A durable idempotent-command Tool Plan with ambiguous response reconciles the same owning Product Command identity/idempotency key.
6. On Symbolic/Parameter paths, a Tool Result without a Launch Record may reconstruct the exact launch linkage only after verifying the
   child Experiment identity. An existing Launch Record consumes the sole child budget; restart cannot launch another child.
7. On REUSE, absence of a Launch Record is required. Recovery follows the exact Research submit receipt, Run, Result, and Evidence
   facts; it must not create a Search Experiment or a new Research command identity.
8. Search and Research recovery remain owned by ADR 0121/0122 and existing Product Command, Run, and Attempt authorities.
9. A completed Evidence input without a Next Experiment Proposal may deterministically reconstruct that proposal from exact inputs;
   it may not execute it.
10. Missing, conflicting, corrupt, unsupported, resource-mismatched, or runtime-mismatched facts fail closed; recovery never guesses.

### Compatibility with ADR 0120, 0121, and 0122

ADR 0120 remains the sole Search Experiment/Iteration occurrence provenance Authority. Its `MODEL_ASSISTED` vocabulary remains valid
for methods that truly use a model internally, but an Agent-selected B3.2/B3.3 child does not thereby become model-assisted. Agent model
facts remain exclusively in Agent provenance and the Launch Record; they are not copied into child Search decision context.

ADR 0121 retains deterministic enumeration, exact Catalog/Evaluation/Algorithm closure, Proposal reconstruction, ordered output,
contiguous ledger, and historical/runtime separation. No model output changes its order or candidate meaning.

ADR 0122 retains immutable Search Policy, deterministic Feedback Decision, Research Evidence reader, Product Command identity, durable
budget accounting, and STOP Authority. Agent commentary and model scores are not algorithm inputs.

This closure changes neither ADR 0121 nor ADR 0122. In particular, direct REUSE Research is not an amendment to either Search method.
No existing implementation schema, identity, Store, Product route, or OpenAPI document changes in B3.4.0.

## Consequences

- A probabilistic model can influence which bounded experiment is selected without becoming a scientific fact or policy authority.
- Every model and Agent-visible Tool occurrence, including queries, has immutable, versioned, exact provenance.
- Crash/restart never requires silently regenerating a model response or guessing whether work exists.
- One Session chooses exactly one bounded evaluation path; only Symbolic/Parameter may create at most one child Experiment, while
  direct REUSE creates none and B3.2/B3.3 retain internal deterministic Authority.
- A narrow future Product API can expose Search without database, Store, filesystem, or Core-internal bypass.
- B3.4 V1 stops after one bounded formal evaluation path and one unexecuted Next Experiment Proposal.
- The design adds durable provenance and API work to later phases but does not implement an Orchestrator, model integration, Search API,
  or Agent runtime now.

## Rejected alternatives

- LLM output as an executable Research Definition without exact schema validation.
- LLM-computed IC, RankIC, Sharpe, or another numeric claim as Research Evidence.
- Agent-declared Qualification, Factor Admission, Promotion, Strategy status, or LIVE permission.
- Agent-specific Candidate, Factor-status database, Research Result Store, Search engine, or Research runtime.
- Executing Search/Research before committing the exact Model Call Result and Tool Call Plan.
- Calling the model again to replay history or to resolve an unknown prior outcome.
- Silent provider/model fallback, retry-until-valid, heuristic prose extraction, or chain-of-thought persistence.
- Mutable conversation/session state as sole recovery truth.
- Approximate/latest Catalog resolution or a projection that becomes a second Catalog Authority.
- Bare workflow, prompt, schema, or policy fingerprints that cannot exact-load typed immutable content.
- Treating `REUSE_EXISTING` as a singleton ADR 0121 Symbolic Search Experiment.
- Invoking a query or resolve operation before committing its Tool Call Plan.
- Direct SQL, JSON Store, Parquet, filesystem, Python, shell, Git, package installation, Broker, Promotion, Admission, or LIVE tools.
- Automatically executing the Next Experiment Proposal.
- Changing B3.2 to `MODEL_ASSISTED` because an Agent selected it.

## Out of scope

```text
LLM Orchestrator or Agent package implementation
model-provider SDK or real model call
prompt templates and runtime function calling
Agent/Search HTTP routes, OpenAPI, DTOs, or persistence
Search execution changes
RAG, literature retrieval, vector database, Experiment Memory, or novelty search
L3 code generation, sandbox, PR automation, or Factor Pool
automatic Qualification, Asset Admission, Promotion, SIM automation, or LIVE
detailed authentication/RBAC implementation
```

## Constitution consistency

Constitution Impact: **NO**.

This decision strengthens Uniqueness and Single Authority by separating every Agent, Search, Research, Evidence, Qualification,
Promotion, and LIVE identity; Determinism by making model outputs exact recorded inputs to deterministic downstream transformation;
Reproducibility and Traceability through immutable model/tool/session/launch lineage; Fail-Closed behavior through strict schemas,
UNKNOWN outcomes, and exact reference verification; Recoverability through durable facts and owning-API reconciliation; and Explicit
Boundaries by requiring the versioned Product API and denying database/Core-internal access. It changes no Trading Kernel semantics,
remains market-agnostic, grants the Agent no LIVE Authority, and requires no Constitution change.

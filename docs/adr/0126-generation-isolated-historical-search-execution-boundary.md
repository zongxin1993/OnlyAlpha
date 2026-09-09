# ADR 0126: Generation-Isolated Historical Search Execution Boundary

- Status: Accepted
- Date: 2026-09-09
- Decision maker: repository owner through the PRE-E.B implementation authorization
- Related: ADR 0104, 0116, 0117, 0120, 0121, 0122, 0124, 0125

## Context

ADR 0125 makes the immutable Runtime Work binding the sole `Search Experiment -> Runtime Generation` selection. Exact metadata does
not make execution historical when the current Product interpreter executes another generation's Provider, Calculation, Resolver or
Search Algorithm bytes. Loading old wheels into the Product interpreter would also contaminate module and entry-point state and make
coexisting generations ambiguous.

The existing Runtime Generation closure already binds one exact Core wheel, Quant Asset/Calculation wheels, explicitly supplied Support
wheels, Catalog Generation, Calculation implementations and Validation Evidence. Its builder reconstructs a clean environment only from
content-addressed artifacts using `--no-index --no-deps`, and hosted verification rechecks the retained wheels, installed RECORD files,
Provider/Catalog closure and Calculation implementations. Current Core wheels contain the Symbolic and Parameter Search algorithms,
contexts, resolvers and execution support. A historical generation created from an older Core/manager artifact that lacks this contract
is readable but is not executable through PRE-E.B.

## Decision

### Sole selection and authority split

Every executable Search mutation starts with:

```text
Search Experiment E
-> only_search_experiment_work_id(E)
-> OnlyRuntimeGenerationWorkAuthority.require_work_binding(...)
-> exact active Runtime Generation G
```

No Catalog, semantic version, package version, `ACTIVE_FOR_NEW_WORK`, current or latest lookup may select or replace G.

The parent Product/Search process retains Product Admission/Receipt, expected-state admission, bounded orchestration, Research Product
Command submission and every durable Search commit. The generation worker owns only exact generation-specific Catalog, Calculation
Registry, Resolver and Search Algorithm computation/verification. It has no Search Store, Product Receipt or PostgreSQL mutation
authority. Database polling or writes are not worker IPC.

### Process and artifact boundary

One Runtime Generation uses one clean environment and one isolated worker interpreter. Different generation fingerprints never share an
interpreter. Several Experiments bound to the same generation may reuse its worker. Historical wheels never enter the Product
interpreter through `sys.path`, `importlib`, reload or object proxying.

The Host Manager accepts an already selected exact generation. It exact-loads the manifest and Validation Evidence, calls the existing
`OnlyRuntimeGenerationBuilder.rebuild_validated()` when its disposable environment is absent, starts the worker with that environment's
Python in isolated mode, and exact-verifies its handshake. Environment root, PID, pipe, process lifetime, cache state and startup time are
operational projections excluded from all semantic identities. Cache deletion reconstructs the same generation from immutable facts.

### Search Generation Execution V1

`ONLYALPHA_SEARCH_GENERATION_EXECUTION_V1` is a strict canonical transport-neutral request/response contract. Its V1 allow-list is:

```text
DERIVE_SYMBOLIC_ENUMERATION
DERIVE_PARAMETER_DECISION
RESOLVE_SYMBOLIC_RESEARCH
RESOLVE_PARAMETER_RESEARCH
```

Requests bind schema version, contract version, exact Runtime Generation, operation kind and canonical operation payload. Success binds
the same identities plus canonical result payload and its fingerprint. Failures use a closed typed error vocabulary. Unknown fields,
versions, operations, capability values and identity mismatches fail closed. There is no module name, function name, `eval`, `exec`,
shell command or arbitrary file-read operation.

The worker handshake proves schema/contract version, Runtime Generation fingerprint, Core execution fingerprint, Catalog Generation
fingerprint, Validation Evidence fingerprint and supported capabilities. Before advertising it, the worker calls
`only_verify_hosted_runtime_generation(expected_validation_evidence)`. The parent checks every field against G before any operation.

Only canonical DTOs and explicit immutable-Authority locators cross the boundary. Python objects, callables, Catalogs and Registries never
cross it. Dataset handoff is an exact Snapshot fingerprint plus the configured Dataset Store root; the path is a non-identity locator,
and the worker exact-loads and verifies only that Snapshot through the existing Dataset Authority.

### Recovery semantics

Worker computation is deterministic and creates no durable semantic fact. Worker death or response loss before a parent commit therefore
creates no Search effect; retrying the same request under G derives the same result. Parent death after response but before commit repeats
the same computation. Parent death after Search commit but before Product Receipt follows ADR 0124 historical-effect proof and repairs
only the Receipt. No retry may advance the next occurrence.

Same-generation startup is protected by one per-generation single-flight boundary. A dead worker is discarded and a later request starts
the same exact G. Missing/corrupt artifacts, evidence, installed seal/RECORD, wrong-generation handshakes, protocol mismatch and unsupported
capabilities are distinct typed failures; none falls back to current code.

## Engineering evidence and derived protections

- Python subprocess guidance: use an argument sequence without a shell; manage pipes so a child cannot deadlock on unconsumed output.
- Python isolated-mode guidance: `-I` ignores ambient Python environment and user-site influence.
- PyPA repeatable-install guidance: explicit artifacts, exact versions/hashes and `--no-deps` prevent undeclared dependency resolution.
- AlphaGen/Qlib/RD-Agent remain advisory examples of search/evaluator and workflow separation; none becomes an OnlyAlpha Authority.

OnlyAlpha derives tests for strict protocol parsing, no arbitrary invocation, exact handshake, artifact/RECORD corruption, worker death,
response loss, cache deletion, same-G single-flight, G1/G2 isolation, parent module pollution and same-Catalog/different-Runtime identity.
Third-party retry loops, mutable job status, evaluators and distributed runtimes are rejected.

## Consequences

Historical Search can execute generation-sensitive computation under exact immutable bytes while Product and Search semantic Authorities
remain in the parent process. Multiple generations can coexist without import contamination. Older generations lacking V1 fail as
`HISTORICAL_GENERATION_CAPABILITY_UNSUPPORTED`; they are never upgraded implicitly.

The process boundary adds environment build and IPC cost. That cost is accepted for exactness, recoverability and coexistence. Querying
already durable facts need not start a worker unless executable historical verification is required.

## Rejected alternatives

- Selecting a generation by Catalog, algorithm identity, current/latest or activation state.
- Importing historical wheels into the Product interpreter or sharing an interpreter between G1 and G2.
- Pickle/cloudpickle/marshal, callable/Catalog/Registry proxies or generic Python RPC.
- Worker writes to Search/Product stores or uses PostgreSQL as IPC.
- Current Resolver, Calculation Registry or Search Algorithm fallback.
- Mutable worker-status business records, distributed schedulers, HTTP/OpenAPI, Agent/LLM/RAG or LIVE authority.

## Constitution consistency

Constitution Impact: **NO**.

This decision strengthens deterministic exact execution, one Authority per fact, process isolation, append-only recovery, traceability and
fail-closed behavior. It changes no Search identity, Runtime Work binding, Research Result, Product Command identity, Trading Kernel,
Agent or LIVE Authority and keeps Core market-agnostic.

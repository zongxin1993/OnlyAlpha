# Exact hosted Chart Calculation execution projection

## Ownership and permissions

This internal boundary consumes the existing [typed Run admission](chart-calculation-run-admission.md).
It creates no Run Attempt, lease, state transition, Calculation Result, Execution Evidence, Research Result or Artifact.
It is not wired to HTTP, Web, the scheduler or the legacy Worker. Result Plan V4 remains rejected by the production Research Runtime.

The Application service accepts an Operation identity, never a caller Graph or outputs. It loads the original Operation,
INPUT_READY preparation, stored compilation and Operation-to-Run relation through their verified owning readers.
The reserved Run must still be CHART_CALCULATION QUEUED/revision 0. The complete input verifier rechecks the sealed Revision
pin, immutable Snapshot physical/logical proof, materialization lineage, Catalog witness and original Runtime Work ownership.

| Mandatory dimension | Owner / exact identity | Verification | Missing or different proof |
|---|---|---|---|
| Operation / Receipt / reserved Run | Product admission reader | Original admission and consumed reservation relation | Error, no dispatch |
| Preparation / Revision / source / instrument / bar semantics | Preparation reader and sealed input pin | Whole INPUT_READY chain and pin-to-intent relation | Error, no dispatch |
| Compilation / Graph / output / implementation | Stored compilation reader and exact hosted compiler | Complete frozen relation; host recompilation must equal stored resolution | Error, no fallback |
| Snapshot / materialization | Dataset Authority | Official physical verifier plus exact pinned materialization lineage | Error, no repair or rematerialization |
| Run occurrence / state | Research Run admission reader | Original reserved ID, exact compilation reference, QUEUED/0 | CANCELLED refuses execution; no new state |
| Runtime / Work | Runtime Generation Authority | Original active CHART_CALCULATION_INPUT binding and exact eligible manifest at both boundaries | Error, no rebinding |
| Numeric values / readiness | Registered RESEARCH backend and Calculation executor | One atomic execute_with_readiness; complete membership, type and row-wise compatibility | Error, no V1 downgrade |
| Host | Runtime Generation manager | Exact artifacts/installed bytes and capability handshake | Error, no receiver Registry fallback |

READY, ACTIVE_FOR_NEW_WORK and DRAINING generations remain eligible for their original active bound work.
RETIRED generations may support historical compilation reads but never this numerical operation. Released/inactive Work is
readable history, not execution permission. No successful projection confers publication permission, even while Work remains active.

## Transport and producer closure

The new numeric capability is distinct from RESOLVE_RESEARCH_CALCULATION_PUBLICATION, which remains compile-only.
Only the Application producer issues the process-local execution request capability. The general host execute entry refuses
the numeric operation; the dedicated host port requires an actual issued capability, not serialized Python seals or equal DTOs.
The port consumes that capability once; failure/completion cannot reuse it. Recalculation re-enters the owning readers.

The versioned wire request names the original Run, compilation and exact input/axis. It is structural data inside the
already authenticated isolated host pipe, not a serialized capability. The worker verifies the exact Specification against
its own registered compiler before using the existing V2 executor. Neither Registry nor provider objects cross the process boundary.

The response is a strict read-only EXECUTED_UNPUBLISHED projection, with exact request correlation, immutable lineage,
numeric decimal values and explicit point states/reasons. The receiver verifies all membership and axis relations against
its original request. A parsed response cannot become a native verified Execution V2 or mint Evidence. Future publication
must be separately authorized and proved at the native producer boundary; projection text is not that proof.
Tables use bounded, uncompressed JSON rows with explicit Arrow schema descriptors; Decimal values use exact strings,
not floats. Unknown encoding/compression, fields, coercions and excessive row/cell budgets fail before Arrow allocation.
Preallocation budgets include fixed-width slots for null values, validity bitmaps and all string offsets/data.
Values and readiness share one total decoded budget; the second table must fit the bytes remaining after the first,
before allocating any of its Arrow arrays. The combined projection retains a defensive total-size check.
The parsed/native projection freezes writable Arrow buffers. No IPC decompression is admitted by this contract.

## Failure, lifecycle and resources

All applicable incomplete, malformed, unavailable or complete-different proof is an error, never a negative scientific
result or certified absence. Cancellation before dispatch refuses work; cancellation observed after dispatch discards the
projection. Host timeout/loss refuses a successful projection and creates no durable effect. The owning Run and Runtime
eligibility are reloaded at completion. No PostgreSQL command/frontier lock is held during numerical work.
The dispatch linearization point is the complete command-line write. A short owning Runtime shared lifecycle fence and
Research Run `FOR SHARE NOWAIT` read-only row fence cover validation through that write, serializing against release,
retirement and durable cancellation. Both fences release immediately after sending, before waiting for numeric output.
The process-local cancellation Event is cooperative: a cancellation racing the send discards any eventual projection.

Finite inputs and transport have explicit row/byte limits. Numeric host work is single-flight, with busy rejection instead
of an unbounded queue. Operational deadlines affect availability only, never numeric identity. Repeating after loss reloads
the original frozen relation and computes again under the same exact generation; there is no successful-result cache.

Limits are 100,000 input rows, 64 MiB stored/decoded input and decoded projection, and 32 MiB per wire message.
The existing Dataset Authority provides a bounded reader of the same immutable Snapshot, freezing bounded physical
manifest and partition bytes, checking the complete global-to-partition row sum, hash/schema/row and uncompressed metadata budgets before decoding, then checking dictionary
expansion incrementally per row before constructing the full table. It neither repairs nor introduces a second store identity.
The numeric pipe has the manager's response deadline (30 seconds by default), including partial-line reads and blocked
writes, and cooperative cancellation checked throughout transport. Startup and worker-lock contention reject immediately.
Disposable environment reconstruction remains the existing Infrastructure `acquire` lifecycle (normally already used by
stored compilation); numeric execution never performs an unbounded installation. A missing environment returns unavailable
until Infrastructure prepares the same exact generation. A lost worker can restart inside an existing exact environment.

## Versions and compatibility

The existing identities remain unchanged: Compilation V1; Specification V3; Job Plan V2; Result Plan V4 (compile-only in
production Runtime); Calculation execution V2; publication contract schema 1 with (Result 2, Evidence 2, Readiness 1).
SMA semantic version remains 1 and its algorithm/provider bytes are not changed. The internal execution projection/request
use schema 1. The Search Generation envelope remains V1 with an additive, explicit numeric capability; retained hosts
without that capability fail closed. No existing V1/V2 Research Run semantics or persistent formats are migrated.

## Engineering evidence

ADR 0126 and FP-RUNTIME-001 capture the exact-process invariant. CPython gh-117378 / PR 126632 demonstrates that process
separation alone does not prove executable input isolation. OnlyAlpha keeps artifact-built isolated interpreters and exact
handshakes, tests traps against parent resolution and unsupported-generation execution, and rejects PYTHONPATH workarounds,
in-place reload, pickle and current/latest fallback. These external references are evidence, not permission or Authority.

# Rust Backtest Result / Final Seal

## Responsibility and authority

`onlyalpha_execution::Components::backtest_result(store, manifest, outcome)` is a read-only composition adapter over the existing independently buildable Execution library. It returns a private-field immutable `BacktestResult` with detached `record()` and canonical `encode()` reads. There is no derived-result decoder, writer, cache, persistence format, new dependency or independently deployed service. Result assembly observes owning managers; it never recalculates fees, Account economics, Cluster returns or reconciliation adjustments.

The native semantic identity is `BACKTEST_RESULT@1`, schema1. This isolated result is not wire-compatible with the currently admitted Python Result (whose actual serializer is schema4). ADR0034's schema3 decision established Account/Cluster authority separation; it does not grant language/artifact equivalence. Native results retain distinct exact implementation provenance.

## Explicit completion boundary

The mandatory caller-declared manifest is an exact schema1 object with:

- `configuration`: SHA256 of the complete canonical Execution configuration, including BACKTEST kind, Generation, all Cluster revisions and capital scope;
- `kernel_artifact`: exact immutable Kernel artifact digest;
- `input_pin`: exact immutable upstream input composition digest;
- `initial_time` and `final_time`: canonical Domain Timestamp records, explicit nanosecond instants;
- `inputs`: the complete ordered list of canonical Execution input SHA256 values, with no duplicate entries and at most65536 occurrences.

The owning caller must retain and bind this manifest to its immutable work identity. The library verifies the actual current Ready prefix against every observed manifest element, not merely a final count or shared head. Completion requires consuming the entire declared transcript, and every observed fact must lie within the declared time interval. Changed mandatory inputs, artifact, pin, time or configuration produce a different result or an error. Missing, malformed or wrong-family proof cannot establish absence.

**`completion_scope` is always `EXECUTION_TRANSCRIPT`.** The current Rust composition does not own market replay, Dataset exhaustion, Strategy dispatch, Broker queue drain or Event delivery lifecycle. A caller-declared digest is not producer authentication or proof of those lifecycle facts. A complete transcript proves only that this declared bounded sequence and its owning projections are available and checked. It does not certify official Backtest completion, Runtime READY, Evidence publication, a service restart/upgrade or Rust activation. R5 must bind these inputs through the actual admitted Runtime driver, prove its upstream input closure and lifecycle drains, and pass the normal Shipping Web UI flow. A boolean `completed` or an empty pending queue alone is never completion evidence.

Final seal freezes the returned observation; it does not freeze the mutable Execution source or forbid subsequent safety processing. Further accepted input yields another source/result identity. The old returned value stays immutable. The seal is a separate `READ_ONLY_OBSERVATION` with explicit final time and the verified source. It is not a fabricated Account journal occurrence and does not increment owning performance point counts.

## Source, facts and projections

The complete Ready guard verifies Store availability/head, no pending projection, contiguous genesis lineage, every transaction-cause index, exact configuration/Generation/Cluster revision and all six current owner checkpoint hashes. Result, Account performance and final Fee-aware reconciliation must bind the same source. The Store contract remains serialized and immutable; digest verification does not authenticate an untrusted Store implementation.

Only Ready input facts enter the ordered `facts` sequence. Only its FILL family enters `trades`; transport delivery receipts are not execution facts. Order count comes from the owning Order state. The result includes final Account, Position and Allocation snapshots, all configured Ledger snapshots, Order lifecycle records, the full Account timeline, each complete Ledger occurrence timeline with an explicit genesis observation, and structured diagnostics. Cluster membership and stable ordering come from the complete configured scope, never the first Ledger or registration position.

`runtime_performance` is the existing Account-owned result, including its exact numerical and historical-quality semantics. Each `cluster_performance` explicitly names `STRATEGY_LEDGER` authority and projects the corresponding owning Ledger's existing performance fields. Ledger rates use their owning single precision8 HALF_EVEN boundary (including the corrected large-coefficient double-rounding regression); Ledger availability conventions are not silently replaced with Account analytical policy, and Cluster values are not combined to manufacture Account returns. Genesis points and per-Cluster occurrence indexes are read-only views; original Ledger sequence/time/cause/outcome and snapshots remain intact.

## Outcomes and failure semantics

The strict schema1 outcome has `status` and `reason`. COMPLETED requires a null reason; FAILED, CANCELLED, INCOMPLETE and UNKNOWN require a bounded nonempty business reason. The original request and reason are retained, and driver termination is the first diagnostic so final checks cannot hide it.

- A missing/unavailable/corrupt/foreign/unready current source, wrong manifest prefix, extra observed input or invalid time is an error, including when partial output was requested. No official fact is invented for an unready transaction.
- A requested COMPLETED result with an unconsumed transcript is an error.
- A valid current manifest prefix may produce FAILED, CANCELLED or INCOMPLETE output; its explicit closure remains partial. UNKNOWN maps to INCOMPLETE while preserving the UNKNOWN request and reason. Cancellation never implies that orders were cancelled or holds released.
- Complete economic mismatch makes the result FAILED for every requested outcome, with exact Account/Ledger differences and the original termination diagnostic retained. There is no tolerance, balancing write or lost root cause.
- A requested completion with an open/UNKNOWN Order, outstanding Risk hold, reserved Account cash/Margin, Account reconciliation flag, Position stale proof or Ledger reconciliation flag becomes FAILED. Open positions and legitimate unsettled cash/asset state are not automatically failures.

Operational Event acknowledgement can change independently of economics. Returned facts exclude delivered bits, and neither content identity nor business fingerprint changes solely because an Event was acknowledged or a new process reconstructed the same source. No caller-authored operational metadata is mixed into business diagnostics. Reasons are explicit stable business inputs, not auto-formatted tracebacks, file paths or wall-clock text.

## Identity and recovery

`determinism_fingerprint` and `result_fingerprint` hash the entire stable result content before the two fingerprint fields and `id` are installed. They retain failures, requested outcome/reason, warnings/quality flags, all economic values, complete input manifest, scope/Generation/artifact, source and owning history. This identity compares the same immutable scoped work across restart; it is not a cross-artifact or differently scoped run equivalence claim. `BTR-` content identity additionally binds the two fingerprints. Canonical UTF8 JSON uses sorted object keys, exact integer timestamps and decimal strings, with no floats, wall-clock reads, random ids or platform-sized numeric reinterpretation.

Recovery reuses the existing exact Execution/owner readers and replay. There is no Result checkpoint or parallel history writer. Real-file/new-process and every pending-projection-cut tests prove library reconstruction and refusal semantics; they do not replace actual service restart, history migration or deployment upgrade evidence.

## Reference mapping and limits

Python `runtime/backtest/result.py`, `run_plan.py`, `result/business_projection.py`, `result/fingerprint.py` and the Result Collector are audited migration references. Native Result assembles only facts already owned by the selected Rust composition; it does not transliterate the Python Engine/Collector/Analytics/Artifact/Report package graph.

Independent literals cover empty single/multiple Cluster, zero capital and a real partial-fill/cancel path. The correct empty-run common subset exercises actual Python Account/Ledger owners, performance projector, final reconciliation, Result model/serializer and business projection. This proves the declared monetary/return/count subset, not whole-record or whole-Runtime parity. Native tests additionally cover real multi-Cluster rounding mismatch, pending/unavailable sources, wrong-context/leaf mutations, UNKNOWN and partial termination, detached history, Event receipt invariance and fresh-process equality.

Reference differences are explicit: Python BacktestStatus currently has only COMPLETED/FAILED; native diagnostic cancellation/incomplete/UNKNOWN are not falsely compared. Python RunPlan appends FINAL_SEAL through its projector and may choose the Clock when valuation time is absent; native sealing is read-only with a mandatory explicit time. Python fingerprint recursively excludes named metadata keys; native accepts no operational envelope and retains every source/authority field instead of deleting nested fields by name. The previously classified Account performance reference deviations remain documented in its owning contract. No broad Python repair or compatibility shim is introduced.

FP-STORAGE-001 (RQAlpha479) motivates complete source closure and missing-history rejection. [Nautilus2701](https://github.com/nautechsystems/nautilus_trader/issues/2701) motivates detached historical snapshots and direct owning consumer tests. Mutable point aliases, current-balance-only recovery and report float/clock defaults are rejected.

Formal Runtime admission, official end-of-replay producer, Product API/Web integration, Artifact/Report export, FIFO analytics, SIM/LIVE, Python retirement and deployment/history migration remain separate owning work.

The [native Replay Driver](rust-backtest-replay.md) can additionally bind its finite market/control stream and verify passive Broker/Event drain. Its nested Backtest Result remains an `EXECUTION_TRANSCRIPT`; neither native library proof alone grants formal Runtime/Evidence publication authority.

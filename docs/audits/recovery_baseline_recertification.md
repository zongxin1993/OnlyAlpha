# Recovery Baseline Independent Re-Certification (Path B)

Process record under AGENTS.md §9.1 (process documents may carry process identity). This
document is the explicit written justification required by the golden-evidence governance rule
in `docs/testing.md` for the recovery baseline strategy-identity change sealed at `f0c9274c`.

## 1. Identity change under re-certification

| Item | Value |
| --- | --- |
| Old strategy identity | `f5b1399155f63fdf4efecd3a6a12fd0cf4fa1126408b2736d5dbefd17bb0597b` (sealed at `6e62c18e`, unchanged through `f0c9274c~1`) |
| New strategy identity | `b8e389ad83146692237c20a8bd8949c2f9ae840872f6facdff25f27d300014eb` (sealed at `f0c9274c`, current committed value in both baseline manifests) |
| Affected baselines | `test-data/recovery/long_close_multi_fill_baseline/`, `test-data/recovery/multi_cluster_close_baseline/` |

## 2. Semantic reason for the fingerprint change

Commit `16ac75a6` (Repository Semantic Identity Cleanup) renamed semantic-identity strings in
`src/onlyalpha/strategy/admission.py`, `src/onlyalpha/strategy/execution.py`,
`src/onlyalpha/calculation/compatibility.py`, `src/onlyalpha/calculation/equivalence.py` and
`tests/runtime_support/runner.py`. Those strings are inputs of the strategy implementation
fingerprint, so the fingerprint changed. **No trading semantics changed**: `f0c9274c`'s source
diff touches no strategy/canonicalization module, and a line-level diff inspection of the
re-sealed `canonical_projection.json` against `f0c9274c~1` shows the changed lines are limited
to identity-bearing values — `strategy_id` (`f5b13991…` → `b8e389ad…`), the per-run `runtime_id`
and its derived identifiers (`order_id`, `position_id`, `allocation_id`, ledger/transaction
ids, `assessment_id`, `fee_application_id`, binding/resolution/accrual fingerprints). No amount,
price, quantity, timestamp sequence or trading-behavior field changed. The regenerated
projection reproduces byte-exactly from current code (§5). The change is identity-string drift,
not behavior drift.

## 3. Migration rationale

The two recovery baselines were sealed at `6e62c18e` — before the `16ac75a6` identity-string
drift was absorbed into the sealed golden evidence. From that point on, the sealed manifests'
`strategy_fingerprints` no longer matched fingerprints computed by current code, which is
exactly what the fail-closed guard `RECOVERY_BASELINE_STRATEGY_IDENTITY_MISMATCH`
(`tests/support/recovery_baselines.py`) is designed to surface (9 inherited recovery failures
predating L4). Path A (reverting `16ac75a6`) would restore a known-invalid identity and re-red
the lane without proof. Path B was therefore chosen: the L4 regeneration at `f0c9274c` re-sealed
the two baselines from current canonical code, restoring lane truth; this document independently
re-certifies that re-sealed identity.

## 4. Exact regenerated artifacts (verified via `git show --name-only f0c9274c -- test-data/recovery/`)

```
test-data/recovery/long_close_multi_fill_baseline/canonical_projection.json
test-data/recovery/long_close_multi_fill_baseline/database.sqlite3.gz
test-data/recovery/long_close_multi_fill_baseline/manifest.json
test-data/recovery/multi_cluster_close_baseline/canonical_projection.json
test-data/recovery/multi_cluster_close_baseline/database.sqlite3.gz
test-data/recovery/multi_cluster_close_baseline/manifest.json
```

## 5. Reproduction command and expected result

Command (read-only reproduction proof; the tree is restored with
`git checkout -- test-data/recovery` afterwards, and no baseline change is committed):

```bash
uv run --no-sync python scripts/regenerate_recovery_baselines.py \
  --baseline long_close_multi_fill_baseline \
  --baseline multi_cluster_close_baseline
```

Expected result — the deterministic, identity-bearing subset reproduces exactly:

1. `strategy_fingerprints` in BOTH regenerated manifests equal
   `b8e389ad83146692237c20a8bd8949c2f9ae840872f6facdff25f27d300014eb` — the committed value
   (verified across multiple independent regeneration runs, including the two-run evidence in
   the Task 9 diagnosis and the re-dispatch run);
2. `canonical_projection.json` is byte-identical to the committed file for both baselines
   (`git diff` on the two projection files is empty);
3. every other manifest field is identical to the committed manifest.

`database.sqlite3.gz` and the two derived manifest fields `database_fingerprint` /
`database_template` DO differ on every regeneration run — this is expected and is NOT evidence
of baseline invalidity; see the disclosed limitation in §6. A "regenerate → empty git diff"
expectation is NOT claimed anywhere in this certification, because it is factually unachievable
for the DB artifact on any tree (including `f0c9274c`'s own commit).

## 6. Disclosed limitation: wall-clock timestamp in the persisted database (pre-existing defect)

The persisted SQLite database embeds `runtime_persistence_metadata.created_at`, written at
schema init from SQLite wall-clock UTC —
`src/onlyalpha/runtime/persistence/store.py:761`
(`SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')`) — not from the injected fake clock. Because
`database_fingerprint` is computed over the DB bytes, `database.sqlite3.gz` bytes and the
`database_fingerprint` / `database_template` manifest fields are per-run nondeterministic on
any tree. Full logical-dump comparison of two independent regenerations (Task 9 diagnosis)
proved this single key/value row is the ONLY logical difference in the entire database: schema,
all fact tables, checkpoints, transactions, outbox, scenario timestamps (fake-clock),
`runtime_id`, `checkpoint_id` and all transaction/fact identities are logically identical
across runs.

Assessment:

- This is a PRE-EXISTING determinism defect in the persistence/regeneration pipeline, untouched
  by `f0c9274c` and orthogonal to baseline strategy identity. It does NOT affect the strategy
  identity or the canonical projection, which reproduce exactly (§5).
- It is nonetheless a genuine finding against PROJECT_CONSTITUTION.md §4.2 ("Any time … that can
  affect the result MUST become an explicit recorded input … Hidden nondeterminism is
  forbidden"): a wall-clock value feeds a certified `database_fingerprint`. Fixing it
  (pinning/fake-clocking `created_at` or excluding it from the fingerprint) would require
  re-sealing the golden evidence and is therefore OUT OF SCOPE for this re-certification; it is
  flagged here for a separate scoped task and owner decision.
- The recovery lane stays green despite this because `tests/support/recovery_baselines.py`
  never re-runs the original engine run: it content-verifies the COMMITTED archive against the
  COMMITTED fingerprint (self-consistent), compares current strategy fingerprints against the
  committed manifest (fail-closed guard), and compares the recovered projection against the
  committed `canonical_projection.json`.

## 7. Re-certification conclusion

The new identity `b8e389ad83146692237c20a8bd8949c2f9ae840872f6facdff25f27d300014eb` is
independently re-certified as the valid, reproducible strategy identity of both recovery
baselines under current canonical code. The `database_fingerprint` nondeterminism is disclosed
as a pre-existing orthogonal defect and does not weaken this certification, which rests on the
exactly-reproducing identity-bearing subset (§5).

## 8. Independent Review result

Pending — to be completed by the bounded Independent Review.

## 9. Bar semantic and construction identity re-certification (2026-09-28)

This section records the separate re-certification required by the breaking Bar semantic and
construction consolidation based on `4f1445d009d7f448bd6033a20279ccbb53d5ca31`.

The old baselines persisted `OnlyBarType` schema 1 with `aggregation_source` and a step-based
specification. The regenerated baselines persist schema 2 with `instrument_id` plus exact
`OnlyBarSemantic` (`FIXED_DURATION`, window, stride, alignment, price type and adjustment
policy). Strategy inputs now freeze an exact construction recipe. This is an intentional
identity break; no legacy payload is translated or silently reinterpreted.

| Item | Old | New |
| --- | --- | --- |
| Strategy fingerprints | `b8e389ad83146692237c20a8bd8949c2f9ae840872f6facdff25f27d300014eb` or `1c278a395b536cad8deb400d32956792a31ffc7c9ec069f0238011333fca2e96` | `8b267896bc113b456e0da1bcf932fa0dffaa5853841450d592c517242222591b` |
| Persisted Bar type | schema 1, step plus aggregation source | schema 2, semantic only |
| Construction requirement | implicit source classification | exact immutable recipe |

Affected baselines are `long_close_multi_fill_baseline`, `long_close_whole_baseline`,
`multi_cluster_close_baseline` and `terminal_after_partial_fill_baseline`; each has a regenerated
`canonical_projection.json`, `database.sqlite3.gz` and `manifest.json`. Configuration, result,
database and derived runtime identities change because they transitively bind the new Bar and
Strategy identities. Prices, quantities, ordered market/execution facts and scenario behavior
remain governed by the same recovery assertions.

Reproduction and verification:

```bash
uv run --no-sync python scripts/regenerate_recovery_baselines.py \
  --baseline long_close_multi_fill_baseline \
  --baseline long_close_whole_baseline \
  --baseline multi_cluster_close_baseline \
  --baseline terminal_after_partial_fill_baseline

.venv/bin/pytest -q \
  tests/runtime/recovery/test_recovery_baseline_support.py \
  tests/integration/test_engine_recovery_long_close_multi_fill.py \
  tests/integration/test_engine_recovery_multi_cluster_close_cost.py
```

The selected recovery proof passed all 19 cases. The bounded independent review found no
Authority split, compatibility fallback or behavioral weakening in the changed recovery
projection. The pre-existing wall-clock limitation in section 6 still applies to raw database
byte reproduction and is not used as semantic equivalence evidence.

## 2026-10-03 — Indicator closure and construction checkpoint rebuild provenance

This section explains replacement of the four recovery artifact sets inherited from
`0bc6ee66f73bc3246f21e15932a90c4db6a57ea9`. The replacement commit is the Git commit
introducing this section and its associated artifacts; this is artifact lineage, not an
Exact-SHA certification or authorization to continue another task.

| Identity | Value |
| --- | --- |
| Previous Strategy Revision | `8b267896bc113b456e0da1bcf932fa0dffaa5853841450d592c517242222591b` |
| Replacement Strategy Revision | `eb87637d272485956685bba49d6eb24a511d7fdacfcc1c660ca9652efa70a30c` |

The source comparison is `4997d76..0bc6ee66`. Accepted ADR 0137 adds atomic RESEARCH
readiness for SMA@1 and preserves legacy values. Indicator provider version changes
from 5 to 6. Its `registration.py` changes the declared SMA readiness capability;
`research.py` adds `execute_with_readiness`, delegating numeric output to the existing
`execute` implementation. Trading algorithm files and their bytes do not change.

The direct Strategy identity cause is the exact implementation resource closure, not
provider version alone or a hash of the entire Catalog. Indicator registrations declare
`registration.py` in both TRADING and RESEARCH implementation manifests; RESEARCH also
declares `research.py`. `only_python_implementation_manifest` hashes those resource bytes,
and the implementation fingerprint binds their bundle. Provider content and Catalog
generation identities propagate the changed implementation inventory separately.

The recovery Strategy graph contains RSI(period 14) and rolling-return(periods 1 and 3)
plus predicate nodes, rather than the newly readiness-capable SMA. All three indicator nodes acquire
new RESEARCH and TRADING implementation fingerprints through the shared resource files.
ADR 0097 and `OnlyStrategyRevision.semantic_payload` bind those exact fingerprints.
Old/current Revision comparisons retain the same graph, parameters, universe, exact
market-input contract and signal semantics, including every predicate node binding.
This is classification **B: conservative implementation identity change with unchanged
scenario trading behavior**, not a change to the Calculation semantic identity.

Affected artifact directories are:

- `test-data/recovery/long_close_whole_baseline/`
- `test-data/recovery/long_close_multi_fill_baseline/`
- `test-data/recovery/multi_cluster_close_baseline/`
- `test-data/recovery/terminal_after_partial_fill_baseline/`

Each directory replaces exactly `manifest.json`, `canonical_projection.json` and
`database.sqlite3.gz`. All four current scenarios derive the replacement Strategy
fingerprint; both multi-cluster configurations derive the same exact Revision. No
unaffected baseline is included.

Reproduce separately in two clean copies of the source commit through the canonical
Compose test profile:

```bash
deploy/run-tests.sh python scripts/regenerate_recovery_baselines.py \
  --baseline long_close_whole_baseline \
  --baseline long_close_multi_fill_baseline \
  --baseline multi_cluster_close_baseline \
  --baseline terminal_after_partial_fill_baseline
```

For old/current scenario comparison, compare complete canonical business projections
recursively, retaining object keys, array cardinalities and ordering. Every differing
leaf must be the exact previous-to-replacement Strategy fingerprint at a Strategy
identity/reference location. This preserves prices, quantities, fees, timestamps,
execution ordering, decision contents and cancellation outcomes; dropping arbitrary
identity or fingerprint fields is not an equivalence proof.

For the two new runs, compare projection bytes and every manifest field except
`database_fingerprint` and its derived `database_template`. Independently validate each
archive against its own database fingerprint. Compare the complete SQLite schema and
sorted logical rows, excluding only the `runtime_persistence_metadata` row whose key
is `created_at`, not the whole table or any other timestamp. This is the pre-existing
wall-clock limitation described above: raw SQLite/archive bytes are not promised to
reproduce identically.

The two isolated productions of these replacement artifacts yielded the following
identical projection bytes (SHA-256); each also matched the separately executed current
uninterrupted scenario. Complete deterministic manifest contents matched. Complete
schema/row comparison identified only the documented `created_at` difference; each
archive's decompressed SHA-256 matched its own manifest and SQLite integrity check.

| Baseline | Projection SHA-256 | Orders / fills / terminal orders | Old/current differing projection leaves |
| --- | --- | --- | --- |
| `long_close_whole_baseline` | `98f4a2325dc47f419044216425fccc5cf050f74346a3927ca99c3efb478bf582` | 2 / 2 / 0 | 10 |
| `long_close_multi_fill_baseline` | `ed48cbcd68a164e540020ceca0cb312095a13adac0c3ed76cd9a2b783acfbd54` | 2 / 6 / 0 | 18 |
| `multi_cluster_close_baseline` | `53b07cfbd904169db86d4644540e094b85d92e2e8d4e7c85a194f4ecea6475d2` | 4 / 4 / 0 | 20 |
| `terminal_after_partial_fill_baseline` | `bdae790b2b9dc560de1954d9f9fc3d9b99e99873b4a0c396b988f8311ebf4ca1` | 1 / 2 / 1 | 8 |

Those old/current leaves are exclusively exact Strategy fingerprint substitutions in
Strategy result/last-decision identity, execution/request/order facts and order Strategy
references. They do not alter the remaining projection contents or ordered relationships.
Independent examination also reconstructed node/Revision hashes and the request-to-order,
execution-to-trade, nested fee and runtime/cluster ownership relations without dropping
identities. These projections expose final Strategy decisions, not full per-Bar indicator
traces; the comparison establishes equality of represented scenario behavior and unchanged
trading algorithm/input definitions, not observation of every intermediate calculation.

### Historical construction checkpoint rebuild

The replacement archives also rebuild a separate, pre-existing breaking checkpoint
contract. This is not indicator identity propagation. The inherited archives were last
produced at `c98340e08ae781f2c5dbc07fb15fabf85732e0f7`. Their
`market-data.aggregation` participant has schema 1. Commit
`aaa8b3114c6b42ca7c00fb3137d88619e0f6b40c` introduced typed construction graph/lane
execution and participant schema 2; commit
`a90617f4f26ccfae8a455e7196e9d54ced0511e6` introduced the compiled construction DAG
and participant schema 3. Both precede the `4997d76` readiness baseline. The current
contract is documented in `docs/market_data_pipeline.md` section 3: old aggregation
checkpoint formats are rejected and require rebuild, not implicit reinterpretation.

At checkpoint sequences 29 and 30 in every affected archive, the old aggregation
payload has empty `aggregators` and `reference_counts`, with `creation_count = 0`.
The rebuilt schema 3 payload also has `creation_count = 0` and empty `lanes`:
these scenarios have provider-native Bars, not stateful derived executors. The new
representation additionally binds:

- source identity `synthetic-cn-etf`;
- construction graph fingerprint
  `4e8bcfc9d96805d427ce29d5cfd97212de0defface36bdacdb41a21db7b5609e`;
- the exact RAW, LAST-price, SESSION_START, 1-minute window/stride
  `TESTETF.XSHG` provider Bar type;
- provider reference count 1 for single-cluster scenarios and 2 for the two-cluster
  scenario.

These are explicit additions to the recoverable construction contract. Equality of
business projections does not make schema 1 and schema 3 interchangeable. Checkpoint
component/aggregate hashes and participant registry fingerprints change accordingly;
transaction payload hashes separately follow the changed Strategy attribution.

The artifact operation is a fresh deterministic scenario execution and replacement
of its test Golden, not an in-place database migration or a legacy checkpoint loader.
The previous bytes remain addressable in Git history. Current restoration must reject
old schema/context and accept only the complete exact current graph/source/provider
binding. No backward compatibility with schema 1 or 2 is claimed or introduced.
The replacement justification therefore has two distinct causes: conservative
indicator implementation identity change and the historical construction checkpoint
rebuild. Economic facts, ordered relationships and cancellation outcomes remain subject
to the full projection comparison and unchanged recovery assertions.

The scoped construction checks use the existing canonical tests without changing their
assertions:

```bash
deploy/run-tests.sh python -m pytest -q \
  tests/market_data/test_construction_runtime.py \
  tests/market_data/test_bar_aggregation.py
```

For each archive's two aggregation checkpoints, the additional native-lane reproduction
constructs the manager with the exact source, provider Bar type and Cluster reference
count. Its freshly captured payload must equal the entire replacement payload and
restore/capture must preserve that equality. The old schema 1 payload, schema 2 payload,
wrong source, wrong graph, missing provider, wrong provider count and missing lane array
must all fail as `CONSTRUCTION_CHECKPOINT_REBUILD_REQUIRED` without changing manager
state. The schema replacement is justified by these exact binding checks, not by deleting
old context fields or accepting a partially proven checkpoint.

### Dependent exact-identity test vectors

Two dependent test vectors retain exact literal assertions for the changed closure.
Both prior values reproduce from `4997d76`; the replacements derive from `0bc6ee66`.
The Search Submit V1 intent retains all non-identity fields: the Catalog binding changes
in both intent and Search Space, and the algorithm manifest's declared
`calculation/registry.py` resource changes because it now validates readiness registration
metadata. Search Space, algorithm and command fingerprints follow those exact inputs.
Qualification retains its policy, research result and evaluation criterion/outcome;
the three changed indicator bindings propagate through its Strategy Revision, exact
Freeze relation and evidence subject binding into the Decision identity.

| Test vector | Previous | Replacement |
| --- | --- | --- |
| Search Submit V1 command | `796179dc26dac9d3bf618298ef58d27e6c16fbbc5a208dcafa795b16745d181c` | `11d4363e751b4461fbf9a3b372c536a4bd46cc078a52eb71160dc9fe56c3be64` |
| Qualification Decision | `ac2c56d4cdc7619b70db319915dc5fd795a7e92d0076005ea8e78820f072e983` | `62210343e398aab82295ce49c546e41da93b220113d89eec93456b50e959bd85` |

The tests retain their V1 fail-closed, V2 runtime/science separation, immutable decision
verification, approved outcome and replay assertions. No Product schema, Calculation
semantic identity or fingerprint algorithm is changed by this vector replacement.

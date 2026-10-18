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


## Domain canonical Bar identity development-contract evolution (2026-10-17)

This is the explicit artifact-change justification required by `docs/testing.md`, not a
new quality or completion authority. ADR 0140 records the owner-selected direct evolution:
BarSemantic schema 3, canonical Volume/Value parameters in formation schema 2, and no
legacy reader, alias or fallback. Repository scenarios must bind the current exact Strategy
Revision; the existing identity guard correctly rejects the previous Golden references.

The four controlled recovery scenarios are re-executed using the unchanged
`scripts/regenerate_recovery_baselines.py` into an isolated output directory. Only their
three test artifacts (Manifest, canonical projection, SQLite archive) are replaced. This
is fresh test evidence construction, not migration or reinterpretation of business data.
Prior artifact bytes remain in Git history; no application store or user-data is modified.

All four current scenarios bind Strategy fingerprint
`4e0feaaf5218e5dd5d15faee7ae0876735105f876630be084084ac1208bcbbd8`.
The complete old/current projection comparison has differences only in Strategy identity
references and the final decision's Bar-bound observation key/fingerprint. All other leaves,
collection ordering and lengths are equal, including prices, quantities, fees, balances,
PnL, timestamps, order/execution status and ownership relations. Manifest order/fill/terminal
counts, checkpoint ID and committed transaction/fact sequences are equal. The broker
checkpoint differs only in its serialized latest Bar's semantic schema version (2 to 3);
its other fields are equal. Configuration/scenario/result and database fingerprints follow
the current exact inputs. This comparison does not remove identities from actual recovery
assertions: those compare the entire current projection and result fingerprint.

| Test baseline | Prior Strategy fingerprint | Changed projection leaves | Replacement database fingerprint |
| --- | --- | ---: | --- |
| `long_close_multi_fill_baseline` | `98edd221d92e9e7235270257b54813f587217e130cdec1a88714bb5d6504720b` | 20 | `56f28b49585976fe8da583508a96f0f4c4174f5b68bfcdb2881bd1e830858816` |
| `long_close_whole_baseline` | `eb87637d272485956685bba49d6eb24a511d7fdacfcc1c660ca9652efa70a30c` | 12 | `e0c237c8cf58176c4fd99d13fe37b6ff8f24bf02be783cc381190d983df8e1c9` |
| `multi_cluster_close_baseline` | `98edd221d92e9e7235270257b54813f587217e130cdec1a88714bb5d6504720b` | 24 | `8ab24176137790cc8b7e63b22ea9d0bd669826b67a7c40638cb3a7acc5ab9b88` |
| `terminal_after_partial_fill_baseline` | `eb87637d272485956685bba49d6eb24a511d7fdacfcc1c660ca9652efa70a30c` | 10 | `ba5dfcc4460bbee71ef2f1171a17c39ebde6c784e66d884f1bb1d68b09121b7d` |

Reproduction uses the canonical dev validation entry with `uv run python -c`, importing
`scripts.regenerate_recovery_baselines`, assigning its `TARGET` and `CACHE` to isolated
`/workspace/test-results/` directories and invoking `regenerate` for `BASELINES` serially.
Compare complete canonical projections recursively; only the identity fields described
above may differ. Verify Manifest references, archive content digest and SQLite integrity
using the normal recovery fixture reader, then execute the unmodified Recovery/SIM Recovery
assertions through `scripts/test_suite.py`. Regeneration is never added to a lane or CI.
The pre-existing archive creation-time limitation documented above still applies; archive
byte identity across independent generation runs is not claimed. Current reader restoration
and fault/restart tests remain required and are not certified by this justification alone.


Independent reconstruction distinguishes the archived HEAD source identity
`81c629c6e59534a0952112dbe31a24a3ec2d7898698299c17923f98c42a96f6c`
from the two older sealed Golden identities in the table. Those Golden identities already
lag the HEAD source; they are not claimed to be reproducible from current HEAD code.
Changing only `market_input_contract.bar_semantic.schema_version` and
`market_input_contract.construction_requirement.recipe.target_semantic.schema_version`
from 2 to 3 in that archived Revision semantic payload reconstructs the current
`4e0feaaf...` identity above, preserving graph, implementation bindings, universe and
signals. The archived implementation resource bytes were compared against Git HEAD.
Old/new latest-Bar JSON independently reconstructs all ten final-observation key and
fingerprint occurrences using the pure canonical hash rules, without loading schema 2
through the current reader.

Two independent fresh current scenario runs have byte-equal canonical projections and
equal Manifest fields except `database_fingerprint` and `database_template`. Full SQLite
logical dumps differ only in the previously disclosed `runtime_persistence_metadata`
`created_at` row. Archives retain their exact content digests and integrity checks.
The affected artifact set is exactly `canonical_projection.json`, `manifest.json` and
`database.sqlite3.gz` within each of the four baseline directories listed above (12 files).
Current readers still reject the old Bar schema; this replacement introduces no fallback
and does not constitute a deployment migration or business-history upgrade proof.


### Direct Research and Qualification identity consumers

The same current Bar Contract propagates into Dataset definitions and source construction
metadata, Snapshot identities, Calculation/Statistics/Research Result manifests and the
Strategy Revision/Freeze/Qualification chain. Six existing exact-vector tests in five
files update their literal current identities atomically; their assertions, replay checks,
fresh-process checks and round-trip validation remain present. No hash algorithm changes.

Archived HEAD reproduces the prior Coverage, Effect, Indicator and Result V1/V2 pins.
Independent plain canonical JSON plus SHA-256 reconstruction verifies 28 formulas per
source cohort: summary logical/content/result and serialization, Dataset definition and
Snapshot, Calculation/result, Result plan/content/result and fixed-time serialization,
Qualification subject/relation/decision and the unchanged Search intent. Coverage/Effect
summary objects, Indicator graph and numerical result content, and Qualification graph,
policy and APPROVED outcome remain equal. Identity-sorted V2 collections can reorder
when their exact fingerprints change; semantic comparison matches candidates by assignment
and series by their subject/output contract, retaining all elements and relationships.

The prior Qualification literals additionally lag archived HEAD: the archived source
subject is `d39379d26aff6fd9efeb5651abddd5b7e8baa561bde3bc5f4336f1fd261f32a2`,
its relation is `7880436a07fefbc10a4718f1012d3d7be002331c658af33e0c5f8fbd78e770f7`
and decision is `156752f3c11dfac4d80706da10d43fb5b38b8cb45c8cad3a41f5cd8d4dda9152`.
The actual current subject/relation/decision follow the explicit schema-3 increment; the
old literal staleness is separate from that increment. Search is equal across HEAD/current
and therefore its unrelated stale assertion is left unchanged. No broader golden cleanup
is authorized or performed.

The exact literal replacements are shown below. Each pair is retained as an exact
assertion in its original test; unchanged hashes are not removed. This is a change
justification, not a claim that the full repository or historical deployment is certified.

| Owning test file | Prior literal | Current literal |
| --- | --- | --- |
| `tests/research/evaluation/test_coverage_summary.py` | `395cd7437d8e7cd85c174b28065a30d94da82762036df16798bb0cc53e3763c4` | `76d8d0caa653c285701d30e73ed4af9e22a36dc6fc9974e0f3a88a21e1d48103` |
| `tests/research/evaluation/test_coverage_summary.py` | `4668d4461bbd52ce4c22bf16c82c5f522388606b17253880db7d7917429024c2` | `0c9e27e7931fc9ace53c3cfe61c237d4f0b9b17ba152a4271a46057209f3626b` |
| `tests/research/evaluation/test_coverage_summary.py` | `4c9fb1ca9f584878d85b0cf70d1d30f549cf4963b502abc70ea5cb5f7aad11fb` | `b810a670a79a58c1091eea84505ef9a4f8f5439c0c114c3baf5cb0918351a77b` |
| `tests/research/evaluation/test_coverage_summary.py` | `2925303c5eaecfc419a6bfbe3b07392ab97151fc43e67544ff44f15c95b4682e` | `ee0d1b5f5369a127cdf519a0c51edb23f0c360213e968e67a9728caa755055ad` |
| `tests/research/evaluation/test_coverage_summary.py` | `38a5bb6f48c36d471984e2825da547e18ba44f07077d8177450afb5ffb258b81` | `70d8c1f787572f93d4431d1c0e869d62737cffc90ee89c76fc4fcf442327ae9d` |
| `tests/research/evaluation/test_effect_summary.py` | `d5afc888af75f735965cc72049be1ed024390bb2347748ee31449ebccc2ef0a5` | `fc1a627725a90b3ad185aa9ff30b06d22ff75d9aad591787c5253112c0d42cb0` |
| `tests/research/evaluation/test_effect_summary.py` | `5d57581803a3ef6e843b2ae1f203cb9c479f056f259c0d37c310f2e6caf369a9` | `43db702d3b7a947a1512b99d30ac2a1aba6888f43e967b96facff5354a43bc45` |
| `tests/research/evaluation/test_effect_summary.py` | `3ca2b13da5b27ec78fda56f87c04b6ca3876073c77fa2ed86af2791b8a8c4449` | `845fc278f66f7bb618fde60fd9e427e09fff2130c56b21b280a716bbf375347c` |
| `tests/research/evaluation/test_effect_summary.py` | `f929261a743fc02d3e055364479fa5158a0ab913496c801d8c5f6c63d7f95cad` | `79a15a53fd1a2c9f68591b38721af6e0d7a41223b95e492db75de34744f650f2` |
| `tests/research/evaluation/test_effect_summary.py` | `454c31044c3a6cf624939bca129dbbb263b02a50bb17728d6dce93559bd4dd7f` | `d9e7e36edb57823b1f4a4046a3c539c3de92eabea60afb8124bba958c3db7b9a` |
| `tests/research/factor/test_indicator_identity_regression.py` | `446a9b5c8b664da3e175f31f28e9514094a52055d47fd2ec40edc1ead10bb54d` | `2e885d9894d9515d3406b15261d3b8a83389bb57465d2b72edd6a4d0e887473e` |
| `tests/research/factor/test_indicator_identity_regression.py` | `c69bd8a2e7439eb0aa7c86140b914433d0ca7f49a3bf44924d8891ec4460d381` | `45ce99c423959fe518114e6a7d66275253767ebb3936c83529233e3de263a013` |
| `tests/research/result/test_identity.py` | `e3941921eb094e8bf1443d3aae512bf8002af9bb7ae520b97979ff06535f1b34` | `81c76d374cbfdfa678d13aa5caf1f446cd84adada909e57769e9433496b4b33b` |
| `tests/research/result/test_identity.py` | `3b64271f49607b744f669c85230c28c47565a13decd49176d1f59b071a1078b1` | `3c59d735c059c20cb476a4197ce03b635cfc509f635ba7436e1489565046d4eb` |
| `tests/research/result/test_identity.py` | `76c838643e6f456eb9a4a16fbe31c1b6361964a10ef7ec942f375f8cd076b27d` | `812b0250125cf24259f79fa1141db01c844063d9ef8a6103d0103399a4d05b34` |
| `tests/research/result/test_identity.py` | `66fa5759ebeea384e57d669805f9af2ec589d295067ca2a4fb6e4c3979e1b154` | `52403441341e38ddfeb080a9f1ba302901ac1797c489df6181993b319f332132` |
| `tests/research/result/test_identity.py` | `1b655f4580a1b195b4af128db7218089abc4c61df26e27ed0aac503d3ee615a9` | `cef580fcf1a90fdd4e60b24b858e1b85834ba20952a9645aef7be4f388d519c1` |
| `tests/research/result/test_identity.py` | `782c4e29a7fc2d7b36f80a8882db905ee00c70f2634133a4da77811a859152fe` | `9d68d35d8e9b5fcb877fbb704b4ec2f816961e11cda642590dbfb8998abec511` |
| `tests/research/result/test_identity.py` | `5f83d24daa97c02aa9f5e6d3b4d3aa5fc85d1fbb6cfd7df9db857b4678c1bdd5` | `625d97c23f5a5780523bc9efb321791d761873214a0232cfc111bfc09ff09bba` |
| `tests/research/result/test_identity.py` | `4c2408d84e6a5ede4454bf6edb5b4d0e2e1c81f4ea0069e68b61168e1a0c6756` | `8032a40eb3735a04a274f30a0a5a97859975183dc1a2908559805622a81f0c00` |
| `tests/strategy/test_strategy_qualification.py` | `0a028c03c9cd39322171a060006df4f5cb62b16b37f4d2c31a935fc653d86fa9` | `57d6d7af1ab513750b68e6d208b2c26b7b0e0470e420d455c49b1134df32b3b9` |
| `tests/strategy/test_strategy_qualification.py` | `e2fc37d5867ec1f198b849accb693c58a7c5d6f419e1fa49f8df2a37cf8e3bfa` | `4e9bc21319df2403f79b0b1b179fb89e787dd04678fbfb75fd3a3daec0bd0137` |
| `tests/strategy/test_strategy_qualification.py` | `c79ad0d7a317c79c43d2dd67d75f11b7f4f2ccf0056a123bd9f91dd5887f20fb` | `df98b87eeab081e3c15cdbe242588913e2b09dd789c74b75b492212605aca386` |


### Release distribution provenance increment 0.10.7 to 0.10.8

The coordinated release graph changes the Indicator Provider resource's declared
`distribution_version`. Its exact resource SHA and RESEARCH implementation evidence
bindings therefore change. Independent reconstruction from both resource byte cohorts
verifies the six bindings and the existing Qualification subject/relation/decision and
Search command formulas. Graphs, TRADING bindings, parameters, numerical outputs, policy
and APPROVED outcome remain unchanged. The two Qualification tests retain their exact
subject/relation/decision and fresh-process/replay assertions. Search now has a genuine
release-provenance increment, independently of its previously disclosed stale literal:
the 0.10.7 source computed `046100...`, while 0.10.8 computes the current value below.

| Test owner | Previous literal | Current literal |
| --- | --- | --- |
| `tests/strategy/test_strategy_qualification.py` | `57d6d7af1ab513750b68e6d208b2c26b7b0e0470e420d455c49b1134df32b3b9` | `83e07a47e4af760827feef3cf1f3234b167e9d5c54eb72af4c1f8c06f30070b6` |
| `tests/strategy/test_strategy_qualification.py` | `4e9bc21319df2403f79b0b1b179fb89e787dd04678fbfb75fd3a3daec0bd0137` | `f9e3cb4e7f94f26042d4768d05da306483d6fa34368feecac28150835808b7a6` |
| `tests/strategy/test_strategy_qualification.py` | `df98b87eeab081e3c15cdbe242588913e2b09dd789c74b75b492212605aca386` | `15d009c504cf4e983ce2aa3e2b696ecd3cb1f215027dcfdee2c6a3921f287d51` |
| `tests/research/search/symbolic/test_search_product_adapter.py` | `11d4363e751b4461fbf9a3b372c536a4bd46cc078a52eb71160dc9fe56c3be64` | `f579dfa67d1284b7177a15570698ddf5a60c50050baa60a1106c5e9a21a7d511` |

The four controlled recovery test scenarios are freshly executed with the unchanged
generator and current release closure. Their exact Strategy attribution changes from
`4e0feaaf5218e5dd5d15faee7ae0876735105f876630be084084ac1208bcbbd8` to
`5761654082f83dd5208083b426d42d9a7800c127819a634f86e1f0044f0a78c3`.
The complete old/new projections differ only in these Strategy identity leaves. Every
other value, key, ordered collection and economic fact is equal. Manifest counts,
checkpoint ID, committed transaction/fact sequences and full broker checkpoint are equal.
Configuration/result/archive fingerprints and release provenance bind the current inputs.
This is replacement of the same 12 test artifacts, not migration of business data.

| Test baseline | Changed Strategy identity leaves | Current database fingerprint |
| --- | ---: | --- |
| `long_close_multi_fill_baseline` | 18 | `05776d6327ff016abdb1d2fa3cf9d69d3db4019fd1ee84e2bab7e3fa2ac9d956` |
| `long_close_whole_baseline` | 10 | `50437ac5ad159e9ccdf8d730292978f86a8351952373acea6834875496718e05` |
| `multi_cluster_close_baseline` | 20 | `dc07ca90afdfb64ab7d054ee8bd92e270669b0eb29cfec3588225c3906acb820` |
| `terminal_after_partial_fill_baseline` | 8 | `6db4dc64b7a1f222324345b21d707d7ebcadd35f4dceb64803aa8e962cd1dcc4` |

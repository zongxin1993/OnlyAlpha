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

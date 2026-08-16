# P7.9 Research Artifact Materialization & Portable Read Boundary

## Task Context

- Base branch: `master`
- Task Base SHA: `e0db67f4a074e00c0fb8e0c7e775d1aa8a38106f`
- Resulting HEAD: unchanged base SHA plus the current uncommitted P7.9 worktree; no implementation commit was created
- Version: `0.7.9`
- Increment state: `P7.9 — VERIFIED LOCALLY`
- P7 milestone state: `IN_PROGRESS`; P7 Final Certification is `NOT COMPLETE`

The only pre-existing dirty item was the untracked P7.9 prompt, which was preserved. Repository truth confirmed P7.8 as the latest
verified increment, Research Result as exact Statistics composition authority, Statistics Result as row semantic authority, and
Research/Live factories as intentionally unsupported.

## Modification and Impact Scope

Modified scope: `onlyalpha.research.artifact`, public Research exports, focused Research Artifact and architecture tests, the
`research-artifact` canonical lane, impact-aware propagation, quality/certification matrices, ADR/current-truth documentation, and
the synchronized workspace version graph.

Impact scope: the Research Result consumer contract, Statistics public semantic contract, immutable Parquet/Manifest persistence,
portable verification, Research/Trading dependency firewall, quality infrastructure, and package metadata. Trading Kernel, Broker,
Account, Position, Risk, Settlement, Backtest, SIM, Live implementation, Research Runtime activation, Query/API/Web, optimizer, and
new Statistics/Analytics semantics were not modified.

## Architecture and Authority Decision

Statistics Result remains the Statistics rows semantic authority. Research Result remains the exact Statistics Result composition
authority. Research Artifact is a disposable, rebuildable, derived immutable read view and is not a new Research or Statistics
authority.

`OnlyResearchArtifactMaterializer` starts from verified Research Result persistence, follows only its exact canonical references,
verified-loads each exact Statistics Result, and revalidates Dataset, Statistics Plan, row content, and Statistics Result linkage
before producing a complete candidate. It never scans a Store or publishes a partial candidate.

`OnlyParquetResearchArtifactStore` depends on no upstream Store. A published Artifact can be loaded and fully verified with Dataset,
Calculation, Statistics, and Research Result roots unavailable. The store provides no authority restore/import path.

## Artifact Contract

V1 publishes exactly:

- `artifact_manifest.json`
- `statistics.parquet`

The Parquet schema is exactly `statistics_fingerprint`, `ts_event_ns`, `statistic_value` as Decimal(38,12), `sample_count`, and
`status`, ordered by Statistics fingerprint and timestamp. The strict versioned manifest embeds exact Research Result identities,
one Dataset Snapshot identity, a canonical Statistics catalog with full Statistics Plans and identity layers, the logical Arrow
schema, exact row counts, physical byte SHA256, logical Artifact content fingerprint, and UTC audit time.

No Artifact Plan fingerprint or Artifact Result identity was introduced. Logical identity is derived from schema/profile, upstream
Research Result identity, Dataset identity, and the canonical Statistics catalog. Audit time, path, staging location, compression,
process identity, and disposition are excluded. Parquet byte SHA256 is a separate physical-integrity proof.

## Persistence, Recovery, and Portable Verification

Commit writes a unique stage directory, verifies the Parquet logical round trip, writes the manifest, executes complete staged
self-verification, and atomically renames the directory. Equal re-entry verifies and returns `REUSED`, including publication-race
losers. Different logical content at the same profile/schema plus Research Result address returns
`DETERMINISTIC_ARTIFACT_CONFLICT`. Existing corruption remains `ARTIFACT_CORRUPT`; it is never missing, deleted, repaired, or rebuilt
over.

Portable verification proves exact filesystem membership and rejects symlinks; verifies Manifest fields, profile/version, UTC time,
byte hash, Arrow schema, canonical/duplicate-free rows, and row counts; recomputes each Statistics fingerprint/content/result
identity; reconstructs Research Result plan/content/result identity; and finally recomputes Artifact logical content identity.

## Validation Evidence

Focused development evidence:

- `uv run pytest tests/research/artifact tests/architecture/test_research_artifact_boundaries.py -q` — 41 passed before the final
  defensive-contract expansion.
- `uv run python scripts/test_suite.py research-artifact --coverage` — 53 passed; lines 96.49%, branches 93.37%, total coverage
  95.70%.
- `uv run python scripts/test_suite.py research-artifact` — 53 passed.
- `uv run python scripts/test_suite.py research-result` — 28 passed.
- affected Ruff check/format — passed.
- `uv run mypy src/onlyalpha/research/artifact` — passed, 6 source files.
- `uv run lint-imports` — 3 contracts kept, 0 broken.
- `uv run python scripts/version_sync.py check` — workspace release graph consistent at 0.7.9.

The first verification-infrastructure FULL_LOCAL run correctly failed one current-truth architecture assertion that still expected
P7.8/0.7.8. The assertion and README current state were updated to P7.9/0.7.9; its exact regression test then passed. The final run:

`UV_CACHE_DIR=/tmp/onlyalpha-uv-cache UV_OFFLINE=1 uv run --offline python scripts/verify.py agent --base e0db67f4a074e00c0fb8e0c7e775d1aa8a38106f`

passed all 24 gates: 9 release static checks; Research Artifact 53, Research Result 28, Research Evaluation 96, Research Sweep 27,
Research Factor 57, Research Job 30, Research Calculation 127, Calculation 58, Research Dataset 36, core-full 1,787, recovery 330,
SIM recovery 38, A-share 24, MiniQMT contract 34; and workspace build. The canonical lanes collected 2,725 tests. Full logs:
`test-results/verification/20260816T054554Z-e0db67f4a074-36848/`.

The version helper's first online lock attempt could not reach PyPI in the restricted environment after updating metadata. The lock
was then resolved successfully with `uv lock --offline --python 3.12`, followed by a successful version-sync check.

## Gates Not Executed

P7 Final-SHA Certification, Remote CI, CodeQL, Semgrep certification, dependency-audit certification, Nightly Heavy Quality,
repository-wide coverage, mutation testing, and P7 Final Closure were not executed. This report claims `VERIFIED LOCALLY`, not
`CERTIFIED` or `ACCEPTED`.

## Remaining Limitations

Query Service, HTTP/RPC API, Web UI, visualization, optimizer/ranking, new aggregate research analytics, cross-Dataset composition,
Artifact catalog/search, Artifact authority import/restore, distributed workers, Research Runtime lifecycle, and Live Runtime remain
unimplemented. Research Artifact intentionally remains a small read boundary rather than a generic Trading/Research Artifact
framework.

# P7 Final Certification Closure

Date: 2026-08-17

## Status

```text
Milestone: P7 — Vectorized Research Runtime
Status: DONE / CERTIFIED
Final Subject SHA: 6b051705c7638dc3acb02dde430c3c2348121811
Final-SHA Certification Run: 31986131977
Certification Artifact: certification-6b051705c7638dc3acb02dde430c3c2348121811
Certification Verdict: ACCEPTED
```

This report records the external certification fact for the immutable P7 implementation subject. It does not redefine implementation semantics; source, formal tests, accepted ADRs and the certification artifact remain authoritative.

## P7 Exit Condition Review

P7 required a stable Research Job/Plan contract, deterministic Dataset/Calculation identity, serializable immutable Result/Artifact, read-only Query/API and a browser Web boundary.

The final subject contains the complete Research chain:

```text
Historical Dataset Snapshot
→ Research Calculation
→ Calculation Result
→ Research Job / Parameter Sweep
→ Target / Statistics
→ Research Result
→ Research Artifact
→ Query / HTTP API
→ Research Web
```

It also contains the finite Research Runtime product path:

```text
OnlyEngine
→ add_research_workload(...)
→ initialize / start / run_runtime
→ existing immutable Research authorities
→ Research Result / Artifact
```

The P7.12 Web boundary consumes only verified portable Artifact-derived HTTP responses; it does not access execution Stores, Parquet paths or Research Runtime mutable state. HTTP v2 represents Decimal and exact nanosecond/cursor values as canonical strings, and the Web admission layer retains exact event time as `bigint` and exact Decimal as text.

## Remote Certification Evidence

GitHub Actions `Final-SHA Certification` run `31986131977` completed successfully for exact subject:

```text
6b051705c7638dc3acb02dde430c3c2348121811
```

Mandatory certification jobs completed with `success`, including:

- immutable subject verification;
- repository static checks;
- all-package build;
- Research Web static/unit/build/E2E;
- canonical calculation and Research lanes;
- `core-full`;
- `recovery`;
- `sim-recovery`;
- `ashare`;
- `miniqmt-contract`;
- mandatory branch coverage;
- Semgrep;
- dependency audit;
- CodeQL for Python and JavaScript/TypeScript;
- aggregate certification verdict.

The resulting certification evidence is:

```json
{
  "schema_version": 1,
  "subject_sha": "6b051705c7638dc3acb02dde430c3c2348121811",
  "workflow_run": "31986131977",
  "verdict": "ACCEPTED",
  "required_gates": {
    "subject": "success",
    "static": "success",
    "build": "success",
    "web": "success",
    "lanes": "success",
    "coverage": "success",
    "semgrep": "success",
    "dependency-audit": "success",
    "codeql": "success"
  }
}
```

The certification artifact digest reported by GitHub Actions is:

```text
sha256:b68b7ca8faac64a228e161bab8beb28a049d70fb905cca1e0e79688939688211
```

## Closure Decision

The formal quality sequence required by `docs/engineering/quality-system.md` is:

```text
Task Complete x N
→ Phase Gate
→ Phase Complete
→ Freeze Final SHA
→ Final-SHA Certification
→ Certified
```

The exact P7 subject has passed the complete Final-SHA mandatory matrix and the final certification artifact verdict is `ACCEPTED`.

Therefore:

```text
P7 — DONE / CERTIFIED
```

P7 no longer blocks entry into P8.

## Scope of the Certification Claim

P7 certification proves the implemented finite Research semantic/read product boundary. It does not claim completion of:

- Web-native Research submission/control;
- Research Scheduler / durable Worker queue;
- PostgreSQL operational control plane;
- Optimizer;
- Historical Data Platform / ClickHouse integration;
- full heterogeneous Research+Trading lifecycle in one Engine;
- Live Runtime;
- full-market product support.

These capabilities must not be inferred from P7 certification.

## Current-Truth Closure Note

This report and the roadmap/README update that reference it are documentation/current-truth changes made after the immutable certified subject. They do not change the certified P7 implementation SHA.

The certified implementation subject remains exactly:

```text
6b051705c7638dc3acb02dde430c3c2348121811
```

Any later implementation change must be evaluated under the gate corresponding to its own Task/Phase scope and must not be described as part of that immutable P7 certification artifact.

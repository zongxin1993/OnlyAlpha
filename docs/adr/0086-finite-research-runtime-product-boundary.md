# ADR 0086: Finite Research Runtime Product Boundary

## Context

P7.0–P7.10 established immutable Dataset, Calculation, Statistics, Research Result and Artifact authorities, while Engine/Factory/Session contracts
still assumed a Trading-shaped Runtime. Activating Research by making Broker, Account, Market Product and persistence fields optional would weaken
the Trading contract and create ambiguous ownership.

## Decision

Engine/Factory/Session depend on minimal structural Runtime product, environment and plan contracts. Finite, waitable and plugin-resource snapshot
capabilities remain separate. Existing Trading plan/environment contracts remain strong.

`OnlyResearchWorkloadPlan` is an application composition contract with no semantic fingerprint. `OnlyResearchRuntime` is a finite product that starts
from one exact verified Dataset Snapshot and delegates in fixed order to existing Job, Sweep, Statistics, Research Result and Artifact authorities.
It owns no durable semantic store and recovers only through exact workload re-entry plus verified immutable reuse.

The default composition root creates one `OnlyCalculationRegistry`; plugin discovery registers into it once, and both Indicator Trading resolution and
Research backend resolution consume it.

P7.11 supports Research-only Engine execution through `add_research_workload()` and `run_runtime()`. Research and Trading mixed in one Engine fails
closed until the heterogeneous lifecycle target is implemented. `OnlyEngine.run()` retains its Backtest-only behavior.

## Consequences

- Research requires no Cluster, Account, Broker, Market Product, Trading Kernel, Trading persistence or Runtime checkpoint.
- Existing Research identities and content-addressed storage paths remain unchanged and independent of Runtime ID.
- Corrupt existing authorities fail closed and are never rebuilt or overwritten by Runtime.
- Research YAML/CLI, Web, Scheduler, database control plane, LIVE and complete heterogeneous Engine lifecycle remain out of scope.

## Invariants Introduced

- Runtime product common contracts contain no Trading-specific optional fields.
- A workload validates one Dataset closure, globally unique Calculation ownership and exact Statistics/Result closure before durable execution.
- Runtime determinism evidence excludes Runtime ID, audit time, physical layout and EXECUTED/REUSED disposition.
- OnlyEngine remains the sole product-level execution entry.

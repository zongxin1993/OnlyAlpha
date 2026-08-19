# ADR 0093: Decision Definition, Exact Graph, and Cross-Runtime Semantic Equivalence

- Status: Accepted
- Date: 2026-08-19
- Related: ADR 0068, 0070, 0079, 0088, 0092; P8.4 Research Studio Web; `docs/strategy_product_architecture.md`

## Context

P7 established Runtime-independent Calculation semantics with separate RESEARCH and TRADING backends. P8.4 now needs a human- and machine-authorable Research surface that can express registered Indicators/Factors, Eligibility, and Entry/Exit signal conditions without introducing a second Research semantic plane.

The same product direction also needs a durable answer to a longer-term problem: Research, Backtest, Sim, and Live must not each own a different implementation of the same strategy signal logic. If a Web Builder produces one rule while a later Backtest `Strategy.py` reimplements that rule, semantic drift becomes unavoidable and Research evidence no longer proves what the Trading Runtime executes.

The representative example is:

```text
RSI.value < 30
AND
Momentum.score > 0
```

The user-facing meaning must remain identical regardless of whether the data is processed as historical Arrow arrays or incrementally from realtime events.

## Decision

### Authoring truth is a backend-independent semantic definition

The Web Builder, programmatic clients, and future LLM/Agent clients must produce the same canonical, versioned domain contract.

The authoring direction is:

```text
Human Web Builder
        │
Programmatic Client ──→ Semantic Definition
        │
LLM / Agent
        │
        ▼
Deterministic Resolver / Compiler
        ▼
Exact Decision / Calculation Graph
```

The browser must not directly author an internal node graph, Graphviz DOT, Python callback, or Runtime-specific strategy implementation as the semantic authority.

`Definition` answers **what the user means**. `Exact Graph` answers **what OnlyAlpha will execute**.

### Decision Definition is the reusable signal-semantic boundary

The long-lived reusable portion of a research/strategy intent is conceptually a `Decision Definition` containing at least:

```text
Calculations
├── Indicators → published Features
└── Factors → published Scores

Eligibility Expression
Entry Signal Expression
Exit Signal Expression
```

The exact type/class name is not frozen by this ADR; the semantic boundary is.

Research-specific concerns such as Dataset Snapshot selection, parameter candidate exploration, Target, Statistics, Result, and Artifact remain outside the reusable decision semantics where appropriate.

A future Strategy Revision may freeze an exact Decision Definition/Graph together with additional strategy identity evidence, but P8.4 does not itself create Strategy Revision authority.

### Signal expressions are structured and closed

P8.4 authoring uses a finite typed Boolean expression grammar rather than arbitrary executable code.

Initial expression primitives are limited to:

```text
AND
OR
NOT
==
!=
<
<=
>
>=
```

Operands are typed references to admitted Dataset fields, published Calculation outputs, or typed literals.

No `eval`, arbitrary Python expression, JavaScript expression, or opaque string DSL becomes execution authority.

### Eligibility, Entry, and Exit share mechanics but not domain roles

The three expressions may share the same Boolean AST and lowering infrastructure, but their meanings remain distinct:

```text
Eligibility
→ whether an observation/instrument qualifies for the research/decision context

Entry Signal
→ whether the entry condition is true at an observation

Exit Signal
→ whether the exit condition is true at an observation
```

The lowering layer must not silently rewrite:

```text
entry = eligibility AND entry
exit  = eligibility AND exit
```

Such policy would destroy independent facts and introduce hidden trading behavior.

### Research Signal is not an Order

A Research Entry/Exit signal is a Boolean research fact, not an execution side effect.

```text
ENTRY_SIGNAL == true
!=
BUY Order

EXIT_SIGNAL == true
!=
SELL Order
```

Research records the signal series/evidence and stops there.

A future Backtest/Sim/Live Trading layer may consume the same signal through Position, Portfolio, Risk, Order, Broker, and Execution policies. Those policies do not redefine the signal condition.

### Boolean AST lowers into the existing Calculation execution plane

P8.4 must not create an independent `PredicateRuntime`, `PredicateResultStore`, or second recovery/reuse system.

The required direction is:

```text
Typed Boolean AST
        ↓
Canonicalization + Type Admission
        ↓
Deterministic Predicate/Signal Lowering
        ↓
Internal Calculation Graph primitives
        ↓
Existing Graph materialization / identity
        ↓
Existing Calculation Runtime
        ↓
Immutable Calculation Result / downstream evidence
```

Internal primitives may include typed comparisons and Boolean combinators. They are compiler/runtime implementation details and are not user-facing Calculation catalog items.

A narrow execution semantic kind such as `PREDICATE` may be introduced if implementation proves that existing `INDICATOR / FACTOR / TARGET` kinds cannot represent the Boolean semantics truthfully. If introduced, it must reuse the Calculation Registry/Definition/backend/executor infrastructure rather than creating a new engine, and P8.4 must not imply a Trading backend automatically exists.

### Semantic terminal roles must survive lowering

Two mathematically identical Boolean expressions used for different roles must remain distinguishable in exact semantics.

For example:

```text
RSI < 30 → Eligibility
```

is not the same semantic fact as:

```text
RSI < 30 → Entry Signal
```

The exact graph/projection therefore needs an explicit role-bearing terminal or equivalent exact semantic representation so that `ELIGIBILITY`, `ENTRY_SIGNAL`, and `EXIT_SIGNAL` can be proven by Result/Artifact evidence rather than inferred from UI placement.

### Candidate-relative signal semantics are resolved inside the graph

If a Calculation parameter is swept, downstream signal expressions are candidate-relative automatically.

Example:

```text
RSI.period      = [7, 14, 21]
Momentum.window = [10, 20]
Entry           = RSI.value < 30 AND Momentum.score > 0
```

The target Research candidate space is the finite Cartesian product:

```text
3 × 2 = 6 candidates
```

For each candidate, Entry/Exit/Eligibility bind to that candidate's exact Calculation outputs. The system must not run a second signal-side candidate join that guesses which Calculation result belongs to which signal.

### One semantic definition, multiple execution strategies

The Decision semantics remain invariant across Runtime products. The execution strategy may differ.

Target Runtime model:

```text
RESEARCH
→ historical batch / vectorized execution

BACKTEST
→ historical incremental / event-driven execution

SIM
→ realtime incremental / event-driven execution

LIVE
→ realtime incremental / event-driven execution
```

For the same admitted observations and the same exact semantic definition, outputs at the same semantic time must be equivalent.

Conceptually:

```text
ResearchVectorBackend(input_history)[t]
==
TradingIncrementalBackend(input_0 ... input_t).value
```

This equivalence applies to shared causal Indicators, Factors, Eligibility, and Entry/Exit signal semantics.

Vectorization is an execution optimization, not permission to use a different algorithm.

### Shared Decision semantics must be causal

A Decision Definition that is intended to cross Research → Backtest → Sim → Live may depend only on information available at or before the decision time.

Future-looking Target calculations are Research evaluation semantics and must not leak into the shared Decision Graph.

```text
Decision(t)
→ observations/calculation state available <= t

Target(t)
→ may intentionally describe a future outcome for Research evaluation
```

### Cross-backend equivalence is a required verification direction

As the shared Decision boundary is implemented, OnlyAlpha should establish equivalence tests that feed identical historical observations through vectorized Research and incremental Trading backends and compare admitted outputs by timestamp/instrument.

At minimum, the verification direction covers:

```text
published Indicator outputs
published Factor outputs
Eligibility
Entry Signal
Exit Signal
```

Warmup, missing-value, timestamp, numeric precision, and input-binding semantics must be Definition-owned and cannot diverge by backend.

## Consequences

- Strategy signal logic stops being primarily a new `Strategy.py` implementation for every idea.
- Human Web authoring and future Agent authoring converge on one canonical contract.
- Research can use Arrow/vector operations while Backtest/Sim/Live use incremental execution without changing semantic meaning.
- Signal generation is reusable across products while signal consumption remains product-specific.
- Existing Calculation identity, verified reuse, Result, recovery, and Artifact authority remain the execution foundation.
- Parameter Sweep produces exact candidate-relative signal graphs rather than requiring a second signal expansion system.
- Future Research → Backtest promotion can freeze/reuse exact decision semantics instead of reimplementing the researched rule.

## Rejected alternatives

Rejected as semantic authority:

- generated Python files executed as the primary meaning of a Web-authored strategy;
- a second Predicate/Signal execution engine beside Calculation Runtime;
- browser-side RSI/Factor/Signal recomputation;
- opaque string expressions evaluated with `eval` or equivalent;
- separate Research-only and Trading-only signal definitions;
- silently combining Eligibility with Entry/Exit;
- treating Entry/Exit Signal as immediate Order execution;
- allowing vectorized Research code to use future information in a supposedly shared live-decision semantic.

A human-readable Python-like preview/export may exist as presentation, but it is never execution authority.

## Validation

Implementations derived from this ADR must verify:

1. Web, programmatic clients, and future Agents can target the same versioned semantic contract.
2. Exact Graph is produced by deterministic server/domain resolution rather than React-private graph construction.
3. Eligibility, Entry, and Exit remain separate semantic facts.
4. Signal expressions are closed, typed, canonical, and fail closed on unknown/incompatible references.
5. Candidate-relative signals bind to exact candidate Calculation outputs.
6. Research execution produces authoritative Boolean signal series/evidence and does not emit Orders.
7. No second Predicate Runtime/Result authority is introduced.
8. Shared Decision semantics remain causal.
9. Cross-backend semantic equivalence tests become mandatory before claiming a Calculation/Decision path is safely shared across Research and Trading.

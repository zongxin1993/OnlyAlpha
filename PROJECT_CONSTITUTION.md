# OnlyAlpha Project Constitution

**Status:** FOUNDING CONSTITUTION  
**Authority:** L0 — Highest normative authority  
**Mutability:** IMMUTABLE by normal engineering work  
**Applies to:** All architecture, ADRs, roadmaps, tasks, prompts, code, tests, plugins, Web, Agent and Infrastructure

---

## 0. Constitutional Authority

This document defines what OnlyAlpha exists to become and the principles that cannot be traded away.

All lower-level artifacts MUST conform to this Constitution:

```text
PROJECT_CONSTITUTION.md
        ↓
Target Architecture / Contracts
        ↓
Accepted ADRs
        ↓
Roadmap / Work Program
        ↓
Task Contract / Prompt
        ↓
Implementation / Tests
```

No ADR, task, implementation difficulty, market rule, provider limitation, optimization or Agent recommendation may supersede, weaken or reinterpret this Constitution.

Current source code and tests are authoritative only for **what is implemented now**. They MUST NOT be used to infer that an unimplemented capability is no longer a product goal.

If a requested task conflicts with this Constitution, implementation MUST stop and report `PLAN_CONFLICT`.

---

# 1. Why OnlyAlpha Exists

OnlyAlpha exists to build a personal quantitative system that can be owned, understood, controlled and operated for the long term.

It is not merely a quantitative framework, trading SDK, backtest library or collection of scripts.

OnlyAlpha is intended to provide one complete system covering:

```text
Data acquisition
→ Data organization
→ Durable storage
→ Research
→ Factor management
→ Strategy definition
→ Backtest
→ SIM
→ LIVE
→ Execution
→ Recovery
→ Evidence
→ Audit
```

The fundamental problem it solves is:

> How can a personal quantitative idea move from data and research into real trading while preserving one identity, deterministic behavior, full traceability, reproducibility and recoverability across the entire lifecycle?

OnlyAlpha therefore pursues a stable internal quantitative world outside a changing external market world.

---

# 2. What OnlyAlpha Is

OnlyAlpha is a long-running **Stateful Quant System** deployed on servers as a set of clearly bounded nodes.

The product is not centered on `python strategy.py`. Normal operation is:

```text
Server start
→ OnlyAlpha nodes start
→ Durable state recovery
→ External reconciliation
→ Ready
→ Long-running operation
```

The system contains, conceptually:

- a stable Trading Kernel;
- data acquisition and real-time market-data capabilities;
- broker / execution gateways;
- durable database and persistence services;
- a versioned control API;
- a responsive Web interface for all normal human operations;
- an Agent that uses the formal API;
- infrastructure that manages node identity, deployment, compatibility, health, upgrade and recovery.

OnlyAlpha is a node system, but it is **not** a microservice-for-every-class architecture. Deployment boundaries require a real reason such as independent lifecycle, operating-system dependency, fault domain, resource boundary or upgrade cadence.

---

# 3. What OnlyAlpha Is Not

OnlyAlpha MUST NOT become:

- an uncontrolled autonomous trading black box;
- a system where the source of a signal cannot be determined;
- a system with multiple competing authorities for the same fact;
- a system whose components communicate through undocumented side effects;
- a repository with unclear module ownership, unclear interfaces or unclear dependency direction;
- a provider-specific trading core;
- a system whose normal operation requires direct Python calls into internal objects;
- a system where Web, Agent or database writes can bypass formal authority;
- a system that cannot explain, replay or recover its own state evolution.

Complexity is allowed. Hidden authority and untraceable behavior are not.

---

# 4. Fundamental Invariants

The following are constitutional invariants. They are requirements, not recommendations.

## 4.1 Uniqueness

One semantic fact has one canonical identity and one authoritative representation.

Equivalent semantics MUST converge to the same identity within the same identity domain. Semantic change MUST create a new identity rather than silently mutating the old meaning.

The system MUST NOT maintain parallel official truths.

## 4.2 Determinism

Given the same:

```text
Kernel version
+ canonical configuration
+ Strategy Revision
+ initial state
+ ordered input facts
```

OnlyAlpha MUST produce the same state transitions and outputs.

Any time, randomness, model version, external response, human decision or Agent decision that can affect the result MUST become an explicit recorded input, versioned configuration or formal fact.

Hidden nondeterminism is forbidden in canonical trading semantics.

## 4.3 Market-Agnostic Core

OnlyAlpha Core MUST NOT need to know whether it is trading stocks, futures, crypto, Binance, QMT, CTP or any other concrete market/provider.

Core understands only OnlyAlpha canonical semantics.

Market/provider/regulatory/protocol differences MUST terminate at plugin / adapter / gateway boundaries.

## 4.4 Single Authority

Every formal fact category MUST have one explicit Authority.

Possessing a copy of data does not confer Authority.

External venues own external execution facts. OnlyAlpha owns its internal intent, policy, strategy identity, promotion, reconciliation and recoverable local state according to explicit contracts.

Authority cannot move because another component is more convenient to modify.

## 4.5 Reproducibility

Important results MUST be reproducible from immutable evidence and explicit versions.

Research and Backtest MUST be bound to immutable inputs such as Dataset Snapshots, Strategy Revisions, calculation/model versions, configuration revisions and Kernel version.

LIVE cannot recreate the real market, but OnlyAlpha MUST record enough market facts, decisions, intents, provider observations and state transitions to replay why it acted as it did.

## 4.6 Fail-Closed

If OnlyAlpha cannot prove a risk-increasing action is safe and correct, it MUST refuse that action.

Fail-Closed does not mean process exit.

Under uncertainty the system MUST continue the safety path required for observation, fills, cancellation, persistence, reconciliation, recovery and risk reduction.

`UNKNOWN` is a first-class state. Unknown submit outcome MUST NOT be converted into blind retry.

## 4.7 Explicit Boundaries

Every significant component MUST define:

```text
What it owns
What it does not own
Inputs
Outputs
Authority
Public contract
Dependencies
Failure semantics
Persistence semantics
Lifecycle
```

Cross-node interactions MUST use explicit versioned contracts.

Database access is persistence, not automatically an integration API.

Implementation convenience never justifies boundary violation.

## 4.8 Recoverability

Crash and restart are normal lifecycle events.

No critical truth may exist only in volatile memory.

OnlyAlpha MUST be able to recover by:

```text
Durable facts
+ deterministic state reconstruction
+ external reconciliation
→ one valid authoritative state
```

Recovery by guesswork is forbidden.

## 4.9 Traceability

Every important formal action MUST have a reconstructable causal chain.

For a real execution, the system must be able to trace conceptually:

```text
Market Fact
→ Strategy Decision
→ Portfolio / Risk Decision
→ Order Intent
→ Broker Submission
→ Venue Order
→ Fill
→ Position / Runtime State
```

Traceability is stronger than logging. It must answer who produced a fact, from what input, under which runtime/strategy/version, why it happened and what it caused.

---

# 5. The Immutable / Variable Boundary

The primary architectural classification rule is:

> OnlyAlpha Core implements what should not change when external market rules change.

If a capability may change because of:

```text
Market
Exchange
Broker
Provider
Regulation
Trading rule
Instrument convention
Vendor API
Protocol version
```

it belongs outside Core behind a plugin contract.

If it does not change with the market and is part of universal quantitative/trading semantics, it may belong in Core.

OnlyAlpha does not try to eliminate market differences. It isolates them.

```text
Changing external world
        ↓
Plugins / Gateways
        ↓
Stable canonical contracts
        ↓
OnlyAlpha Core
        ↓
Deterministic state
```

---

# 6. Trading Kernel

The Trading Kernel is the long-term stable center of OnlyAlpha.

It owns only market-independent canonical concepts and state transitions, such as:

- identity;
- canonical facts;
- strategy semantics;
- runtime semantics;
- portfolio semantics;
- risk semantics;
- order-intent semantics;
- execution state machine;
- authority rules;
- recovery and reconciliation semantics;
- traceability;
- evidence and promotion semantics.

The Kernel MUST NOT accumulate provider-specific branches such as:

```text
if provider == ...
if exchange == ...
if market == ...
```

as canonical business logic.

A new market difference MUST first be modeled in a plugin. Core may evolve only when evidence shows that a genuinely universal trading concept is missing.

Core stability means not that Core can never change, but that external market change no longer forces Core change.

---

# 7. Plugin Boundary

Plugins absorb all change originating from the external market world.

Plugins may own:

- provider protocols and DTOs;
- market data formats;
- instrument translation;
- trading calendars and sessions;
- quantity/price restrictions;
- settlement and margin conventions;
- provider authentication;
- provider error semantics;
- connection/reconnect behavior;
- venue-specific order capabilities;
- compatibility with changing provider API versions.

OnlyAlpha defines capability contracts; plugins implement them.

```text
OnlyAlpha Contract
       ↓
Plugin implementation
       ↓
Concrete market/provider
```

Plugins may not redefine Core Authority or canonical semantics.

---

# 8. Web Boundary

Web is the formal human interaction surface.

Web has only three permanent responsibilities:

```text
Display
Input / management
Command submission
```

All normal human operations MUST be performed through Web and the formal OnlyAlpha API.

Web MUST NOT own trading, strategy, risk, promotion or runtime Authority.

Web displays facts and collects user intent; OnlyAlpha decides and executes according to canonical rules.

Direct database mutation, direct Core object mutation or Python REPL operation is not a normal product workflow.

---

# 9. API Boundary

OnlyAlpha exposes one formal external control surface: the versioned OnlyAlpha API.

Human interaction:

```text
Human → Web → API → OnlyAlpha
```

Agent interaction:

```text
Agent → API → OnlyAlpha
```

CLI or SDK, if provided, are API clients rather than alternate internal-control paths.

External clients MUST NOT control the running system by importing internal Python objects.

---

# 10. Agent Boundary

Agent is responsible only for factor-oriented research work:

- factor hypothesis;
- factor code implementation;
- factor mining;
- factor testing;
- factor combination and parameter exploration;
- research execution;
- factor management;
- Backtest;
- SIM;
- evidence analysis and recommendation.

Agent MUST use the formal OnlyAlpha API.

Agent MUST NOT:

- directly import/control internal Kernel objects as a production control path;
- directly mutate databases as an authority path;
- bypass validation, evidence, promotion, risk or audit;
- acquire LIVE Authority.

Agent may research, Backtest and SIM autonomously within granted permissions.

**LIVE activation, LIVE strategy change and material LIVE risk authorization require explicit human operation.**

The human boundary is permanent.

---

# 11. Infrastructure Boundary

Infrastructure owns stable system-level engineering invariants required for the node system to operate coherently:

- node identity;
- deployment boundaries;
- component identity and version;
- service interfaces;
- compatibility rules;
- health model;
- upgrade protocol;
- rollback protocol;
- persistence topology;
- network/security boundaries;
- observability contracts;
- failure domains;
- lifecycle and recovery orchestration.

Infrastructure defines stable rules, not immutable technology vendors.

Docker, Kubernetes, PostgreSQL, ClickHouse, FastAPI or another concrete technology may change. The invariant is that nodes, contracts, compatibility, lifecycle, health and recovery remain explicit and controlled.

Infrastructure MUST NOT become a second trading authority.

---

# 12. Change-Rate Architecture

OnlyAlpha intentionally separates components by expected change rate.

```text
Trading Kernel / canonical semantics  → lowest change rate
Infrastructure contracts             → low change rate
Provider / market plugins            → change with markets/providers
Web                                  → product/UI evolution
Factor research / Agent              → highest change rate
```

As the system matures, external change should increasingly be absorbed by plugins and high-change layers rather than propagated into the Kernel.

A primary architecture quality metric is:

> How much must the Trading Kernel change when a completely new market/provider is added?

The desired answer approaches zero.

---

# 13. Product Control and Explainability

OnlyAlpha must remain personally controllable.

For every formal trading signal or action, the system MUST be able to identify, as applicable:

```text
Strategy Revision
Input facts
Factor/calculation/model version
Parameters
Runtime
Decision path
Risk decision
Order Intent
Execution observation
Resulting state
```

A signal whose cause cannot be determined is not acceptable as a formal OnlyAlpha trading fact.

No AI, Agent, model or component may use “the system thinks so” as sufficient execution authority.

---

# 14. Constitutional Decision Rule

For any new capability, architecture change or implementation, ask:

```text
Does it preserve uniqueness?
Is Authority explicit?
Is behavior deterministic?
Is Core still market-agnostic?
Can the result be reproduced?
Can the causal chain be traced?
Can state be recovered after crash?
Does uncertainty fail closed?
Are component boundaries respected?
```

Any critical answer of `NO` or `UNKNOWN` blocks architectural acceptance.

When performance, convenience or delivery speed conflict with correctness, constitutional correctness wins.

---

# 15. Governance and Immutability

This Constitution is read-only for normal development.

Codex, Agents and ordinary implementation tasks have **no authority** to modify, supersede, weaken or reinterpret it.

They may report a conflict, but they may not resolve that conflict by changing this file.

Accepted ADRs are subordinate to this Constitution and cannot supersede it.

A task that would require changing the Constitution MUST stop with `PLAN_CONFLICT` and require an explicit founding-governance decision by the repository owner outside the normal implementation workflow.

Repository automation SHOULD verify the Constitution fingerprint and reject ordinary changes to it.

---

# 16. Constitutional Summary

OnlyAlpha exists to create:

> A stable, controllable, long-running personal quantitative system in which a market-agnostic Trading Kernel owns only invariant trading semantics, changing market rules are isolated behind plugins, every formal fact has one Authority and identity, state evolution is deterministic and traceable, results are reproducible, failures are recoverable, uncertainty fails closed, humans operate through Web, Agents operate through API and never own LIVE authority, and Infrastructure keeps the whole node system explicit, compatible and manageable.

OnlyAlpha does not eliminate change.

**OnlyAlpha identifies change, isolates it at the correct boundary, and protects what must remain invariant.**

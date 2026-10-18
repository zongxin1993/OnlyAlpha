# MarketData organization and delivery implementation plan

Execute inline with executing-plans/TDD and one fresh final independent reviewer. Owner delegates design and implementation
without approval handoffs. Execution/evidence stays in ignored test-results, not a repository status ledger.
Spec: ../specs/2026-10-18-rust-market-data-delivery-design.md. Constitution impact NO; version0.10.10.

## Review focus

- Nested manifests must influence dev admission; deeper test-data paths and extracted dependencies cannot read undeclared trees.
- A late scope/freshness/sequence failure must not consume an earlier Cluster's planning cursor.
- Separate Clusters can validly advance at the same timestamp; no global time cursor or decoded readiness authorization.
- Checkpoint membership/owner/subscription/nested graph and timestamps must validate fully before replacement.
- Unregister ends a registration lifetime; no unsupported durable exactly-once or real restart claim.

## Task1: Organize MarketData and admit the declared delivery closure

Move state/construction under market_data without changing package names, identities or existing algorithms. Update workspace,
relative Domain paths, include_str fixture depths, named-source guards, isolated module extraction, direct tool fixtures and
owning navigation. Test nested manifests in dev environment_inputs and reject old top-level layout. Observe RED then implement.
Add delivery manifest/empty source/test skeleton; direct edges Domain/State/Construction + exact num-bigint/serde_json. Update
lock local package and version graph/fakes, no registry change. Prepare the one fixed dev image after final manifest inputs.
Run affected layout/environment/version/guard tests and existing module tests. No standalone umbrella wrapper.

## Task2: Subscription values and delivery planning

Tests first for explicit ID, set canonicalization, graph/instrument matching, default/explicit primary, non-time explicit
primary, unsupported policy and strict record types. Implement src/lib.rs (public exports/compile-fail), subscription.rs,
owner.rs and minimal private record.rs (no generic framework). Tests for sorted Cluster routing, primary-only view isolation,
LatestClosed/SameEventTime, wrong owner/clustered input, duplicate/late input and registration ID conflicts. route validates
all candidate views/cursors before commit; no callback/readiness/actual Strategy execution. Test errors unchanged and independent
same-time Clusters. Use State/Construction real APIs in tests, no test-only production hooks.

## Task3: Recovery and independent common-reference corpus

Checkpoint schema1 binds exact receiver owner/config; reader rejects duplicate rows, owner aliases, malformed nested graph,
missing/extra/foreign registration and nonexact/out-of-range timestamps. Fresh preconfigured replay/idempotence/late row failure
must preserve actual prior state. Many sequential updates retain only one cursor per active registration. Add hand-specified
subscription/routing vectors under test-data/market-data-delivery plus real Python comparison consumer; classify reference bugs.

## Task4: Enforced isolation, owning docs, verification and publication

Add Delivery pure-source/manifest reverse-edge/hidden input guards and independently extracted Domain+State+Construction+
Delivery closure. Update developer/business navigation and owning Contract only; no official Runtime writer. Run affected
Python consumers/tools/environment tests, Ruff check/format and mypy changed scripts, module debug/release/fmt/Clippy; bounded
simplicity and one fresh independent whole-branch proof review. Fix blocking findings with real RED->GREEN regressions.
Run final canonical rust-kernel lane on frozen source, exact Constitution/version consistency, Critical0High0. Fetch master,
fast-forward only an equivalent tested tree, push normally and fetch alignment. No release/version bump or business-data action.

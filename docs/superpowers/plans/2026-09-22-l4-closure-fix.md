# L4 Closure Fix: Production Composition, Canonical Cutover & Certification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the six remaining L4 gaps (CF-A..CF-F): canonical production Integration Runtime composition, Agent deployment cutover to INTEGRATION_REVISION, real-PostgreSQL golden certification, recovery-baseline governance repair, Agent secret-transport confidentiality, and Runtime Generation hosting boundary clarification.

**Architecture:** One reusable production composition helper assembles the persistence-backed `OnlyIntegrationRuntimeResolver` (Postgres state store + credential authority + type catalog projection over existing plugin discovery + probe store + optional generation reader) and is injected into `only_default_engine_services` via a resolver-factory parameter by the worker composition roots. Agent canonical deployment flips `deploy/docker-compose.dev.yml` to INTEGRATION_REVISION with bootstrap-provisioned provider integration, READY probe, model profile and token files. Secret-bearing agent transport rejects `http://`/unverified-TLS unless an explicit dev-only flag is set.

**Tech Stack:** Python 3.12+, psycopg (Postgres), FastAPI/uvicorn, pytest (markers: integration/external/postgres), Docker Compose dev topology, stdlib urllib/ssl for agent transport.

**Spec:** `/Users/zongxin/workspace/OnlyAlpha_prompt/OnlyAlpha_L4_Closure_Fix_Production_Composition_Canonical_Cutover_Codex_Task.md`

**Baseline:** `master@fb34756f83a307990409ae2eaaf92c816a643870` (work on branch `codex/l4-closure-fix`). This plan file is a process artifact — do NOT commit it.

## Global Constraints

- HARD STOP: no L5 work, no legacy deletion, no hot reload, no provider/Broker/model failover, no latest Revision/Secret/Plugin-generation fallback, no second Integration/Credential authority, no second plugin discovery path.
- Runtime never means latest; current pointers select new work only; LEGACY xor INTEGRATION_REVISION fence with no precedence logic.
- Master key: runtime paths use `only_load_master_key` (fail closed); only bootstrap/tests may use `only_ensure_dev_master_key`.
- `PROJECT_CONSTITUTION.md`, fingerprints, and quality gates are read-only except where this plan explicitly extends gates (task-sanctioned).
- Correctness tests are deterministic/hermetic/offline-first; no `sleep()`-based proofs; no skip/xfail of real failures; no weakened assertions.
- Repo semantic identity: no process labels (L4/CF-x/task ids) in new source/test/fixture names — use domain semantics (e.g. `test_tushare_postgres_runtime_golden.py`, not `test_cf_c_pg01.py`).
- Test placement: `tests/<area>/` mirrors `src/<area>/`; cross-cutting certification lives under `tests/certification/<domain>/`; every test package dir has `__init__.py`.
- Env: `uv sync --all-packages --all-groups` is the canonical local env; Postgres tests run only through `deploy/docker-compose.dev.yml` `test` profile or the CI service container (`ONLYALPHA_POSTGRES_DSN`).
- Validation per AGENTS.md §4: targeted tests → affected ruff check/format → affected mypy → affected canonical lanes; this is a HIGH-risk task → bounded Independent Review required before STOP.
- Commit per workstream; CF-D recertification MUST be its own commit.

## Key existing facts (verified 2026-09-22 at fb34756f)

- `only_default_engine_services(*, fail_fast=True, runtime_persistence_store_factory=None, market_product_resources=None, calculation_catalog_generation=None, authoring_generation_fingerprint=None, integration_runtime_resolver=None)` — `src/onlyalpha/runtime/defaults.py:43`; internal plugin discovery at :64; resolver lands in `OnlyComponentFactoryRegistries.integration_runtime_resolver` (`src/onlyalpha/runtime/assembler.py:36`).
- Resolver: `OnlyIntegrationRuntimeResolver(state, credentials, catalog, *, probes=None, runtime_generations=None)` — `src/onlyalpha/application/integration_runtime.py:210`; reader protocols at :170-207; `admit_new`/`admit_new_reference` flags `require_current_revision`/`require_ready_probe` (:228-282); DB failures surface as `INTEGRATION_RUNTIME_PERSISTENCE_UNAVAILABLE`, missing reader/generation as `INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE` (:345-351).
- Authorities: `OnlyPostgresIntegrationStore(dsn, *, options=None, now=..., _connection=None)` (`src/onlyalpha/persistence/postgres/integration_store.py:37`); `OnlyPostgresIntegrationProductStore(dsn, master_key, *, options=None, now=...)` (`integration_product_store.py:49`); `OnlyPostgresCredentialAuthority(dsn, master_key, *, options=None, now=...)` with `create/rotate/read_secret` (`credentials.py:90`); `OnlyPostgresIntegrationProbeStore(dsn, *, options=None)` (`integration_probe_store.py:20`); `OnlyIntegrationTypeCatalog(data_sources, brokers, component_types=())` (`src/onlyalpha/application/integration_type_catalog.py:24`).
- Master key: `only_load_master_key(path)` / `only_ensure_dev_master_key(path)` / `MASTER_KEY_FILE = Path("secrets")/"dev-master-key"` — `src/onlyalpha/persistence/postgres/credentials.py:27,38,64`.
- Workers: `src/onlyalpha/backtest/worker_main.py:79` (discovers plugins at :103-115; plan builder at :137); `src/onlyalpha/backtest/worker.py:81-102` (`OnlyBacktestProductEnginePlanBuilder.__init__` calls `only_default_engine_services(fail_fast=True, market_product_resources=...)`); `src/onlyalpha/research/worker_main.py:113` (`only_default_engine_services(fail_fast=True)`). Both have `postgres.dsn`, `OnlyUserDataLayout`, `runtime_generations` authority in scope. `packages/onlyalpha-authoring-execution-worker/src/onlyalpha_authoring_execution_worker/generation.py:210` has no integration concept.
- Runtime admission: `only_admit_data_source_runtime_configuration` / `only_resolve_data_source_runtime_configuration` (`src/onlyalpha/runtime/data_source_integration.py:37,75,117`), broker equivalents (`src/onlyalpha/runtime/broker_integration.py:37,59,103,147`); `_reject_unhosted_generation` rejects ANY non-null `runtime_generation_fingerprint` with `INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE`. resolver=None + INTEGRATION mode → `INTEGRATION_RUNTIME_RESOLVER_UNAVAILABLE`.
- Engine admission evidence: `OnlyUserDataLayout.runtime_admission_evidence_path(engine_id, runtime_id, cluster_id, config_fingerprint)` (`src/onlyalpha/output/user_data.py:98`); recovery: `OnlyEngine.recover_cluster_from_evidence` (`src/onlyalpha/engine/engine.py:125`), recovery path requires exact binding (`INTEGRATION_RUNTIME_RECOVERY_BINDING_REQUIRED`).
- Tushare integration mode: `OnlyTushareDataSourceFactory.parse_runtime_integration_config(public_configuration, resolved_secrets)` returns `OnlyTushareConfig.parse({**public_configuration, "token_env": None, "token": resolved_secrets["token"]})` (`plugs/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare/data_source/factory.py`). Legacy `resolve_token()` reads env first (`config.py`).
- Agent mode CLI: `packages/onlyalpha-agent-orchestrator/src/onlyalpha_agent_orchestrator/node_main.py` — `--model-configuration-mode` required (:58-62), INTEGRATION triple `--integration-runtime-authority-url/--integration-runtime-authority-token-file/--model-profile-file` (:83-87), `CONFIGURATION_MODE_CONFLICT` fencing (:118-138), `compose_from_integration` (:124-135) → `OnlyAgentProductionRuntimeV1.compose_from_integration` calls `provider_resolver.admit_new(model_profile)` at startup (`production.py:547-565`).
- Transport: `OnlyAgentProviderRuntimeAuthorityConfigV1(base_url, bearer_token, timeout_seconds=10.0, verify_tls=True)` accepts both `http` and `https` (`provider_integration.py:299-323`); `verify_tls=False` silently uses `ssl._create_unverified_context()` (:593); client `OnlyHttpAgentProviderRuntimeAuthorityV1` (:337-440) collapses errors to `AGENT_PROVIDER_AUTHORITY_UNAVAILABLE`/`AGENT_WORKFLOW_RUNTIME_MISMATCH`.
- Server authority: `packages/onlyalpha-http-server/src/onlyalpha_http_server/agent_provider_runtime.py` — `/internal/v1/agent-provider-runtime/{admit-new,continue-exact}`, bearer via `secrets.compare_digest`, returns plaintext `api_credential`; mounted only when `--agent-runtime-token-file` given (`main.py:1010-1024`); server-side resolver requires `require_current_revision=True, require_ready_probe=True` for admit-new (`provider_integration.py:253-262`).
- Model profile: `OnlyAgentModelProfileV1(schema_version=1, provider_integration_id, provider_revision_fingerprint[64hex], provider_runtime_configuration_fingerprint[64hex], model_id, model_version, required_capabilities ⊇ {CHAT, STRUCTURED_OUTPUT}, model_profile_fingerprint[self-verifying])` — `provider_integration.py:50-124`.
- Deployment: `deploy/docker-compose.dev.yml` — agent service hardcoded `--model-configuration-mode LEGACY` with NO bootstrap flags (:154-155, i.e. currently an *unconfigured* stub); api service lacks `--agent-runtime-token-file`/`--agent-node-url`; `scripts/bootstrap.py` provisions migrations + `only_ensure_dev_master_key` only; networks: `database` (internal) + `application`; fixture pattern: `tests/runtime_support/binance_spot_probe_fixture.py` run via `python -m` in runtime image, certs on shared volume, `SSL_CERT_FILE` env.
- Existing architecture gates to extend: `tests/architecture/test_integration_configuration_boundaries.py` (forbidden-import lists at :55-74 for runtime/plugs/agent-orch and :168-187 for runtime/research/backtest; master-key pin at :152-165), `tests/architecture/test_agent_orchestration_boundaries.py`, `tests/architecture/test_database_compose_deployment.py` (compose pinning pattern).
- Recovery facts: L4 commit `f0c9274c` regenerated both `test-data/recovery/{long_close_multi_fill,multi_cluster_close}_baseline/` (strategy_fingerprints `f5b1399155f63fdf…` → `b8e389ad83146692237c20a8bd8949c2f9ae840872f6facdff25f27d300014eb`); drift source is `16ac75a6` "Repository Semantic Identity Cleanup" (edited `src/onlyalpha/strategy/admission.py`, `strategy/execution.py`, `calculation/compatibility.py`, `calculation/equivalence.py`, `tests/runtime_support/runner.py` string literals → implementation fingerprint change), NOT L4 (`git diff 2c85813a..fb34756f -- src/` touches no strategy/canonicalization module). Regeneration tool: `scripts/regenerate_recovery_baselines.py --baseline {…}` (unguarded, manual, referenced only in `docs/testing.md:89`); guard: `tests/support/recovery_baselines.py:78` `RECOVERY_BASELINE_STRATEGY_IDENTITY_MISMATCH`.
- Lanes (`scripts/test_suite.py`): `RESEARCH_POSTGRES` = tests/research/postgres + tests/persistence + test_postgres_operational_authority.py; `RESEARCH_PRODUCT_CERTIFICATION` = tests/certification/research_product + test_research_deployment_boundaries.py, selector `postgres or not external`, run by CI job `research-product-certification` with a Postgres service container; `database-compose` CI job runs compose `test` profile → `database-acceptance` lane. Postgres test fixture pattern: `tests/persistence/conftest.py` (`postgres_dsn` drops/recreates schema + migrates), markers `[pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]`.

---

### Task 1: CF-A — Canonical production Integration Runtime composition helper

**Files:**
- Create: `src/onlyalpha/persistence/postgres/integration_runtime_composition.py`
- Modify: `src/onlyalpha/persistence/postgres/__init__.py` (exports)
- Test: `tests/persistence/test_integration_runtime_composition.py`

**Interfaces:**
- Consumes: `OnlyIntegrationRuntimeResolver`, `OnlyIntegrationRuntimeGenerationReader` (application.integration_runtime); `OnlyIntegrationTypeCatalog`; `OnlyPostgresIntegrationStore`, `OnlyPostgresCredentialAuthority`, `OnlyPostgresIntegrationProbeStore`, `OnlyPostgresOperationalConnectionOptions`, `only_load_master_key`; `OnlyDataSourceFactoryRegistry`, `OnlyBrokerFactoryRegistry`; `OnlyIntegrationTypeDescriptorV1`.
- Produces (used by Tasks 2, 7, 8):
  ```python
  @dataclass(frozen=True, slots=True)
  class OnlyIntegrationRuntimeCompositionV1:
      postgres_dsn: str
      master_key_path: Path
      connection_options: OnlyPostgresOperationalConnectionOptions | None = None
      runtime_generations: OnlyIntegrationRuntimeGenerationReader | None = None
      component_types: tuple[OnlyIntegrationTypeDescriptorV1, ...] = ()

  def only_compose_integration_runtime_resolver(
      composition: OnlyIntegrationRuntimeCompositionV1,
      data_sources: OnlyDataSourceFactoryRegistry,
      brokers: OnlyBrokerFactoryRegistry,
  ) -> OnlyIntegrationRuntimeResolver: ...
  ```

Placement rationale: `src/onlyalpha/runtime/**`, `src/onlyalpha/research/**`, `src/onlyalpha/backtest/**` are forbidden from importing integration persistence (architecture gates at `tests/architecture/test_integration_configuration_boundaries.py:55,168`); `persistence/postgres` already imports `application.integration_*` (product store), so this module follows the established dependency direction and becomes the single sanctioned composition root for persistence-backed resolvers.

- [ ] **Step 1: Write failing tests** in `tests/persistence/test_integration_runtime_composition.py` (no DB needed for construction; do NOT request the `postgres_dsn` fixture in these tests so they run outside Postgres lanes too):

```python
"""Production composition of the persistence-backed Integration Runtime Resolver."""

from pathlib import Path

import pytest
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.persistence.postgres import (
    MASTER_KEY_FILE,
    OnlyIntegrationRuntimeCompositionV1,
    only_compose_integration_runtime_resolver,
    only_ensure_dev_master_key,
)


def _composition(root: Path, dsn: str = "postgresql://onlyalpha:onlyalpha@127.0.0.1:5432/onlyalpha") -> OnlyIntegrationRuntimeCompositionV1:
    return OnlyIntegrationRuntimeCompositionV1(postgres_dsn=dsn, master_key_path=root / MASTER_KEY_FILE)


def test_composes_resolver_from_postgres_authorities(tmp_path: Path) -> None:
    only_ensure_dev_master_key(tmp_path / MASTER_KEY_FILE)
    resolver = only_compose_integration_runtime_resolver(
        _composition(tmp_path), OnlyDataSourceFactoryRegistry(), OnlyBrokerFactoryRegistry()
    )
    assert resolver is not None  # PC-01: non-null canonical resolver


def test_missing_master_key_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(Exception) as excinfo:  # PC-04
        only_compose_integration_runtime_resolver(
            _composition(tmp_path), OnlyDataSourceFactoryRegistry(), OnlyBrokerFactoryRegistry()
        )
    assert "CREDENTIAL_MASTER_KEY_MISSING" in str(excinfo.value)


def test_composition_module_never_provisions_master_key() -> None:
    source = Path("src/onlyalpha/persistence/postgres/integration_runtime_composition.py").read_text(encoding="utf-8")
    assert "only_ensure_dev_master_key" not in source
    assert "only_load_master_key" in source
```

Plus a PC-05 test (stable infrastructure error, no legacy fallback) placed in `tests/runtime/test_data_source_integration_runtime.py` style but using the production helper with an unreachable DSN:

```python
def test_integration_admission_with_unreachable_authority_fails_with_stable_error(tmp_path: Path) -> None:
    only_ensure_dev_master_key(tmp_path / MASTER_KEY_FILE)
    resolver = only_compose_integration_runtime_resolver(
        _composition(tmp_path, dsn="postgresql://onlyalpha:onlyalpha@127.0.0.1:1/onlyalpha"),
        OnlyDataSourceFactoryRegistry(),
        OnlyBrokerFactoryRegistry(),
    )
    # admit an INTEGRATION_REVISION data-source runtime config (copy config construction from
    # tests/integration/test_data_source_integration_runtime.py) and assert:
    # pytest.raises(OnlyIntegrationRuntimeError) with code INTEGRATION_RUNTIME_PERSISTENCE_UNAVAILABLE
    # (verify exact code raised by resolver when load_integration fails; do NOT expect any LEGACY result)
```

If the unreachable-DSN connection attempt is slow, point the DSN at a closed port on 127.0.0.1 (port 1 refuses instantly).

- [ ] **Step 2: Run tests, verify they fail** (`uv run pytest tests/persistence/test_integration_runtime_composition.py -v` → ImportError).

- [ ] **Step 3: Implement the module** (complete):

```python
"""Single production composition root for the persistence-backed Integration Runtime Resolver.

Bootstrap provisions Integration authority state; this module only loads it. A missing
durable master key fails closed. The type catalog is a projection over the caller's
already-discovered plugin registries — this module performs no plugin discovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeGenerationReader,
    OnlyIntegrationRuntimeResolver,
)
from onlyalpha.application.integration_type_catalog import OnlyIntegrationTypeCatalog
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.persistence.postgres.credentials import OnlyPostgresCredentialAuthority, only_load_master_key
from onlyalpha.persistence.postgres.integration_probe_store import OnlyPostgresIntegrationProbeStore
from onlyalpha.persistence.postgres.integration_store import OnlyPostgresIntegrationStore
from onlyalpha.persistence.postgres.operational import OnlyPostgresOperationalConnectionOptions
from onlyalpha.plugin.integration import OnlyIntegrationTypeDescriptorV1


@dataclass(frozen=True, slots=True)
class OnlyIntegrationRuntimeCompositionV1:
    postgres_dsn: str
    master_key_path: Path
    connection_options: OnlyPostgresOperationalConnectionOptions | None = None
    runtime_generations: OnlyIntegrationRuntimeGenerationReader | None = None
    component_types: tuple[OnlyIntegrationTypeDescriptorV1, ...] = ()


def only_compose_integration_runtime_resolver(
    composition: OnlyIntegrationRuntimeCompositionV1,
    data_sources: OnlyDataSourceFactoryRegistry,
    brokers: OnlyBrokerFactoryRegistry,
) -> OnlyIntegrationRuntimeResolver:
    master_key = only_load_master_key(composition.master_key_path)
    return OnlyIntegrationRuntimeResolver(
        OnlyPostgresIntegrationStore(composition.postgres_dsn, options=composition.connection_options),
        OnlyPostgresCredentialAuthority(
            composition.postgres_dsn, master_key, options=composition.connection_options
        ),
        OnlyIntegrationTypeCatalog(data_sources, brokers, composition.component_types),
        probes=OnlyPostgresIntegrationProbeStore(composition.postgres_dsn, options=composition.connection_options),
        runtime_generations=composition.runtime_generations,
    )


__all__ = ["OnlyIntegrationRuntimeCompositionV1", "only_compose_integration_runtime_resolver"]
```

Verify the exact import path of `OnlyPostgresOperationalConnectionOptions` (see `src/onlyalpha/persistence/postgres/__init__.py`) and adjust. Export both names from `src/onlyalpha/persistence/postgres/__init__.py` alongside `MASTER_KEY_FILE`.

- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Baseline validation**: `uv run ruff check src/onlyalpha/persistence/postgres/integration_runtime_composition.py tests/persistence/test_integration_runtime_composition.py`, `uv run ruff format --check` same, `uv run mypy src/onlyalpha/persistence/postgres/integration_runtime_composition.py`.
- [ ] **Step 6: Commit** `feat: add canonical production integration runtime composition`.

---

### Task 2: CF-A — Wire production workers through the composition helper

**Files:**
- Modify: `src/onlyalpha/runtime/defaults.py` (new factory parameter)
- Modify: `src/onlyalpha/backtest/worker.py:81-102`, `src/onlyalpha/backtest/worker_main.py`
- Modify: `src/onlyalpha/research/worker_main.py`
- Modify: `packages/onlyalpha-http-server/src/onlyalpha_http_server/main.py:1010-1024` (reuse helper for agent-provider resolver)
- Modify: `packages/onlyalpha-authoring-execution-worker/src/onlyalpha_authoring_execution_worker/generation.py` (docstring only — documented non-consumer)
- Test: `tests/runtime/test_default_engine_services_integration_factory.py` (new), extend `tests/architecture/test_integration_configuration_boundaries.py`
- Fix fixtures of any existing test that starts a worker main without a master key (audit below)

**Interfaces:**
- Consumes: Task 1 helper.
- Produces: `only_default_engine_services(..., integration_runtime_resolver_factory: Callable[[OnlyDataSourceFactoryRegistry, OnlyBrokerFactoryRegistry], OnlyIntegrationRuntimeResolver] | None = None)`; `OnlyBacktestProductEnginePlanBuilder(..., integration_runtime_resolver_factory=None)`.

Design decisions (frozen):
- The factory runs ONCE inside `only_default_engine_services` right after internal plugin discovery, so the catalog projects the engine's own discovered registries (no second discovery, §10 of spec). Supplying both `integration_runtime_resolver` and the factory → `ValueError("INTEGRATION_RUNTIME_COMPOSITION_CONFLICT")`.
- Workers ALWAYS pass the factory (production topology). Missing master key ⇒ worker startup fails closed with `CREDENTIAL_MASTER_KEY_MISSING` (spec §9, PC-04). Bootstrap provisions the key in canonical topology (compose `bootstrap` service already does; affected test fixtures must call `only_ensure_dev_master_key` — test bootstrap context, allowed).
- `runtime_generations` (the worker's `OnlyRuntimeGenerationWorkAuthority`, which structurally satisfies `OnlyIntegrationRuntimeGenerationReader.require_runtime_generation`) is passed through — L4CF-07 explicit reader.
- authoring-execution-worker intentionally does NOT consume Integration runtime config (calculation-authoring domain); resolver stays absent ⇒ INTEGRATION_REVISION admission fails closed with `INTEGRATION_RUNTIME_RESOLVER_UNAVAILABLE`. Document in `generation.py` module docstring (spec §8 "fail explicitly and document why").
- `src/onlyalpha/engine/engine.py:894` lazy default stays resolver-less (non-production convenience path; INTEGRATION admission fails closed). Do not touch.

- [ ] **Step 1: Write failing test** `tests/runtime/test_default_engine_services_integration_factory.py`:

```python
def test_factory_receives_discovered_registries_and_injects_resolver() -> None:
    seen: list[tuple[object, object]] = []

    def factory(data_sources, brokers):
        seen.append((data_sources, brokers))
        return _resolver_stub  # any object; assert identity lands on components

    services = only_default_engine_services(fail_fast=True, integration_runtime_resolver_factory=factory)
    assert len(seen) == 1
    assert seen[0][0] is services.assembler.components.data_sources
    assert seen[0][1] is services.assembler.components.brokers
    assert services.assembler.components.integration_runtime_resolver is _resolver_stub


def test_resolver_and_factory_together_raise_conflict() -> None:
    with pytest.raises(ValueError, match="INTEGRATION_RUNTIME_COMPOSITION_CONFLICT"):
        only_default_engine_services(integration_runtime_resolver=object(), integration_runtime_resolver_factory=lambda d, b: object())
```

(`_resolver_stub`: use a trivially constructed `OnlyIntegrationRuntimeResolver` with in-memory fakes copied from `tests/application/test_integration_runtime.py:159-194`, or `cast` — mypy-clean approach preferred.)

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement defaults.py change**: add parameter; after `discovery = only_discover_plugins(...)` and predicate registration, before `OnlyEngineRunAssembler` construction:

```python
    if integration_runtime_resolver is not None and integration_runtime_resolver_factory is not None:
        raise ValueError("INTEGRATION_RUNTIME_COMPOSITION_CONFLICT")
    resolver = integration_runtime_resolver
    if resolver is None and integration_runtime_resolver_factory is not None:
        resolver = integration_runtime_resolver_factory(data_sources, brokers)
```

pass `resolver` into `OnlyComponentFactoryRegistries`. Import only `Callable` typing + `OnlyIntegrationRuntimeResolver` (already imported) — `defaults.py` must NOT import integration persistence (gate at boundaries test :55 stays green).

- [ ] **Step 4: Wire backtest worker**: `OnlyBacktestProductEnginePlanBuilder.__init__` gains keyword `integration_runtime_resolver_factory: Callable[[OnlyDataSourceFactoryRegistry, OnlyBrokerFactoryRegistry], OnlyIntegrationRuntimeResolver] | None = None`, forwarded to `only_default_engine_services` at `worker.py:97`. In `worker_main.py` after `layout`/`runtime_generations` exist (both already in scope):

```python
    from functools import partial
    from onlyalpha.persistence.postgres import MASTER_KEY_FILE, OnlyIntegrationRuntimeCompositionV1, only_compose_integration_runtime_resolver

    integration_runtime_factory = partial(
        only_compose_integration_runtime_resolver,
        OnlyIntegrationRuntimeCompositionV1(
            postgres_dsn=postgres.dsn,
            master_key_path=layout.root / MASTER_KEY_FILE,
            connection_options=options,
            runtime_generations=runtime_generations,
        ),
    )
```

pass as `integration_runtime_resolver_factory=integration_runtime_factory` into `OnlyBacktestProductEnginePlanBuilder(...)`. Move imports to module top (ruff). Note `src/onlyalpha/backtest/**` may not import `integration_store`/`integration_product_store` (gate :168) — the new composition module is NOT in that forbidden set; Task 2 Step 7 adds it deliberately to the runtime/plugs/agent forbidden list only.

- [ ] **Step 5: Wire research worker**: same pattern at `research/worker_main.py:113`:

```python
    services = only_default_engine_services(fail_fast=True, integration_runtime_resolver_factory=integration_runtime_factory)
```

with `OnlyPostgresOperationalConnectionOptions()` already present as `operational_options`, `postgres.dsn`, `layout.root / MASTER_KEY_FILE`, `runtime_generations`.

- [ ] **Step 6: Refactor http-server agent-provider branch** (`main.py:1010-1024`) to reuse the helper (single composition authority, spec §7):

```python
    agent_provider_runtime=(
        None
        if args.agent_runtime_token_file is None
        else (
            OnlyAgentProviderRuntimeResolverV1(
                only_compose_integration_runtime_resolver(
                    OnlyIntegrationRuntimeCompositionV1(
                        postgres_dsn=postgres.dsn,
                        master_key_path=layout.root / MASTER_KEY_FILE,
                        connection_options=operational_options,
                        component_types=(OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE,),
                    ),
                    data_sources,
                    brokers,
                )
            ),
            args.agent_runtime_token_file.read_text(encoding="utf-8").strip(),
        )
    ),
```

Keep `integration_master_key` loading at :571 for the product/command services (control plane) unchanged. The helper re-reads the same key file — same authority, no second secret path. Add the helper import to http-server main (packages/ is not gate-restricted). Verify variable names (`data_sources`, `brokers`, `operational_options`, `layout`) against actual main.py scope at :920-960 and adjust.

- [ ] **Step 7: Extend architecture gates** in `tests/architecture/test_integration_configuration_boundaries.py`:
  - Add `"onlyalpha.persistence.postgres.integration_runtime_composition"` to BOTH forbidden sets (:56 runtime/plugs/agent-orch, :169 runtime/research/backtest) — workers import it from `worker_main.py` under `src/onlyalpha/backtest|research`… **wait**: the :168 gate roots include those dirs, so adding the module to that forbidden set would fail. Resolution: the :168 gate forbids *binding integration revision semantics inside runtime/research/backtest business logic*; worker mains are composition roots. Mechanically: keep :168 set unchanged (it lists `integration_store`, `integration_product_store`, `integration_configuration`, `integration_application` — the helper module is a different name), and add a NEW positive gate test:

```python
def test_production_workers_compose_the_canonical_integration_runtime_resolver() -> None:
    for relative in ("src/onlyalpha/backtest/worker_main.py", "src/onlyalpha/research/worker_main.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "only_compose_integration_runtime_resolver" in source
        assert "integration_runtime_resolver_factory" in source
        assert "only_ensure_dev_master_key" not in source


def test_only_the_composition_root_assembles_persistence_backed_resolvers() -> None:
    construction_sites = {
        str(path.relative_to(ROOT))
        for root in (ROOT / "src", ROOT / "packages", ROOT / "plugs")
        for path in _python_files(root)
        if "OnlyIntegrationRuntimeResolver(" in path.read_text(encoding="utf-8")
    }
    assert construction_sites <= {
        "src/onlyalpha/application/integration_runtime.py",  # class definition site
        "src/onlyalpha/persistence/postgres/integration_runtime_composition.py",
        "packages/onlyalpha-http-server/src/onlyalpha_http_server/main.py",  # via helper import only — see below
    }
```

    Refine after implementation: if http-server main.py only calls the helper (no direct `OnlyIntegrationRuntimeResolver(` construction), the allowlist shrinks to the first two entries — prefer that and assert it. Also add the composition module to the runtime/plugs/agent forbidden list at :56 (runtime must not import it directly; factories receive callables).
  - Update the master-key pin test (:152-165) if it enumerates files; add assertion that `integration_runtime_composition.py` contains `only_load_master_key` and not `only_ensure_dev_master_key` (already unit-tested in Task 1; gate keeps it permanent).

- [ ] **Step 8: Audit and fix affected tests**: `grep -rln "worker_main" tests/` → `tests/research/postgres/test_backtest_execution_authority.py`, `test_postgres_authority.py`, `test_parameter_search_recovery.py`, `tests/certification/research_product/*` (crash_worker.py etc.), `tests/backtest/test_worker.py`. For each that starts a worker main against a tmp user-data root: ensure the fixture provisions `only_ensure_dev_master_key(root / MASTER_KEY_FILE)` before startup (certification support already does at `tests/certification/research_product/support.py:34` — verify). Run those test files locally (postgres-marked ones via compose `test` profile) and fix fallout. Do NOT weaken any assertion; only add key provisioning.

- [ ] **Step 9: Document authoring-execution-worker boundary**: extend module docstring of `generation.py`: it composes calculation-authoring engine services only; it intentionally never consumes Integration-backed runtime configuration — INTEGRATION_REVISION admission fails closed with `INTEGRATION_RUNTIME_RESOLVER_UNAVAILABLE`. No code change.

- [ ] **Step 10: Run targeted tests** (PC-01..PC-05 evidence): new tests + `uv run pytest tests/runtime/test_data_source_integration_runtime.py tests/runtime/test_broker_integration_runtime.py tests/integration/test_data_source_integration_runtime.py tests/integration/test_broker_integration_vertical.py tests/backtest/test_worker.py tests/architecture/test_integration_configuration_boundaries.py -x -q` (PC-03 legacy compatibility = these existing LEGACY workloads unchanged, plus database-acceptance lane in Task 11).
- [ ] **Step 11: ruff/mypy affected scope**; `uv run python scripts/test_suite.py architecture`.
- [ ] **Step 12: Commit** `feat: wire production workers to canonical integration runtime composition`.

---

### Task 3: CF-E — Agent secret transport confidentiality

**Files:**
- Modify: `packages/onlyalpha-agent-orchestrator/src/onlyalpha_agent_orchestrator/provider_integration.py:299-323` (config), `node_main.py` (flag)
- Modify: callers using `http://` authority URLs in tests/dev: `packages/onlyalpha-agent-orchestrator/tests/test_node_service.py`, `tests/test_production_symbolic_e2e.py`, `packages/onlyalpha-http-server/tests/test_agent_provider_runtime.py` (client-side configs only)
- Test: extend `packages/onlyalpha-agent-orchestrator/tests/test_provider_integration.py`

**Interfaces:**
- Produces: `OnlyAgentProviderRuntimeAuthorityConfigV1(base_url, bearer_token, timeout_seconds=10.0, verify_tls=True, allow_insecure_transport=False)`; error code `AGENT_PROVIDER_AUTHORITY_TRANSPORT_INSECURE`; node_main flag `--allow-insecure-runtime-authority-transport` (store_true, INTEGRATION-mode-only).

Design (frozen — smallest architecture-compatible option, spec §31): production confidentiality = HTTPS with strict certificate verification (client-side enforcement; server TLS termination remains infrastructure/deployment concern — document in report §E). `http://` or `verify_tls=False` require the explicit dev-only flag; without it → fail closed at configuration time (startup), not at request time. Bearer auth unchanged and still mandatory. No large secret-service subsystem.

- [ ] **Step 1: Write failing tests** in `test_provider_integration.py`:

```python
def test_production_configuration_rejects_plain_http_authority() -> None:  # AG-04
    with pytest.raises(ValueError, match="AGENT_PROVIDER_AUTHORITY_TRANSPORT_INSECURE"):
        OnlyAgentProviderRuntimeAuthorityConfigV1("http://runtime-authority.internal/internal/v1/agent-provider-runtime", "token")


def test_production_configuration_rejects_unverified_tls() -> None:
    with pytest.raises(ValueError, match="AGENT_PROVIDER_AUTHORITY_TRANSPORT_INSECURE"):
        OnlyAgentProviderRuntimeAuthorityConfigV1("https://runtime-authority.internal/x", "token", verify_tls=False)


def test_explicit_development_configuration_may_allow_plain_http() -> None:
    config = OnlyAgentProviderRuntimeAuthorityConfigV1("http://127.0.0.1:1/x", "token", allow_insecure_transport=True)
    assert config.base_url == "http://127.0.0.1:1/x"


def test_https_configuration_accepted_and_bearer_still_required() -> None:
    config = OnlyAgentProviderRuntimeAuthorityConfigV1("https://runtime-authority.internal/x", "token")
    assert config.verify_tls is True
    with pytest.raises(ValueError, match="AGENT_PROVIDER_AUTHORITY_CONFIG_INVALID"):
        OnlyAgentProviderRuntimeAuthorityConfigV1("https://runtime-authority.internal/x", "")


def test_untrusted_certificate_fails_closed(tmp_path) -> None:
    # real-socket proof: start ssl server with fresh self-signed cert (pattern:
    # tests/runtime_support/binance_spot_probe_fixture.py cert generation), point config at
    # https://127.0.0.1:<port> with verify_tls=True (no SSL_CERT_FILE trust), call admit_new
    # with a stub profile through OnlyHttpAgentProviderRuntimeAuthorityV1 and assert
    # ValueError("AGENT_PROVIDER_AUTHORITY_UNAVAILABLE") — TLS verification failure is fail-closed.


def test_trusted_ca_https_transport_succeeds(tmp_path, monkeypatch) -> None:
    # same server, but monkeypatch.setenv("SSL_CERT_FILE", str(ca_bundle)) so the default
    # ssl context trusts it; stub transport NOT injected — real urlopen round-trip returns a
    # canned admit-new response body; assert resolved endpoint and that the sentinel
    # api_credential never appears in repr(config), repr(resolved), or str(exc) on error paths.
```

For the TLS server tests, factor a tiny in-test `ssl.HTTPServer` helper (copy cert-generation approach from `tests/runtime_support/binance_spot_probe_fixture.py`; keep server handler responses canned). If `urlopen` default context does not honor `SSL_CERT_FILE` on the platform used in CI, fall back to `ssl.create_default_context(cafile=...)` injection ONLY if the transport already accepts a context — check `_authority_transport` (`provider_integration.py:586-604`): it passes `context=` when `verify_tls` is False; for True it passes default. Python's default context DOES honor `SSL_CERT_FILE` env — assert via the test itself.

Also node_main-level tests in `test_node_service.py`: `--allow-insecure-runtime-authority-transport` with LEGACY mode → `CONFIGURATION_MODE_CONFLICT`; with INTEGRATION mode + `http://` URL → starts (compose path); without flag + `http://` → `AGENT_PROVIDER_AUTHORITY_TRANSPORT_INSECURE`.

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**: add field `allow_insecure_transport: bool = False` (after `verify_tls`); in `__post_init__` after scheme validation:

```python
        if (parsed.scheme == "http" or not self.verify_tls) and not self.allow_insecure_transport:
            raise ValueError("AGENT_PROVIDER_AUTHORITY_TRANSPORT_INSECURE")
        if not isinstance(self.allow_insecure_transport, bool):
            raise ValueError("AGENT_PROVIDER_AUTHORITY_CONFIG_INVALID")
```

node_main: add flag; pass `allow_insecure_transport=args.allow_insecure_runtime_authority_transport` into the config at :129-132; in the LEGACY branch, if the flag is set → `CONFIGURATION_MODE_CONFLICT` (it is integration-transport configuration). Update existing test/dev callers that use `http://` authority URLs to pass `allow_insecure_transport=True` explicitly (test_node_service.py :432-504 area, test_production_symbolic_e2e.py :735 area — e2e spawns a local http authority, an explicit development configuration), and their node_main argv to include the new flag where the e2e goes through CLI.

- [ ] **Step 4: Run all agent-orchestrator + http-server agent tests, verify pass.**
- [ ] **Step 5: Extend gate**: in `tests/architecture/test_integration_configuration_boundaries.py` (or `test_agent_orchestration_boundaries.py` — follow existing ownership of agent gates), assert `provider_integration.py` rejects `http` without `allow_insecure_transport` (source-level: `"AGENT_PROVIDER_AUTHORITY_TRANSPORT_INSECURE" in source`) and that the insecure flag string appears in `deploy/docker-compose.dev.yml` only for the dev agent service (Task 6 adds it; add this assertion in Task 6's gate work if ordering requires).
- [ ] **Step 6: ruff/mypy affected; commit** `feat: require confidential agent provider runtime transport`.

---

### Task 4: CF-B-1 — Deterministic OpenAI-compatible provider fixture

**Files:**
- Create: `tests/runtime_support/openai_compatible_provider_fixture.py`
- Test: `tests/runtime_support` has no test dir — add smoke test `tests/research/agent/test_openai_compatible_provider_fixture.py` (or co-locate per placement standard under the consuming area; agent area = `tests/research/agent/`)

**Interfaces:**
- Produces: runnable module `python -m tests.runtime_support.openai_compatible_provider_fixture --host H --port P [--token T] [--model-id M] [--model-version V]` serving:
  - `GET /v1/models` → `{"object":"list","data":[{"id":<model_id>,"object":"model","owned_by":"onlyalpha-fixture"}]}`; requires `Authorization: Bearer <token>` else 401.
  - `POST /v1/chat/completions` → minimal deterministic chat response (mirror what `OnlyOpenAICompatibleModelAdapterV1` expects; copy shapes from the fake model server in `packages/onlyalpha-agent-orchestrator/tests/test_production_symbolic_e2e.py` around the `model_url` fixture).
  - `GET /health` → 200.
  - Defaults: token `onlyalpha-dev-agent-provider-secret`, model id `onlyalpha-dev-model`, version `1.0.0`.
- Consumed by Task 5 (bootstrap probe + secret) and Task 6 (compose service).

- [ ] **Step 1: Read `OnlyOpenAICompatibleAgentProviderProbe` implementation** (imported in http-server `main.py:941`; locate via grep `class OnlyOpenAICompatibleAgentProviderProbe`) to learn the exact probe request sequence, expected response schema and auth header semantics for instrument `models`. The fixture MUST satisfy real probe checks CONNECTIVITY + AUTHENTICATION + MODEL_DISCOVERY.
- [ ] **Step 2: Write smoke test first** (start fixture in-process on an ephemeral port via `http.server.ThreadingHTTPServer` in a thread — same structure as `binance_spot_probe_fixture` main; assert `/v1/models` 200 with token, 401 without, `/health` 200, chat completion shape).
- [ ] **Step 3: Implement fixture; run smoke test green.**
- [ ] **Step 4: ruff/mypy; commit** `feat: add deterministic openai compatible provider fixture`.

---

### Task 5: CF-B-2 — Bootstrap provisions canonical Agent provider authority state

**Files:**
- Create: `scripts/agent_provider_bootstrap.py` (imported by `scripts/bootstrap.py`; same `if __package__` import pattern as `scripts/database.py` usage at bootstrap.py:24-27)
- Modify: `scripts/bootstrap.py` (call provisioning after `only_ensure_dev_master_key`)
- Test: `tests/research/postgres/test_agent_provider_bootstrap.py` (postgres-marked) or `tests/persistence/`— follow where existing bootstrap-adjacent postgres tests live (`tests/research/postgres/`); reuse `postgres_dsn` fixture

**Interfaces:**
- Produces: `only_provision_dev_agent_authority(*, postgres_dsn, user_data_root, provider_base_url, provider_api_credential, model_id, model_version, connection_options=None) -> OnlyDevAgentAuthorityProvision` returning `(model_profile_path, control_token_path, product_token_path, runtime_token_path, integration_id, revision_fingerprint)`. Idempotent: if the integration (stable dev id e.g. `OnlyIntegrationId("dev-agent-provider")`) already has a current revision and profile file exists and is valid, skip re-provisioning (compose restarts must not rotate identity).
- Consumes: `OnlyIntegrationCommandService` + `OnlyPostgresIntegrationProductStore` + `OnlyIntegrationTypeCatalog` (with `OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE`) + `OnlyIntegrationProbeService`/`OnlyIntegrationProbeCatalog`/`OnlyOpenAICompatibleAgentProviderProbe` + `OnlyAgentModelProfileV1` + registries via `only_discover_plugins`.

Provisioning sequence (all through existing authorities — no direct SQL, no second command path):
1. `only_ensure_dev_master_key` (already in bootstrap) → load key.
2. Discover plugins into fresh registries (`only_discover_plugins(..., fail_fast=True)`), build catalog with the agent-provider component type.
3. Write token files under `layout.root / "secrets"` with 0600: `agent-control-token`, `agent-product-token`, `agent-runtime-token` (generated via `secrets.token_urlsafe(32)`; stable across restarts — create only if absent).
4. `create_integration(OnlyCreateIntegration(command_id=..., integration_id=dev_id, type_id="openai.compatible.agent_provider", display_name="Dev Agent Provider"))` (idempotent command ids — reuse the receipt-replay semantics of `OnlyPostgresIntegrationProductStore`; use deterministic command ids derived from dev integration id so re-runs replay).
5. `update_integration_draft` to set public config: `base_url=provider_base_url`, `connect_timeout_seconds=10`, `read_timeout_seconds=60`, `verify_tls=False` (plain-HTTP dev fixture; explicit dev configuration value, NOT a transport guard bypass).
6. `set_integration_secret(field_id="api_credential", plaintext_secret=provider_api_credential)`.
7. `publish_integration_revision` → R1.
8. Run probe for R1 through `OnlyIntegrationProbeService` (real probe execution against fixture) → assert attempt status READY (fail bootstrap otherwise — fail closed).
9. Query published revision facts (`OnlyIntegrationQueryService` / store `load_integration`+`load_revision`) → build `OnlyAgentModelProfileV1(provider_integration_id=str(dev_id), provider_revision_fingerprint=<R1 fingerprint>, provider_runtime_configuration_fingerprint=<revision runtime_configuration_fingerprint>, model_id, model_version, required_capabilities=("CHAT","MODEL_DISCOVERY","STRUCTURED_OUTPUT"), model_profile_fingerprint=<compute>)`; write canonical JSON to `layout.root / "agent" / "model-profile.json"` (0644). Check `OnlyAgentModelProfileV1` for a fingerprint computation helper (read `provider_integration.py:50-124`; e2e builds profiles at `test_node_service.py:450-458` — copy that construction exactly).
10. Print provisioning summary JSON (no secrets) from bootstrap.

Read the exact `OnlyCreateIntegration`/`OnlyUpdateIntegrationDraft`/`OnlySetIntegrationSecret`/`OnlyPublishIntegrationRevision` field lists and command-id types from `src/onlyalpha/application/integration_application.py:50-150` and copy e2e/test usage patterns (`tests/application/test_integration_application.py`, `tests/research/postgres/test_postgres_authority.py` integration sections) for construction details.

- [ ] **Step 1: Write failing postgres-marked test**: provision against real postgres + in-process Task-4 fixture (start on ephemeral port); assert: token files exist 0600; model-profile.json parses via `OnlyAgentModelProfileV1.from_dict`; published revision is current; probe attempt READY recorded; second run is idempotent (same revision fingerprint, no new secrets generation — assert credential generation stays 1); summary contains no secret values.
- [ ] **Step 2: Run (compose test profile), verify fail.**
- [ ] **Step 3: Implement `scripts/agent_provider_bootstrap.py`; hook into `scripts/bootstrap.py` behind dev env with safe defaults:

```python
    only_provision_dev_agent_authority(
        postgres_dsn=postgres_dsn,
        user_data_root=user_data_root,
        provider_base_url=os.environ.get("ONLYALPHA_AGENT_PROVIDER_BASE_URL", "http://agent-provider-fixture:8080/v1"),
        provider_api_credential=os.environ.get("ONLYALPHA_AGENT_PROVIDER_TOKEN", "onlyalpha-dev-agent-provider-secret"),
        model_id=os.environ.get("ONLYALPHA_AGENT_PROVIDER_MODEL_ID", "onlyalpha-dev-model"),
        model_version=os.environ.get("ONLYALPHA_AGENT_PROVIDER_MODEL_VERSION", "1.0.0"),
    )
```

- [ ] **Step 4: Run test green; ruff/mypy; commit** `feat: provision dev agent provider authority in bootstrap`.

---

### Task 6: CF-B-3 — Canonical deployment cutover (compose + gates + docs)

**Files:**
- Modify: `deploy/docker-compose.dev.yml` (agent, api, bootstrap services; new `agent-provider-fixture` service)
- Modify/extend: `tests/architecture/test_agent_orchestration_boundaries.py` (AG-01/AG-02/AG-04-deployment pins), `tests/architecture/test_database_compose_deployment.py` if it enumerates services
- Create: `docs/deployment_agent.md` (or extend the existing deployment doc — check `docs/` for the canonical deployment/README location; if none, create `docs/deployment.md` section) documenting canonical INTEGRATION_REVISION deployment and the explicit non-canonical LEGACY compatibility invocation
- Test: AG-03 already enforced at `node_main.py:118-138` + `test_node_service.py:507-534` — verify coverage, extend if the both-configurations case is missing

**Compose changes (frozen design):**

```yaml
  agent-provider-fixture:
    build: {context: .., dockerfile: deploy/Dockerfile.dev, target: runtime}
    command: ["python", "-m", "tests.runtime_support.openai_compatible_provider_fixture", "--host", "0.0.0.0", "--port", "8080"]
    healthcheck: {test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"], interval: 5s, timeout: 5s, retries: 20, start_period: 5s}
    networks: [database, application]
```

- `bootstrap`: add `depends_on: agent-provider-fixture: condition: service_healthy`; keep `ONLYALPHA_AGENT_PROVIDER_*` defaults (fixture alias on database network).
- `api`: command gains `"--agent-node-url", "http://agent:8010", "--agent-control-token-file", "/var/lib/onlyalpha/secrets/agent-control-token", "--agent-runtime-token-file", "/var/lib/onlyalpha/secrets/agent-runtime-token"`.
- `agent`: add volume `user-data:/var/lib/onlyalpha:ro`; command becomes:

```yaml
    command:
      ["serve", "--model-configuration-mode", "INTEGRATION_REVISION",
       "--durable-root", "/var/lib/onlyalpha-agent",
       "--coordination-root", "/var/run/onlyalpha-agent",
       "--product-api-url", "http://api:8000",
       "--product-api-contract", "<path-to-contracts/product-api/v2/openapi.json inside runtime image — verify WORKDIR in deploy/Dockerfile.dev>",
       "--product-token-file", "/var/lib/onlyalpha/secrets/agent-product-token",
       "--integration-runtime-authority-url", "http://api:8000/internal/v1/agent-provider-runtime",
       "--integration-runtime-authority-token-file", "/var/lib/onlyalpha/secrets/agent-runtime-token",
       "--model-profile-file", "/var/lib/onlyalpha/agent/model-profile.json",
       "--allow-insecure-runtime-authority-transport",
       "--control-token-file", "/var/lib/onlyalpha/secrets/agent-control-token",
       "--host", "0.0.0.0", "--port", "8010"]
```

(`--allow-insecure-runtime-authority-transport` is the explicit dev-only exception — internal compose network, plain HTTP; production deployments omit it and must serve HTTPS. The agent healthcheck now proves real INTEGRATION_REVISION startup: `compose_from_integration` → `admit_new` → current revision + READY probe.)

- [ ] **Step 1: Write failing gates first** (AG-01/AG-02): parse `deploy/docker-compose.dev.yml` (yaml) in `test_agent_orchestration_boundaries.py`:

```python
def test_canonical_agent_deployment_selects_integration_revision() -> None:  # AG-01
    compose = yaml.safe_load((ROOT / "deploy/docker-compose.dev.yml").read_text(encoding="utf-8"))
    command = compose["services"]["agent"]["command"]
    mode = command[command.index("--model-configuration-mode") + 1]
    assert mode == "INTEGRATION_REVISION"
    assert "LEGACY" not in command


def test_legacy_agent_deployment_is_documented_explicit_compatibility_only() -> None:  # AG-02
    doc = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")  # adjust to actual doc path
    assert "--model-configuration-mode LEGACY" in doc
    assert "compatibility" in doc.lower()
```

Check how `test_database_compose_deployment.py` parses compose and follow its conventions (it may forbid new services or networks — update its expectations deliberately, since compose topology governance requires owner sanction: this task IS the sanctioned change; AGENTS.md §6 compose-topology rule is about not adding a *second* compose file — we extend the canonical one).

- [ ] **Step 2: Implement compose + docs changes; run gates green.**
- [ ] **Step 3: Real-stack validation**: `docker compose -f deploy/docker-compose.dev.yml up -d --build` (or the repo's canonical bring-up per `docs/testing.md` / `deploy/run-web-e2e.sh`), then assert: bootstrap logs provisioning summary; api healthy; agent healthy (INTEGRATION_REVISION admit_new succeeded against fixture + READY probe); `curl -s -H "Authorization: Bearer $(docker compose exec -T api cat /var/lib/onlyalpha/secrets/agent-runtime-token)" -X POST http://localhost:8000/internal/v1/agent-provider-runtime/admit-new -d '{"schema_version":1,"model_profile":<profile json>}'` returns binding; wrong token → 401. Then `docker compose down` (keep volumes decision: default down without -v; document).
- [ ] **Step 4: Run web-e2e compose lane locally if practical** (`deploy/run-web-e2e.sh`) to catch regressions from api/agent flag changes; otherwise rely on CI `web-product-e2e`.
- [ ] **Step 5: ruff/mypy n/a (yaml/docs); run `uv run python scripts/test_suite.py architecture`; commit** `feat: cut canonical agent deployment over to integration revision`.

---

### Task 7: CF-C-1 — Tushare real-PostgreSQL Product→Runtime golden vertical

**Files:**
- Create: `tests/certification/integration_runtime/__init__.py`, `conftest.py` (copy `postgres_dsn` fixture pattern from `tests/persistence/conftest.py:13`), `test_tushare_postgres_runtime_golden.py`
- Modify: `scripts/test_suite.py` — add `"tests/certification/integration_runtime"` to `RESEARCH_PRODUCT_CERTIFICATION` lane paths (lane expression `postgres or not external` already selects the new postgres-marked tests; CI job `research-product-certification` provides the Postgres service). This lane-definition change is task-sanctioned (spec §54 requires the golden vertical in canonical validation) — record justification in the commit message.
- Modify: `tests/architecture/test_quality_policy_contract.py` / lane-pinning tests IF they enumerate lane paths (check and update deliberately).

**Interfaces:** Consumes Task 1 helper (production composition — spec §22: no test-only resolver path), `OnlyIntegrationCommandService` + `OnlyPostgresIntegrationProductStore` (product authority), `only_admit_data_source_runtime_configuration` / `only_resolve_data_source_runtime_configuration`, `OnlyUserDataLayout.runtime_admission_evidence_path`.

Test module markers: `pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]` (copy from `tests/research/postgres/test_postgres_authority.py:119`). Sentinels: R1 token `golden-tushare-token-r1`, R2 token `golden-tushare-token-r2`, ambient conflict `ambient-tushare-token-must-not-win`.

- [ ] **Step 1: Write the golden tests** (ordered, sharing module-scoped provisioning fixture):
  - `test_create_set_secret_publish_r1` (PG-01): real migrate; product store + command service + catalog (real discovered tushare descriptor via `only_discover_plugins`); create integration (stable id), draft public config (tushare public fields per descriptor — read `plugs/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare/descriptor.py` for the exact contract fields), set secret R1 sentinel, publish → capture R1 revision fingerprint + runtime_configuration_fingerprint + credential generation (expect 1).
  - `test_production_resolver_admits_exact_r1` (PG-02): compose resolver via `only_compose_integration_runtime_resolver` with real dsn + dev master key; build `OnlyDataSourceRuntimeConfig` in INTEGRATION_REVISION mode referencing R1 (copy config construction from `tests/integration/test_data_source_integration_runtime.py`); `only_admit_data_source_runtime_configuration(...)`; assert resolved `OnlyTushareConfig.token == golden-tushare-token-r1`, `token_env is None`; assert binding records exact credential generation 1 + revision fingerprint.
  - `test_ambient_environment_token_cannot_win` (PG-03): `monkeypatch.setenv("ONLYALPHA_TUSHARE_TOKEN", ambient)`; re-resolve; token still R1 sentinel; also assert `resolve_token()` on the resolved config never consults env (token_env None).
  - `test_restart_and_rotate_then_recover_r1_exactly` (PG-04/PG-05): persist admitted binding evidence to `OnlyUserDataLayout(tmp).runtime_admission_evidence_path(...)` exactly as the engine does (copy from engine admission-evidence writer / `tests/integration/test_data_source_integration_runtime.py`); rotate secret → generation 2 (`OnlySetIntegrationSecret` again on new draft) + publish R2; construct a FRESH resolver instance (restart); recover old work via `only_admit_data_source_runtime_configuration(..., recovery=True)` with the persisted R1 binding → token == R1 sentinel (exact old generation still available → succeeds with old secret); new admission (current pointer) → R2 + generation-2 token; reference-admission of R1 with `require_current_revision=True` → fails (no current-Revision substitution).
  - `test_secret_never_leaks` (PG-06): assert R1/R2 sentinels absent from: evidence file text, `repr(binding)`, `repr(resolved.secrets)`, `str(resolved.public_configuration)`, command receipts, and a raw DB dump of the integration + credential tables (`SELECT`::text via psycopg — ciphertext only); assert credential rows contain neither sentinel.
- [ ] **Step 2: Run via compose test profile**: `docker compose -f deploy/docker-compose.dev.yml --profile test run --rm test python -m pytest tests/certification/integration_runtime -q` → iterate to green. (This is Required Behavior evidence — real Postgres is不可替代.)
- [ ] **Step 3: Lane check**: `uv run python scripts/test_suite.py research-product-certification` locally with `ONLYALPHA_POSTGRES_DSN` from a compose-run, or rely on Step 2 + CI; confirm lane selector picks the new directory.
- [ ] **Step 4: ruff/mypy; commit** `test: certify tushare product to runtime postgres golden vertical`.

---

### Task 8: CF-C-2 — Broker real-PostgreSQL bounded proof

**Files:**
- Create: `tests/certification/integration_runtime/test_binance_broker_postgres_runtime_golden.py`
- Reuse: `tests/runtime_support/binance_spot_probe_fixture.py` (in-process start with temp CA dir, `SSL_CERT_FILE` monkeypatch — copy compose fixture invocation pattern), fake private transport pattern from `tests/integration/test_broker_integration_vertical.py`

**Scope (bounded, spec §21 — no real orders):** real Postgres integration persistence + real encrypted api_key/api_secret generations + real READY probe attempt (executed by `OnlyIntegrationProbeService` against the in-process deterministic Binance-shaped fixture) + production-helper resolver. Prove: new LIVE-mode admission requires current exact Revision + exact READY probe + exact secret generations; `OnlyBinanceSpotBrokerIntegrationConfig` carries direct secrets; conflicting `ONLYALPHA_BINANCE_TESTNET_API_KEY/SECRET` env cannot win; rotate→R2 does not mutate R1 recovery.

- [ ] **Step 1: Read seams**: binance broker integration type descriptor (`plugs/onlyalpha-plugin-binance/src/onlyalpha_plugin_binance/descriptor.py`), probe factory wiring (`spot/data_source/probe.py`, broker `probe` at `spot/broker_factory.py`), `OnlyPostgresIntegrationProbeStore` write surface, and how `OnlyIntegrationProbeService` executes+records attempts (mirror `tests/application/test_integration_probe.py` real-probe patterns and the web-e2e binance golden flow).
- [ ] **Step 2: Write failing tests** mirroring Task 7 structure for the broker category (`expected_category=BROKER`, LIVE admission flags `require_current_revision=True, require_ready_probe=True`), including a negative: delete/withhold the READY probe attempt (fresh integration without probe) → admission fails `INTEGRATION_RUNTIME_PROBE_NOT_READY` (verify exact code in `integration_runtime.py:385+`).
- [ ] **Step 3: Implement to green via compose test profile; if the real probe execution proves non-hermetic in pytest (network aliasing constraints), fall back to composing the probe service against `http://127.0.0.1:<fixture-port>` with fixture-served HTTPS + CA via SSL_CERT_FILE (the fixture already supports this); document the chosen path in the test module docstring. Do NOT fake the probe attempt row if the real probe service can run.**
- [ ] **Step 4: ruff/mypy; commit** `test: certify binance broker postgres runtime golden vertical`.

---

### Task 9: CF-D — Recovery baseline independent re-certification (Path B) + governance rule

**Evidence already established (research phase, 2026-09-22):** fingerprint change `f5b13991…`→`b8e389ad…` originates from `16ac75a6` (semantic-identity string edits in `strategy/admission.py`, `strategy/execution.py`, `calculation/compatibility.py`, `calculation/equivalence.py`, `tests/runtime_support/runner.py` → implementation fingerprint drift), sealed-baseline mismatch predated L4 (9 inherited recovery failures), L4's `f0c9274c` diff touches no strategy/canonicalization module, and the regenerated baselines match current canonical semantics. ⇒ Path B (independent re-certification) is justified; Path A (revert) would restore a known-invalid identity and re-red the lane without proof.

**Files:**
- Create: `docs/audits/recovery_baseline_recertification.md` (process doc — allowed identity under AGENTS.md §9.1)
- Modify: `docs/testing.md` (permanent golden-evidence governance rule, spec §28)
- Create: `tests/architecture/test_recovery_baseline_governance.py`
- NO changes to `test-data/recovery/**` (baselines stay as regenerated by f0c9274c)

- [ ] **Step 1: Deterministic reproduction proof**: run `uv run python scripts/regenerate_recovery_baselines.py --baseline long_close_multi_fill` and `--baseline multi_cluster_close` (verify exact CLI choices first), then `git status --porcelain test-data/recovery/` and `git diff --stat test-data/recovery/` MUST be empty — committed baselines are byte-reproducible from current canonical code. If any diff appears: STOP, investigate (non-determinism or invalid baseline ⇒ escalate; do not commit regenerated output). Restore any accidental dirt with `git checkout -- test-data/recovery` ONLY after recording the diff as evidence.
- [ ] **Step 2: Write `docs/audits/recovery_baseline_recertification.md`** containing exactly (spec §27): old identity `f5b1399155f63fdf…` (sealed at `6e62c18e`), new identity `b8e389ad83146692237c20a8bd8949c2f9ae840872f6facdff25f27d300014eb`, semantic reason (`16ac75a6` semantic-identity cleanup changed implementation fingerprint inputs; no trading-semantics change), migration rationale (baselines sealed before the drift absorbed it; L4 regeneration at `f0c9274c` restored lane truth), exact regenerated artifacts (6 files listed), reproduction command (Step 1 command + expected empty diff), review result (filled in Task 11 after Independent Review).
- [ ] **Step 3: Add governance rule to `docs/testing.md`** near the regeneration command (:89): any change to a recovery baseline / golden snapshot / certified canonical projection / expected historical fingerprint requires explicit written justification (independent re-certification record under `docs/audits/`); regenerating golden evidence merely to make CI green is forbidden; CI green never certifies a baseline change by itself.
- [ ] **Step 4: Add gate** `tests/architecture/test_recovery_baseline_governance.py`:

```python
def test_golden_recovery_baselines_are_not_regenerated_by_automation() -> None:
    callers = {
        str(path.relative_to(ROOT))
        for root in (ROOT / ".github/workflows", ROOT / "scripts", ROOT / "tests")
        for path in root.rglob("*")
        if path.suffix in {".py", ".yml", ".yaml", ".sh"}
        and "regenerate_recovery_baselines" in path.read_text(encoding="utf-8")
    }
    assert callers <= {"tests/architecture/test_recovery_baseline_governance.py", "tests/support/recovery_baselines.py"}


def test_recovery_identity_guard_remains_fail_closed() -> None:
    source = (ROOT / "tests/support/recovery_baselines.py").read_text(encoding="utf-8")
    assert "RECOVERY_BASELINE_STRATEGY_IDENTITY_MISMATCH" in source


def test_baseline_changes_require_documented_recertification() -> None:
    doc = (ROOT / "docs/testing.md").read_text(encoding="utf-8")
    assert "docs/audits/" in doc and "justification" in doc.lower()
```

(Adjust allowlist to actual current referencers found by grep — verified today: `tests/architecture/test_product_surface_boundaries.py`, `tests/support/recovery_baselines.py`, `docs/testing.md`, `docs/architecture/product_authority_contract.toml`; include the architecture test file in the allowlist or scope the gate to `.github/workflows` + `scripts/test_suite.py` + `scripts/verify.py` + non-architecture tests — choose the tightest formulation that passes on the current tree and fails if a lane/CI ever invokes the script.)
- [ ] **Step 5: Run recovery lane** `uv run python scripts/test_suite.py recovery` — expected green at HEAD (baselines match); this also re-proves L4CF-35 (assertions unweakened — `tests/runtime/recovery/test_recovery_baseline_support.py:49` still asserts the guard fires).
- [ ] **Step 6: ruff/mypy (new test file); commit (SEPARATE commit, spec §27)** `docs: independently re-certify recovery baseline strategy identity`.

---

### Task 10: CF-F — Runtime Generation hosting boundary made explicit

**Files:**
- Modify: `src/onlyalpha/runtime/data_source_integration.py` + `src/onlyalpha/runtime/broker_integration.py` (module/`_reject_unhosted_generation` docstrings only — behavior already fail-closed and stays)
- Modify: `docs/integration_type_configuration_contract.md` (add "Runtime Generation hosting boundary" section)
- Test: extend `tests/runtime/test_broker_integration_runtime.py` (broker-side gap)

**Decision (frozen, spec §36):** full historical Plugin artifact hosting is OUT of scope — evidence: `OnlyRuntimeGenerationManifest` (`src/onlyalpha/runtime/generation.py:125`) has no integration/plugin artifact concept; the only materialization mechanism (`packages/onlyalpha-runtime-generation-manager/host_manager.py`) hosts isolated SEARCH workers per ADR 0126, not in-process DataSource/Broker factory registries; no Postgres generation ledger exists. Classified as a later dedicated task.

- [ ] **Step 1: Write failing broker test** mirroring `tests/runtime/test_data_source_integration_runtime.py:124-163`: broker binding with a well-formed non-null `runtime_generation_fingerprint`, matching binance broker factory registered in ambient registry → `only_admit_broker_runtime_configuration` raises `OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE")`; assert the ambient factory was never used (no latest/ambient fallback).
- [ ] **Step 2: Run, verify fail (or pass if trivially covered — verify it genuinely exercises the broker adapter path; then implement if needed).**
- [ ] **Step 3: Document**: in both adapters' `_reject_unhosted_generation` docstrings state the exact boundary — declared generations are validated by the Resolver's generation reader but execution of exact historical Plugin artifacts is not hosted yet; any non-null fingerprint fails closed; no latest fallback; hosting is a dedicated future task. Add matching section to `docs/integration_type_configuration_contract.md` (current support: generation fingerprint modeled + validated + fail-closed; unsupported: historical plugin artifact execution).
- [ ] **Step 4: ruff/mypy; targeted runtime tests; commit** `docs: bound runtime generation hosting to explicit fail-closed contract` (include test in same commit — it pins documented behavior).

---

### Task 11: Full validation, Independent Review, Final Report

- [ ] **Step 1: Run spec §54 validation order locally** (record outputs):
  1. targeted production composition tests (Task 1/2 files); 2. targeted resolver tests (`tests/application/test_integration_runtime.py`); 3. Tushare golden (compose test profile); 4. Broker vertical + broker golden; 5. agent provider unit tests (`packages/onlyalpha-agent-orchestrator/tests`, `tests/research/agent`); 6. agent production symbolic e2e (`tests/.../test_production_symbolic_e2e.py` per its lane `agent-orchestrator`); 7. agent secure transport tests; 8. runtime admission/recovery tests (`tests/runtime`, recovery lane); 9. recovery baseline independent check (Task 9 Step 1 re-run); 10. `scripts/test_suite.py architecture`; 11. database-compose (`docker compose --profile test run --rm test python scripts/test_suite.py database-acceptance`); 12. `scripts/test_suite.py research-product-certification` (with Postgres); 13. static/type/format (`release-static` lane or repo canonical ruff/mypy invocation per `docs/testing.md`); 14-15. CodeQL + full Layered Quality run in CI after push.
- [ ] **Step 2: Known-inherited failures triage**: `fast` lane fingerprint-assertion reds documented in project memory (`tests/strategy/test_strategy_qualification.py::test_same_subject_policy_and_research_evidence…`, `plugs/onlyalpha-plugin-indicators/tests/test_b1_financial.py`) — classify each failure as new regression / inherited / certified migration (spec §51); do not mask.
- [ ] **Step 3: Bounded Independent Review (HIGH-risk + proof-bearing)**: dispatch a fresh reviewer subagent with scope = Modification Scope + real Impact Scope + directly-related invariants; reviewer MUST independently re-derive: composition authority uniqueness, fail-closed paths (missing key, missing DB, insecure transport, unhosted generation, missing probe), no-latest guarantees (Revision/Secret/Generation), admission atomicity ordering (binding persisted before runnable), legacy/integration fence, secret non-leakage, and the CF-D re-certification evidence chain; then compare against implementation. Fill review result into `docs/audits/recovery_baseline_recertification.md` and the final report. Critical=0, High=0 required.
- [ ] **Step 4: Push branch + open PR** (confirm with user first); classify CI results per §51; CodeQL + Third-Party Quality + Layered Quality from CI (L4CF-52..54).
- [ ] **Step 5: Write Final Report (spec §56 A–J) in conversation** — before/after SHAs, commits by workstream, composition ownership map, canonical vs legacy deployment, golden vertical evidence trace (Create→Secret→Publish R1→Restart→Resolve R1→Rotate→Publish R2→Recover R1), transport mechanism, recovery Path B proof, generation boundary statement, negative guarantees checklist, CI lane classification, review verdict. Report `L4 CLOSURE_FIX_CLOSED`; assess `L4 FULLY_CLOSED` criteria (production composition canonical ✓, agent canonical deployment integration-based ✓, real postgres certification ✓, recovery governance resolved ✓, Critical=0 High=0 ✓). Then STOP — do not begin L5. End with current Beijing time (AGENTS.md rule).

## Self-Review Notes

- Spec coverage: CF-A→Tasks 1-2; CF-B→Tasks 4-6; CF-C→Tasks 7-8; CF-D→Task 9; CF-E→Task 3; CF-F→Task 10; §46 gates distributed (Tasks 2/3/6/9/10) + §54/§56→Task 11. L4CF-40..43 (negative guarantees) enforced by Global Constraints + review checklist. L4CF-44..54 → Task 11.
- Acceptance-test mapping: PC-01..05→Tasks 1-2; AG-01..04→Tasks 3/6; PG-01..06→Tasks 7-8; recovery→Task 9; generation→Task 10.
- Open verification points flagged inline for executors: exact probe check semantics (Task 4 Step 1), profile fingerprint computation helper (Task 5), `OnlyUpdateIntegrationDraft` field shape (Tasks 5/7), image WORKDIR for contract path (Task 6), lane-path pinning tests (Task 7), probe-store write surface (Task 8). These are read-before-implement steps, not placeholders.
- Type consistency: helper signature `only_compose_integration_runtime_resolver(composition, data_sources, brokers)` and `OnlyIntegrationRuntimeCompositionV1` fields used identically in Tasks 1/2/6/7/8; factory parameter name `integration_runtime_resolver_factory` identical in defaults.py, worker.py, worker mains, and gates.

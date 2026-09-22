"""Tushare Product→Runtime golden vertical certified against real PostgreSQL.

One unbroken authority chain, no mocks and no test-only resolver path: Product commands
(create → draft → secret → publish) flow through ``OnlyIntegrationCommandService`` over
``OnlyPostgresIntegrationProductStore``; Runtime admission of the exact published Revision
flows through the canonical production composition root
``only_compose_integration_runtime_resolver``. The module is one ordered narrative: the
provisioned Revision R1 feeds exact admission, ambient-environment defeat, restart plus
secret rotation recovery semantics, and the secret non-leakage proof.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import psycopg
import pytest
from onlyalpha_plugin_tushare.config import OnlyTushareConfig
from onlyalpha_plugin_tushare.data_source.factory import OnlyTushareDataSourceFactory
from psycopg import sql

from onlyalpha.application.integration_application import (
    OnlyCreateIntegration,
    OnlyIntegrationCommandResult,
    OnlyIntegrationCommandService,
    OnlyPublishIntegrationRevision,
    OnlySetIntegrationSecret,
    OnlyUpdateIntegrationDraft,
)
from onlyalpha.application.integration_configuration import (
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationSecretBinding,
)
from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeBindingV1,
    OnlyIntegrationRuntimeError,
    OnlyIntegrationRuntimeResolver,
)
from onlyalpha.application.integration_type_catalog import OnlyIntegrationTypeCatalog
from onlyalpha.application.product_command_receipt import OnlyProductCommandId, OnlyProductCommandReceipt
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.config.models import (
    OnlyDataSourceCoverageConfig,
    OnlyDataSourceRuntimeConfig,
    OnlyJsonMapping,
    OnlyRuntimeConfigurationMode,
)
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId, OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    MASTER_KEY_FILE,
    OnlyIntegrationRuntimeCompositionV1,
    OnlyPostgresIntegrationProductStore,
    only_compose_integration_runtime_resolver,
    only_ensure_dev_master_key,
)
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.plugin.integration import OnlyIntegrationCategory, only_integration_capability_ids
from onlyalpha.runtime.data_source_integration import (
    only_admit_data_source_runtime_configuration,
    only_resolve_data_source_runtime_configuration,
)

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]

NOW = datetime(2026, 9, 22, tzinfo=UTC)
TUSHARE_TYPE_ID = "tushare.daily.market_data"
INTEGRATION_ID = OnlyIntegrationId("7d4c1a8e-9b2f-4d6a-8c3e-2f1a0b9d8c7e")
R1_TOKEN = "golden-tushare-token-r1"
R2_TOKEN = "golden-tushare-token-r2"
AMBIENT_TOKEN = "ambient-tushare-token-must-not-win"
SOURCE_ID = OnlyMarketDataSourceId("tushare-golden")
ENGINE_ID = OnlyEngineId("tushare-golden")
RUNTIME_ID = OnlyRuntimeId("tushare-golden-runtime")
CLUSTER_ID = OnlyClusterId("tushare-golden-cluster")
REQUIRED_CAPABILITIES = OnlyDataSourceCapabilities(historical_bars=True)
INSTRUMENT_TABLES = (
    "integration",
    "integration_draft",
    "integration_draft_secret_binding",
    "integration_revision",
    "integration_revision_secret_binding",
    "product_credential",
    "product_command_admission",
    "product_command_receipt",
)


def _command(number: int) -> OnlyProductCommandId:
    return OnlyProductCommandId(f"00000000-0000-4000-8000-{number:012d}")


@dataclass
class GoldenVertical:
    """Artifacts captured by provisioning and extended by the ordered narrative."""

    dsn: str
    master_key_path: Path
    data_sources: OnlyDataSourceFactoryRegistry
    brokers: OnlyBrokerFactoryRegistry
    catalog: OnlyIntegrationTypeCatalog
    store: OnlyPostgresIntegrationProductStore
    commands: OnlyIntegrationCommandService
    user_data_root: Path
    r1_revision_fingerprint: str
    r1_runtime_configuration_fingerprint: str
    r1_secret_binding: OnlyIntegrationSecretBinding
    provision_results: tuple[OnlyIntegrationCommandResult, ...]
    receipts: list[OnlyProductCommandReceipt] = field(default_factory=list)
    admitted_binding: dict[str, object] | None = None
    evidence_path: Path | None = None
    r2_revision_fingerprint: str | None = None
    r2_runtime_configuration_fingerprint: str | None = None
    r2_secret_binding: OnlyIntegrationSecretBinding | None = None


@pytest.fixture(scope="module")
def golden_vertical(postgres_dsn: str, tmp_path_factory: pytest.TempPathFactory) -> GoldenVertical:
    """Provision the Product side once: create, draft, secret R1, publish Revision R1."""

    user_data_root = tmp_path_factory.mktemp("tushare-golden-user-data")
    master_key_path = user_data_root / MASTER_KEY_FILE
    master_key = only_ensure_dev_master_key(master_key_path)
    data_sources = OnlyDataSourceFactoryRegistry()
    brokers = OnlyBrokerFactoryRegistry()
    only_discover_plugins(
        data_sources,
        brokers,
        OnlyBrokerFeeContractRegistry(),
        OnlyMarketProductFactoryRegistry(),
        None,
        fail_fast=True,
        include_calculations=False,
    )
    catalog = OnlyIntegrationTypeCatalog(data_sources, brokers)
    store = OnlyPostgresIntegrationProductStore(postgres_dsn, master_key, now=lambda: NOW)
    commands = OnlyIntegrationCommandService(catalog, store, master_key)
    results = (
        commands.create_integration(
            OnlyCreateIntegration(_command(1), INTEGRATION_ID, TUSHARE_TYPE_ID, "Tushare Golden")
        ),
        commands.update_integration_draft(
            OnlyUpdateIntegrationDraft(_command(2), INTEGRATION_ID, 1, {"frequency": "1d", "adjustment": "qfq"}, None)
        ),
        commands.set_integration_secret(OnlySetIntegrationSecret(_command(3), INTEGRATION_ID, 2, "token", R1_TOKEN)),
        commands.publish_integration_revision(OnlyPublishIntegrationRevision(_command(4), INTEGRATION_ID, 3)),
    )
    r1_revision_fingerprint = results[3].receipt.outcome_ref.outcome_id
    revision = store.load_revision(r1_revision_fingerprint)
    secret_bindings = store.load_revision_secret_bindings(r1_revision_fingerprint)
    if len(secret_bindings) != 1:
        raise AssertionError("provisioning must publish exactly one secret binding")
    return GoldenVertical(
        dsn=postgres_dsn,
        master_key_path=master_key_path,
        data_sources=data_sources,
        brokers=brokers,
        catalog=catalog,
        store=store,
        commands=commands,
        user_data_root=user_data_root,
        r1_revision_fingerprint=r1_revision_fingerprint,
        r1_runtime_configuration_fingerprint=revision.runtime_configuration_fingerprint,
        r1_secret_binding=secret_bindings[0],
        provision_results=results,
        receipts=[result.receipt for result in results],
    )


def _compose_resolver(golden: GoldenVertical) -> OnlyIntegrationRuntimeResolver:
    """Compose a fresh resolver instance through the canonical production composition root."""

    return only_compose_integration_runtime_resolver(
        OnlyIntegrationRuntimeCompositionV1(
            postgres_dsn=golden.dsn,
            master_key_path=golden.master_key_path,
        ),
        golden.data_sources,
        golden.brokers,
    )


def _integration_source(binding: object) -> OnlyDataSourceRuntimeConfig:
    return OnlyDataSourceRuntimeConfig(
        source_id=SOURCE_ID,
        plugin_id="",
        enabled=True,
        data_version=OnlyDataVersion("golden"),
        coverage=OnlyDataSourceCoverageConfig(instrument_ids=(OnlyInstrumentId.parse("000001.SZ"),)),
        configuration_mode=OnlyRuntimeConfigurationMode.INTEGRATION_REVISION,
        integration_binding=cast(OnlyJsonMapping, dict(cast(dict[str, object], binding))),
    )


def _r1_reference(golden: GoldenVertical) -> dict[str, object]:
    return {
        "integration_id": INTEGRATION_ID.value,
        "revision_fingerprint": golden.r1_revision_fingerprint,
    }


def test_create_set_secret_publish_r1(golden_vertical: GoldenVertical) -> None:
    golden = golden_vertical
    assert [result.replayed for result in golden.provision_results] == [False, False, False, False]

    descriptor = golden.catalog.require(TUSHARE_TYPE_ID)
    record = next(item for item in golden.data_sources.records() if item.descriptor.plugin_id == "tushare")
    assert record.factory.integration_type == descriptor

    integration = golden.store.load_integration(INTEGRATION_ID)
    assert integration.type_id == TUSHARE_TYPE_ID
    assert integration.lifecycle_state is OnlyIntegrationLifecycleState.ACTIVE
    assert integration.current_revision_fingerprint == golden.r1_revision_fingerprint

    revision = golden.store.load_revision(golden.r1_revision_fingerprint)
    assert revision.revision_sequence == 1
    assert revision.type_descriptor_fingerprint == descriptor.fingerprint
    assert dict(revision.configuration_document) == {
        "adjustment": "qfq",
        "cache_policy": "prefer_cache",
        "frequency": "1d",
        "strict_validation": True,
    }
    assert dict(revision.probe_configuration_document or {}) == {"instrument": "000001.SZ"}

    assert golden.r1_secret_binding.field_id == "token"
    assert golden.r1_secret_binding.credential_generation == 1

    draft = golden.store.load_draft(INTEGRATION_ID)
    assert draft.draft_version == 4
    assert draft.base_revision_fingerprint == golden.r1_revision_fingerprint


def test_production_resolver_admits_exact_r1(golden_vertical: GoldenVertical) -> None:
    golden = golden_vertical
    resolver = _compose_resolver(golden)

    admitted = only_admit_data_source_runtime_configuration(
        _integration_source(_r1_reference(golden)),
        resolver,
        REQUIRED_CAPABILITIES,
    )
    binding = OnlyIntegrationRuntimeBindingV1.from_dict(dict(admitted.integration_binding or {}))
    assert binding.integration_id == INTEGRATION_ID
    assert binding.revision_fingerprint == golden.r1_revision_fingerprint
    assert binding.runtime_configuration_fingerprint == golden.r1_runtime_configuration_fingerprint
    assert binding.type_id == TUSHARE_TYPE_ID
    assert binding.category is OnlyIntegrationCategory.DATA_SOURCE
    assert binding.runtime_generation_fingerprint is None

    factory, config = only_resolve_data_source_runtime_configuration(
        admitted, golden.data_sources, resolver, REQUIRED_CAPABILITIES
    )
    assert isinstance(factory, OnlyTushareDataSourceFactory)
    assert isinstance(config, OnlyTushareConfig)
    assert config.token == R1_TOKEN
    assert config.token_env is None
    assert config.resolve_token() == R1_TOKEN

    assert golden.store.load_revision_secret_bindings(binding.revision_fingerprint) == (golden.r1_secret_binding,)
    golden.admitted_binding = binding.to_dict()


def test_ambient_environment_token_cannot_win(golden_vertical: GoldenVertical, monkeypatch: pytest.MonkeyPatch) -> None:
    golden = golden_vertical
    monkeypatch.setenv("ONLYALPHA_TUSHARE_TOKEN", AMBIENT_TOKEN)
    resolver = _compose_resolver(golden)

    admitted = only_admit_data_source_runtime_configuration(
        _integration_source(_r1_reference(golden)),
        resolver,
        REQUIRED_CAPABILITIES,
    )
    _, config = only_resolve_data_source_runtime_configuration(
        admitted, golden.data_sources, resolver, REQUIRED_CAPABILITIES
    )
    assert isinstance(config, OnlyTushareConfig)
    assert config.token == R1_TOKEN
    assert config.token_env is None
    assert config.resolve_token() == R1_TOKEN


def test_restart_and_rotate_then_recover_r1_exactly(golden_vertical: GoldenVertical) -> None:
    golden = golden_vertical
    assert golden.admitted_binding is not None
    binding = OnlyIntegrationRuntimeBindingV1.from_dict(golden.admitted_binding)

    payload = {
        "data_sources": [
            {"source_id": SOURCE_ID.value, "integration_binding": golden.admitted_binding},
        ]
    }
    evidence_path = OnlyUserDataLayout(golden.user_data_root).runtime_admission_evidence_path(
        ENGINE_ID,
        RUNTIME_ID,
        CLUSTER_ID,
        only_canonical_fingerprint(payload),
    )
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_bytes(only_canonical_json(payload).encode("utf-8"))
    golden.evidence_path = evidence_path

    restarted = _compose_resolver(golden)
    persisted = json.loads(evidence_path.read_text(encoding="utf-8"))["data_sources"][0]["integration_binding"]
    recovered = only_admit_data_source_runtime_configuration(
        _integration_source(persisted), restarted, REQUIRED_CAPABILITIES, recovery=True
    )
    assert OnlyIntegrationRuntimeBindingV1.from_dict(dict(recovered.integration_binding or {})) == binding
    _, recovered_config = only_resolve_data_source_runtime_configuration(
        recovered, golden.data_sources, restarted, REQUIRED_CAPABILITIES
    )
    assert isinstance(recovered_config, OnlyTushareConfig)
    assert recovered_config.token == R1_TOKEN

    rotated = golden.commands.set_integration_secret(
        OnlySetIntegrationSecret(_command(5), INTEGRATION_ID, 4, "token", R2_TOKEN)
    )
    published = golden.commands.publish_integration_revision(
        OnlyPublishIntegrationRevision(_command(6), INTEGRATION_ID, 5)
    )
    golden.receipts.extend((rotated.receipt, published.receipt))
    r2_revision_fingerprint = published.receipt.outcome_ref.outcome_id
    assert r2_revision_fingerprint != golden.r1_revision_fingerprint
    r2_revision = golden.store.load_revision(r2_revision_fingerprint)
    r2_secret_bindings = golden.store.load_revision_secret_bindings(r2_revision_fingerprint)
    assert len(r2_secret_bindings) == 1
    assert r2_secret_bindings[0].credential_id == golden.r1_secret_binding.credential_id
    assert r2_secret_bindings[0].credential_generation == 2
    golden.r2_revision_fingerprint = r2_revision_fingerprint
    golden.r2_runtime_configuration_fingerprint = r2_revision.runtime_configuration_fingerprint
    golden.r2_secret_binding = r2_secret_bindings[0]

    rotated_resolver = _compose_resolver(golden)

    # The retired exact generation is never substituted: R1 recovery now fails closed.
    with pytest.raises(OnlyIntegrationRuntimeError) as retired:
        only_admit_data_source_runtime_configuration(
            _integration_source(persisted), rotated_resolver, REQUIRED_CAPABILITIES, recovery=True
        )
    assert retired.value.code == "INTEGRATION_RUNTIME_SECRET_UNAVAILABLE"

    current = golden.store.load_integration(INTEGRATION_ID).current_revision_fingerprint
    assert current == r2_revision_fingerprint
    admitted_r2 = only_admit_data_source_runtime_configuration(
        _integration_source({"integration_id": INTEGRATION_ID.value, "revision_fingerprint": r2_revision_fingerprint}),
        rotated_resolver,
        REQUIRED_CAPABILITIES,
    )
    _, r2_config = only_resolve_data_source_runtime_configuration(
        admitted_r2, golden.data_sources, rotated_resolver, REQUIRED_CAPABILITIES
    )
    assert isinstance(r2_config, OnlyTushareConfig)
    assert r2_config.token == R2_TOKEN
    assert r2_config.token_env is None

    with pytest.raises(OnlyIntegrationRuntimeError) as substituted:
        rotated_resolver.admit_new_reference(
            INTEGRATION_ID.value,
            golden.r1_revision_fingerprint,
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
            required_capabilities=only_integration_capability_ids(REQUIRED_CAPABILITIES),
            require_current_revision=True,
        )
    assert substituted.value.code == "INTEGRATION_RUNTIME_BINDING_INVALID"


def test_secret_never_leaks(golden_vertical: GoldenVertical) -> None:
    golden = golden_vertical
    assert golden.evidence_path is not None
    assert golden.r2_revision_fingerprint is not None
    sentinels = (R1_TOKEN, R2_TOKEN, AMBIENT_TOKEN)

    resolver = _compose_resolver(golden)
    resolved = resolver.admit_new_reference(
        INTEGRATION_ID.value,
        golden.r2_revision_fingerprint,
        expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        required_capabilities=only_integration_capability_ids(REQUIRED_CAPABILITIES),
    )
    admitted_r2 = only_admit_data_source_runtime_configuration(
        _integration_source(resolved.binding.to_dict()), resolver, REQUIRED_CAPABILITIES, recovery=True
    )
    _, config = only_resolve_data_source_runtime_configuration(
        admitted_r2, golden.data_sources, resolver, REQUIRED_CAPABILITIES
    )
    assert isinstance(config, OnlyTushareConfig)
    # Positive control: the sentinel really exists behind the credential authority, so its
    # absence from every durable and observable surface below is meaningful.
    assert config.token == R2_TOKEN

    surfaces = {
        "evidence": golden.evidence_path.read_text(encoding="utf-8"),
        "binding": repr(resolved.binding),
        "secrets": repr(resolved.secrets),
        "public_configuration": str(resolved.public_configuration),
        "runtime_config": repr(config),
        "receipts": repr(tuple(golden.receipts)),
    }
    for name, surface in surfaces.items():
        for sentinel in sentinels:
            assert sentinel not in surface, name

    with psycopg.connect(golden.dsn) as connection:
        dumped = {
            table: tuple(
                cast(str, row[0])
                for row in connection.execute(
                    sql.SQL("SELECT record::text FROM {} AS record").format(sql.Identifier(table))
                ).fetchall()
            )
            for table in INSTRUMENT_TABLES
        }
    assert dumped["product_credential"]
    assert len(dumped["integration_revision"]) == 2
    for table, rows in dumped.items():
        for row in rows:
            for sentinel in sentinels:
                assert sentinel not in row, table

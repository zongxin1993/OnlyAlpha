import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from onlyalpha_plugin_tushare.data_source.resource import OnlyTushareHistoricalDataSource
from onlyalpha_plugin_tushare.descriptor import DATA_INTEGRATION_TYPE

from onlyalpha.application.integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
)
from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeError,
    OnlyIntegrationRuntimeResolver,
)
from onlyalpha.application.integration_type_catalog import OnlyIntegrationTypeCatalog
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.engine.models import OnlyEngineConfig
from onlyalpha.runtime.defaults import only_default_engine_services
from tests.runtime_support.runner import only_migrate_cluster_to_strategy

NOW = datetime(2026, 9, 21, tzinfo=UTC)
INTEGRATION_ID = OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
CREDENTIAL_ID = "ba13b6b1-af9a-450f-833d-48f5002297dc"


@dataclass
class _State:
    integration: OnlyIntegration
    revision: OnlyIntegrationRevision
    bindings: tuple[OnlyIntegrationSecretBinding, ...]

    def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration:
        assert integration_id == self.integration.integration_id
        return self.integration

    def load_revision(self, revision_fingerprint: str) -> OnlyIntegrationRevision:
        assert revision_fingerprint == self.revision.revision_fingerprint
        return self.revision

    def load_revision_secret_bindings(self, revision_fingerprint: str) -> tuple[OnlyIntegrationSecretBinding, ...]:
        assert revision_fingerprint == self.revision.revision_fingerprint
        return self.bindings


class _Credentials:
    def __init__(self) -> None:
        self.reads: list[tuple[str, int]] = []

    def read_secret(self, credential_id: str, credential_generation: int) -> str:
        self.reads.append((credential_id, credential_generation))
        return "exact-tushare-token"


def test_exact_revision_creates_tushare_component_through_engine_without_environment(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ONLYALPHA_TUSHARE_TOKEN", "wrong-environment-token")
    registry = OnlyDataSourceFactoryRegistry()
    from onlyalpha_plugin_tushare.data_source.factory import OnlyTushareDataSourceFactory

    registry.register(OnlyTushareDataSourceFactory())
    catalog = OnlyIntegrationTypeCatalog(registry, OnlyBrokerFactoryRegistry())
    bindings = (OnlyIntegrationSecretBinding("token", CREDENTIAL_ID, 7),)
    revision = OnlyIntegrationRevision.from_resolved(
        integration_id=INTEGRATION_ID,
        revision_sequence=1,
        type_id=DATA_INTEGRATION_TYPE.type_id.value,
        type_descriptor_fingerprint=DATA_INTEGRATION_TYPE.fingerprint,
        type_descriptor_document=DATA_INTEGRATION_TYPE.to_dict(include_fingerprint=False),
        configuration_document={"frequency": "1d", "adjustment": "qfq"},
        probe_configuration_document={"instrument": "000001.SZ"},
        secret_bindings=bindings,
        created_at=NOW,
    )
    integration = OnlyIntegration(
        INTEGRATION_ID,
        revision.type_id,
        "Tushare exact",
        OnlyIntegrationLifecycleState.ACTIVE,
        revision.revision_fingerprint,
        NOW,
        NOW,
    )
    credentials = _Credentials()
    state = _State(integration, revision, bindings)
    resolver = OnlyIntegrationRuntimeResolver(state, credentials, catalog)
    baseline = only_migrate_cluster_to_strategy(
        OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json"),
        tmp_path,
    )
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["strategy"] = {"fingerprint": baseline.strategy.fingerprint}
    payload["factors"] = []
    source_payload = payload["data_sources"][0]
    source_payload.pop("plugin")
    source_payload.pop("extensions", None)
    source_payload["configuration_mode"] = "INTEGRATION_REVISION"
    source_payload["integration"] = {
        "integration_id": INTEGRATION_ID.value,
        "revision_fingerprint": revision.revision_fingerprint,
    }
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)
    services = only_default_engine_services(integration_runtime_resolver=resolver)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("tushare-integration"), tmp_path), services=services)

    engine.add_cluster(config)
    admitted = engine.cluster_definitions[0]
    admitted_binding = admitted.data_sources[0].integration_binding
    assert admitted_binding is not None
    assert admitted_binding["revision_fingerprint"] == revision.revision_fingerprint
    assert "exact-tushare-token" not in str(admitted.normalized_payload)

    state.integration = replace(state.integration, lifecycle_state=OnlyIntegrationLifecycleState.DISABLED)
    engine.initialize()
    runtime = engine.runtimes[0]
    component = cast(OnlyTushareHistoricalDataSource, runtime._plugin_resources[0])  # type: ignore[attr-defined]
    actual_request = component._request  # type: ignore[attr-defined]

    assert component._config.resolve_token() == "exact-tushare-token"  # type: ignore[attr-defined]
    assert set(credentials.reads) == {(CREDENTIAL_ID, 7)}
    assert actual_request.instruments == admitted.reference_data.instrument_by_id
    assert actual_request.universes == admitted.universes
    assert actual_request.coverage == admitted.data_sources[0].coverage
    assert all("000001.SZ" != str(item) for item in actual_request.instruments)

    denied = OnlyEngine(OnlyEngineConfig(OnlyEngineId("tushare-denied"), tmp_path), services=services)
    with pytest.raises(OnlyIntegrationRuntimeError) as raised:
        denied.add_cluster(config)
    assert raised.value.code == "INTEGRATION_RUNTIME_DISABLED"

    disguised = OnlyEngine(OnlyEngineConfig(OnlyEngineId("tushare-disguised"), tmp_path), services=services)
    with pytest.raises(OnlyIntegrationRuntimeError) as disguised_error:
        disguised.add_cluster(admitted)
    assert disguised_error.value.code == "INTEGRATION_RUNTIME_RECOVERY_BINDING_FORBIDDEN"

    recovered = OnlyEngine(OnlyEngineConfig(OnlyEngineId("tushare-recovered"), tmp_path), services=services)
    recovered.recover_cluster(admitted)
    recovered.initialize()
    recovered_component = cast(
        OnlyTushareHistoricalDataSource,
        recovered.runtimes[0]._plugin_resources[0],  # type: ignore[attr-defined]
    )
    assert recovered_component._config.resolve_token() == "exact-tushare-token"  # type: ignore[attr-defined]
    recovered.close()
    engine.close()

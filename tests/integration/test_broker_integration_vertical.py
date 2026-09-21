from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

import pytest
from onlyalpha_plugin_binance.common.private_http import OnlyBinanceHttpResponse
from onlyalpha_plugin_binance.descriptor import SPOT_BROKER_INTEGRATION_TYPE
from onlyalpha_plugin_binance.spot.broker_factory import (
    OnlyBinanceSpotBrokerFactory,
    OnlyBinanceSpotBrokerIntegrationConfig,
    OnlyBinanceSpotBrokerResource,
)

from onlyalpha.application.integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
)
from onlyalpha.application.integration_probe import OnlyIntegrationProbeAttempt
from onlyalpha.application.integration_runtime import OnlyIntegrationRuntimeError, OnlyIntegrationRuntimeResolver
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue
from onlyalpha.broker.reconciliation import OnlyDurableBrokerCommandEvidenceStore
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.config.models import OnlyBrokerRuntimeConfig, OnlyRuntimeConfigurationMode
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyEngineId, OnlyRuntimeId
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.engine.models import OnlyEngineConfig
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.fee.broker_contract import only_simulation_zero_broker_fee_contract
from onlyalpha.plugin.broker import OnlyBrokerCreateRequest
from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities
from onlyalpha.plugin.integration_probe import OnlyIntegrationProbePolicy, OnlyIntegrationProbeRequest
from onlyalpha.runtime.broker_integration import (
    only_admit_broker_runtime_configuration,
    only_resolve_broker_runtime_configuration,
)
from onlyalpha.runtime.defaults import only_default_engine_services
from tests.runtime_support.runner import only_migrate_cluster_to_strategy

NOW = datetime(2026, 9, 21, tzinfo=UTC)
INTEGRATION_ID = OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
KEY_ID = "ba13b6b1-af9a-450f-833d-48f5002297dc"
SECRET_ID = "ca13b6b1-af9a-450f-833d-48f5002297dc"
REQUIRED = OnlyBrokerPluginCapabilities(
    submit_order=True,
    cancel_order=True,
    query_orders=True,
    query_trades=True,
    query_positions=True,
    live_execution=True,
)


class _State:
    def __init__(self, integration: OnlyIntegration) -> None:
        self.integration = integration
        self.revisions: dict[str, OnlyIntegrationRevision] = {}
        self.bindings: dict[str, tuple[OnlyIntegrationSecretBinding, ...]] = {}

    def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration:
        if integration_id != self.integration.integration_id:
            raise LookupError
        return self.integration

    def load_revision(self, fingerprint: str) -> OnlyIntegrationRevision:
        return self.revisions[fingerprint]

    def load_revision_secret_bindings(self, fingerprint: str) -> tuple[OnlyIntegrationSecretBinding, ...]:
        return self.bindings[fingerprint]


class _Credentials:
    def __init__(self) -> None:
        self.reads: list[tuple[str, int]] = []

    def read_secret(self, credential_id: str, generation: int) -> str:
        self.reads.append((credential_id, generation))
        prefix = "key" if credential_id == KEY_ID else "secret"
        return f"{prefix}-generation-{generation}"


class _Catalog:
    @staticmethod
    def require(type_id: str):
        if type_id != SPOT_BROKER_INTEGRATION_TYPE.type_id.value:
            raise LookupError
        return SPOT_BROKER_INTEGRATION_TYPE


class _Probes:
    def __init__(self) -> None:
        self.attempts: dict[str, OnlyIntegrationProbeAttempt] = {}

    def latest_probe_attempt(self, _integration_id: OnlyIntegrationId, fingerprint: str):
        return self.attempts.get(fingerprint)


class _Stream:
    def connect(self, *_args: object) -> None: ...

    def send(self, _payload: bytes) -> None: ...

    def close(self) -> None: ...


def _revision(
    sequence: int, generation: int
) -> tuple[OnlyIntegrationRevision, tuple[OnlyIntegrationSecretBinding, ...]]:
    bindings = (
        OnlyIntegrationSecretBinding("api_key", KEY_ID, generation),
        OnlyIntegrationSecretBinding("api_secret", SECRET_ID, generation),
    )
    revision = OnlyIntegrationRevision.from_resolved(
        integration_id=INTEGRATION_ID,
        revision_sequence=sequence,
        type_id=SPOT_BROKER_INTEGRATION_TYPE.type_id.value,
        type_descriptor_fingerprint=SPOT_BROKER_INTEGRATION_TYPE.fingerprint,
        type_descriptor_document=SPOT_BROKER_INTEGRATION_TYPE.to_dict(include_fingerprint=False),
        configuration_document={"environment": "SPOT_TESTNET", "currencies": {"USDT": 8}},
        probe_configuration_document=None,
        secret_bindings=bindings,
        created_at=NOW,
    )
    return revision, bindings


def _ready_attempt(revision: OnlyIntegrationRevision, generation: int) -> OnlyIntegrationProbeAttempt:
    request = OnlyIntegrationProbeRequest.create(
        probe_attempt_id=f"8ec96368-f447-45fe-9fc2-2596a7c7b9b{generation}",
        integration_id=INTEGRATION_ID.value,
        revision=revision,
        resolved_secrets={
            "api_key": f"key-generation-{generation}",
            "api_secret": f"secret-generation-{generation}",
        },
        policy=OnlyIntegrationProbePolicy(),
        deadline_monotonic=10_000_000_000,
    )

    def read_only(method, url, _headers, _timeout, _maximum):
        assert method == "GET" and "/api/v3/account?" in url and "/api/v3/order" not in url
        return OnlyBinanceHttpResponse(200, {}, b'{"balances":[],"canTrade":true}')

    result = OnlyBinanceSpotBrokerFactory(private_transport=read_only).probe(request)
    return OnlyIntegrationProbeAttempt.from_result(result, revision)


def _reference(revision: OnlyIntegrationRevision) -> OnlyBrokerRuntimeConfig:
    return OnlyBrokerRuntimeConfig(
        OnlyBrokerGatewayId("binance"),
        "",
        True,
        configuration_mode=OnlyRuntimeConfigurationMode.INTEGRATION_REVISION,
        integration_binding=MappingProxyType(
            {
                "integration_id": INTEGRATION_ID.value,
                "revision_fingerprint": revision.revision_fingerprint,
            }
        ),
    )


def test_exact_live_broker_vertical_pins_revision_probe_and_secret_generation(monkeypatch, tmp_path) -> None:
    r1, b1 = _revision(1, 3)
    r2, b2 = _revision(2, 4)
    state = _State(
        OnlyIntegration(
            INTEGRATION_ID,
            SPOT_BROKER_INTEGRATION_TYPE.type_id.value,
            "Binance Spot",
            OnlyIntegrationLifecycleState.ACTIVE,
            r1.revision_fingerprint,
            NOW,
            NOW,
        )
    )
    state.revisions = {r1.revision_fingerprint: r1, r2.revision_fingerprint: r2}
    state.bindings = {r1.revision_fingerprint: b1, r2.revision_fingerprint: b2}
    credentials = _Credentials()
    probes = _Probes()
    probes.attempts[r1.revision_fingerprint] = _ready_attempt(r1, 3)
    probes.attempts[r2.revision_fingerprint] = _ready_attempt(r2, 4)
    resolver = OnlyIntegrationRuntimeResolver(state, credentials, _Catalog(), probes=probes)
    registry = OnlyBrokerFactoryRegistry()
    factory = OnlyBinanceSpotBrokerFactory(user_stream_transport=_Stream)
    registry.register(factory)
    monkeypatch.setenv("ONLYALPHA_BINANCE_TESTNET_API_KEY", "ambient-key-must-not-win")
    monkeypatch.setenv("ONLYALPHA_BINANCE_TESTNET_API_SECRET", "ambient-secret-must-not-win")

    services = only_default_engine_services(integration_runtime_resolver=resolver)
    fee_contract = only_simulation_zero_broker_fee_contract("binance-spot")
    services.assembler.components.broker_fee_contracts.register(fee_contract)
    baseline = only_migrate_cluster_to_strategy(
        OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json"),
        tmp_path,
    )
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["type"] = "LIVE"
    payload["cluster"]["runtime_type"] = "LIVE"
    payload["strategy"] = {"fingerprint": baseline.strategy.fingerprint}
    payload["factors"] = []
    payload["accounts"][0]["broker_fee_contract"] = {
        "contract_id": fee_contract.contract_id,
        "contract_version": fee_contract.contract_version,
    }
    broker_payload = payload["brokers"][0]
    broker_payload.pop("plugin")
    broker_payload.pop("extensions", None)
    broker_payload["configuration_mode"] = "INTEGRATION_REVISION"
    broker_payload["integration"] = {
        "integration_id": INTEGRATION_ID.value,
        "revision_fingerprint": r1.revision_fingerprint,
    }
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("broker-integration"), tmp_path), services=services)
    engine.add_cluster(OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path))
    admitted_by_engine = engine.cluster_definitions[0].brokers[0]
    assert admitted_by_engine.integration_binding is not None
    assert admitted_by_engine.integration_binding["revision_fingerprint"] == r1.revision_fingerprint

    admitted_r1 = admitted_by_engine
    selected, config_r1 = only_resolve_broker_runtime_configuration(admitted_r1, registry, resolver, REQUIRED)
    assert selected is factory
    assert isinstance(config_r1, OnlyBinanceSpotBrokerIntegrationConfig)
    assert (config_r1.api_key, config_r1.api_secret) == ("key-generation-3", "secret-generation-3")
    component = factory.create(
        OnlyBrokerCreateRequest(
            OnlyBrokerGatewayId("binance"),
            config_r1,
            "LIVE",
            REQUIRED,
            OnlyBacktestClock(NOW),
            OnlyEventBus(),
            OnlyBoundedBrokerInboundQueue(16),
            OnlyRuntimeId("runtime-r1"),
            OnlyAccountId("account"),
            OnlyMoney(Decimal("1000"), OnlyCurrency("USDT", 8)),
            logging.getLogger("broker-integration-vertical"),
            OnlyDurableBrokerCommandEvidenceStore((tmp_path / "commands.jsonl").resolve()),
        )
    )
    assert isinstance(component.resource, OnlyBinanceSpotBrokerResource)

    state.integration = replace(state.integration, current_revision_fingerprint=r2.revision_fingerprint)
    with pytest.raises(OnlyIntegrationRuntimeError, match="INTEGRATION_RUNTIME_BINDING_INVALID"):
        only_admit_broker_runtime_configuration(
            _reference(r1),
            resolver,
            REQUIRED,
            require_current_revision=True,
            require_ready_probe=True,
        )

    _, still_r1 = only_resolve_broker_runtime_configuration(admitted_r1, registry, resolver, REQUIRED)
    admitted_r2 = only_admit_broker_runtime_configuration(
        _reference(r2),
        resolver,
        REQUIRED,
        require_current_revision=True,
        require_ready_probe=True,
    )
    _, config_r2 = only_resolve_broker_runtime_configuration(admitted_r2, registry, resolver, REQUIRED)

    assert isinstance(still_r1, OnlyBinanceSpotBrokerIntegrationConfig)
    assert isinstance(config_r2, OnlyBinanceSpotBrokerIntegrationConfig)
    assert still_r1.api_key == "key-generation-3"
    assert config_r2.api_key == "key-generation-4"
    assert admitted_r1.integration_binding != admitted_r2.integration_binding
    assert set(credentials.reads) == {
        (KEY_ID, 3),
        (SECRET_ID, 3),
        (KEY_ID, 4),
        (SECRET_ID, 4),
    }


def test_new_live_admission_fails_closed_without_active_current_exact_ready_probe() -> None:
    revision, bindings = _revision(1, 3)
    state = _State(
        OnlyIntegration(
            INTEGRATION_ID,
            SPOT_BROKER_INTEGRATION_TYPE.type_id.value,
            "Binance Spot",
            OnlyIntegrationLifecycleState.DISABLED,
            revision.revision_fingerprint,
            NOW,
            NOW,
        )
    )
    state.revisions[revision.revision_fingerprint] = revision
    state.bindings[revision.revision_fingerprint] = bindings
    resolver = OnlyIntegrationRuntimeResolver(state, _Credentials(), _Catalog(), probes=_Probes())

    with pytest.raises(OnlyIntegrationRuntimeError, match="INTEGRATION_RUNTIME_DISABLED"):
        only_admit_broker_runtime_configuration(
            _reference(revision),
            resolver,
            REQUIRED,
            require_current_revision=True,
            require_ready_probe=True,
        )

    state.integration = replace(state.integration, lifecycle_state=OnlyIntegrationLifecycleState.ACTIVE)
    with pytest.raises(OnlyIntegrationRuntimeError, match="INTEGRATION_RUNTIME_PROBE_REQUIRED"):
        only_admit_broker_runtime_configuration(
            _reference(revision),
            resolver,
            REQUIRED,
            require_current_revision=True,
            require_ready_probe=True,
        )

"""Binance Spot Broker Product→Runtime golden vertical certified against real PostgreSQL.

One unbroken authority chain under LIVE-mode admission, no mocks of any OnlyAlpha authority
and no test-only resolver path: Product commands (create → draft → api_key/api_secret →
publish) flow through ``OnlyIntegrationCommandService`` over ``OnlyPostgresIntegrationProductStore``;
the READY probe is executed and recorded for real by ``OnlyIntegrationProbeService`` over
``OnlyPostgresIntegrationProbeStore``; Runtime admission of the exact published Revision flows
through the canonical production composition root ``only_compose_integration_runtime_resolver``
with the LIVE flags ``require_current_revision=True`` and ``require_ready_probe=True``.

Probe execution path (documented per the certification brief): the REAL probe service runs the
production ``OnlyBinanceSpotBrokerFactory.probe`` — real configuration parsing, real HMAC-SHA256
request signing and the real read-only ``GET /api/v3/account`` call — against a deterministic
in-process Binance-shaped venue double installed through the factory's private-transport seam.
The Compose probe fixture serves only public market-data endpoints behind Compose-only network
aliases (``api.binance.com``) and has no signed account surface, so a real-socket TLS probe is
non-hermetic in the pytest lane; the venue double verifies the exact api key header and request
signature derived from the persisted encrypted secret and rejects any order path, so the proof
stays read-only and offline. The probe attempt rows are written by the real PostgreSQL probe
store and never faked. NO real orders are created anywhere in this module.
"""

from __future__ import annotations

import hmac
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import psycopg
import pytest
from onlyalpha_plugin_binance.common.environment import OnlyBinanceEnvironment
from onlyalpha_plugin_binance.common.private_http import OnlyBinanceHttpResponse, only_binance_hmac_sha256
from onlyalpha_plugin_binance.descriptor import SPOT_BROKER_INTEGRATION_TYPE
from onlyalpha_plugin_binance.spot.broker_factory import (
    OnlyBinanceSpotBrokerFactory,
    OnlyBinanceSpotBrokerIntegrationConfig,
)
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
from onlyalpha.application.integration_probe import OnlyIntegrationProbeService
from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeBindingV1,
    OnlyIntegrationRuntimeError,
    OnlyIntegrationRuntimeResolver,
)
from onlyalpha.application.integration_type_catalog import (
    OnlyIntegrationProbeCatalog,
    OnlyIntegrationTypeCatalog,
)
from onlyalpha.application.product_command_receipt import OnlyProductCommandId, OnlyProductCommandReceipt
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.config.models import OnlyBrokerRuntimeConfig, OnlyJsonMapping, OnlyRuntimeConfigurationMode
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId, OnlyRuntimeId
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    MASTER_KEY_FILE,
    OnlyIntegrationRuntimeCompositionV1,
    OnlyPostgresCredentialAuthority,
    OnlyPostgresIntegrationProductStore,
    only_compose_integration_runtime_resolver,
    only_ensure_dev_master_key,
)
from onlyalpha.persistence.postgres.integration_probe_store import OnlyPostgresIntegrationProbeStore
from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities
from onlyalpha.plugin.integration import OnlyIntegrationCategory, only_integration_capability_ids
from onlyalpha.plugin.integration_probe import OnlyIntegrationProbeStatus
from onlyalpha.runtime.broker_integration import (
    only_admit_broker_runtime_configuration,
    only_resolve_broker_runtime_configuration,
)

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]

NOW = datetime(2026, 9, 22, tzinfo=UTC)
BROKER_TYPE_ID = "binance.spot.broker"
INTEGRATION_ID = OnlyIntegrationId("3f9b6c2d-8a41-4e7b-9d05-6c1e2b7a4f90")
R1_API_KEY = "golden-binance-api-key-r1"
R1_API_SECRET = "golden-binance-api-secret-r1"
R2_API_KEY = "golden-binance-api-key-r2"
R2_API_SECRET = "golden-binance-api-secret-r2"
AMBIENT_API_KEY = "ambient-binance-api-key-must-not-win"
AMBIENT_API_SECRET = "ambient-binance-api-secret-must-not-win"
GATEWAY_ID = OnlyBrokerGatewayId("binance-spot-golden")
ENGINE_ID = OnlyEngineId("binance-broker-golden")
RUNTIME_ID = OnlyRuntimeId("binance-broker-golden-runtime")
CLUSTER_ID = OnlyClusterId("binance-broker-golden-cluster")
REQUIRED_CAPABILITIES = OnlyBrokerPluginCapabilities(
    submit_order=True,
    cancel_order=True,
    query_orders=True,
    query_trades=True,
    query_positions=True,
    live_execution=True,
)
ACCOUNT_PAYLOAD = b'{"balances":[{"asset":"USDT","free":"1.5","locked":"0"}],"canTrade":true}'
INSTRUMENT_TABLES = (
    "integration",
    "integration_draft",
    "integration_draft_secret_binding",
    "integration_revision",
    "integration_revision_secret_binding",
    "integration_probe_attempt",
    "product_credential",
    "product_command_admission",
    "product_command_receipt",
)


def _command(number: int) -> OnlyProductCommandId:
    return OnlyProductCommandId(f"00000000-0000-4000-8000-{number:012d}")


@dataclass
class _DeterministicBinanceVenue:
    """In-process Binance-shaped venue double behind the factory's private-transport seam.

    Mirrors the deterministic scenario surface of the Compose probe fixture (``ALL_PASS`` /
    ``OFFLINE``). In ``ALL_PASS`` it accepts only the read-only signed account request and
    verifies the exact api key header plus the HMAC-SHA256 signature over the canonical query,
    so a READY attempt proves the persisted encrypted secret reached the venue boundary. Any
    order path is rejected: this certification never places orders.
    """

    scenario: str = "ALL_PASS"
    expected_api_key: str = field(default="", repr=False)
    expected_api_secret: str = field(default="", repr=False)
    received_requests: list[tuple[str, str, str]] = field(default_factory=list, repr=False)

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> OnlyBinanceHttpResponse:
        api_key_header = str(headers.get("X-MBX-APIKEY", ""))
        self.received_requests.append((method, url, api_key_header))
        if self.scenario == "OFFLINE":
            return OnlyBinanceHttpResponse(503, {}, b'{"code":-1000,"msg":"service unavailable"}')
        if method != "GET" or "/api/v3/account?" not in url or "/api/v3/order" in url:
            return OnlyBinanceHttpResponse(404, {}, b'{"code":-1003,"msg":"unknown endpoint"}')
        canonical_query, separator, signature = url.partition("&signature=")
        if (
            not separator
            or api_key_header != self.expected_api_key
            or not hmac.compare_digest(
                signature,
                only_binance_hmac_sha256(self.expected_api_secret, canonical_query.split("?", 1)[1]),
            )
        ):
            return OnlyBinanceHttpResponse(401, {}, b'{"code":-2015,"msg":"invalid api key or signature"}')
        return OnlyBinanceHttpResponse(200, {}, ACCOUNT_PAYLOAD)


class _SequentialProbeAttemptIdentity:
    """Deterministic uuid4-shaped probe attempt identities ordered by issuance."""

    def __init__(self) -> None:
        self._issued = 0

    def __call__(self) -> uuid.UUID:
        self._issued += 1
        return uuid.UUID(f"00000000-0000-4000-8000-{self._issued:012d}")


@dataclass
class GoldenVertical:
    """Artifacts captured by provisioning and extended by the ordered narrative."""

    dsn: str
    master_key_path: Path
    data_sources: OnlyDataSourceFactoryRegistry
    brokers: OnlyBrokerFactoryRegistry
    factory: OnlyBinanceSpotBrokerFactory
    venue: _DeterministicBinanceVenue
    catalog: OnlyIntegrationTypeCatalog
    store: OnlyPostgresIntegrationProductStore
    attempts: OnlyPostgresIntegrationProbeStore
    probes: OnlyIntegrationProbeService
    commands: OnlyIntegrationCommandService
    user_data_root: Path
    r1_revision_fingerprint: str
    r1_runtime_configuration_fingerprint: str
    r1_secret_bindings: tuple[OnlyIntegrationSecretBinding, ...]
    provision_results: tuple[OnlyIntegrationCommandResult, ...]
    receipts: list[OnlyProductCommandReceipt] = field(default_factory=list)
    admitted_binding: dict[str, object] | None = None
    evidence_path: Path | None = None
    r2_revision_fingerprint: str | None = None
    r2_runtime_configuration_fingerprint: str | None = None


@pytest.fixture(scope="module")
def golden_vertical(postgres_dsn: str, tmp_path_factory: pytest.TempPathFactory) -> GoldenVertical:
    """Provision the Product side once: create, draft, secrets R1, publish Revision R1."""

    user_data_root = tmp_path_factory.mktemp("binance-broker-golden-user-data")
    master_key_path = user_data_root / MASTER_KEY_FILE
    master_key = only_ensure_dev_master_key(master_key_path)
    venue = _DeterministicBinanceVenue()
    factory = OnlyBinanceSpotBrokerFactory(private_transport=venue)
    data_sources = OnlyDataSourceFactoryRegistry()
    brokers = OnlyBrokerFactoryRegistry()
    brokers.register(factory)
    catalog = OnlyIntegrationTypeCatalog(data_sources, brokers)
    store = OnlyPostgresIntegrationProductStore(postgres_dsn, master_key, now=lambda: NOW)
    attempts = OnlyPostgresIntegrationProbeStore(postgres_dsn)
    probes = OnlyIntegrationProbeService(
        store,
        attempts,
        OnlyPostgresCredentialAuthority(postgres_dsn, master_key),
        OnlyIntegrationProbeCatalog(data_sources, brokers),
        attempt_id_factory=_SequentialProbeAttemptIdentity(),
    )
    commands = OnlyIntegrationCommandService(catalog, store, master_key)
    results = (
        commands.create_integration(
            OnlyCreateIntegration(_command(1), INTEGRATION_ID, BROKER_TYPE_ID, "Binance Spot Broker Golden")
        ),
        commands.update_integration_draft(
            OnlyUpdateIntegrationDraft(_command(2), INTEGRATION_ID, 1, {"currencies": {"USDT": 8}}, None)
        ),
        commands.set_integration_secret(
            OnlySetIntegrationSecret(_command(3), INTEGRATION_ID, 2, "api_key", R1_API_KEY)
        ),
        commands.set_integration_secret(
            OnlySetIntegrationSecret(_command(4), INTEGRATION_ID, 3, "api_secret", R1_API_SECRET)
        ),
        commands.publish_integration_revision(OnlyPublishIntegrationRevision(_command(5), INTEGRATION_ID, 4)),
    )
    r1_revision_fingerprint = results[4].receipt.outcome_ref.outcome_id
    revision = store.load_revision(r1_revision_fingerprint)
    secret_bindings = store.load_revision_secret_bindings(r1_revision_fingerprint)
    if [(item.field_id, item.credential_generation) for item in secret_bindings] != [("api_key", 1), ("api_secret", 1)]:
        raise AssertionError("provisioning must publish exactly the generation-1 api_key/api_secret bindings")
    return GoldenVertical(
        dsn=postgres_dsn,
        master_key_path=master_key_path,
        data_sources=data_sources,
        brokers=brokers,
        factory=factory,
        venue=venue,
        catalog=catalog,
        store=store,
        attempts=attempts,
        probes=probes,
        commands=commands,
        user_data_root=user_data_root,
        r1_revision_fingerprint=r1_revision_fingerprint,
        r1_runtime_configuration_fingerprint=revision.runtime_configuration_fingerprint,
        r1_secret_bindings=secret_bindings,
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


def _integration_broker(binding: object) -> OnlyBrokerRuntimeConfig:
    return OnlyBrokerRuntimeConfig(
        gateway_id=GATEWAY_ID,
        plugin_id="",
        enabled=True,
        configuration_mode=OnlyRuntimeConfigurationMode.INTEGRATION_REVISION,
        integration_binding=cast(OnlyJsonMapping, dict(cast(dict[str, object], binding))),
    )


def _r1_reference(golden: GoldenVertical) -> dict[str, object]:
    return {
        "integration_id": INTEGRATION_ID.value,
        "revision_fingerprint": golden.r1_revision_fingerprint,
    }


def _admit_live(resolver: OnlyIntegrationRuntimeResolver, binding: object) -> OnlyBrokerRuntimeConfig:
    return only_admit_broker_runtime_configuration(
        _integration_broker(binding),
        resolver,
        REQUIRED_CAPABILITIES,
        require_current_revision=True,
        require_ready_probe=True,
    )


def test_create_set_secrets_publish_r1(golden_vertical: GoldenVertical) -> None:
    golden = golden_vertical
    assert [result.replayed for result in golden.provision_results] == [False, False, False, False, False]

    descriptor = golden.catalog.require(BROKER_TYPE_ID)
    assert descriptor == SPOT_BROKER_INTEGRATION_TYPE
    assert golden.brokers.resolve("binance-spot") is golden.factory
    assert golden.factory.integration_type == descriptor

    integration = golden.store.load_integration(INTEGRATION_ID)
    assert integration.type_id == BROKER_TYPE_ID
    assert integration.lifecycle_state is OnlyIntegrationLifecycleState.ACTIVE
    assert integration.current_revision_fingerprint == golden.r1_revision_fingerprint

    revision = golden.store.load_revision(golden.r1_revision_fingerprint)
    assert revision.revision_sequence == 1
    assert revision.type_descriptor_fingerprint == descriptor.fingerprint
    assert dict(revision.configuration_document) == {
        "currencies": {"USDT": 8},
        "environment": "SPOT_TESTNET",
        "max_response_bytes": 8 * 1024 * 1024,
        "recv_window_ms": 5_000,
        "timeout_seconds": 10,
    }
    assert dict(revision.probe_configuration_document or {}) == {"instrument": "BTCUSDT"}

    assert len({item.credential_id for item in golden.r1_secret_bindings}) == 2

    draft = golden.store.load_draft(INTEGRATION_ID)
    assert draft.draft_version == 5
    assert draft.base_revision_fingerprint == golden.r1_revision_fingerprint


def test_live_admission_requires_a_recorded_ready_probe(golden_vertical: GoldenVertical) -> None:
    golden = golden_vertical
    resolver = _compose_resolver(golden)
    reference = _r1_reference(golden)

    # A fresh integration without any probe attempt fails closed before any admission.
    with pytest.raises(OnlyIntegrationRuntimeError) as missing:
        _admit_live(resolver, reference)
    assert missing.value.code == "INTEGRATION_RUNTIME_PROBE_REQUIRED"

    # A real probe execution against an OFFLINE venue records a real non-READY attempt.
    golden.venue.scenario = "OFFLINE"
    golden.venue.expected_api_key = R1_API_KEY
    golden.venue.expected_api_secret = R1_API_SECRET
    offline = golden.probes.probe(INTEGRATION_ID, golden.r1_revision_fingerprint)
    assert offline.overall_status is OnlyIntegrationProbeStatus.OFFLINE
    persisted_offline = golden.attempts.latest_probe_attempt(INTEGRATION_ID, golden.r1_revision_fingerprint)
    assert persisted_offline is not None
    assert persisted_offline.probe_attempt_id == offline.probe_attempt_id
    assert persisted_offline.overall_status is OnlyIntegrationProbeStatus.OFFLINE
    assert persisted_offline.result_fingerprint == offline.result_fingerprint

    with pytest.raises(OnlyIntegrationRuntimeError) as not_ready:
        _admit_live(resolver, reference)
    assert not_ready.value.code == "INTEGRATION_RUNTIME_PROBE_NOT_READY"

    # The real probe service then executes the signed read-only account probe to READY.
    golden.venue.scenario = "ALL_PASS"
    ready = golden.probes.probe(INTEGRATION_ID, golden.r1_revision_fingerprint)
    assert ready.overall_status is OnlyIntegrationProbeStatus.READY
    assert ready.runtime_configuration_fingerprint == golden.r1_runtime_configuration_fingerprint
    persisted_ready = golden.attempts.latest_probe_attempt(INTEGRATION_ID, golden.r1_revision_fingerprint)
    assert persisted_ready is not None
    assert persisted_ready.probe_attempt_id == ready.probe_attempt_id
    assert persisted_ready.overall_status is OnlyIntegrationProbeStatus.READY

    method, url, api_key_header = golden.venue.received_requests[-1]
    assert method == "GET"
    assert "/api/v3/account?" in url and "/api/v3/order" not in url
    assert api_key_header == R1_API_KEY


def test_production_resolver_admits_exact_r1_in_live_mode(golden_vertical: GoldenVertical) -> None:
    golden = golden_vertical
    resolver = _compose_resolver(golden)

    admitted = _admit_live(resolver, _r1_reference(golden))
    binding = OnlyIntegrationRuntimeBindingV1.from_dict(dict(admitted.integration_binding or {}))
    assert binding.integration_id == INTEGRATION_ID
    assert binding.revision_fingerprint == golden.r1_revision_fingerprint
    assert binding.runtime_configuration_fingerprint == golden.r1_runtime_configuration_fingerprint
    assert binding.type_id == BROKER_TYPE_ID
    assert binding.category is OnlyIntegrationCategory.BROKER
    assert binding.runtime_generation_fingerprint is None

    factory, config = only_resolve_broker_runtime_configuration(
        admitted, golden.brokers, resolver, REQUIRED_CAPABILITIES
    )
    assert factory is golden.factory
    assert isinstance(config, OnlyBinanceSpotBrokerIntegrationConfig)
    assert config.environment is OnlyBinanceEnvironment.SPOT_TESTNET
    assert config.api_key == R1_API_KEY
    assert config.api_secret == R1_API_SECRET
    assert config.currencies == (("USDT", 8),)
    assert config.rest_base_url == "https://testnet.binance.vision"

    assert golden.store.load_revision_secret_bindings(binding.revision_fingerprint) == golden.r1_secret_bindings
    golden.admitted_binding = binding.to_dict()


def test_ambient_environment_credentials_cannot_win(
    golden_vertical: GoldenVertical, monkeypatch: pytest.MonkeyPatch
) -> None:
    golden = golden_vertical
    monkeypatch.setenv("ONLYALPHA_BINANCE_TESTNET_API_KEY", AMBIENT_API_KEY)
    monkeypatch.setenv("ONLYALPHA_BINANCE_TESTNET_API_SECRET", AMBIENT_API_SECRET)
    resolver = _compose_resolver(golden)

    admitted = _admit_live(resolver, _r1_reference(golden))
    _, config = only_resolve_broker_runtime_configuration(admitted, golden.brokers, resolver, REQUIRED_CAPABILITIES)
    assert isinstance(config, OnlyBinanceSpotBrokerIntegrationConfig)
    assert config.api_key == R1_API_KEY
    assert config.api_secret == R1_API_SECRET
    assert AMBIENT_API_KEY not in (config.api_key, config.api_secret)
    assert AMBIENT_API_SECRET not in (config.api_key, config.api_secret)


def test_restart_and_rotate_then_recover_semantics(golden_vertical: GoldenVertical) -> None:
    golden = golden_vertical
    assert golden.admitted_binding is not None
    binding = OnlyIntegrationRuntimeBindingV1.from_dict(golden.admitted_binding)

    payload = {
        "brokers": [
            {"gateway_id": GATEWAY_ID.value, "integration_binding": golden.admitted_binding},
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
    persisted = json.loads(evidence_path.read_text(encoding="utf-8"))["brokers"][0]["integration_binding"]
    recovered = only_admit_broker_runtime_configuration(
        _integration_broker(persisted),
        restarted,
        REQUIRED_CAPABILITIES,
        recovery=True,
        require_current_revision=True,
        require_ready_probe=True,
    )
    assert OnlyIntegrationRuntimeBindingV1.from_dict(dict(recovered.integration_binding or {})) == binding
    _, recovered_config = only_resolve_broker_runtime_configuration(
        recovered, golden.brokers, restarted, REQUIRED_CAPABILITIES
    )
    assert isinstance(recovered_config, OnlyBinanceSpotBrokerIntegrationConfig)
    assert recovered_config.api_key == R1_API_KEY
    assert recovered_config.api_secret == R1_API_SECRET

    rotated_key = golden.commands.set_integration_secret(
        OnlySetIntegrationSecret(_command(6), INTEGRATION_ID, 5, "api_key", R2_API_KEY)
    )
    rotated_secret = golden.commands.set_integration_secret(
        OnlySetIntegrationSecret(_command(7), INTEGRATION_ID, 6, "api_secret", R2_API_SECRET)
    )
    published = golden.commands.publish_integration_revision(
        OnlyPublishIntegrationRevision(_command(8), INTEGRATION_ID, 7)
    )
    golden.receipts.extend((rotated_key.receipt, rotated_secret.receipt, published.receipt))
    r2_revision_fingerprint = published.receipt.outcome_ref.outcome_id
    assert r2_revision_fingerprint != golden.r1_revision_fingerprint
    r2_revision = golden.store.load_revision(r2_revision_fingerprint)
    assert r2_revision.revision_sequence == 2
    assert r2_revision.runtime_configuration_fingerprint != golden.r1_runtime_configuration_fingerprint
    r2_secret_bindings = golden.store.load_revision_secret_bindings(r2_revision_fingerprint)
    assert [(item.field_id, item.credential_generation) for item in r2_secret_bindings] == [
        ("api_key", 2),
        ("api_secret", 2),
    ]
    assert [item.credential_id for item in r2_secret_bindings] == [
        item.credential_id for item in golden.r1_secret_bindings
    ]
    golden.r2_revision_fingerprint = r2_revision_fingerprint
    golden.r2_runtime_configuration_fingerprint = r2_revision.runtime_configuration_fingerprint

    rotated_resolver = _compose_resolver(golden)

    # The retired exact generations are never substituted: R1 recovery now fails closed.
    with pytest.raises(OnlyIntegrationRuntimeError) as retired:
        only_admit_broker_runtime_configuration(
            _integration_broker(persisted),
            rotated_resolver,
            REQUIRED_CAPABILITIES,
            recovery=True,
            require_current_revision=True,
            require_ready_probe=True,
        )
    assert retired.value.code == "INTEGRATION_RUNTIME_SECRET_UNAVAILABLE"

    assert golden.store.load_integration(INTEGRATION_ID).current_revision_fingerprint == r2_revision_fingerprint

    # R2 earns its own real READY probe with the rotated generation-2 secrets.
    golden.venue.expected_api_key = R2_API_KEY
    golden.venue.expected_api_secret = R2_API_SECRET
    r2_probe = golden.probes.probe(INTEGRATION_ID, r2_revision_fingerprint)
    assert r2_probe.overall_status is OnlyIntegrationProbeStatus.READY
    assert r2_probe.runtime_configuration_fingerprint == golden.r2_runtime_configuration_fingerprint
    assert golden.venue.received_requests[-1][2] == R2_API_KEY

    admitted_r2 = _admit_live(
        rotated_resolver,
        {"integration_id": INTEGRATION_ID.value, "revision_fingerprint": r2_revision_fingerprint},
    )
    _, r2_config = only_resolve_broker_runtime_configuration(
        admitted_r2, golden.brokers, rotated_resolver, REQUIRED_CAPABILITIES
    )
    assert isinstance(r2_config, OnlyBinanceSpotBrokerIntegrationConfig)
    assert r2_config.api_key == R2_API_KEY
    assert r2_config.api_secret == R2_API_SECRET

    with pytest.raises(OnlyIntegrationRuntimeError) as substituted:
        _admit_live(rotated_resolver, _r1_reference(golden))
    assert substituted.value.code == "INTEGRATION_RUNTIME_BINDING_INVALID"


def test_secret_never_leaks(golden_vertical: GoldenVertical) -> None:
    golden = golden_vertical
    assert golden.evidence_path is not None
    assert golden.r2_revision_fingerprint is not None
    sentinels = (R1_API_KEY, R1_API_SECRET, R2_API_KEY, R2_API_SECRET, AMBIENT_API_KEY, AMBIENT_API_SECRET)

    resolver = _compose_resolver(golden)
    resolved = resolver.admit_new_reference(
        INTEGRATION_ID.value,
        golden.r2_revision_fingerprint,
        expected_category=OnlyIntegrationCategory.BROKER,
        required_capabilities=only_integration_capability_ids(REQUIRED_CAPABILITIES),
        require_current_revision=True,
        require_ready_probe=True,
    )
    admitted_r2 = only_admit_broker_runtime_configuration(
        _integration_broker(resolved.binding.to_dict()),
        resolver,
        REQUIRED_CAPABILITIES,
        recovery=True,
    )
    _, config = only_resolve_broker_runtime_configuration(admitted_r2, golden.brokers, resolver, REQUIRED_CAPABILITIES)
    assert isinstance(config, OnlyBinanceSpotBrokerIntegrationConfig)
    # Positive control: the sentinels really exist behind the credential authority, so their
    # absence from every durable and observable surface below is meaningful.
    assert config.api_key == R2_API_KEY
    assert config.api_secret == R2_API_SECRET

    r1_attempt = golden.attempts.latest_probe_attempt(INTEGRATION_ID, golden.r1_revision_fingerprint)
    r2_attempt = golden.attempts.latest_probe_attempt(INTEGRATION_ID, golden.r2_revision_fingerprint)
    assert r1_attempt is not None and r2_attempt is not None
    surfaces = {
        "evidence": golden.evidence_path.read_text(encoding="utf-8"),
        "binding": repr(resolved.binding),
        "secrets": repr(resolved.secrets),
        "public_configuration": str(resolved.public_configuration),
        "runtime_config": repr(config),
        "receipts": repr(tuple(golden.receipts)),
        "r1_probe_attempt": str(r1_attempt.to_dict()),
        "r2_probe_attempt": str(r2_attempt.to_dict()),
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
    assert len(dumped["integration_probe_attempt"]) == 3
    for table, rows in dumped.items():
        for row in rows:
            for sentinel in sentinels:
                assert sentinel not in row, table

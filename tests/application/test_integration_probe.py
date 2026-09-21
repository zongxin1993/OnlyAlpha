from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest

from onlyalpha.application.integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
)
from onlyalpha.application.integration_probe import (
    OnlyIntegrationOperationalQueryService,
    OnlyIntegrationProbeAttempt,
    OnlyIntegrationProbeService,
)
from onlyalpha.application.integration_type_catalog import OnlyIntegrationProbeCatalog
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.plugin import (
    ONLYALPHA_PLUGIN_API_VERSION,
    OnlyDataSourceCapabilities,
    OnlyPluginDescriptor,
    OnlyPluginType,
)
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationConfigurationFieldV1,
    OnlyIntegrationProbeCheck,
    OnlyIntegrationProbeContractV1,
    OnlyIntegrationProbeMode,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
    OnlyIntegrationValueKind,
)
from onlyalpha.plugin.integration_probe import (
    OnlyIntegrationProbeCheckResult,
    OnlyIntegrationProbeCheckStatus,
    OnlyIntegrationProbeFailureKind,
    OnlyIntegrationProbePolicy,
    OnlyIntegrationProbeRequest,
    OnlyIntegrationProbeResult,
    OnlyIntegrationProbeStatus,
)

NOW = datetime(2026, 9, 21, tzinfo=UTC)
INTEGRATION_ID = OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
ATTEMPT_ID = "a52eb762-34cf-47d4-8cca-56ef93f0d2ac"


def _descriptor(*, secret: bool = False) -> OnlyIntegrationTypeDescriptorV1:
    fields = ()
    if secret:
        fields = (
            OnlyIntegrationConfigurationFieldV1(
                "token", OnlyIntegrationValueKind.STRING, True, secret=True, display_name="Token"
            ),
        )
    return OnlyIntegrationTypeDescriptorV1(
        type_id=OnlyIntegrationTypeId("test.market_data"),
        category=OnlyIntegrationCategory.DATA_SOURCE,
        display_name="Test market data",
        description="Deterministic local test provider.",
        provider_id="test",
        implementation_id="test-data",
        implementation_version="1.0.0",
        public_api_version=str(ONLYALPHA_PLUGIN_API_VERSION),
        capabilities=("HISTORICAL_BARS",),
        configuration_contract=OnlyIntegrationConfigurationContractV1(fields=fields),
        probe_contract=OnlyIntegrationProbeContractV1(
            OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT,
            "TEST",
            True,
            (OnlyIntegrationProbeCheck.CONNECTIVITY, OnlyIntegrationProbeCheck.HISTORICAL_DATA),
        ),
    )


def _revision(
    descriptor: OnlyIntegrationTypeDescriptorV1,
    *,
    bindings: tuple[OnlyIntegrationSecretBinding, ...] = (),
    sequence: int = 1,
    timeout_seconds: int = 3,
) -> OnlyIntegrationRevision:
    return OnlyIntegrationRevision.from_resolved(
        integration_id=INTEGRATION_ID,
        revision_sequence=sequence,
        type_id=descriptor.type_id.value,
        type_descriptor_fingerprint=descriptor.fingerprint,
        type_descriptor_document=descriptor.to_dict(include_fingerprint=False),
        configuration_document={"timeout_seconds": timeout_seconds},
        probe_configuration_document={"instrument": "TEST"},
        secret_bindings=bindings,
        created_at=NOW,
    )


@dataclass
class _StateStore:
    integration: OnlyIntegration
    revision: OnlyIntegrationRevision
    bindings: tuple[OnlyIntegrationSecretBinding, ...] = ()

    def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration:
        assert integration_id == INTEGRATION_ID
        return self.integration

    def load_revision(self, revision_fingerprint: str) -> OnlyIntegrationRevision:
        assert revision_fingerprint == self.revision.revision_fingerprint
        return self.revision

    def load_revision_secret_bindings(self, revision_fingerprint: str) -> tuple[OnlyIntegrationSecretBinding, ...]:
        assert revision_fingerprint == self.revision.revision_fingerprint
        return self.bindings


class _AttemptStore:
    def __init__(self) -> None:
        self.items: list[OnlyIntegrationProbeAttempt] = []

    def insert_probe_attempt(self, attempt: OnlyIntegrationProbeAttempt) -> None:
        self.items.append(attempt)

    def get_probe_attempt(self, probe_attempt_id: str) -> OnlyIntegrationProbeAttempt:
        return next(item for item in self.items if item.probe_attempt_id == probe_attempt_id)

    def list_probe_attempts(self, integration_id: OnlyIntegrationId) -> tuple[OnlyIntegrationProbeAttempt, ...]:
        return tuple(item for item in reversed(self.items) if item.integration_id == integration_id)

    def latest_probe_attempt(
        self, integration_id: OnlyIntegrationId, revision_fingerprint: str
    ) -> OnlyIntegrationProbeAttempt | None:
        matches = [
            item
            for item in self.items
            if item.integration_id == integration_id and item.revision_fingerprint == revision_fingerprint
        ]
        return max(matches, key=lambda item: (item.completed_at, item.probe_attempt_id), default=None)


class _Credentials:
    def __init__(self) -> None:
        self.reads: list[tuple[str, int]] = []

    def read_secret(self, credential_id: str, credential_generation: int) -> str:
        self.reads.append((credential_id, credential_generation))
        return "memory-only-secret"


class _Factory:
    descriptor = OnlyPluginDescriptor(
        "test-data",
        OnlyPluginType.DATA_SOURCE,
        "1.0.0",
        ONLYALPHA_PLUGIN_API_VERSION,
        "Test data",
        "OnlyAlpha",
        OnlyDataSourceCapabilities(historical_bars=True),
    )

    def __init__(self, descriptor: OnlyIntegrationTypeDescriptorV1) -> None:
        self.integration_type = descriptor
        self.requests: list[OnlyIntegrationProbeRequest] = []
        self.status = OnlyIntegrationProbeStatus.READY

    def parse_config(self, extensions: object) -> object:
        return extensions

    def validate_request(self, request: object) -> tuple[()]:
        del request
        return ()

    def create(self, request: object) -> object:
        raise AssertionError("Probe must not call the Runtime DataSource create() path")

    def probe(self, request: OnlyIntegrationProbeRequest) -> OnlyIntegrationProbeResult:
        self.requests.append(request)
        checks = {
            OnlyIntegrationProbeStatus.READY: (
                _check(OnlyIntegrationProbeCheck.CONNECTIVITY),
                _check(OnlyIntegrationProbeCheck.HISTORICAL_DATA),
            ),
            OnlyIntegrationProbeStatus.DEGRADED: (
                _check(OnlyIntegrationProbeCheck.CONNECTIVITY),
                _failed(OnlyIntegrationProbeCheck.HISTORICAL_DATA, OnlyIntegrationProbeFailureKind.DEGRADED),
            ),
            OnlyIntegrationProbeStatus.OFFLINE: (
                _failed(OnlyIntegrationProbeCheck.CONNECTIVITY, OnlyIntegrationProbeFailureKind.OFFLINE),
                _skipped(OnlyIntegrationProbeCheck.HISTORICAL_DATA),
            ),
            OnlyIntegrationProbeStatus.FAILED: (
                _check(OnlyIntegrationProbeCheck.CONNECTIVITY),
                _failed(OnlyIntegrationProbeCheck.HISTORICAL_DATA, OnlyIntegrationProbeFailureKind.FAILED),
            ),
        }[self.status]
        return OnlyIntegrationProbeResult.create(
            request,
            probe_instrument="TEST",
            checks=checks,
            started_at=NOW,
            completed_at=NOW + timedelta(milliseconds=12),
        )


def _check(check: OnlyIntegrationProbeCheck) -> OnlyIntegrationProbeCheckResult:
    return OnlyIntegrationProbeCheckResult(check, OnlyIntegrationProbeCheckStatus.PASS, 3)


def _failed(
    check: OnlyIntegrationProbeCheck, failure_kind: OnlyIntegrationProbeFailureKind
) -> OnlyIntegrationProbeCheckResult:
    return OnlyIntegrationProbeCheckResult(
        check,
        OnlyIntegrationProbeCheckStatus.FAIL,
        3,
        failure_kind=failure_kind,
        error_code="TEST_FAILURE",
        detail="Sanitized failure",
    )


def _skipped(check: OnlyIntegrationProbeCheck) -> OnlyIntegrationProbeCheckResult:
    return OnlyIntegrationProbeCheckResult(check, OnlyIntegrationProbeCheckStatus.SKIPPED, 0)


def _service(
    *,
    descriptor: OnlyIntegrationTypeDescriptorV1 | None = None,
    lifecycle: OnlyIntegrationLifecycleState = OnlyIntegrationLifecycleState.ACTIVE,
    bindings: tuple[OnlyIntegrationSecretBinding, ...] = (),
) -> tuple[
    OnlyIntegrationProbeService,
    _StateStore,
    _AttemptStore,
    _Credentials,
    _Factory,
]:
    descriptor = descriptor or _descriptor()
    revision = _revision(descriptor, bindings=bindings)
    state = _StateStore(
        OnlyIntegration(
            INTEGRATION_ID,
            descriptor.type_id.value,
            "Test source",
            lifecycle,
            revision.revision_fingerprint,
            NOW,
            NOW,
        ),
        revision,
        bindings,
    )
    attempts = _AttemptStore()
    credentials = _Credentials()
    factory = _Factory(descriptor)
    data_sources = OnlyDataSourceFactoryRegistry()
    data_sources.register(cast(object, factory))
    catalog = OnlyIntegrationProbeCatalog(data_sources, OnlyBrokerFactoryRegistry())
    service = OnlyIntegrationProbeService(
        state,
        attempts,
        credentials,
        catalog,
        attempt_id_factory=lambda: UUID(ATTEMPT_ID),
    )
    return service, state, attempts, credentials, factory


def test_probe_requires_current_published_exact_revision_before_provider_io() -> None:
    service, state, attempts, _, factory = _service()

    with pytest.raises(OnlyIntegrationError) as mismatch:
        service.probe(INTEGRATION_ID, "f" * 64)
    assert mismatch.value.code == "INTEGRATION_CURRENT_REVISION_CONFLICT"
    assert factory.requests == [] and attempts.items == []

    state.integration = replace(state.integration, current_revision_fingerprint=None)
    with pytest.raises(OnlyIntegrationError) as draft_only:
        service.probe(INTEGRATION_ID, state.revision.revision_fingerprint)
    assert draft_only.value.code == "INTEGRATION_CURRENT_REVISION_CONFLICT"
    assert factory.requests == []


def test_archived_rejected_disabled_allowed_and_runtime_create_never_used() -> None:
    service, state, attempts, _, factory = _service(lifecycle=OnlyIntegrationLifecycleState.ARCHIVED)

    with pytest.raises(OnlyIntegrationError) as archived:
        service.probe(INTEGRATION_ID, state.revision.revision_fingerprint)
    assert archived.value.code == "INTEGRATION_ARCHIVED"
    assert factory.requests == []

    state.integration = replace(state.integration, lifecycle_state=OnlyIntegrationLifecycleState.DISABLED)
    attempt = service.probe(INTEGRATION_ID, state.revision.revision_fingerprint)
    assert attempt.overall_status is OnlyIntegrationProbeStatus.READY
    assert attempts.items == [attempt]


def test_probe_resolves_exact_secret_generation_into_memory_only_request() -> None:
    binding = OnlyIntegrationSecretBinding("token", "bf1702ca-104e-4eb6-983a-93b3af201f43", 7)
    service, state, attempts, credentials, factory = _service(descriptor=_descriptor(secret=True), bindings=(binding,))

    attempt = service.probe(INTEGRATION_ID, state.revision.revision_fingerprint)

    assert credentials.reads == [(binding.credential_id, 7)]
    assert dict(factory.requests[0].resolved_secrets) == {"token": "memory-only-secret"}
    assert "memory-only-secret" not in repr(attempt)
    assert "memory-only-secret" not in str(attempt.to_dict())
    assert attempts.items == [attempt]


def test_probe_policy_is_bounded_and_passed_without_runtime_dependencies() -> None:
    policy = OnlyIntegrationProbePolicy(9.0, 2.0, 4)
    service, state, _, _, factory = _service()

    service.probe(INTEGRATION_ID, state.revision.revision_fingerprint, policy=policy)

    request = factory.requests[0]
    assert request.policy == policy
    assert request.deadline_monotonic > 0
    assert not hasattr(request, "engine")
    assert not hasattr(request, "runtime")
    assert not hasattr(request, "event_bus")
    for invalid in ((0.0, 1.0, 1), (1.0, 2.0, 1), (1.0, 1.0, 0)):
        with pytest.raises(ValueError, match="INTEGRATION_PROBE_POLICY_INVALID"):
            OnlyIntegrationProbePolicy(*invalid)


def test_probe_rejects_provider_result_after_total_deadline() -> None:
    service, state, attempts, _, _ = _service()
    readings = iter((100.0, 116.0))
    service._monotonic = lambda: next(readings)

    with pytest.raises(OnlyIntegrationError) as timeout:
        service.probe(INTEGRATION_ID, state.revision.revision_fingerprint)

    assert timeout.value.code == "INTEGRATION_PROBE_TIMEOUT"
    assert attempts.items == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (OnlyIntegrationProbeStatus.READY, OnlyIntegrationProbeStatus.READY),
        (OnlyIntegrationProbeStatus.DEGRADED, OnlyIntegrationProbeStatus.DEGRADED),
        (OnlyIntegrationProbeStatus.OFFLINE, OnlyIntegrationProbeStatus.OFFLINE),
        (OnlyIntegrationProbeStatus.FAILED, OnlyIntegrationProbeStatus.FAILED),
    ],
)
def test_current_operational_status_is_exact_revision_projection(
    status: OnlyIntegrationProbeStatus, expected: OnlyIntegrationProbeStatus
) -> None:
    service, state, attempts, _, factory = _service()
    query = OnlyIntegrationOperationalQueryService(state, attempts)
    assert query.get_operational_status(INTEGRATION_ID).status is OnlyIntegrationProbeStatus.UNKNOWN

    factory.status = status
    first = service.probe(INTEGRATION_ID, state.revision.revision_fingerprint)
    assert query.get_operational_status(INTEGRATION_ID).status is expected
    assert query.get_operational_status(INTEGRATION_ID).probe_attempt_id == first.probe_attempt_id

    next_revision = _revision(_descriptor(), sequence=2, timeout_seconds=4)
    state.revision = next_revision
    state.integration = replace(state.integration, current_revision_fingerprint=next_revision.revision_fingerprint)
    current = query.get_operational_status(INTEGRATION_ID)
    assert current.status is OnlyIntegrationProbeStatus.UNKNOWN
    assert query.list_probe_attempts(INTEGRATION_ID) == (first,)
    assert query.get_probe_attempt(first.probe_attempt_id) == first


def test_latest_attempt_tie_breaks_by_completed_time_then_attempt_id() -> None:
    _, state, attempts, _, _ = _service()
    base = OnlyIntegrationProbeAttempt.from_result(
        _Factory(_descriptor()).probe(
            OnlyIntegrationProbeRequest.create(
                probe_attempt_id="752eb762-34cf-47d4-8cca-56ef93f0d2ac",
                integration_id=INTEGRATION_ID.value,
                revision=state.revision,
                resolved_secrets={},
                policy=OnlyIntegrationProbePolicy(),
                deadline_monotonic=10.0,
            )
        ),
        state.revision,
    )
    later_id = OnlyIntegrationProbeAttempt.from_result(
        _Factory(_descriptor()).probe(
            OnlyIntegrationProbeRequest.create(
                probe_attempt_id="f52eb762-34cf-47d4-8cca-56ef93f0d2ac",
                integration_id=INTEGRATION_ID.value,
                revision=state.revision,
                resolved_secrets={},
                policy=OnlyIntegrationProbePolicy(),
                deadline_monotonic=10.0,
            )
        ),
        state.revision,
    )
    attempts.items.extend((base, later_id))

    status = OnlyIntegrationOperationalQueryService(state, attempts).get_operational_status(INTEGRATION_ID)
    assert status.probe_attempt_id == later_id.probe_attempt_id

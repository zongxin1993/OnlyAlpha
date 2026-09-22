from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace

import pytest

from onlyalpha.application.integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
)
from onlyalpha.application.integration_probe import OnlyIntegrationProbeAttempt
from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeBindingV1,
    OnlyIntegrationRuntimeError,
    OnlyIntegrationRuntimeResolver,
)
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationConfigurationFieldV1,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
    OnlyIntegrationValueKind,
)
from onlyalpha.plugin.integration_probe import OnlyIntegrationProbeStatus

NOW = datetime(2026, 9, 21, tzinfo=UTC)
INTEGRATION_ID = OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
CREDENTIAL_ID = "ba13b6b1-af9a-450f-833d-48f5002297dc"
SECRET = "NEVER_PERSIST_RUNTIME_SECRET"
OTHER_INTEGRATION_ID = OnlyIntegrationId("a52eb762-34cf-47d4-8cca-56ef93f0d2ac")


def _descriptor() -> OnlyIntegrationTypeDescriptorV1:
    return OnlyIntegrationTypeDescriptorV1(
        type_id=OnlyIntegrationTypeId("test.market_data"),
        category=OnlyIntegrationCategory.DATA_SOURCE,
        display_name="Test market data",
        description="Deterministic local provider.",
        provider_id="test",
        implementation_id="test-data",
        implementation_version="1.0.0",
        public_api_version="1.1",
        capabilities=("HISTORICAL_BARS",),
        configuration_contract=OnlyIntegrationConfigurationContractV1(
            fields=(
                OnlyIntegrationConfigurationFieldV1(
                    "token",
                    OnlyIntegrationValueKind.STRING,
                    required=True,
                    secret=True,
                    display_name="Token",
                ),
                OnlyIntegrationConfigurationFieldV1(
                    "timeout_seconds",
                    OnlyIntegrationValueKind.DURATION,
                    required=False,
                    default=10,
                    display_name="Timeout",
                ),
            )
        ),
    )


def _revision(
    descriptor: OnlyIntegrationTypeDescriptorV1,
    *,
    integration_id: OnlyIntegrationId = INTEGRATION_ID,
    generation: int = 3,
) -> tuple[OnlyIntegrationRevision, tuple[OnlyIntegrationSecretBinding, ...]]:
    bindings = (OnlyIntegrationSecretBinding("token", CREDENTIAL_ID, generation),)
    revision = OnlyIntegrationRevision.from_resolved(
        integration_id=integration_id,
        revision_sequence=1,
        type_id=descriptor.type_id.value,
        type_descriptor_fingerprint=descriptor.fingerprint,
        type_descriptor_document=descriptor.to_dict(include_fingerprint=False),
        configuration_document={"timeout_seconds": 12},
        probe_configuration_document=None,
        secret_bindings=bindings,
        created_at=NOW,
    )
    return revision, bindings


@dataclass
class _State:
    integration: OnlyIntegration
    revision: OnlyIntegrationRevision
    bindings: tuple[OnlyIntegrationSecretBinding, ...]

    def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration:
        if integration_id != self.integration.integration_id:
            raise LookupError("missing integration")
        return self.integration

    def load_revision(self, revision_fingerprint: str) -> OnlyIntegrationRevision:
        if revision_fingerprint != self.revision.revision_fingerprint:
            raise LookupError("missing revision")
        return self.revision

    def load_revision_secret_bindings(self, revision_fingerprint: str) -> tuple[OnlyIntegrationSecretBinding, ...]:
        if revision_fingerprint != self.revision.revision_fingerprint:
            raise LookupError("missing revision")
        return self.bindings


class _Catalog:
    def __init__(self, descriptor: OnlyIntegrationTypeDescriptorV1 | None) -> None:
        self.descriptor = descriptor

    def require(self, type_id: str) -> OnlyIntegrationTypeDescriptorV1:
        if self.descriptor is None or self.descriptor.type_id.value != type_id:
            raise LookupError("implementation unavailable")
        return self.descriptor


class _Credentials:
    def __init__(self) -> None:
        self.reads: list[tuple[str, int]] = []

    def read_secret(self, credential_id: str, credential_generation: int) -> str:
        self.reads.append((credential_id, credential_generation))
        return SECRET


class _Probes:
    def __init__(self, attempt: OnlyIntegrationProbeAttempt | None = None) -> None:
        self.attempt = attempt

    def latest_probe_attempt(
        self, integration_id: OnlyIntegrationId, revision_fingerprint: str
    ) -> OnlyIntegrationProbeAttempt | None:
        del integration_id, revision_fingerprint
        return self.attempt


class _RuntimeGenerations:
    def __init__(self, accepted: str) -> None:
        self.accepted = accepted
        self.requests: list[str] = []

    def require_runtime_generation(self, runtime_generation_fingerprint: str) -> object:
        self.requests.append(runtime_generation_fingerprint)
        if runtime_generation_fingerprint != self.accepted:
            raise LookupError("generation unavailable")
        return object()


def _resolver(
    *,
    lifecycle: OnlyIntegrationLifecycleState = OnlyIntegrationLifecycleState.ACTIVE,
    current: bool = True,
    catalog_descriptor: OnlyIntegrationTypeDescriptorV1 | None = None,
    revision: OnlyIntegrationRevision | None = None,
    bindings: tuple[OnlyIntegrationSecretBinding, ...] | None = None,
    credentials: _Credentials | None = None,
    probes: _Probes | None = None,
) -> tuple[OnlyIntegrationRuntimeResolver, OnlyIntegrationRevision, _Credentials]:
    descriptor = _descriptor()
    exact_revision, exact_bindings = _revision(descriptor)
    selected_revision = revision or exact_revision
    selected_bindings = exact_bindings if bindings is None else bindings
    integration = OnlyIntegration(
        INTEGRATION_ID,
        descriptor.type_id.value,
        "Test",
        lifecycle,
        selected_revision.revision_fingerprint if current else "a" * 64,
        NOW,
        NOW,
    )
    credential_reader = credentials or _Credentials()
    return (
        OnlyIntegrationRuntimeResolver(
            _State(integration, selected_revision, selected_bindings),
            credential_reader,
            _Catalog(descriptor if catalog_descriptor is None else catalog_descriptor),
            probes=probes,
        ),
        selected_revision,
        credential_reader,
    )


def test_admission_and_recovery_pin_exact_revision_and_secret_generation_without_plaintext_evidence() -> None:
    resolver, revision, credentials = _resolver()

    admitted = resolver.admit_new(
        INTEGRATION_ID,
        revision.revision_fingerprint,
        expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        required_capabilities=("HISTORICAL_BARS",),
    )
    binding_document = admitted.binding.to_dict()
    recovered = resolver.resolve(
        OnlyIntegrationRuntimeBindingV1.from_dict(binding_document),
        expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        required_capabilities=("HISTORICAL_BARS",),
    )

    assert credentials.reads == [(CREDENTIAL_ID, 3), (CREDENTIAL_ID, 3)]
    assert admitted.binding.revision_fingerprint == revision.revision_fingerprint
    assert admitted.type_descriptor == _descriptor()
    assert admitted.public_configuration == {"timeout_seconds": 12}
    assert admitted.secrets.require("token") == SECRET
    assert recovered.binding == admitted.binding
    assert SECRET not in repr(admitted)
    assert SECRET not in repr(admitted.secrets)
    assert SECRET not in str(binding_document)
    assert "secrets" not in binding_document


def test_pointer_and_lifecycle_changes_affect_new_admission_but_not_exact_recovery() -> None:
    resolver, revision, _ = _resolver()
    admitted = resolver.admit_new(
        INTEGRATION_ID,
        revision.revision_fingerprint,
        expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        require_current_revision=True,
    )
    resolver._state.integration = replace(  # type: ignore[attr-defined]
        resolver._state.integration,  # type: ignore[attr-defined]
        lifecycle_state=OnlyIntegrationLifecycleState.DISABLED,
        current_revision_fingerprint="b" * 64,
    )

    with pytest.raises(OnlyIntegrationRuntimeError) as denied:
        resolver.admit_new(
            INTEGRATION_ID,
            revision.revision_fingerprint,
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
            require_current_revision=True,
        )
    recovered = resolver.resolve(
        admitted.binding,
        expected_category=OnlyIntegrationCategory.DATA_SOURCE,
    )

    assert denied.value.code == "INTEGRATION_RUNTIME_DISABLED"
    assert recovered.binding == admitted.binding


def test_new_admission_rejects_a_revision_owned_by_another_integration() -> None:
    descriptor = _descriptor()
    foreign_revision, bindings = _revision(descriptor, integration_id=OTHER_INTEGRATION_ID)
    requested = OnlyIntegration(
        INTEGRATION_ID,
        descriptor.type_id.value,
        "Requested",
        OnlyIntegrationLifecycleState.ACTIVE,
        foreign_revision.revision_fingerprint,
        NOW,
        NOW,
    )
    foreign = replace(requested, integration_id=OTHER_INTEGRATION_ID, display_name="Foreign")

    class _MultiState(_State):
        def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration:
            return requested if integration_id == INTEGRATION_ID else foreign

    resolver = OnlyIntegrationRuntimeResolver(
        _MultiState(requested, foreign_revision, bindings),
        _Credentials(),
        _Catalog(descriptor),
    )

    with pytest.raises(OnlyIntegrationRuntimeError) as raised:
        resolver.admit_new(
            INTEGRATION_ID,
            foreign_revision.revision_fingerprint,
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        )

    assert raised.value.code == "INTEGRATION_RUNTIME_BINDING_INVALID"


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda binding: replace(binding, revision_fingerprint="f" * 64), "INTEGRATION_RUNTIME_REVISION_NOT_FOUND"),
        (
            lambda binding: replace(binding, integration_id=OnlyIntegrationId("a52eb762-34cf-47d4-8cca-56ef93f0d2ac")),
            "INTEGRATION_RUNTIME_REVISION_NOT_FOUND",
        ),
        (lambda binding: replace(binding, type_id="other.market_data"), "INTEGRATION_RUNTIME_BINDING_INVALID"),
        (
            lambda binding: replace(binding, category=OnlyIntegrationCategory.BROKER),
            "INTEGRATION_RUNTIME_CATEGORY_MISMATCH",
        ),
        (
            lambda binding: replace(binding, type_descriptor_fingerprint="e" * 64),
            "INTEGRATION_RUNTIME_IMPLEMENTATION_MISMATCH",
        ),
        (
            lambda binding: replace(binding, runtime_configuration_fingerprint="d" * 64),
            "INTEGRATION_RUNTIME_CONFIGURATION_CORRUPT",
        ),
    ],
)
def test_exact_binding_mismatches_fail_closed(
    mutation: Callable[[OnlyIntegrationRuntimeBindingV1], OnlyIntegrationRuntimeBindingV1],
    expected: str,
) -> None:
    resolver, revision, _ = _resolver()
    exact = OnlyIntegrationRuntimeBindingV1.from_revision(revision, OnlyIntegrationCategory.DATA_SOURCE)

    with pytest.raises(OnlyIntegrationRuntimeError) as raised:
        resolver.resolve(
            mutation(exact),
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        )

    assert raised.value.code == expected


def test_category_capability_implementation_and_secret_failures_remain_distinguishable() -> None:
    resolver, revision, _ = _resolver()
    binding = OnlyIntegrationRuntimeBindingV1.from_revision(revision, OnlyIntegrationCategory.DATA_SOURCE)

    with pytest.raises(OnlyIntegrationRuntimeError) as category:
        resolver.resolve(binding, expected_category=OnlyIntegrationCategory.BROKER)
    with pytest.raises(OnlyIntegrationRuntimeError) as capability:
        resolver.resolve(
            binding,
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
            required_capabilities=("REALTIME_DATA",),
        )

    unavailable, unavailable_revision, _ = _resolver(catalog_descriptor=None)
    unavailable._catalog.descriptor = None  # type: ignore[attr-defined]
    with pytest.raises(OnlyIntegrationRuntimeError) as implementation:
        unavailable.resolve(
            OnlyIntegrationRuntimeBindingV1.from_revision(unavailable_revision, OnlyIntegrationCategory.DATA_SOURCE),
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        )

    class _UnavailableCredentials(_Credentials):
        def read_secret(self, credential_id: str, credential_generation: int) -> str:
            del credential_id, credential_generation
            raise RuntimeError(SECRET)

    secret_resolver, secret_revision, _ = _resolver(credentials=_UnavailableCredentials())
    with pytest.raises(OnlyIntegrationRuntimeError) as secret:
        secret_resolver.resolve(
            OnlyIntegrationRuntimeBindingV1.from_revision(secret_revision, OnlyIntegrationCategory.DATA_SOURCE),
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        )

    assert category.value.code == "INTEGRATION_RUNTIME_CATEGORY_MISMATCH"
    assert capability.value.code == "INTEGRATION_RUNTIME_CAPABILITY_MISMATCH"
    assert implementation.value.code == "INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE"
    assert secret.value.code == "INTEGRATION_RUNTIME_SECRET_UNAVAILABLE"
    assert SECRET not in str(secret.value)
    assert secret.value.__cause__ is None


def test_new_admission_requires_exact_ready_probe_when_requested() -> None:
    resolver, revision, _ = _resolver(probes=_Probes())

    with pytest.raises(OnlyIntegrationRuntimeError) as missing:
        resolver.admit_new(
            INTEGRATION_ID,
            revision.revision_fingerprint,
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
            require_ready_probe=True,
        )

    assert missing.value.code == "INTEGRATION_RUNTIME_PROBE_REQUIRED"

    not_ready = SimpleNamespace(
        overall_status=OnlyIntegrationProbeStatus.DEGRADED,
        integration_id=INTEGRATION_ID,
        revision_fingerprint=revision.revision_fingerprint,
        runtime_configuration_fingerprint=revision.runtime_configuration_fingerprint,
    )
    resolver, revision, _ = _resolver(probes=_Probes(not_ready))  # type: ignore[arg-type]
    with pytest.raises(OnlyIntegrationRuntimeError) as degraded:
        resolver.admit_new(
            INTEGRATION_ID,
            revision.revision_fingerprint,
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
            require_ready_probe=True,
        )

    assert degraded.value.code == "INTEGRATION_RUNTIME_PROBE_NOT_READY"


def test_runtime_binding_parser_rejects_unknown_or_malformed_evidence() -> None:
    resolver, revision, _ = _resolver()
    document = OnlyIntegrationRuntimeBindingV1.from_revision(revision, OnlyIntegrationCategory.DATA_SOURCE).to_dict()

    with pytest.raises(OnlyIntegrationRuntimeError) as unknown:
        OnlyIntegrationRuntimeBindingV1.from_dict({**document, "secret": SECRET})
    with pytest.raises(OnlyIntegrationRuntimeError) as malformed:
        OnlyIntegrationRuntimeBindingV1.from_dict({**document, "schema_version": 2})

    assert unknown.value.code == "INTEGRATION_RUNTIME_BINDING_INVALID"
    assert malformed.value.code == "INTEGRATION_RUNTIME_BINDING_INVALID"
    assert SECRET not in str(unknown.value)
    assert resolver is not None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("integration_id", "not-a-uuid"),
        ("category", "NOT_A_CATEGORY"),
    ],
)
def test_runtime_binding_parser_sanitizes_invalid_nested_values(field: str, value: str) -> None:
    _, revision, _ = _resolver()
    document = OnlyIntegrationRuntimeBindingV1.from_revision(revision, OnlyIntegrationCategory.DATA_SOURCE).to_dict()

    with pytest.raises(OnlyIntegrationRuntimeError) as raised:
        OnlyIntegrationRuntimeBindingV1.from_dict({**document, field: value})

    assert raised.value.code == "INTEGRATION_RUNTIME_BINDING_INVALID"
    assert raised.value.__cause__ is None
    assert value not in str(raised.value)


def test_declared_runtime_generation_requires_exact_generation_authority() -> None:
    generation = "f" * 64
    resolver, revision, _ = _resolver()
    binding = OnlyIntegrationRuntimeBindingV1.from_revision(
        revision,
        OnlyIntegrationCategory.DATA_SOURCE,
        runtime_generation_fingerprint=generation,
    )

    with pytest.raises(OnlyIntegrationRuntimeError) as unavailable:
        resolver.resolve(binding, expected_category=OnlyIntegrationCategory.DATA_SOURCE)

    authority = _RuntimeGenerations(generation)
    admitted = OnlyIntegrationRuntimeResolver(
        resolver._state,
        resolver._credentials,
        resolver._catalog,
        runtime_generations=authority,
    ).resolve(binding, expected_category=OnlyIntegrationCategory.DATA_SOURCE)

    assert unavailable.value.code == "INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE"
    assert authority.requests == [generation]
    assert admitted.binding.runtime_generation_fingerprint == generation


def test_state_and_probe_outages_are_not_reported_as_absence_or_policy_denial() -> None:
    resolver, revision, _ = _resolver()

    class _UnavailableState(_State):
        def load_revision(self, revision_fingerprint: str) -> OnlyIntegrationRevision:
            del revision_fingerprint
            raise ConnectionError("raw database detail")

    state_unavailable = OnlyIntegrationRuntimeResolver(
        _UnavailableState(
            resolver._state.integration,  # type: ignore[attr-defined]
            revision,
            resolver._state.bindings,  # type: ignore[attr-defined]
        ),
        resolver._credentials,
        resolver._catalog,
    )
    with pytest.raises(OnlyIntegrationRuntimeError) as state_error:
        state_unavailable.resolve(
            OnlyIntegrationRuntimeBindingV1.from_revision(revision, OnlyIntegrationCategory.DATA_SOURCE),
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        )

    class _UnavailableProbes(_Probes):
        def latest_probe_attempt(
            self, integration_id: OnlyIntegrationId, revision_fingerprint: str
        ) -> OnlyIntegrationProbeAttempt | None:
            del integration_id, revision_fingerprint
            raise ConnectionError("raw database detail")

    probe_unavailable, probe_revision, _ = _resolver(probes=_UnavailableProbes())
    with pytest.raises(OnlyIntegrationRuntimeError) as probe_error:
        probe_unavailable.admit_new(
            INTEGRATION_ID,
            probe_revision.revision_fingerprint,
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
            require_ready_probe=True,
        )

    assert state_error.value.code == "INTEGRATION_RUNTIME_PERSISTENCE_UNAVAILABLE"
    assert probe_error.value.code == "INTEGRATION_RUNTIME_PERSISTENCE_UNAVAILABLE"
    assert state_error.value.__cause__ is None
    assert probe_error.value.__cause__ is None


def test_publish_race_closes_admission_on_one_exact_revision() -> None:
    descriptor = _descriptor()
    r1, b1 = _revision(descriptor, generation=3)
    r2, b2 = _revision(descriptor, generation=4)
    initial = OnlyIntegration(
        INTEGRATION_ID,
        descriptor.type_id.value,
        "Test",
        OnlyIntegrationLifecycleState.ACTIVE,
        r1.revision_fingerprint,
        NOW,
        NOW,
    )
    integration_read = Event()
    publish_committed = Event()

    class RacingState:
        integration = initial

        def load_integration(self, _integration_id: OnlyIntegrationId) -> OnlyIntegration:
            snapshot = self.integration
            integration_read.set()
            assert publish_committed.wait(5)
            return snapshot

        @staticmethod
        def load_revision(fingerprint: str) -> OnlyIntegrationRevision:
            return {r1.revision_fingerprint: r1, r2.revision_fingerprint: r2}[fingerprint]

        @staticmethod
        def load_revision_secret_bindings(fingerprint: str) -> tuple[OnlyIntegrationSecretBinding, ...]:
            return {r1.revision_fingerprint: b1, r2.revision_fingerprint: b2}[fingerprint]

    state = RacingState()
    credentials = _Credentials()
    resolver = OnlyIntegrationRuntimeResolver(state, credentials, _Catalog(descriptor))
    with ThreadPoolExecutor(max_workers=1) as executor:
        admitted = executor.submit(
            resolver.admit_new,
            INTEGRATION_ID,
            r1.revision_fingerprint,
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
            require_current_revision=True,
        )
        assert integration_read.wait(5)
        state.integration = replace(initial, current_revision_fingerprint=r2.revision_fingerprint)
        publish_committed.set()
        resolved = admitted.result()

    assert resolved.binding.revision_fingerprint == r1.revision_fingerprint
    assert credentials.reads == [(CREDENTIAL_ID, 3)]


def test_disable_race_has_only_fully_admitted_or_denied_outcomes() -> None:
    resolver, revision, _ = _resolver()
    integration_read = Event()
    disable_committed = Event()
    state = resolver._state  # type: ignore[attr-defined]
    original_load = state.load_integration

    def load_before_disable(integration_id: OnlyIntegrationId) -> OnlyIntegration:
        snapshot = original_load(integration_id)
        integration_read.set()
        assert disable_committed.wait(5)
        return snapshot

    state.load_integration = load_before_disable  # type: ignore[method-assign]
    with ThreadPoolExecutor(max_workers=1) as executor:
        admitted = executor.submit(
            resolver.admit_new,
            INTEGRATION_ID,
            revision.revision_fingerprint,
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        )
        assert integration_read.wait(5)
        state.integration = replace(state.integration, lifecycle_state=OnlyIntegrationLifecycleState.DISABLED)
        disable_committed.set()
        assert admitted.result().binding.revision_fingerprint == revision.revision_fingerprint

    with pytest.raises(OnlyIntegrationRuntimeError, match="INTEGRATION_RUNTIME_DISABLED"):
        resolver.admit_new(
            INTEGRATION_ID,
            revision.revision_fingerprint,
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        )


def test_secret_rotation_race_never_substitutes_a_new_generation() -> None:
    read_started = Event()
    rotation_committed = Event()

    class RacingCredentials(_Credentials):
        def read_secret(self, credential_id: str, credential_generation: int) -> str:
            self.reads.append((credential_id, credential_generation))
            read_started.set()
            assert rotation_committed.wait(5)
            raise LookupError("old generation retired")

    credentials = RacingCredentials()
    resolver, revision, _ = _resolver(credentials=credentials)
    with ThreadPoolExecutor(max_workers=1) as executor:
        admitted = executor.submit(
            resolver.admit_new,
            INTEGRATION_ID,
            revision.revision_fingerprint,
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        )
        assert read_started.wait(5)
        rotation_committed.set()
        with pytest.raises(OnlyIntegrationRuntimeError, match="INTEGRATION_RUNTIME_SECRET_UNAVAILABLE"):
            admitted.result()

    assert credentials.reads == [(CREDENTIAL_ID, 3)]

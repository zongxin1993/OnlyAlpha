from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from onlyalpha.application.integration_application import (
    OnlyCreateIntegration,
    OnlyIntegrationCommandResult,
    OnlyIntegrationCommandService,
    OnlyIntegrationConfigurationResolver,
    OnlyIntegrationQueryService,
    OnlySetIntegrationSecret,
    only_integration_secret_commitment,
)
from onlyalpha.application.integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationDraft,
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationSecretBinding,
)
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
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

INTEGRATION_ID = OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
COMMAND_ID = OnlyProductCommandId("f110020c-93b1-4823-b9c4-e834880ace84")


def _field(
    field_id: str,
    kind: OnlyIntegrationValueKind,
    *,
    required: bool = False,
    default: str | int | float | bool | None = None,
    secret: bool = False,
    enum_values: tuple[str, ...] = (),
    minimum: int | float | None = None,
    maximum: int | float | None = None,
) -> OnlyIntegrationConfigurationFieldV1:
    return OnlyIntegrationConfigurationFieldV1(
        field_id,
        kind,
        required=required,
        default=default,
        secret=secret,
        display_name=field_id,
        enum_values=enum_values,
        minimum=minimum,
        maximum=maximum,
    )


def _descriptor(
    *,
    selectable_probe: bool = True,
    probe: bool = True,
    secret_required: bool = True,
) -> OnlyIntegrationTypeDescriptorV1:
    return OnlyIntegrationTypeDescriptorV1(
        type_id=OnlyIntegrationTypeId("binance.spot.market_data"),
        category=OnlyIntegrationCategory.DATA_SOURCE,
        display_name="Binance Spot",
        description="Binance Spot market data",
        provider_id="binance",
        implementation_id="binance",
        implementation_version="1.0.0",
        public_api_version="1.1",
        capabilities=("HISTORICAL_BARS",),
        configuration_contract=OnlyIntegrationConfigurationContractV1(
            fields=(
                _field("api_key", OnlyIntegrationValueKind.STRING, required=secret_required, secret=True),
                _field("enabled", OnlyIntegrationValueKind.BOOLEAN, default=True),
                _field("environment", OnlyIntegrationValueKind.ENUM, required=True, enum_values=("LIVE", "TEST")),
                _field("name", OnlyIntegrationValueKind.STRING, required=True),
                _field("path", OnlyIntegrationValueKind.PATH),
                _field("retries", OnlyIntegrationValueKind.INTEGER, default=3, minimum=0, maximum=5),
                _field("timeout", OnlyIntegrationValueKind.DURATION, default=10.0, minimum=0.1),
                _field("weight", OnlyIntegrationValueKind.NUMBER, required=True),
                _field("weights", OnlyIntegrationValueKind.STRING_INTEGER_MAP),
            )
        ),
        probe_contract=(
            OnlyIntegrationProbeContractV1(
                OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT,
                "BTCUSDT",
                selectable_probe,
                (OnlyIntegrationProbeCheck.REFERENCE_DATA,),
            )
            if probe
            else None
        ),
    )


def test_draft_validation_rejects_unknown_secret_and_invalid_values_but_allows_incomplete() -> None:
    resolver = OnlyIntegrationConfigurationResolver()
    descriptor = _descriptor()

    public, probe = resolver.validate_draft(descriptor, {"weight": 1}, None)

    assert public == {"weight": 1}
    assert probe is None
    for document in (
        {"unknown": 1},
        {"api_key": "plaintext"},
        {"enabled": 1},
        {"retries": True},
        {"retries": 2.0},
        {"retries": 6},
        {"environment": "PAPER"},
        {"weights": {"BTC": True}},
        {"weights": {"BTC": 2.0}},
        {"weights": {1: 2}},
        {"weight": 10**400},
    ):
        with pytest.raises(OnlyIntegrationError) as raised:
            resolver.validate_draft(descriptor, document, None)
        assert raised.value.code == "INTEGRATION_CONFIGURATION_INVALID"


def test_publication_materializes_defaults_and_canonicalizes_numeric_and_map_values() -> None:
    resolver = OnlyIntegrationConfigurationResolver()
    descriptor = _descriptor()
    binding = OnlyIntegrationSecretBinding(
        "api_key",
        "ba13b6b1-af9a-450f-833d-48f5002297dc",
        1,
    )

    first = resolver.resolve_publication(
        INTEGRATION_ID,
        descriptor,
        {
            "environment": "LIVE",
            "name": "primary",
            "weight": 1.0,
            "weights": {"ETH": 2, "BTC": 1},
        },
        None,
        (binding,),
    )
    second = resolver.resolve_publication(
        INTEGRATION_ID,
        descriptor,
        {
            "environment": "LIVE",
            "name": "primary",
            "weight": 1,
            "weights": {"BTC": 1, "ETH": 2},
        },
        {},
        (binding,),
    )

    assert first.public_configuration == {
        "enabled": True,
        "environment": "LIVE",
        "name": "primary",
        "retries": 3,
        "timeout": 10,
        "weight": 1,
        "weights": {"BTC": 1, "ETH": 2},
    }
    assert first.probe_configuration == {"instrument": "BTCUSDT"}
    assert first.configuration_fingerprint == second.configuration_fingerprint
    assert first.runtime_configuration_fingerprint == second.runtime_configuration_fingerprint


def test_publication_rejects_missing_public_or_secret_requirements() -> None:
    resolver = OnlyIntegrationConfigurationResolver()
    descriptor = _descriptor()

    with pytest.raises(OnlyIntegrationError) as public_error:
        resolver.resolve_publication(INTEGRATION_ID, descriptor, {"weight": 1}, None, ())
    assert public_error.value.code == "INTEGRATION_CONFIGURATION_INCOMPLETE"

    with pytest.raises(OnlyIntegrationError) as secret_error:
        resolver.resolve_publication(
            INTEGRATION_ID,
            descriptor,
            {"environment": "LIVE", "name": "primary", "weight": 1},
            None,
            (),
        )
    assert secret_error.value.code == "INTEGRATION_SECRET_REQUIRED"


def test_optional_secret_may_be_absent_and_unknown_binding_is_rejected() -> None:
    resolver = OnlyIntegrationConfigurationResolver()
    public = {"environment": "LIVE", "name": "primary", "weight": 1}

    resolved = resolver.resolve_publication(
        INTEGRATION_ID,
        _descriptor(secret_required=False),
        public,
        None,
        (),
    )

    assert resolved.secret_bindings == ()
    with pytest.raises(OnlyIntegrationError) as wrong_field:
        resolver.resolve_publication(
            INTEGRATION_ID,
            _descriptor(secret_required=False),
            public,
            None,
            (
                OnlyIntegrationSecretBinding(
                    "not_a_secret",
                    "ba13b6b1-af9a-450f-833d-48f5002297dc",
                    1,
                ),
            ),
        )
    assert wrong_field.value.code == "INTEGRATION_SECRET_BINDING_INVALID"


def test_probe_resolution_enforces_contract_and_stays_out_of_runtime_identity() -> None:
    resolver = OnlyIntegrationConfigurationResolver()
    binding = OnlyIntegrationSecretBinding(
        "api_key",
        "ba13b6b1-af9a-450f-833d-48f5002297dc",
        1,
    )
    public = {"environment": "LIVE", "name": "primary", "weight": 1}

    first = resolver.resolve_publication(INTEGRATION_ID, _descriptor(), public, None, (binding,))
    second = resolver.resolve_publication(
        INTEGRATION_ID,
        _descriptor(),
        public,
        {"instrument": "ETHUSDT"},
        (binding,),
    )

    assert first.probe_configuration == {"instrument": "BTCUSDT"}
    assert second.probe_configuration == {"instrument": "ETHUSDT"}
    assert first.runtime_configuration_fingerprint == second.runtime_configuration_fingerprint
    assert first.probe_configuration_fingerprint != second.probe_configuration_fingerprint

    with pytest.raises(OnlyIntegrationError) as fixed:
        resolver.validate_draft(_descriptor(selectable_probe=False), public, {"instrument": "ETHUSDT"})
    assert fixed.value.code == "INTEGRATION_PROBE_CONFIGURATION_INVALID"
    with pytest.raises(OnlyIntegrationError) as absent:
        resolver.validate_draft(_descriptor(probe=False), public, {"instrument": "BTCUSDT"})
    assert absent.value.code == "INTEGRATION_PROBE_CONFIGURATION_INVALID"


def test_runtime_identity_changes_with_exact_secret_generation() -> None:
    resolver = OnlyIntegrationConfigurationResolver()
    public = {"environment": "LIVE", "name": "primary", "weight": 1}
    first_binding = OnlyIntegrationSecretBinding(
        "api_key",
        "ba13b6b1-af9a-450f-833d-48f5002297dc",
        1,
    )
    rotated_binding = OnlyIntegrationSecretBinding(
        first_binding.field_id,
        first_binding.credential_id,
        2,
    )

    first = resolver.resolve_publication(INTEGRATION_ID, _descriptor(), public, None, (first_binding,))
    rotated = resolver.resolve_publication(INTEGRATION_ID, _descriptor(), public, None, (rotated_binding,))

    assert first.runtime_configuration_fingerprint != rotated.runtime_configuration_fingerprint


def test_publication_candidate_constructs_revision_without_caller_supplied_fingerprints() -> None:
    binding = OnlyIntegrationSecretBinding(
        "api_key",
        "ba13b6b1-af9a-450f-833d-48f5002297dc",
        1,
    )
    candidate = OnlyIntegrationConfigurationResolver().resolve_publication(
        INTEGRATION_ID,
        _descriptor(),
        {"environment": "LIVE", "name": "primary", "weight": 1},
        None,
        (binding,),
    )

    revision = candidate.to_revision(1, datetime(2026, 9, 21, tzinfo=UTC))

    assert revision.integration_id == INTEGRATION_ID
    assert revision.configuration_fingerprint == candidate.configuration_fingerprint
    assert revision.runtime_configuration_fingerprint == candidate.runtime_configuration_fingerprint
    assert revision.secret_binding_fingerprint == candidate.secret_binding_fingerprint


def test_secret_commitment_is_keyed_context_separated_and_redacted_from_command_repr() -> None:
    key = b"k" * 32
    first = only_integration_secret_commitment(key, INTEGRATION_ID, "api_key", "secret")

    assert first == only_integration_secret_commitment(key, INTEGRATION_ID, "api_key", "secret")
    assert first != only_integration_secret_commitment(key, INTEGRATION_ID, "api_key", "changed")
    assert first != only_integration_secret_commitment(
        key,
        OnlyIntegrationId("672e3601-506f-45ea-ad7e-452e36f548ea"),
        "api_key",
        "secret",
    )
    assert first != only_integration_secret_commitment(key, INTEGRATION_ID, "api_secret", "secret")
    assert first != hashlib.sha256(b"secret").hexdigest()
    command = OnlySetIntegrationSecret(COMMAND_ID, INTEGRATION_ID, 1, "api_key", "secret")
    assert "secret" not in repr(command)


def test_command_service_resolves_current_type_and_creates_global_product_admission() -> None:
    descriptor = _descriptor()
    store = _CommandStore(descriptor)
    service = OnlyIntegrationCommandService(_Catalog(descriptor), store, b"k" * 32)

    result = service.create_integration(
        OnlyCreateIntegration(COMMAND_ID, INTEGRATION_ID, descriptor.type_id.value, "Primary")
    )

    assert result.receipt.command_kind is OnlyProductCommandKind.CREATE_INTEGRATION
    assert result.receipt.outcome_ref == OnlyProductCommandOutcomeRef(
        OnlyProductCommandOutcomeKind.INTEGRATION,
        INTEGRATION_ID.value,
    )
    assert store.admissions[-1].command_kind is OnlyProductCommandKind.CREATE_INTEGRATION


def test_secret_command_fingerprint_uses_commitment_not_plaintext_and_changes_with_secret() -> None:
    descriptor = _descriptor()
    store = _CommandStore(descriptor)
    service = OnlyIntegrationCommandService(_Catalog(descriptor), store, b"k" * 32)

    command = OnlySetIntegrationSecret(COMMAND_ID, INTEGRATION_ID, 1, "api_key", "plain-secret")
    service.set_integration_secret(command)
    first = store.admissions[-1].command_fingerprint
    service.set_integration_secret(command)
    same = store.admissions[-1].command_fingerprint
    service.set_integration_secret(
        OnlySetIntegrationSecret(COMMAND_ID, INTEGRATION_ID, 1, "api_key", "different-secret")
    )
    changed = store.admissions[-1].command_fingerprint

    assert first == same
    assert first != changed
    assert "plain-secret" not in repr(store.admissions)


@dataclass
class _Catalog:
    descriptor: OnlyIntegrationTypeDescriptorV1

    def require(self, type_id: str) -> OnlyIntegrationTypeDescriptorV1:
        if type_id != self.descriptor.type_id.value:
            raise LookupError(type_id)
        return self.descriptor


class _CommandStore:
    def __init__(self, descriptor: OnlyIntegrationTypeDescriptorV1) -> None:
        self.admissions = []
        self.descriptor = descriptor

    def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration:
        return OnlyIntegration(
            integration_id,
            self.descriptor.type_id.value,
            "Primary",
            OnlyIntegrationLifecycleState.ACTIVE,
            None,
            datetime(2026, 9, 21, tzinfo=UTC),
            datetime(2026, 9, 21, tzinfo=UTC),
        )

    def load_draft(self, integration_id: OnlyIntegrationId) -> OnlyIntegrationDraft:
        return OnlyIntegrationDraft.create(
            integration_id=integration_id,
            descriptor=self.descriptor,
            public_configuration={},
            probe_configuration=None,
            created_at=datetime(2026, 9, 21, tzinfo=UTC),
        )

    def replay_command(self, admission, integration_id, outcome_kind):  # type: ignore[no-untyped-def]
        return None

    def create_integration_with_receipt(self, admission, integration_id, descriptor, display_name):  # type: ignore[no-untyped-def]
        self.admissions.append(admission)
        return _result(admission, OnlyProductCommandOutcomeKind.INTEGRATION, integration_id.value)

    def set_secret_with_receipt(  # type: ignore[no-untyped-def]
        self, admission, integration_id, expected_draft_version, descriptor, field_id, plaintext_secret
    ):
        self.admissions.append(admission)
        return _result(admission, OnlyProductCommandOutcomeKind.INTEGRATION, integration_id.value)


def _result(admission, outcome_kind, outcome_id):  # type: ignore[no-untyped-def]
    return OnlyIntegrationCommandResult(
        OnlyProductCommandReceipt(
            admission.command_id,
            admission.command_kind,
            admission.command_fingerprint,
            OnlyProductCommandOutcomeRef(outcome_kind, outcome_id),
            datetime(2026, 9, 21, tzinfo=UTC),
        ),
        replayed=False,
    )


def test_integration_query_list_is_persisted_filtered_and_deterministic() -> None:
    later = OnlyIntegration(
        OnlyIntegrationId("00000000-0000-4000-8000-000000000002"),
        "binance.spot.market_data",
        "Later",
        OnlyIntegrationLifecycleState.ACTIVE,
        None,
        datetime(2026, 9, 21, 1, tzinfo=UTC),
        datetime(2026, 9, 21, 1, tzinfo=UTC),
    )
    earlier = OnlyIntegration(
        OnlyIntegrationId("00000000-0000-4000-8000-000000000001"),
        "binance.spot.market_data",
        "Earlier",
        OnlyIntegrationLifecycleState.ACTIVE,
        None,
        datetime(2026, 9, 21, tzinfo=UTC),
        datetime(2026, 9, 21, tzinfo=UTC),
    )

    class Store:
        def list_integrations(self, type_id, lifecycle_state):  # type: ignore[no-untyped-def]
            assert type_id == "binance.spot.market_data"
            assert lifecycle_state is OnlyIntegrationLifecycleState.ACTIVE
            return later, earlier

    listed = OnlyIntegrationQueryService(Store()).list_integrations(  # type: ignore[arg-type]
        type_id="binance.spot.market_data",
        lifecycle_state=OnlyIntegrationLifecycleState.ACTIVE,
    )

    assert listed == (earlier, later)

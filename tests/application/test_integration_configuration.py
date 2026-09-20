from dataclasses import replace
from datetime import UTC, datetime

import pytest

from onlyalpha.application.integration_configuration import (
    OnlyIntegrationDraft,
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
    only_integration_secret_binding_fingerprint,
)
from onlyalpha.canonical import only_canonical_json
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

NOW = datetime(2026, 9, 20, tzinfo=UTC)


def _descriptor() -> OnlyIntegrationTypeDescriptorV1:
    return OnlyIntegrationTypeDescriptorV1(
        type_id=OnlyIntegrationTypeId("binance.spot.market_data"),
        category=OnlyIntegrationCategory.DATA_SOURCE,
        display_name="Binance Spot Market Data",
        description="Binance Spot market-data access.",
        provider_id="binance",
        implementation_id="binance",
        implementation_version="1.0.0",
        public_api_version="1.1",
        capabilities=("HISTORICAL_BARS",),
        configuration_contract=OnlyIntegrationConfigurationContractV1(
            fields=(
                OnlyIntegrationConfigurationFieldV1(
                    "api_key",
                    OnlyIntegrationValueKind.STRING,
                    required=True,
                    secret=True,
                    display_name="API key",
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
        probe_contract=OnlyIntegrationProbeContractV1(
            OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT,
            "BTCUSDT",
            True,
            (OnlyIntegrationProbeCheck.REFERENCE_DATA,),
        ),
    )


def test_integration_id_requires_canonical_uuid4() -> None:
    value = "b52eb762-34cf-47d4-8cca-56ef93f0d2ac"

    assert str(OnlyIntegrationId(value)) == value
    for invalid in ("", "BINANCE", "b52eb76234cf47d48cca56ef93f0d2ac"):
        with pytest.raises(OnlyIntegrationError) as raised:
            OnlyIntegrationId(invalid)
        assert raised.value.code == "INTEGRATION_ID_INVALID"


def test_draft_freezes_exact_descriptor_and_keeps_probe_separate_from_public_configuration() -> None:
    descriptor = _descriptor()
    draft = OnlyIntegrationDraft.create(
        integration_id=OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
        descriptor=descriptor,
        public_configuration={"timeout_seconds": 12},
        probe_configuration={"instrument": "BTCUSDT"},
        created_at=NOW,
    )

    assert draft.type_descriptor_fingerprint == descriptor.fingerprint
    assert only_canonical_json(draft.type_descriptor_document) == only_canonical_json(
        descriptor.to_dict(include_fingerprint=False)
    )
    assert draft.public_configuration_document == {"timeout_seconds": 12}
    assert draft.probe_configuration_document == {"instrument": "BTCUSDT"}
    assert "instrument" not in draft.public_configuration_document
    assert draft.draft_version == 1


def test_draft_rejects_declared_secret_fields_in_public_configuration() -> None:
    with pytest.raises(OnlyIntegrationError) as raised:
        OnlyIntegrationDraft.create(
            integration_id=OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
            descriptor=_descriptor(),
            public_configuration={"api_key": "plaintext"},
            probe_configuration={},
            created_at=NOW,
        )

    assert raised.value.code == "INTEGRATION_CONFIGURATION_DOCUMENT_INVALID"


def test_draft_rejects_declared_secret_fields_in_probe_configuration() -> None:
    with pytest.raises(OnlyIntegrationError) as raised:
        OnlyIntegrationDraft.create(
            integration_id=OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
            descriptor=_descriptor(),
            public_configuration={},
            probe_configuration={"api_key": "plaintext"},
            created_at=NOW,
        )

    assert raised.value.code == "INTEGRATION_CONFIGURATION_DOCUMENT_INVALID"


def test_revision_derivation_rejects_a_forged_draft_containing_plaintext_secret() -> None:
    draft = OnlyIntegrationDraft.create(
        integration_id=OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
        descriptor=_descriptor(),
        public_configuration={},
        probe_configuration=None,
        created_at=NOW,
    )
    forged = replace(draft, public_configuration_document={"api_key": "plaintext"})

    with pytest.raises(OnlyIntegrationError) as raised:
        OnlyIntegrationRevision.from_draft(forged, 1, "a" * 64, (), NOW)

    assert raised.value.code == "INTEGRATION_CONFIGURATION_DOCUMENT_INVALID"


def test_revision_derivation_rejects_a_forged_probe_containing_plaintext_secret() -> None:
    draft = OnlyIntegrationDraft.create(
        integration_id=OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
        descriptor=_descriptor(),
        public_configuration={},
        probe_configuration=None,
        created_at=NOW,
    )
    forged = replace(draft, probe_configuration_document={"api_key": "plaintext"})

    with pytest.raises(OnlyIntegrationError) as raised:
        OnlyIntegrationRevision.from_draft(forged, 1, "a" * 64, (), NOW)

    assert raised.value.code == "INTEGRATION_CONFIGURATION_DOCUMENT_INVALID"


def test_secret_binding_fingerprint_is_order_independent_and_generation_sensitive() -> None:
    first = OnlyIntegrationSecretBinding("api_secret", "7f69c217-e483-401f-b8f1-8960540b5327", 2)
    second = OnlyIntegrationSecretBinding("api_key", "ba13b6b1-af9a-450f-833d-48f5002297dc", 1)

    fingerprint = only_integration_secret_binding_fingerprint((first, second))

    assert fingerprint == only_integration_secret_binding_fingerprint((second, first))
    rotated = OnlyIntegrationSecretBinding(first.field_id, first.credential_id, 3)
    assert fingerprint != only_integration_secret_binding_fingerprint((second, rotated))


@pytest.mark.parametrize("generation", [True, 1.0])
def test_secret_binding_generation_requires_an_integer(generation: object) -> None:
    with pytest.raises(OnlyIntegrationError) as raised:
        OnlyIntegrationSecretBinding(
            "api_key",
            "ba13b6b1-af9a-450f-833d-48f5002297dc",
            generation,  # type: ignore[arg-type]
        )

    assert raised.value.code == "INTEGRATION_SECRET_BINDING_INVALID"


def test_revision_identity_converges_and_excludes_sequence_and_timestamps() -> None:
    draft = OnlyIntegrationDraft.create(
        integration_id=OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
        descriptor=_descriptor(),
        public_configuration={"timeout_seconds": 12},
        probe_configuration={"instrument": "BTCUSDT"},
        created_at=NOW,
    )
    bindings = (OnlyIntegrationSecretBinding("api_key", "ba13b6b1-af9a-450f-833d-48f5002297dc", 1),)
    runtime_fingerprint = "a" * 64

    first = OnlyIntegrationRevision.from_draft(draft, 1, runtime_fingerprint, bindings, NOW)
    second = OnlyIntegrationRevision.from_draft(
        draft,
        99,
        runtime_fingerprint,
        bindings,
        datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert first.revision_fingerprint == second.revision_fingerprint
    assert first.configuration_fingerprint == second.configuration_fingerprint
    assert first.probe_configuration_fingerprint == second.probe_configuration_fingerprint
    assert first.secret_binding_fingerprint == only_integration_secret_binding_fingerprint(bindings)


def test_probe_configuration_changes_revision_evidence_but_not_supplied_runtime_identity() -> None:
    integration_id = OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
    first_draft = OnlyIntegrationDraft.create(
        integration_id=integration_id,
        descriptor=_descriptor(),
        public_configuration={"timeout_seconds": 12},
        probe_configuration={"instrument": "BTCUSDT"},
        created_at=NOW,
    )
    second_draft = OnlyIntegrationDraft.create(
        integration_id=integration_id,
        descriptor=_descriptor(),
        public_configuration={"timeout_seconds": 12},
        probe_configuration={"instrument": "ETHUSDT"},
        created_at=NOW,
    )

    first = OnlyIntegrationRevision.from_draft(first_draft, 1, "a" * 64, (), NOW)
    second = OnlyIntegrationRevision.from_draft(second_draft, 2, "a" * 64, (), NOW)

    assert first.runtime_configuration_fingerprint == second.runtime_configuration_fingerprint
    assert first.configuration_fingerprint == second.configuration_fingerprint
    assert first.probe_configuration_fingerprint != second.probe_configuration_fingerprint
    assert first.revision_fingerprint != second.revision_fingerprint

"""Production composition of the persistence-backed Integration Runtime Resolver."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from onlyalpha_plugin_tushare.descriptor import DATA_INTEGRATION_TYPE

from onlyalpha.application.integration_configuration import (
    OnlyIntegrationId,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
)
from onlyalpha.application.integration_runtime import OnlyIntegrationRuntimeError
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.persistence.postgres import (
    MASTER_KEY_FILE,
    OnlyIntegrationRuntimeCompositionV1,
    only_compose_integration_runtime_resolver,
    only_ensure_dev_master_key,
)
from onlyalpha.plugin.integration import OnlyIntegrationCategory

NOW = datetime(2026, 9, 22, tzinfo=UTC)
INTEGRATION_ID = OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
CREDENTIAL_ID = "ba13b6b1-af9a-450f-833d-48f5002297dc"


def _composition(
    root: Path, dsn: str = "postgresql://onlyalpha:onlyalpha@127.0.0.1:5432/onlyalpha"
) -> OnlyIntegrationRuntimeCompositionV1:
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


def test_integration_admission_with_unreachable_authority_fails_with_stable_error(tmp_path: Path) -> None:
    only_ensure_dev_master_key(tmp_path / MASTER_KEY_FILE)
    resolver = only_compose_integration_runtime_resolver(
        _composition(tmp_path, dsn="postgresql://onlyalpha:onlyalpha@127.0.0.1:1/onlyalpha"),
        OnlyDataSourceFactoryRegistry(),
        OnlyBrokerFactoryRegistry(),
    )
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
    # PC-05: stable infrastructure error, never a legacy fallback result.
    with pytest.raises(OnlyIntegrationRuntimeError) as raised:
        resolver.admit_new(
            INTEGRATION_ID,
            revision.revision_fingerprint,
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        )
    assert raised.value.code == "INTEGRATION_RUNTIME_PERSISTENCE_UNAVAILABLE"

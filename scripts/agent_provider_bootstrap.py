"""Dev bootstrap provisioning of canonical Agent Provider Integration authority state.

All durable state flows through the existing authorities only: the Integration command
service over the PostgreSQL product store (receipt-replay idempotency), the PostgreSQL
credential authority, the Integration probe service, and the Integration query service.
This module contains no direct SQL and no second command or credential path.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from onlyalpha_agent_orchestrator.provider_integration import (
    OnlyAgentModelProfileV1,
    OnlyOpenAICompatibleAgentProviderProbe,
)

from onlyalpha.application.integration_application import (
    OnlyCreateIntegration,
    OnlyIntegrationCommandService,
    OnlyIntegrationQueryService,
    OnlyPublishIntegrationRevision,
    OnlySetIntegrationSecret,
    OnlyUpdateIntegrationDraft,
)
from onlyalpha.application.integration_configuration import (
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationRevision,
)
from onlyalpha.application.integration_probe import OnlyIntegrationProbeService
from onlyalpha.application.integration_type_catalog import OnlyIntegrationProbeCatalog, OnlyIntegrationTypeCatalog
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.canonical import only_canonical_json
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    MASTER_KEY_FILE,
    OnlyPostgresCredentialAuthority,
    OnlyPostgresIntegrationProductStore,
    OnlyPostgresOperationalConnectionOptions,
    only_ensure_dev_master_key,
)
from onlyalpha.persistence.postgres.integration_probe_store import OnlyPostgresIntegrationProbeStore
from onlyalpha.plugin.agent_provider import OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.plugin.integration_probe import OnlyIntegrationProbeStatus

ONLY_DEV_AGENT_PROVIDER_INTEGRATION_ID = OnlyIntegrationId("c85f5c5a-741d-474f-aa1d-a797e837d8da")

# Fixed command identities so every re-run replays the stored Product command receipts
# instead of mutating durable Integration authority state a second time.
_CREATE_COMMAND_ID = OnlyProductCommandId("b937179c-a3a5-4ccd-ae98-8992f7890e5d")
_UPDATE_DRAFT_COMMAND_ID = OnlyProductCommandId("40c02e40-ea6e-41f5-b7fa-0b3ebfcc26fb")
_SET_SECRET_COMMAND_ID = OnlyProductCommandId("b3c27cea-7f64-4e88-a328-2abb48e50931")
_PUBLISH_COMMAND_ID = OnlyProductCommandId("39e8c1c2-6923-45ad-9b23-a4e837e1d07f")

_DEV_DISPLAY_NAME = "Dev Agent Provider"
_REQUIRED_CAPABILITIES = ("CHAT", "MODEL_DISCOVERY", "STRUCTURED_OUTPUT")
_CONTROL_TOKEN_FILE = "agent-control-token"
_PRODUCT_TOKEN_FILE = "agent-product-token"
_RUNTIME_TOKEN_FILE = "agent-runtime-token"
_MODEL_PROFILE_FILE = "model-profile.json"


@dataclass(frozen=True, slots=True)
class OnlyDevAgentAuthorityProvision:
    model_profile_path: Path
    control_token_path: Path
    product_token_path: Path
    runtime_token_path: Path
    integration_id: OnlyIntegrationId
    revision_fingerprint: str

    def summary_document(self) -> dict[str, object]:
        """Provisioning summary that never contains secret values."""

        return {
            "integration_id": self.integration_id.value,
            "integration_type_id": OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE.type_id.value,
            "revision_fingerprint": self.revision_fingerprint,
            "model_profile_path": str(self.model_profile_path),
            "control_token_path": str(self.control_token_path),
            "product_token_path": str(self.product_token_path),
            "runtime_token_path": str(self.runtime_token_path),
        }


def only_provision_dev_agent_authority(
    *,
    postgres_dsn: str,
    user_data_root: Path,
    provider_base_url: str,
    provider_api_credential: str,
    model_id: str,
    model_version: str,
    connection_options: OnlyPostgresOperationalConnectionOptions | None = None,
) -> OnlyDevAgentAuthorityProvision:
    """Provision the canonical dev Agent Provider authority state idempotently.

    Integration creation, draft configuration, encrypted secret, published revision R1,
    and the READY probe certification all flow through existing authorities. Re-runs
    replay receipts and never rotate identity or regenerate secrets. A published
    revision whose probe is not READY fails the provisioning closed.
    """

    layout = OnlyUserDataLayout(user_data_root)
    master_key = only_ensure_dev_master_key(layout.root / MASTER_KEY_FILE)
    secrets_root = layout.root / "secrets"
    control_token_path = secrets_root / _CONTROL_TOKEN_FILE
    product_token_path = secrets_root / _PRODUCT_TOKEN_FILE
    runtime_token_path = secrets_root / _RUNTIME_TOKEN_FILE
    for token_path in (control_token_path, product_token_path, runtime_token_path):
        _ensure_token_file(token_path)
    profile_path = layout.root / "agent" / _MODEL_PROFILE_FILE

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
    agent_type = OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE
    store = OnlyPostgresIntegrationProductStore(postgres_dsn, master_key, options=connection_options)
    commands = OnlyIntegrationCommandService(
        OnlyIntegrationTypeCatalog(data_sources, brokers, (agent_type,)),
        store,
        master_key,
    )
    queries = OnlyIntegrationQueryService(store)

    current = _current_dev_revision(queries)
    if current is not None:
        profile = _load_matching_profile(profile_path, current, model_id, model_version)
        if profile is not None:
            return OnlyDevAgentAuthorityProvision(
                profile_path,
                control_token_path,
                product_token_path,
                runtime_token_path,
                ONLY_DEV_AGENT_PROVIDER_INTEGRATION_ID,
                current.revision_fingerprint,
            )

    dev_id = ONLY_DEV_AGENT_PROVIDER_INTEGRATION_ID
    commands.create_integration(
        OnlyCreateIntegration(_CREATE_COMMAND_ID, dev_id, agent_type.type_id.value, _DEV_DISPLAY_NAME)
    )
    commands.update_integration_draft(
        OnlyUpdateIntegrationDraft(
            _UPDATE_DRAFT_COMMAND_ID,
            dev_id,
            1,
            {
                "base_url": provider_base_url,
                "connect_timeout_seconds": 10,
                "read_timeout_seconds": 60,
                # Explicit dev configuration value for the plain-HTTP provider fixture,
                # not a transport-guard bypass.
                "verify_tls": False,
            },
            None,
        )
    )
    commands.set_integration_secret(
        OnlySetIntegrationSecret(_SET_SECRET_COMMAND_ID, dev_id, 2, "api_credential", provider_api_credential)
    )
    published = commands.publish_integration_revision(OnlyPublishIntegrationRevision(_PUBLISH_COMMAND_ID, dev_id, 3))
    revision_fingerprint = published.receipt.outcome_ref.outcome_id

    probes = OnlyIntegrationProbeService(
        store,
        OnlyPostgresIntegrationProbeStore(postgres_dsn, options=connection_options),
        OnlyPostgresCredentialAuthority(postgres_dsn, master_key, options=connection_options),
        OnlyIntegrationProbeCatalog(data_sources, brokers, ((agent_type, OnlyOpenAICompatibleAgentProviderProbe()),)),
    )
    attempt = probes.probe(dev_id, revision_fingerprint)
    if attempt.overall_status is not OnlyIntegrationProbeStatus.READY:
        raise RuntimeError(f"AGENT_PROVIDER_PROVISION_PROBE_NOT_READY: {attempt.overall_status.value}")

    revision = queries.get_revision(revision_fingerprint)
    profile = OnlyAgentModelProfileV1(
        revision.integration_id.value,
        revision.revision_fingerprint,
        revision.runtime_configuration_fingerprint,
        model_id,
        model_version,
        _REQUIRED_CAPABILITIES,
    )
    _write_model_profile(profile_path, profile)
    return OnlyDevAgentAuthorityProvision(
        profile_path,
        control_token_path,
        product_token_path,
        runtime_token_path,
        dev_id,
        revision_fingerprint,
    )


def _current_dev_revision(queries: OnlyIntegrationQueryService) -> OnlyIntegrationRevision | None:
    try:
        return queries.get_current_revision(ONLY_DEV_AGENT_PROVIDER_INTEGRATION_ID)
    except OnlyIntegrationError as exc:
        if exc.code == "INTEGRATION_NOT_FOUND":
            return None
        raise


def _load_matching_profile(
    path: Path,
    revision: OnlyIntegrationRevision,
    model_id: str,
    model_version: str,
) -> OnlyAgentModelProfileV1 | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        profile = OnlyAgentModelProfileV1.from_dict(payload)
    except (OSError, ValueError):
        return None
    if (
        profile.provider_integration_id != revision.integration_id.value
        or profile.provider_revision_fingerprint != revision.revision_fingerprint
        or profile.provider_runtime_configuration_fingerprint != revision.runtime_configuration_fingerprint
        or profile.model_id != model_id
        or profile.model_version != model_version
    ):
        return None
    return profile


def _ensure_token_file(path: Path) -> None:
    """Create one durable random token file at 0600 without ever replacing an existing one."""

    if path.is_symlink():
        raise ValueError("AGENT_PROVIDER_TOKEN_FILE_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return
    token = secrets.token_urlsafe(32)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(token + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o600)


def _write_model_profile(path: Path, profile: OnlyAgentModelProfileV1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(only_canonical_json(profile.to_dict()))
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o644)


__all__ = [
    "ONLY_DEV_AGENT_PROVIDER_INTEGRATION_ID",
    "OnlyDevAgentAuthorityProvision",
    "only_provision_dev_agent_authority",
]

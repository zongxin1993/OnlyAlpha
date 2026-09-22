"""Bootstrap provisioning of canonical dev Agent Provider Integration authority state."""

from __future__ import annotations

import json
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from onlyalpha_agent_orchestrator.provider_integration import OnlyAgentModelProfileV1

from onlyalpha.application.integration_application import OnlyIntegrationQueryService
from onlyalpha.persistence.postgres import (
    MASTER_KEY_FILE,
    OnlyPostgresIntegrationStore,
    only_load_master_key,
)
from onlyalpha.persistence.postgres.integration_probe_store import OnlyPostgresIntegrationProbeStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.plugin.integration_probe import OnlyIntegrationProbeStatus
from scripts.agent_provider_bootstrap import only_provision_dev_agent_authority
from tests.runtime_support.openai_compatible_provider_fixture import (
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_VERSION,
    DEFAULT_TOKEN,
    only_create_openai_compatible_provider_server,
)

pytestmark = pytest.mark.postgres


@contextmanager
def _running_fixture() -> Iterator[ThreadingHTTPServer]:
    server = only_create_openai_compatible_provider_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _provision(postgres_dsn: str, user_data_root: Path, base_url: str, credential: str = DEFAULT_TOKEN):  # type: ignore[no-untyped-def]
    return only_provision_dev_agent_authority(
        postgres_dsn=postgres_dsn,
        user_data_root=user_data_root,
        provider_base_url=base_url,
        provider_api_credential=credential,
        model_id=DEFAULT_MODEL_ID,
        model_version=DEFAULT_MODEL_VERSION,
    )


def test_bootstrap_provisions_agent_provider_authority_and_replays_without_rotation(
    postgres_dsn: str, tmp_path: Path
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    with _running_fixture() as server:
        base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        first = _provision(postgres_dsn, tmp_path, base_url)

        token_paths = (first.control_token_path, first.product_token_path, first.runtime_token_path)
        assert len(set(token_paths)) == 3
        for path in token_paths:
            assert path.parent == tmp_path / "secrets"
            assert path.is_file() and not path.is_symlink()
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert path.read_text(encoding="utf-8").strip()
        assert first.model_profile_path == tmp_path / "agent" / "model-profile.json"
        assert stat.S_IMODE(first.model_profile_path.stat().st_mode) == 0o644

        profile = OnlyAgentModelProfileV1.from_dict(json.loads(first.model_profile_path.read_text(encoding="utf-8")))
        assert profile.provider_integration_id == first.integration_id.value
        assert profile.provider_revision_fingerprint == first.revision_fingerprint
        assert profile.model_id == DEFAULT_MODEL_ID
        assert profile.model_version == DEFAULT_MODEL_VERSION
        assert profile.required_capabilities == ("CHAT", "MODEL_DISCOVERY", "STRUCTURED_OUTPUT")

        queries = OnlyIntegrationQueryService(OnlyPostgresIntegrationStore(postgres_dsn))
        current = queries.get_current_revision(first.integration_id)
        assert current is not None and current.revision_fingerprint == first.revision_fingerprint
        assert len(queries.list_revision_history(first.integration_id)) == 1
        assert queries.get_revision_secret_status(first.revision_fingerprint)[0].generation == 1
        attempt = OnlyPostgresIntegrationProbeStore(postgres_dsn).latest_probe_attempt(
            first.integration_id, first.revision_fingerprint
        )
        assert attempt is not None and attempt.overall_status is OnlyIntegrationProbeStatus.READY

        token_values = {path.read_text(encoding="utf-8") for path in token_paths}
        master_key = only_load_master_key(tmp_path / MASTER_KEY_FILE)
        summary = json.dumps(first.summary_document(), sort_keys=True)
        assert DEFAULT_TOKEN not in summary
        assert not any(token in summary for token in token_values)

        second = _provision(postgres_dsn, tmp_path, base_url)

        assert second.integration_id == first.integration_id
        assert second.revision_fingerprint == first.revision_fingerprint
        assert second.model_profile_path == first.model_profile_path
        assert {path.read_text(encoding="utf-8") for path in token_paths} == token_values
        assert only_load_master_key(tmp_path / MASTER_KEY_FILE) == master_key
        assert queries.get_revision_secret_status(second.revision_fingerprint)[0].generation == 1
        assert len(queries.list_revision_history(second.integration_id)) == 1
        assert (
            OnlyAgentModelProfileV1.from_dict(json.loads(second.model_profile_path.read_text(encoding="utf-8")))
            == profile
        )
        repeat_summary = json.dumps(second.summary_document(), sort_keys=True)
        assert DEFAULT_TOKEN not in repeat_summary
        assert not any(token in repeat_summary for token in token_values)


def test_bootstrap_fails_closed_when_the_published_revision_probe_is_not_ready(
    postgres_dsn: str, tmp_path: Path
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    with _running_fixture() as server:
        base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        with pytest.raises(RuntimeError, match="AGENT_PROVIDER_PROVISION_PROBE_NOT_READY"):
            _provision(postgres_dsn, tmp_path, base_url, credential="wrong-token")
        assert not (tmp_path / "agent" / "model-profile.json").exists()

"""Fresh-process verified history reader for isolated persistence tests only."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    MASTER_KEY_FILE,
    OnlyPostgresResearchDeploymentStore,
    OnlyPostgresSchemaVerifier,
    only_assert_postgres_test_database,
)
from onlyalpha.persistence.postgres.credentials import OnlyPostgresCredentialAuthority, only_load_master_key
from onlyalpha.research.artifact.scientific_v3_store import OnlyParquetResearchScientificArtifactStoreV3
from onlyalpha.research.operations.deployment import (
    OnlyResearchDeploymentCoherenceVerifier,
    OnlyResearchSemanticStoreIdentity,
)


def main() -> int:
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    only_assert_postgres_test_database(dsn)
    expected = json.loads(sys.stdin.read())
    layout = OnlyUserDataLayout(Path(expected["root"]))
    OnlyPostgresSchemaVerifier(dsn).assert_compatible()
    store_id = OnlyResearchDeploymentCoherenceVerifier(
        OnlyResearchSemanticStoreIdentity(layout.research_root), OnlyPostgresResearchDeploymentStore(dsn)
    ).verify()
    assert str(store_id) == expected["store_id"]
    credentials = OnlyPostgresCredentialAuthority(dsn, only_load_master_key(layout.root / MASTER_KEY_FILE))
    assert (
        credentials.read_secret(expected["credential_id"], expected["credential_generation"])
        == "controlled-history-value"
    )
    artifact = OnlyParquetResearchScientificArtifactStoreV3(layout.research_artifact_root).load_verified(
        expected["result_fingerprint"]
    )
    assert artifact.manifest.artifact_content_fingerprint == expected["artifact_fingerprint"]
    assert [section.to_dict() for section in artifact.manifest.sections] == expected["sections"]
    print("VERIFIED_HISTORY_LOADED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

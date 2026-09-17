from __future__ import annotations

from datetime import UTC, datetime

import psycopg
import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.persistence.postgres import OnlyPostgresPrivateAssetStore, OnlyPostgresResearchRunStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.quant_assets import (
    OnlyPrivateAssetCorruptError,
    OnlyPrivateAssetNotFoundError,
    OnlyPrivateAssetParentMismatchError,
    OnlyPrivateAssetPutDisposition,
    OnlyPrivateAssetStaleBaseError,
    OnlyPrivateL3Asset,
    OnlyPrivateL3Draft,
    OnlyPrivateL4Asset,
    OnlyPrivateL4Draft,
)
from onlyalpha.research.provenance import (
    OnlyResearchAuthoringProvenance,
    OnlyResearchPrivateAssetKind,
    only_research_execution_generation_fingerprint,
)
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunId,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from tests.research.specification.support import registry, specification
from tests.support.research_run_seeder import OnlyPostgresResearchRunSeeder

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


def _l3(factor_id: str = "private.factor.momentum", **changes: object) -> OnlyPrivateL3Draft:
    values: dict[str, object] = {
        "factor_id": factor_id,
        "semantic_version": "1",
        "source_text": "def calculate(api, inputs, parameters):\n    return inputs\n",
        "l3_api_version": 1,
        "l3_api_contract_fingerprint": "a" * 64,
        "input_contract": {"close": {"type": "DECIMAL"}},
        "parameter_contract": {"window": {"type": "INTEGER"}},
        "output_contract": {"value": {"type": "DECIMAL"}},
        "description": "Momentum",
        "economic_rationale": "Trend persistence",
        "category": "momentum",
        "tags": ("trend",),
    }
    values.update(changes)
    return OnlyPrivateL3Draft(**values)  # type: ignore[arg-type]


def _l4(**changes: object) -> OnlyPrivateL4Draft:
    values: dict[str, object] = {
        "strategy_id": "private.strategy.momentum",
        "semantic_version": "1",
        "definition": {"schema_version": 1, "entry": {"factor": "private.factor.momentum@1"}},
        "description": "Momentum strategy",
        "tags": ("long_only",),
    }
    values.update(changes)
    return OnlyPrivateL4Draft(**values)  # type: ignore[arg-type]


def _provenance() -> OnlyResearchAuthoringProvenance:
    values = {
        "experiment_id": "exp-" + "b" * 32,
        "private_asset_kind": OnlyResearchPrivateAssetKind.L3_FACTOR,
        "private_asset_id": "private.factor.momentum",
        "private_asset_revision_fingerprint": "5" * 64,
        "private_asset_content_fingerprint": "6" * 64,
        "candidate_provider_id": "candidate.private.alpha",
        "candidate_provider_version": "7",
        "candidate_provider_content_fingerprint": "8" * 64,
        "catalog_generation_fingerprint": "9" * 64,
    }
    return OnlyResearchAuthoringProvenance(
        schema_version=1,
        **values,
        execution_generation_fingerprint=only_research_execution_generation_fingerprint(**values),
    )


def test_private_l3_l4_authoring_round_trip_publish_and_history(postgres_dsn: str) -> None:
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate()[-1] == "0027_private_asset_authoring_authority"
    store = OnlyPostgresPrivateAssetStore(postgres_dsn)

    l3_asset = OnlyPrivateL3Asset("private.factor.momentum")
    assert store.put_l3_asset(l3_asset) is OnlyPrivateAssetPutDisposition.CREATED
    assert store.put_l3_asset(l3_asset) is OnlyPrivateAssetPutDisposition.REUSED
    assert store.load_l3_asset(l3_asset.factor_id) == l3_asset
    store.save_l3_draft(_l3())
    assert store.load_l3_draft(l3_asset.factor_id) == _l3()
    updated_l3 = _l3(description="Edited")
    store.save_l3_draft(updated_l3)
    assert store.load_l3_draft(l3_asset.factor_id) == updated_l3
    store.save_l3_draft(_l3())
    disposition, l3_r1 = store.publish_l3_revision(l3_asset.factor_id)
    assert disposition is OnlyPrivateAssetPutDisposition.CREATED
    assert store.publish_l3_revision(l3_asset.factor_id) == (OnlyPrivateAssetPutDisposition.REUSED, l3_r1)
    assert store.load_l3_revision(l3_asset.factor_id, l3_r1.revision_fingerprint) == l3_r1

    l3_r2_draft = _l3(
        base_revision_fingerprint=l3_r1.revision_fingerprint,
        source_text=_l3().source_text + "# revision 2\n",
    )
    store.save_l3_draft(l3_r2_draft)
    _, l3_r2 = store.publish_l3_revision(l3_asset.factor_id)
    assert store.list_l3_revision_history(l3_asset.factor_id) == (l3_r1, l3_r2)

    l4_asset = OnlyPrivateL4Asset("private.strategy.momentum")
    store.put_l4_asset(l4_asset)
    store.save_l4_draft(_l4())
    assert store.clear_l4_draft(l4_asset.strategy_id)
    assert not store.clear_l4_draft(l4_asset.strategy_id)
    assert store.load_l4_draft(l4_asset.strategy_id) is None
    store.save_l4_draft(_l4())
    _, l4_r1 = store.publish_l4_revision(l4_asset.strategy_id)
    assert store.load_l4_draft(l4_asset.strategy_id) == _l4()
    assert store.load_l4_revision(l4_asset.strategy_id, l4_r1.revision_fingerprint) == l4_r1
    assert store.list_l4_revision_history(l4_asset.strategy_id) == (l4_r1,)


def test_publication_fails_closed_on_stale_parent_and_asset_mismatch(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresPrivateAssetStore(postgres_dsn)
    for factor_id in ("private.factor.one", "private.factor.two"):
        store.put_l3_asset(OnlyPrivateL3Asset(factor_id))
        store.save_l3_draft(_l3(factor_id))
    _, one_r1 = store.publish_l3_revision("private.factor.one")
    _, two_r1 = store.publish_l3_revision("private.factor.two")

    with pytest.raises(OnlyPrivateAssetNotFoundError):
        store.load_l3_revision("private.factor.two", one_r1.revision_fingerprint)
    with pytest.raises(OnlyPrivateAssetParentMismatchError):
        store.save_l3_draft(_l3("private.factor.one", base_revision_fingerprint=two_r1.revision_fingerprint))
    with pytest.raises(OnlyPrivateAssetParentMismatchError):
        store.save_l3_draft(_l3("private.factor.one", base_revision_fingerprint="f" * 64))

    stale = _l3(
        "private.factor.one",
        base_revision_fingerprint=one_r1.revision_fingerprint,
        source_text=_l3().source_text + "# stale\n",
    )
    current = _l3(
        "private.factor.one",
        base_revision_fingerprint=one_r1.revision_fingerprint,
        source_text=_l3().source_text + "# current\n",
    )
    store.save_l3_draft(current)
    store.publish_l3_revision("private.factor.one")
    store.save_l3_draft(stale)
    with pytest.raises(OnlyPrivateAssetStaleBaseError):
        store.publish_l3_revision("private.factor.one")


def test_exact_load_detects_column_and_payload_corruption(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresPrivateAssetStore(postgres_dsn)
    store.put_l3_asset(OnlyPrivateL3Asset("private.factor.momentum"))
    store.save_l3_draft(_l3())
    _, revision = store.publish_l3_revision("private.factor.momentum")

    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.RaiseException):
        connection.execute(
            "UPDATE private_l3_revision SET source_sha256 = %s WHERE revision_fingerprint = %s",
            ("f" * 64, revision.revision_fingerprint),
        )
    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.RaiseException):
        connection.execute("TRUNCATE private_l3_revision CASCADE")

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("ALTER TABLE private_l3_revision DISABLE TRIGGER private_l3_revision_immutable_trigger")
        connection.execute(
            "UPDATE private_l3_revision SET source_sha256 = %s WHERE revision_fingerprint = %s",
            ("f" * 64, revision.revision_fingerprint),
        )
        connection.execute("ALTER TABLE private_l3_revision ENABLE TRIGGER private_l3_revision_immutable_trigger")
    with pytest.raises(OnlyPrivateAssetCorruptError):
        store.load_l3_revision("private.factor.momentum", revision.revision_fingerprint)

    store.put_l4_asset(OnlyPrivateL4Asset("private.strategy.momentum"))
    store.save_l4_draft(_l4())
    _, l4_revision = store.publish_l4_revision("private.strategy.momentum")
    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.RaiseException):
        connection.execute(
            "UPDATE private_l4_revision SET definition_fingerprint = %s WHERE revision_fingerprint = %s",
            ("d" * 64, l4_revision.revision_fingerprint),
        )

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("ALTER TABLE private_l4_revision DISABLE TRIGGER private_l4_revision_immutable_trigger")
        connection.execute(
            "UPDATE private_l4_revision SET definition_fingerprint = %s WHERE revision_fingerprint = %s",
            ("d" * 64, l4_revision.revision_fingerprint),
        )
        connection.execute("ALTER TABLE private_l4_revision ENABLE TRIGGER private_l4_revision_immutable_trigger")
    with pytest.raises(OnlyPrivateAssetCorruptError):
        store.load_l4_revision("private.strategy.momentum", l4_revision.revision_fingerprint)

    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.RaiseException):
        connection.execute(
            "DELETE FROM private_l4_revision WHERE revision_fingerprint = %s",
            (l4_revision.revision_fingerprint,),
        )


def test_research_run_db_native_provenance_survives_postgres_round_trip(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    spec = specification()
    run = OnlyResearchRun.queued(
        run_id=OnlyResearchRunId("00000000-0000-4000-8000-000000000427"),
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(
            OnlyResearchSpecificationResolver(registry()).resolve(spec)
        ),
        queued_at=datetime(2026, 9, 17, tzinfo=UTC),
        authoring_provenance=_provenance(),
    )
    OnlyPostgresResearchRunSeeder(postgres_dsn).seed_queued(run)

    assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run

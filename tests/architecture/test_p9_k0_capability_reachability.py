"""Prove actor capability minimality and reverse privileged ownership."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.architecture._p9_k0_authority_contract import load_authority_contract
from tests.architecture._p9_k0_capability_reachability import ModuleIndex, actual_capabilities_by_actor

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
CONTRACT = load_authority_contract(ROOT / "docs/architecture/p9_k0_authority_contract.toml")
INDEX = ModuleIndex(ROOT)
ACTUAL = actual_capabilities_by_actor(ROOT, CONTRACT, INDEX)


@pytest.mark.parametrize(
    "source",
    (
        "from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority\n",
        "from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority as Migrator\n",
        "import onlyalpha.persistence.postgres.migration\n",
        "import onlyalpha.persistence.postgres.migration as migration\n",
        "from .persistence.postgres.migration import OnlyPostgresMigrationAuthority\n",
        "from onlyalpha.persistence.postgres.migration import *\n",
    ),
)
def test_ordinary_import_forms_resolve_to_same_migration_capability(source: str) -> None:
    capabilities = INDEX.capabilities_for_source(source, "onlyalpha.synthetic_actor", CONTRACT)
    assert "C11" in capabilities


def test_package_reexport_and_broad_aggregator_exposure_are_resolved() -> None:
    direct = INDEX.capabilities_for_source(
        "from onlyalpha.persistence.postgres import OnlyPostgresSchemaVerifier\n",
        "onlyalpha.synthetic_actor",
        CONTRACT,
    )
    broad_postgres = INDEX.capabilities_for_source(
        "import onlyalpha.persistence.postgres as postgres\n",
        "onlyalpha.synthetic_actor",
        CONTRACT,
    )
    broad_strategy = INDEX.capabilities_for_source(
        "import onlyalpha.strategy as strategy\n",
        "onlyalpha.synthetic_actor",
        CONTRACT,
    )
    assert direct == {"C10"}
    assert "C10" in broad_postgres
    assert "C11" not in broad_postgres
    assert "C05" in broad_strategy
    assert "C07" not in broad_strategy


def test_synthetic_privileged_reexport_expands_aggregator_capability(tmp_path: Path) -> None:
    source_root = tmp_path / "src/onlyalpha"
    migration = source_root / "persistence/postgres/migration.py"
    aggregator = source_root / "persistence/postgres/__init__.py"
    for parent in (source_root, migration.parent):
        parent.mkdir(parents=True, exist_ok=True)
        (parent / "__init__.py").touch()
    migration.write_text("class OnlyPostgresMigrationAuthority: pass\n", encoding="utf-8")
    aggregator.write_text(
        "from .migration import OnlyPostgresMigrationAuthority as OnlyPostgresMigrationAuthority\n"
        "__all__ = ['OnlyPostgresMigrationAuthority']\n",
        encoding="utf-8",
    )
    index = ModuleIndex(tmp_path)
    capabilities = index.capabilities_for_source(
        "import onlyalpha.persistence.postgres as postgres\n",
        "onlyalpha.worker",
        CONTRACT,
    )
    assert capabilities == {"C11"}


def test_forward_actor_capability_proof_has_no_unauthorized_holdings() -> None:
    violations = {
        actor: capabilities - CONTRACT.actors[actor].allowed_capabilities
        for actor, capabilities in ACTUAL.items()
        if capabilities - CONTRACT.actors[actor].allowed_capabilities
    }
    assert violations == {}


def test_reverse_privileged_authority_proof_matches_exact_approved_holders() -> None:
    holders = {
        capability: frozenset(
            actor
            for actor, capabilities in ACTUAL.items()
            if CONTRACT.actors[actor].production and capability in capabilities
        )
        for capability in CONTRACT.capabilities
    }
    expected = {capability: rule.approved_production_holders for capability, rule in CONTRACT.ownership.items()}
    assert holders == expected


def test_real_worker_api_runtime_and_database_policy() -> None:
    assert {"C03", "C10"} <= ACTUAL["A05"]
    assert {"C06", "C07", "C11"}.isdisjoint(ACTUAL["A05"])
    assert "C10" in ACTUAL["A03"]
    assert "C11" not in ACTUAL["A03"]
    assert "C05" in ACTUAL["A07"]
    assert {"C06", "C07", "C11"}.isdisjoint(ACTUAL["A07"])
    assert "C11" in ACTUAL["A10"]
    assert ACTUAL["A12"].isdisjoint({"C17", "C18"})
    assert ACTUAL["A13"].isdisjoint({"C17", "C18"})

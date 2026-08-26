"""Freeze exact privileged concrete composition ownership."""

from __future__ import annotations

from pathlib import Path

import pytest

from onlyalpha.persistence.postgres.migration import (
    OnlyPostgresMigrationAuthority,
    OnlyPostgresSchemaVerifier,
)
from tests.architecture._p9_k0_authority_contract import load_authority_contract
from tests.architecture._p9_k0_capability_reachability import ModuleIndex, actual_constructor_sites

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
CONTRACT = load_authority_contract(ROOT / "docs/architecture/p9_k0_authority_contract.toml")
CONSTRUCTOR_SITES = actual_constructor_sites(ROOT, CONTRACT, ModuleIndex(ROOT))


def test_privileged_concrete_constructor_sites_match_contract_exactly() -> None:
    expected = {identifier: item.approved_paths for identifier, item in CONTRACT.constructors.items()}
    assert CONSTRUCTOR_SITES == expected


def test_schema_verifier_surface_is_read_only() -> None:
    assert {name for name in vars(OnlyPostgresSchemaVerifier) if not name.startswith("_")} == {
        "assert_compatible",
        "status",
    }
    assert "plan" not in vars(OnlyPostgresSchemaVerifier)
    assert "migrate" not in vars(OnlyPostgresSchemaVerifier)


def test_migration_authority_surface_does_not_masquerade_as_verifier() -> None:
    assert {name for name in vars(OnlyPostgresMigrationAuthority) if not name.startswith("_")} == {
        "migrate",
        "plan",
    }
    assert "status" not in vars(OnlyPostgresMigrationAuthority)
    assert "assert_compatible" not in vars(OnlyPostgresMigrationAuthority)


def test_worker_and_api_construct_only_schema_verifier() -> None:
    worker = (ROOT / "src/onlyalpha/research/worker_main.py").read_text(encoding="utf-8")
    api = (ROOT / "packages/api/onlyalpha-api/src/onlyalpha_api/main.py").read_text(encoding="utf-8")
    for source in (worker, api):
        assert "OnlyPostgresSchemaVerifier(" in source
        assert "OnlyPostgresMigrationAuthority" not in source


def test_database_operator_is_only_production_migration_composer() -> None:
    constructor = next(item for item in CONTRACT.constructors.values() if item.capability == "C11")
    assert constructor.approved_paths == {"scripts/database.py"}


def test_kernel_host_has_one_production_composition_and_one_contract_tooling_site() -> None:
    lifecycle = next(item for item in CONTRACT.constructors.values() if item.capability == "C17")
    command = next(item for item in CONTRACT.constructors.values() if item.capability == "C18")
    production_path = "packages/api/onlyalpha-api/src/onlyalpha_api/main.py"
    tooling_path = "scripts/export_research_openapi.py"
    assert CONSTRUCTOR_SITES[lifecycle.id] == {production_path, tooling_path}
    assert CONTRACT.classify_path(production_path).production
    assert not CONTRACT.classify_path(tooling_path).production
    assert CONSTRUCTOR_SITES[command.id] == frozenset()

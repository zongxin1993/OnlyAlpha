"""Validate the single machine-readable P9.K.0 authority policy."""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path

import pytest

from tests.architecture._p9_k0_authority_contract import (
    AuthorityContractError,
    authority_contract_from_document,
    load_authority_contract,
)

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
CONTRACT_PATH = ROOT / "docs/architecture/p9_k0_authority_contract.toml"


def _document() -> dict[str, object]:
    return tomllib.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_repository_authority_contract_is_valid_and_finite() -> None:
    contract = load_authority_contract(CONTRACT_PATH)
    assert contract.version == 1
    assert tuple(contract.facts) == tuple(f"F{number:02d}" for number in range(1, 14))
    assert tuple(contract.capabilities) == tuple(f"C{number:02d}" for number in range(1, 19))
    assert len(contract.actors) == 18
    assert contract.reserved_future_capabilities == {"C18"}


@pytest.mark.parametrize("section", ("facts", "capabilities", "actors"))
def test_duplicate_primary_id_fails_closed(section: str) -> None:
    document = _document()
    values = document[section]
    assert isinstance(values, list)
    values.append(copy.deepcopy(values[0]))
    with pytest.raises(AuthorityContractError, match=f"duplicate {section} ID"):
        authority_contract_from_document(document)


def test_unknown_capability_reference_fails_closed() -> None:
    document = _document()
    facts = document["facts"]
    assert isinstance(facts, list) and isinstance(facts[0], dict)
    facts[0]["mutation_capability"] = "C99"
    with pytest.raises(AuthorityContractError, match="unknown IDs"):
        authority_contract_from_document(document)


def test_unknown_actor_reference_fails_closed() -> None:
    document = _document()
    paths = document["actor_paths"]
    assert isinstance(paths, list) and isinstance(paths[0], dict)
    paths[0]["actor"] = "A99"
    with pytest.raises(AuthorityContractError, match="unknown actor"):
        authority_contract_from_document(document)


def test_mutable_fact_without_exactly_one_mutation_capability_fails_closed() -> None:
    document = _document()
    facts = document["facts"]
    assert isinstance(facts, list) and isinstance(facts[0], dict)
    del facts[0]["mutation_capability"]
    with pytest.raises(AuthorityContractError, match="mutation_capability"):
        authority_contract_from_document(document)
    facts[0]["mutation_capability"] = ["C01", "C02"]
    with pytest.raises(AuthorityContractError, match="mutation_capability"):
        authority_contract_from_document(document)


def test_privileged_capability_without_ownership_rule_fails_closed() -> None:
    document = _document()
    ownership = document["ownership"]
    assert isinstance(ownership, list)
    ownership.pop()
    with pytest.raises(AuthorityContractError, match="ownership rule"):
        authority_contract_from_document(document)


def test_reserved_product_command_capability_cannot_gain_pre_k2_holder() -> None:
    document = _document()
    ownership = document["ownership"]
    assert isinstance(ownership, list)
    reserved = next(item for item in ownership if item["capability"] == "C18")
    reserved["approved_production_holders"] = ["A12"]
    with pytest.raises(AuthorityContractError, match="reserved capability has production holders"):
        authority_contract_from_document(document)


def test_every_sensitive_repository_module_has_exactly_one_actor() -> None:
    contract = load_authority_contract(CONTRACT_PATH)
    sensitive = []
    for source_root in (ROOT / "src", ROOT / "packages", ROOT / "scripts", ROOT / "examples"):
        for path in sorted(source_root.rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            if contract.is_sensitive_path(relative):
                sensitive.append(relative)
                contract.classify_path(relative)
    assert sensitive


def test_unknown_and_ambiguous_actor_classification_fail_closed() -> None:
    contract = load_authority_contract(CONTRACT_PATH)
    with pytest.raises(AuthorityContractError, match="matches 0"):
        contract.classify_path("src/onlyalpha/unknown_authority.py")
    document = _document()
    paths = document["actor_paths"]
    assert isinstance(paths, list)
    paths.append({"pattern": "src/onlyalpha/cli.py", "actor": "A01"})
    ambiguous = authority_contract_from_document(document)
    with pytest.raises(AuthorityContractError, match="matches 2"):
        ambiguous.classify_path("src/onlyalpha/cli.py")


def test_fact_authority_mutation_capability_is_unique() -> None:
    contract = load_authority_contract(CONTRACT_PATH)
    assert all(fact.mutation_capability in contract.capabilities for fact in contract.facts.values())
    assert len(contract.facts) == 13

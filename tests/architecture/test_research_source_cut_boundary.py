"""Bounded guard over the currently admitted source-owned publication paths."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("path", "owner", "methods"),
    (
        (
            "src/onlyalpha/research/experiment/store.py",
            "OnlyJsonSearchProvenanceStore",
            ("commit_experiment", "commit_iteration_plan", "commit_iteration_result"),
        ),
        ("src/onlyalpha/research/agent/store.py", "_OnlyJsonPutOnceStore", ("commit",)),
        ("src/onlyalpha/research/result/result_store.py", "OnlyJsonResearchResultStore", ("commit",)),
        ("src/onlyalpha/research/evaluation/result_store.py", "OnlyParquetResearchStatisticsResultStore", ("commit",)),
        (
            "src/onlyalpha/research/evaluation/factor_pair/result_store.py",
            "OnlyParquetResearchFactorPairStatisticsResultStore",
            ("commit",),
        ),
        (
            "src/onlyalpha/research/evaluation/summary/result_store.py",
            "OnlyJsonResearchSummaryStatisticsResultStore",
            ("commit",),
        ),
        ("src/onlyalpha/strategy/qualification_store.py", "_OnlyQualificationDecisionPublisher", ("_publish",)),
    ),
)
def test_file_source_writer_paths_hold_publication_barrier(path: str, owner: str, methods: tuple[str, ...]) -> None:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    klass = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
    for name in methods:
        method = next(node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name == name)
        assert any(
            isinstance(decorator, ast.Name) and decorator.id in {"only_source_publication", "_source_publication"}
            for decorator in method.decorator_list
        ), (path, owner, name)


def test_postgres_operational_source_tables_have_transactional_capture_triggers() -> None:
    sql = (ROOT / "database/postgres/migrations/0023_research_source_closed_cut.sql").read_text(encoding="utf-8")
    for table in ("research_run", "research_run_attempt", "product_command_admission", "product_command_receipt"):
        assert (
            f"AFTER INSERT OR UPDATE ON {table}\n    FOR EACH ROW EXECUTE FUNCTION research_source_capture_change"
            in sql
        )
        assert f"BEFORE DELETE OR TRUNCATE ON {table}\n    FOR EACH STATEMENT" in sql


def test_generic_file_publisher_is_internal_to_owning_source_stores() -> None:
    from onlyalpha.research import source_cut

    assert not hasattr(source_cut, "OnlyFileSourceCutAuthority")
    assert hasattr(source_cut, "_OnlyFileSourceCutAuthority")


def test_postgres_research_source_cut_store_has_one_research_application_actor() -> None:
    from tests.architecture._product_authority_contract import load_authority_contract

    contract = load_authority_contract(ROOT / "docs/architecture/product_authority_contract.toml")
    path = "src/onlyalpha/persistence/postgres/research_source_cut_store.py"
    assert (ROOT / path).is_file()
    assert contract.is_sensitive_path(path)
    assert contract.classify_path(path).id == "A16"

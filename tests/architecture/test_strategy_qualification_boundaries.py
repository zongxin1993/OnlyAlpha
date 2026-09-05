from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]
QUALIFICATION = ROOT / "src/onlyalpha/strategy/qualification.py"
DECISION_STORE = ROOT / "src/onlyalpha/strategy/qualification_store.py"
PRODUCT = ROOT / "src/onlyalpha/application/strategy_product.py"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.add(node.module)
    return result


def test_qualification_reads_authoritative_manifests_without_runtime_or_raw_data_authority() -> None:
    imports = _imports(QUALIFICATION)
    forbidden = (
        "onlyalpha.domain.market",
        "onlyalpha.research.dataset",
        "onlyalpha.research.evaluation.execution",
        "onlyalpha.backtest.execution",
        "onlyalpha.runtime",
        "onlyalpha.data",
    )
    assert not {name for name in imports if name.startswith(forbidden)}
    source = QUALIFICATION.read_text(encoding="utf-8").lower()
    for forbidden_token in ("openai", "deepseek", "random", "latest", "newest", "sleep("):
        assert forbidden_token not in source


def test_decision_publication_is_evaluator_sealed_and_public_store_is_read_only() -> None:
    tree = ast.parse(QUALIFICATION.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_only_authorize_qualification_decision_publication"
    ]
    assert len(calls) == 1
    store_tree = ast.parse(DECISION_STORE.read_text(encoding="utf-8"))
    public_store = next(
        node
        for node in store_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "OnlyQualificationDecisionStore"
    )
    methods = {node.name for node in public_store.body if isinstance(node, ast.FunctionDef)}
    assert "publish" not in methods and "publish_verified" not in methods


def test_promotion_is_eligibility_only_and_exposes_no_live_qualification_path() -> None:
    qualification_source = QUALIFICATION.read_text(encoding="utf-8")
    product_source = PRODUCT.read_text(encoding="utf-8")
    assert "SIM_TO_LIVE" not in qualification_source
    assert "promote_to_live" not in product_source
    for runtime_state in ("RUNNING", "STARTING", "STOPPING", "FAILED"):
        assert runtime_state not in product_source


def test_qualified_promotion_authorization_has_one_production_call_site() -> None:
    production_roots = (ROOT / "src", ROOT / "packages")
    call_sites: list[Path] = []
    for production_root in production_roots:
        for path in production_root.rglob("*.py"):
            if path == ROOT / "src/onlyalpha/strategy/promotion.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if any(
                isinstance(node, ast.Call)
                and (
                    (isinstance(node.func, ast.Name) and node.func.id == "_only_authorize_qualified_promotion")
                    or (
                        isinstance(node.func, ast.Attribute) and node.func.attr == "_only_authorize_qualified_promotion"
                    )
                )
                for node in ast.walk(tree)
            ):
                call_sites.append(path.relative_to(ROOT))
    assert call_sites == [Path("src/onlyalpha/application/strategy_product.py")]

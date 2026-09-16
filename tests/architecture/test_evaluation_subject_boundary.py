import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

_SUBJECT = "OnlyExactEvaluationIntentSubjectV1"


def test_one_production_subject_definition_and_no_producer_authored_equality() -> None:
    constructors: list[Path] = []
    for path in Path("src/onlyalpha").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == _SUBJECT
            for node in ast.walk(tree)
        ):
            constructors.append(path)

    assert set(constructors) == {
        Path("src/onlyalpha/research/evaluation/subject.py"),
        Path("src/onlyalpha/research/memory/query.py"),
    }
    command = Path("src/onlyalpha/research/command/service.py").read_text(encoding="utf-8")
    assert "OnlyExactEvaluationIntentResolverV1" in command
    for producer in (
        Path("src/onlyalpha/application/product_boundary.py"),
        Path("src/onlyalpha/research/search/symbolic/product.py"),
        Path("src/onlyalpha/research/search/parameter/integration.py"),
    ):
        source = producer.read_text(encoding="utf-8")
        assert _SUBJECT not in source
        assert "evaluation_fingerprint" not in source


def test_subject_resolver_has_no_latest_current_or_state_writes() -> None:
    source = Path("src/onlyalpha/research/evaluation/subject.py").read_text(encoding="utf-8")
    for forbidden in ("latest", "current", "commit(", "save(", "create_queued", "subject_fingerprint="):
        assert forbidden not in source.lower()

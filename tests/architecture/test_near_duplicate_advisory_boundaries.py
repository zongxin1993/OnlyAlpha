from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from onlyalpha.research.evaluation.subject import OnlyExactEvaluationIntentSubjectV1
from onlyalpha.research.memory.advisory import OnlyResearchAdvisoryRepresentationV1
from tests.architecture._architecture_imports import imported_modules_for_path

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]
ADVISORY = ROOT / "src/onlyalpha/research/memory/advisory.py"


def test_near_duplicate_is_read_only_and_has_no_authority_imports() -> None:
    imports = imported_modules_for_path(ADVISORY, ROOT)
    forbidden = (
        "onlyalpha.research.novelty",
        "onlyalpha.research.command",
        "onlyalpha.research.run",
        "onlyalpha.strategy.qualification",
        "onlyalpha.persistence",
    )
    assert not any(name.startswith(forbidden) for name in imports)
    source = ADVISORY.read_text(encoding="utf-8")
    for forbidden_call in ("seal_from_request(", "submit_research_run(", "create_queued", "Qualification"):
        assert forbidden_call not in source


def test_advisory_representation_cannot_replace_scientific_identity() -> None:
    assert OnlyResearchAdvisoryRepresentationV1 is not OnlyExactEvaluationIntentSubjectV1
    parameters = inspect.signature(OnlyExactEvaluationIntentSubjectV1).parameters
    assert "representation_fingerprint" not in parameters
    assert "index_build_revision" not in parameters
    assert "model_content_fingerprint" not in parameters


def test_exact_read_to_act_and_research_command_do_not_import_advisory() -> None:
    assert "from .advisory import" not in (ROOT / "src/onlyalpha/research/memory/__init__.py").read_text(
        encoding="utf-8"
    )
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import onlyalpha.research.memory.query; "
            "assert 'onlyalpha.research.memory.advisory' not in sys.modules",
        ],
        check=True,
        cwd=ROOT,
    )
    for relative in (
        "src/onlyalpha/research/novelty/decision.py",
        "src/onlyalpha/research/novelty/decision_store.py",
        "src/onlyalpha/research/command/service.py",
        "src/onlyalpha/research/command/novelty_admission.py",
    ):
        imports = imported_modules_for_path(ROOT / relative, ROOT)
        assert "onlyalpha.research.memory.advisory" not in imports
        assert "onlyalpha.research.memory" not in imports or "command" in relative

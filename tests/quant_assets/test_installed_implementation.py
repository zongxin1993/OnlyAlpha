"""Hermetic installation/loaded-code verification, not deployment certification."""

from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from onlyalpha.quant_assets import installed_implementation as verifier


def module_fixture(tmp_path, monkeypatch, source):
    path = tmp_path / "fixture.py"
    path.write_text(source)
    module = ModuleType("onlyalpha_fixture.implementation")
    module.__file__ = str(path)
    module.__package__ = "onlyalpha_fixture"
    exec(compile(source, str(path), "exec", dont_inherit=True), vars(module))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return path, module


def test_wheel_record_not_fresh_disk_manifest_is_installed_resource_authority(tmp_path: Path, monkeypatch):
    path, module = module_fixture(tmp_path, monkeypatch, "def evaluate():\n    return 1\n")
    digest = base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).decode().rstrip("=")
    distribution = SimpleNamespace(
        version="1",
        files=(SimpleNamespace(hash=SimpleNamespace(mode="sha256", value=digest)),),
        locate_file=lambda _: path,
    )
    monkeypatch.setattr(verifier.metadata, "distribution", lambda _: distribution)
    verifier.only_require_installed_distribution_module("onlyalpha-fixture", "1", module.__name__)
    path.write_text("def evaluate():\n    return 2\n")
    with pytest.raises(ValueError, match="CHART_STUDY_IMPLEMENTATION_UNAVAILABLE"):
        verifier.only_require_installed_distribution_module("onlyalpha-fixture", "1", module.__name__)


@pytest.mark.parametrize("mutation", ("stale_import", "method", "callable_class", "defaults", "kwdefaults"))
def test_loaded_function_correspondence_includes_code_globals_and_defaults(tmp_path: Path, monkeypatch, mutation):
    source = "def evaluate(value=1, *, quantum=2):\n    return value + quantum\n"
    path, module = module_fixture(tmp_path, monkeypatch, source)
    verifier.only_require_loaded_python_code(module.__name__, path.read_bytes(), path)
    if mutation == "stale_import":
        path.write_text(source.replace("value + quantum", "value - quantum"))
    elif mutation == "method":
        module.evaluate = lambda value=1, quantum=2: 999
    elif mutation == "callable_class":

        class Counterfeit:
            def __new__(cls, *args, **kwargs):
                return 999

        module.evaluate = Counterfeit
    elif mutation == "defaults":
        module.evaluate.__defaults__ = (100,)
    else:
        module.evaluate.__kwdefaults__ = {"quantum": 100}
    with pytest.raises(ValueError, match="CHART_STUDY_IMPLEMENTATION_UNAVAILABLE"):
        verifier.only_require_loaded_python_code(module.__name__, path.read_bytes(), path)


def test_imported_call_alias_cannot_keep_original_manifest_after_replacement(tmp_path: Path, monkeypatch):
    source = "from decimal import Decimal\ndef evaluate(value):\n    return Decimal(value)\n"
    path, module = module_fixture(tmp_path, monkeypatch, source)
    verifier.only_require_loaded_python_code(module.__name__, path.read_bytes(), path)
    module.Decimal = lambda _: 999
    with pytest.raises(ValueError, match="CHART_STUDY_IMPLEMENTATION_UNAVAILABLE"):
        verifier.only_require_loaded_python_code(module.__name__, path.read_bytes(), path)


def test_missing_record_resource_is_not_accepted_as_a_fresh_manifest(tmp_path: Path, monkeypatch):
    path, module = module_fixture(tmp_path, monkeypatch, "def evaluate():\n    return 1\n")
    digest = base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).decode().rstrip("=")
    distribution = SimpleNamespace(
        version="1",
        files=(SimpleNamespace(hash=SimpleNamespace(mode="sha256", value=digest)),),
        locate_file=lambda _: path,
    )
    monkeypatch.setattr(verifier.metadata, "distribution", lambda _: distribution)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        verifier.only_require_installed_distribution_module("onlyalpha-fixture", "1", module.__name__)

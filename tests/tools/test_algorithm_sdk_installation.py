"""Algorithm builds must use their own source closure, never the legacy backend."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts import build_algorithm_sdk


@pytest.fixture
def algorithm_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    original = build_algorithm_sdk.ROOT
    bundle = tmp_path / "source"
    for relative in (
        "packages/backend/python",
        "plugs/onlyalpha-plugin-indicators",
        "plugs/onlyalpha-plugin-operators",
        "plugs/onlyalpha-plugin-targets",
    ):
        shutil.copytree(original / relative, bundle / relative, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    manifest = bundle / "packages/backend/Cargo.toml"
    manifest.write_bytes((original / "packages/backend/Cargo.toml").read_bytes())
    monkeypatch.setattr(build_algorithm_sdk, "ROOT", bundle)
    return bundle


def test_sdk_wheel_build_uses_only_owning_algorithm_sources(algorithm_sources: Path, tmp_path: Path) -> None:
    assert not (algorithm_sources / "src").exists()
    wheels = build_algorithm_sdk.build(tmp_path / "wheels")
    sdk = next(path for path in wheels if path.name.startswith("onlyalpha-"))
    with zipfile.ZipFile(sdk) as archive:
        assert "onlyalpha/algorithm/private_factor.py" in archive.namelist()
        assert "onlyalpha/calculation/definition.py" in archive.namelist()
        assert (
            archive.read("onlyalpha/canonical.py")
            == (algorithm_sources / "packages/backend/python/algorithms/sdk/onlyalpha/canonical.py").read_bytes()
        )
        assert not any(name.startswith(("onlyalpha/application/", "onlyalpha/runtime/")) for name in archive.namelist())


def test_installed_sdk_ignores_ambient_legacy_backend(algorithm_sources: Path, tmp_path: Path) -> None:
    installation = tmp_path / "installed"
    build_algorithm_sdk.install(tmp_path / "wheels", installation)
    poison = tmp_path / "ambient/onlyalpha"
    poison.mkdir(parents=True)
    (poison / "__init__.py").write_text("raise AssertionError('ambient backend was imported')\n")
    code = """
import importlib, sys
from decimal import Decimal
from pathlib import Path
import onlyalpha
from onlyalpha_plugin_indicators.chart_factory import ChartFactory
assert Path(onlyalpha.__file__).is_relative_to(Path(sys.argv[1]))
factory = ChartFactory()
row = next(row for row in factory.catalog() if row['descriptor']['type_id'] == 'onlyalpha.indicator.sma')
result = factory.execute('onlyalpha.indicator.sma', '1', {'period': 2}, {'value': ['2', '4']}, row['implementation_fingerprint'])
assert [Decimal(value) for value in result['outputs']['value']['values']] == [Decimal('2'), Decimal('3')]
for name in ('onlyalpha.application', 'onlyalpha.persistence', 'onlyalpha.runtime', 'onlyalpha.broker'):
    try:
        importlib.import_module(name)
    except ModuleNotFoundError:
        pass
    else:
        raise AssertionError(name)
"""
    completed = subprocess.run(
        [str(installation / "bin/python"), "-B", "-I", "-c", code, str(installation)],
        cwd=poison.parent,
        env={**os.environ, "PYTHONPATH": str(poison.parent)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_legacy_wheel_keeps_importers_on_the_same_extracted_sdk(tmp_path: Path) -> None:
    from scripts.embed_build_provenance import resolve_build_provenance_bytes, write_build_provenance

    root = build_algorithm_sdk.ROOT
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "hatch_build.py", "README.md", "LICENSE", "scripts/embed_build_provenance.py"):
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / name).read_bytes())
    for name in ("src/onlyalpha", "packages/backend/python/algorithms/sdk", "database/postgres/migrations"):
        shutil.copytree(root / name, source / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    write_build_provenance(
        source, source / "src/onlyalpha/_build_provenance.json", resolve_build_provenance_bytes(root)
    )
    completed = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(tmp_path / "wheels")],
        cwd=source,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    wheel = next((tmp_path / "wheels").glob("onlyalpha-*.whl"))
    installed = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        for name in build_algorithm_sdk.SDK:
            # The legacy package retains its own broader public initializers.
            if name in {"__init__.py", "calculation/__init__.py", "quant_assets/__init__.py"}:
                continue
            assert (
                archive.read("onlyalpha/" + name)
                == (root / "packages/backend/python/algorithms/sdk/onlyalpha" / name).read_bytes()
            )
        archive.extractall(installed)
    # Remaining reference consumers use an ordinary wheel, not a source-path shim.
    code = """
from pathlib import Path
import onlyalpha.canonical
from onlyalpha.domain.value import OnlyPrice
from decimal import Decimal
assert Path(onlyalpha.canonical.__file__).is_relative_to(Path(__import__('sys').argv[1]))
assert OnlyPrice(Decimal('1.00'), 2).value == Decimal('1.00')
"""
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code, str(installed)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(installed)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

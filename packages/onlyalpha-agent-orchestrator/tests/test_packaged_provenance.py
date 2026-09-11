from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from runpy import run_path

import onlyalpha_agent_orchestrator.provenance as provenance_module
import pytest
from onlyalpha_agent_orchestrator.provenance import only_agent_orchestrator_packaged_build_provenance


def _canonical(revision: str = "1" * 40, version: str = "0.9.9") -> bytes:
    return (
        json.dumps(
            {
                "distribution_name": "onlyalpha-agent-orchestrator",
                "distribution_version": version,
                "schema_version": 1,
                "source_provenance_authority": "ONLYALPHA_GIT",
                "source_repository": "OnlyAlpha",
                "source_revision": revision,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def test_runtime_exact_loads_canonical_packaged_provenance_without_git(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "installed" / "onlyalpha_agent_orchestrator"
    package.mkdir(parents=True)
    (package / "_build_provenance.json").write_bytes(_canonical())
    monkeypatch.setattr(provenance_module.resources, "files", lambda _package: package)
    monkeypatch.setattr(provenance_module.metadata, "version", lambda _distribution: "0.9.9")

    value = only_agent_orchestrator_packaged_build_provenance()

    assert value.source_revision == "1" * 40
    source = Path(provenance_module.__file__).read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "git rev-parse" not in source


@pytest.mark.parametrize("failure", ("missing", "noncanonical", "wrong_version"))
def test_runtime_packaged_provenance_inconsistency_fails_closed(
    monkeypatch,
    tmp_path: Path,
    failure: str,
) -> None:
    package = tmp_path / "onlyalpha_agent_orchestrator"
    package.mkdir()
    if failure != "missing":
        raw = _canonical()
        if failure == "noncanonical":
            raw = json.dumps(json.loads(raw), indent=2).encode()
        (package / "_build_provenance.json").write_bytes(raw)
    monkeypatch.setattr(provenance_module.resources, "files", lambda _package: package)
    monkeypatch.setattr(
        provenance_module.metadata,
        "version",
        lambda _distribution: "0.9.10" if failure == "wrong_version" else "0.9.9",
    )
    with pytest.raises(ValueError, match="ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_"):
        only_agent_orchestrator_packaged_build_provenance()


def test_carried_sdist_provenance_is_offline_reusable_and_digest_verified(tmp_path: Path) -> None:
    helper_path = Path(__file__).resolve().parents[1] / "provenance_build.py"
    helper = run_path(str(helper_path), run_name="test_orchestrator_provenance_build")
    project = tmp_path / "sdist"
    (project / "src/onlyalpha_agent_orchestrator").mkdir(parents=True)
    (project / "pyproject.toml").write_text('[project]\nversion = "0.9.9"\n', encoding="utf-8")
    raw = helper["build_provenance_bytes"](project, "1" * 40)
    destination = project / "src/onlyalpha_agent_orchestrator/_build_provenance.json"
    helper["write_build_provenance"](destination, raw)

    assert helper["resolve_build_provenance_bytes"](project) == raw
    destination.with_name("_build_provenance.sha256").write_text(hashlib.sha256(b"tampered").hexdigest() + "\n")
    with pytest.raises(ValueError, match="ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_INVALID"):
        helper["resolve_build_provenance_bytes"](project)


def test_provenance_cli_materializes_exact_carrier_for_gitless_build_context(tmp_path: Path) -> None:
    helper_path = Path(__file__).resolve().parents[1] / "provenance_build.py"
    project = tmp_path / "onlyalpha-agent-orchestrator"
    project.mkdir()
    copied_helper = project / "provenance_build.py"
    copied_helper.write_bytes(helper_path.read_bytes())
    (project / "pyproject.toml").write_text('[project]\nversion = "0.9.9"\n', encoding="utf-8")

    subprocess.run(
        [sys.executable, str(copied_helper), "--revision", "1" * 40],
        check=True,
        cwd=tmp_path,
    )

    carrier = project / "src/onlyalpha_agent_orchestrator/_build_provenance.json"
    assert carrier.read_bytes() == _canonical()
    assert carrier.with_name("_build_provenance.sha256").read_text(encoding="ascii") == (
        hashlib.sha256(_canonical()).hexdigest() + "\n"
    )

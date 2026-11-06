from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import dev_verification as verification
from scripts import openapi_contract

pytestmark = pytest.mark.architecture


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.email", "verification@example.invalid")
    git(root, "config", "user.name", "Verification")
    contract = root / "contracts/product-api/v2/openapi.json"
    contract.parent.mkdir(parents=True)
    contract.write_bytes(
        openapi_contract.canonical_bytes(
            {"openapi": "3.1.0", "info": {"title": "Baseline", "version": "2"}, "paths": {}}
        )
    )
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "accepted baseline")
    base = git(root, "rev-parse", "HEAD")
    contract.write_bytes(
        openapi_contract.canonical_bytes(
            {"openapi": "3.1.0", "info": {"title": "Candidate", "version": "2"}, "paths": {}}
        )
    )
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "candidate")
    head = git(root, "rev-parse", "HEAD")
    git(root, "update-ref", "refs/remotes/origin/master", head)
    return root, base, head


def command(base):
    return ["python", "scripts/openapi_contract.py", "verify", "--base", base]


def test_exact_push_baseline_is_frozen_even_when_origin_is_current_head(repository, monkeypatch):
    root, base, head = repository
    verification.freeze_source(root, "without-baseline")
    cut = root / ".test-cache/dev-source-cut"
    absent = subprocess.run(["git", "-C", str(cut), "cat-file", "-e", base], capture_output=True)
    assert absent.returncode != 0  # Reproduces the original no-walk capture omission.
    inputs = verification.freeze_source(
        root, "with-baseline", required_git_revisions=verification.command_git_revisions(command(base))
    )
    marker = json.loads((cut / verification.CUT_METADATA).read_text())
    assert marker["operation_id"] == "with-baseline"
    assert marker["required_git_revisions"] == [base]
    assert marker["inputs"] == inputs == verification.source_inputs(root)
    assert marker["git_inputs"] == verification.git_input_hashes(cut)
    assert git(cut, "rev-parse", "HEAD") == head
    assert git(cut, "rev-parse", "origin/master") == head
    monkeypatch.setattr(openapi_contract, "ROOT", cut)
    exact, document, raw = openapi_contract.load_git_baseline(base)
    assert exact == base
    assert document["info"]["title"] == "Baseline"
    assert raw == openapi_contract.canonical_bytes(document)
    verification.validate_git_revisions(cut, (base,))
    # A later unrelated operation must remove both the declaration and extra objects.
    verification.freeze_source(root, "ordinary")
    assert json.loads((cut / verification.CUT_METADATA).read_text())["required_git_revisions"] == []
    assert subprocess.run(["git", "-C", str(cut), "cat-file", "-e", base], capture_output=True).returncode != 0


@pytest.mark.parametrize("revision", ["HEAD^", "origin/master", "a" * 39, "A" * 40, "0" * 40])
def test_invalid_or_missing_exact_commit_refuses_before_source_cut(repository, revision):
    root, _, _ = repository
    with pytest.raises(ValueError, match="DEV_VERIFICATION_EXACT_GIT_"):
        verification.freeze_source(root, "refused", required_git_revisions=(revision,))
    assert not (root / ".test-cache/dev-source-cut").exists()


def test_tag_and_blob_object_ids_cannot_impersonate_commit(repository):
    root, base, _ = repository
    git(root, "tag", "-a", "accepted", "-m", "tag", base)
    for revision in (
        git(root, "rev-parse", "accepted"),
        git(root, "rev-parse", "HEAD:contracts/product-api/v2/openapi.json"),
    ):
        with pytest.raises(ValueError, match="DEV_VERIFICATION_EXACT_GIT_COMMIT_UNAVAILABLE"):
            verification.validate_git_revisions(root, (revision,))


@pytest.mark.parametrize("arguments", [["--base"], ["--base", "HEAD^"], ["--base", "a" * 40, "--base", "b" * 40]])
def test_ambiguous_or_nonexact_formal_command_refuses(arguments):
    with pytest.raises(ValueError, match="DEV_VERIFICATION_EXACT_GIT_REVISION_REQUIRED"):
        verification.command_git_revisions(["python", "scripts/openapi_contract.py", "verify", *arguments])


def test_script_and_module_use_same_explicit_input_and_ignore_environment(monkeypatch):
    base = "a" * 40
    monkeypatch.setenv("BASE_SHA", "b" * 40)
    monkeypatch.setenv("ONLYALPHA_BASE_SHA", "c" * 40)
    assert verification.command_git_revisions(command(base)) == (base,)
    assert verification.command_git_revisions(command(base)[:-2] + ["--base=" + base]) == (base,)
    assert verification.command_git_revisions(command("a" * 64)) == ("a" * 64,)
    assert verification.command_git_revisions(
        ["python3.12", "-m", "scripts.openapi_contract", "verify", "--base", base]
    ) == (base,)
    assert verification.command_git_revisions(["python", "-V"]) == ()
    assert verification.command_git_revisions(["python", "scripts/openapi_contract.py", "check"]) == ()


@pytest.mark.parametrize("declared", [None, [], ["wrong"], ["HEAD^"], ["BASE", "BASE"], ["HEAD"]])
def test_inside_refuses_missing_or_changed_baseline_metadata_before_launch(repository, tmp_path, monkeypatch, declared):
    root, base, head = repository
    verification.freeze_source(root, "operation", required_git_revisions=(base,))
    cut = root / ".test-cache/dev-source-cut"
    marker_path = cut / verification.CUT_METADATA
    marker = json.loads(marker_path.read_text())
    if declared is None:
        del marker["required_git_revisions"]
    else:
        marker["required_git_revisions"] = [
            base if value == "BASE" else head if value == "HEAD" else value for value in declared
        ]
    marker_path.write_text(json.dumps(marker))
    admitted = tmp_path / "environment.json"
    admitted.write_text("{}")
    monkeypatch.setattr(verification, "ROOT", cut)
    monkeypatch.setattr(verification, "CONTAINER_LOCK", tmp_path / "lock")
    monkeypatch.setattr(verification, "ENVIRONMENT_RECORD", admitted)
    monkeypatch.setattr(verification, "environment_inputs", lambda root: {})
    monkeypatch.setenv("ONLYALPHA_DEV_SOURCE_ROOT", str(root))
    monkeypatch.setattr(verification.subprocess, "Popen", lambda *a, **kw: pytest.fail("unadmitted command started"))
    with pytest.raises(ValueError, match="DEV_VERIFICATION_SOURCE_CUT_NOT_ADMITTED"):
        verification.run_inside(command(base), operation_id="operation")


def test_missing_git_and_product_cut_refuse_explicit_baseline(tmp_path):
    with pytest.raises(ValueError, match="DEV_VERIFICATION_EXACT_GIT_COMMIT_UNAVAILABLE"):
        verification.freeze_source(tmp_path, "missing", required_git_revisions=("a" * 40,))
    with pytest.raises(ValueError, match="DEV_VERIFICATION_PRODUCT_GIT_REFUSED"):
        verification.freeze_source(tmp_path, "product", product=True, required_git_revisions=("a" * 40,))


def test_inside_admits_matching_exact_baseline_to_command_boundary(repository, tmp_path, monkeypatch):
    root, base, _ = repository
    verification.freeze_source(root, "operation", required_git_revisions=(base,))
    cut = root / ".test-cache/dev-source-cut"
    admitted = tmp_path / "environment.json"
    admitted.write_text("{}")
    monkeypatch.setattr(verification, "ROOT", cut)
    monkeypatch.setattr(verification, "CONTAINER_LOCK", tmp_path / "lock")
    monkeypatch.setattr(verification, "ENVIRONMENT_RECORD", admitted)
    monkeypatch.setattr(verification, "environment_inputs", lambda root: {})
    monkeypatch.setenv("ONLYALPHA_DEV_SOURCE_ROOT", str(root))

    class CommandBoundaryReached(Exception):
        pass

    original_popen = verification.subprocess.Popen

    def launch(args, **kwargs):
        if args[0] == "git":
            return original_popen(args, **kwargs)
        assert args[2:] == command(base)
        assert kwargs["cwd"] == cut
        raise CommandBoundaryReached

    monkeypatch.setattr(verification.subprocess, "Popen", launch)
    with pytest.raises(CommandBoundaryReached):
        verification.run_inside(command(base), operation_id="operation")

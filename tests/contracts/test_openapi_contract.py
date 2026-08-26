from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import openapi_contract as governance

pytestmark = pytest.mark.contract

ROOT = Path(__file__).parents[2]
FIXTURES = Path(__file__).parent / "fixtures/openapi"


def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.mark.parametrize(
    ("fixture", "expected"),
    (
        ("base.json", "UNCHANGED"),
        ("compatible_add_path.json", "COMPATIBLE"),
        ("compatible_optional_request_field.json", "COMPATIBLE"),
        ("breaking_remove_path.json", "BREAKING"),
        ("breaking_required_request_field.json", "BREAKING"),
        ("breaking_request_type_change.json", "BREAKING"),
        ("breaking_response_remove_field.json", "BREAKING"),
        ("breaking_response_type_change.json", "BREAKING"),
        ("breaking_operation_id_change.json", "BREAKING"),
        ("breaking_response_enum_expand.json", "BREAKING"),
    ),
)
def test_frozen_compatibility_policy(fixture: str, expected: str) -> None:
    base = _fixture("base.json")
    candidate = _fixture(fixture)
    governance.lint_contract(candidate)
    first = governance.compare_contracts(base, candidate)
    second = governance.compare_contracts(base, candidate)
    assert first.change.value == expected
    assert first == second


def test_canonicalization_and_sha_are_deterministic() -> None:
    first = {"z": [3, 2, 1], "a": {"b": 1, "a": 2}}
    second = {"a": {"a": 2, "b": 1}, "z": [3, 2, 1]}
    first_bytes = governance.canonical_bytes(first)
    assert first_bytes == governance.canonical_bytes(second)
    assert first_bytes.endswith(b"\n")
    assert governance.contract_sha256(first_bytes) == governance.contract_sha256(first_bytes)
    assert governance.contract_sha256(first_bytes) != governance.contract_sha256(first_bytes + b" ")


def test_current_render_is_byte_deterministic_and_has_no_build_metadata() -> None:
    first = governance.rendered_contract()
    second = governance.rendered_contract()
    assert first == second == (ROOT / "contracts/research-api/v2/openapi.json").read_bytes()
    lowered = first.lower()
    for forbidden in (b"generated_at", b"hostname", b"build_number", b"git_sha", str(ROOT).encode()):
        assert forbidden not in lowered


def test_lint_rejects_duplicate_operation_id_and_external_reference() -> None:
    document = _fixture("compatible_add_path.json")
    paths = document["paths"]
    assert isinstance(paths, dict)
    added = paths["/api/v2/items/{item_id}"]
    assert isinstance(added, dict)
    operation = added["get"]
    assert isinstance(operation, dict)
    operation["operationId"] = "create_item"
    operation["responses"] = {
        "200": {"description": "ok", "content": {"application/json": {"schema": {"$ref": "remote.json"}}}}
    }
    with pytest.raises(ValueError, match="duplicate operationId"):
        governance.lint_contract(document)


def test_git_baseline_is_exact_immutable_artifact_and_invalid_sha_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    exact, document, raw = governance.load_git_baseline(base_sha)
    assert exact == base_sha
    assert raw == (ROOT / "contracts/research-api/v2/openapi.json").read_bytes()
    assert governance.contract_sha256(raw) == governance.contract_sha256(governance.canonical_bytes(document))
    assert governance.compare_contracts(document, _fixture("breaking_remove_path.json")).change.value == "BREAKING"
    with pytest.raises(ValueError, match="full lowercase Git object ID"):
        governance.load_git_baseline("HEAD")
    monkeypatch.setattr(governance, "CONTRACT_RELATIVE", Path("contracts/research-api/v2/missing.json"))
    with pytest.raises(ValueError, match="missing from BASE_SHA"):
        governance.load_git_baseline(base_sha)


def test_source_projection_staleness_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    contract = tmp_path / "openapi.json"
    contract.write_bytes(b"{}\n")
    monkeypatch.setattr(governance, "CONTRACT", contract)
    monkeypatch.setattr(governance, "rendered_contract", lambda: b'{"changed":true}\n')
    with pytest.raises(ValueError, match="stale"):
        governance.check_current_contract()


def test_generated_client_staleness_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = tmp_path / "openapi-typescript"
    executable.write_text("pinned", encoding="utf-8")
    committed = tmp_path / "generated.ts"
    committed.write_text("old", encoding="utf-8")

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_text("new", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(governance, "OPENAPI_TYPESCRIPT", executable)
    monkeypatch.setattr(governance, "GENERATED_CLIENT", committed)
    monkeypatch.setattr(governance.subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="stale"):
        governance.check_generated_client()

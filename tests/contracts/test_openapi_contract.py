from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import cast

import pytest

from scripts import openapi_contract as governance

pytestmark = pytest.mark.contract

ROOT = Path(__file__).parents[2]
FIXTURES = Path(__file__).parent / "fixtures/openapi"


def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _request_schema(document: dict[str, object]) -> dict[str, object]:
    return cast(
        dict[str, object],
        document["paths"]["/api/v2/items"]["post"]["requestBody"]["content"]["application/json"]["schema"],  # type: ignore[index]
    )


def _response_schema(document: dict[str, object]) -> dict[str, object]:
    return cast(
        dict[str, object],
        document["paths"]["/api/v2/items"]["post"]["responses"]["200"]["content"]["application/json"][  # type: ignore[index]
            "schema"
        ],
    )


def _comparison_with_schema(
    old_schema: dict[str, object], new_schema: dict[str, object], *, direction: str
) -> governance.CompatibilityResult:
    old = _fixture("base.json")
    new = copy.deepcopy(old)
    if direction == "request":
        _request_schema(old).clear()
        _request_schema(old).update(old_schema)
        _request_schema(new).clear()
        _request_schema(new).update(new_schema)
    else:
        _response_schema(old).clear()
        _response_schema(old).update(old_schema)
        _response_schema(new).clear()
        _response_schema(new).update(new_schema)
    return governance.compare_contracts(old, new)


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
    assert first == second == (ROOT / "contracts/product-api/v2/openapi.json").read_bytes()
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
    committed = subprocess.run(
        ["git", "show", f"{base_sha}:contracts/product-api/v2/openapi.json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    assert raw == committed
    assert governance.contract_sha256(raw) == governance.contract_sha256(governance.canonical_bytes(document))
    assert governance.compare_contracts(document, _fixture("breaking_remove_path.json")).change.value == "BREAKING"
    with pytest.raises(ValueError, match="full lowercase Git object ID"):
        governance.load_git_baseline("HEAD")
    monkeypatch.setattr(governance, "CONTRACT_RELATIVE", Path("contracts/product-api/v2/missing.json"))
    with pytest.raises(ValueError, match="missing from BASE_SHA"):
        governance.load_git_baseline(base_sha)


def test_a0_pre_freeze_authorization_is_exact_and_non_reusable() -> None:
    base_sha = "8901fec27faf8599c965df792d07a84b902583f3"
    exact, baseline_document, baseline = governance.load_git_baseline(base_sha)
    candidate_document, candidate = governance.check_current_contract()
    result = governance.compare_contracts(baseline_document, candidate_document)

    authorization = governance.authorize_a0_pre_freeze_correction(
        base_git_sha=exact,
        baseline=baseline,
        candidate=candidate,
        result=result,
    )

    assert authorization is not None
    assert authorization.adr == "docs/adr/0109-product-api-v2-a0-pre-freeze-contract-correction.md"
    assert len(authorization.breaking_changes) == 48
    assert (
        governance.authorize_a0_pre_freeze_correction(
            base_git_sha=exact,
            baseline=baseline,
            candidate=candidate + b" ",
            result=result,
        )
        is None
    )
    unrelated = governance.CompatibilityResult(
        governance.ContractChange.BREAKING,
        (*result.breaking_changes, "/api/v2/unrelated: path was removed"),
    )
    assert (
        governance.authorize_a0_pre_freeze_correction(
            base_git_sha=exact,
            baseline=baseline,
            candidate=candidate,
            result=unrelated,
        )
        is None
    )


def test_a0_pre_freeze_authorization_manifest_fails_closed_on_extra_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = json.loads(governance.AUTHORIZED_A0_CORRECTIONS.read_text(encoding="utf-8"))
    manifest["reusable_allowlist"] = True
    candidate = tmp_path / "authorized-a0-corrections.json"
    candidate.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(governance, "AUTHORIZED_A0_CORRECTIONS", candidate)

    with pytest.raises(ValueError, match="unexpected fields"):
        governance.load_authorized_a0_correction()


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


@pytest.mark.parametrize(
    ("direction", "old_schema", "new_schema", "expected"),
    (
        ("request", {"const": "A"}, {"const": "A"}, "UNCHANGED"),
        ("request", {"const": "A"}, {}, "COMPATIBLE"),
        ("request", {}, {"const": "A"}, "BREAKING"),
        ("request", {"const": "A"}, {"const": "B"}, "BREAKING"),
        ("response", {"const": "A"}, {"const": "A"}, "UNCHANGED"),
        ("response", {}, {"const": "A"}, "COMPATIBLE"),
        ("response", {"const": "A"}, {}, "BREAKING"),
        ("response", {"const": "A"}, {"const": "B"}, "BREAKING"),
        ("request", {"enum": ["A", "B"]}, {"const": "A"}, "BREAKING"),
        ("response", {"enum": ["A", "B"]}, {"const": "A"}, "COMPATIBLE"),
    ),
)
def test_const_and_enum_compatibility_is_direction_aware(
    direction: str, old_schema: dict[str, object], new_schema: dict[str, object], expected: str
) -> None:
    assert _comparison_with_schema(old_schema, new_schema, direction=direction).change.value == expected


@pytest.mark.parametrize(
    ("direction", "old_value", "new_value", "expected"),
    (
        ("request", {"type": "string", "minLength": 1}, {"type": "string"}, "COMPATIBLE"),
        ("request", {"type": "string"}, {"type": "string", "minLength": 1}, "BREAKING"),
        ("request", False, {"type": "string"}, "COMPATIBLE"),
        ("request", True, False, "BREAKING"),
        ("response", {"type": "string"}, {"type": "string", "minLength": 1}, "COMPATIBLE"),
        ("response", {"type": "string", "minLength": 1}, {"type": "string"}, "BREAKING"),
        ("response", True, False, "COMPATIBLE"),
        ("response", False, {"type": "string"}, "BREAKING"),
    ),
)
def test_additional_properties_compatibility_is_direction_aware(
    direction: str, old_value: object, new_value: object, expected: str
) -> None:
    old_schema = {"type": "object", "additionalProperties": old_value}
    new_schema = {"type": "object", "additionalProperties": new_value}
    assert _comparison_with_schema(old_schema, new_schema, direction=direction).change.value == expected


def test_missing_additional_properties_normalizes_to_allow_any() -> None:
    unconstrained = {"type": "object"}
    explicit_allow = {"type": "object", "additionalProperties": True}
    forbid = {"type": "object", "additionalProperties": False}
    assert _comparison_with_schema(unconstrained, explicit_allow, direction="request").change.value == "COMPATIBLE"
    assert _comparison_with_schema(unconstrained, forbid, direction="request").change.value == "BREAKING"
    assert _comparison_with_schema(unconstrained, forbid, direction="response").change.value == "COMPATIBLE"


@pytest.mark.parametrize("required", (False, True))
def test_closed_response_rejects_new_named_property(required: bool) -> None:
    old_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }
    new_schema = copy.deepcopy(old_schema)
    properties = cast(dict[str, object], new_schema["properties"])
    properties["detail"] = {"type": "string"}
    if required:
        cast(list[str], new_schema["required"]).append("detail")

    result = _comparison_with_schema(old_schema, new_schema, direction="response")

    assert result.change.value == "BREAKING"
    assert any(
        "response property was added but old schema forbids additional properties" in issue
        for issue in result.breaking_changes
    )


@pytest.mark.parametrize("old_additional", (True, None))
def test_open_response_accepts_new_named_property(old_additional: object) -> None:
    old_schema: dict[str, object] = {"type": "object"}
    new_schema: dict[str, object] = {
        "type": "object",
        "properties": {"detail": {"type": "string"}},
    }
    if old_additional is not None:
        old_schema["additionalProperties"] = old_additional
        new_schema["additionalProperties"] = old_additional

    assert _comparison_with_schema(old_schema, new_schema, direction="response").change.value == "COMPATIBLE"


@pytest.mark.parametrize(
    ("old_min_length", "new_min_length", "expected"),
    ((1, 5, "COMPATIBLE"), (5, 1, "BREAKING")),
)
def test_response_named_property_is_checked_against_old_additional_properties_schema(
    old_min_length: int, new_min_length: int, expected: str
) -> None:
    additional_schema = {"type": "string", "minLength": old_min_length}
    old_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": additional_schema,
    }
    new_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": copy.deepcopy(additional_schema),
        "properties": {"detail": {"type": "string", "minLength": new_min_length}},
    }

    assert _comparison_with_schema(old_schema, new_schema, direction="response").change.value == expected


def test_existing_response_property_value_set_remains_directional() -> None:
    old_schema = {"type": "object", "properties": {"status": {"enum": ["A", "B"]}}}
    narrowed_schema = {"type": "object", "properties": {"status": {"enum": ["A"]}}}
    broadened_schema = {"type": "object", "properties": {"status": {"enum": ["A", "B", "C"]}}}

    assert _comparison_with_schema(old_schema, narrowed_schema, direction="response").change.value == "COMPATIBLE"
    assert _comparison_with_schema(old_schema, broadened_schema, direction="response").change.value == "BREAKING"


def test_response_status_addition_and_removal_are_breaking() -> None:
    old = _fixture("base.json")
    added = copy.deepcopy(old)
    added_responses = cast(dict[str, object], added["paths"]["/api/v2/items"]["post"]["responses"])  # type: ignore[index]
    added_responses["202"] = {"description": "accepted"}
    removed = copy.deepcopy(old)
    removed_responses = cast(dict[str, object], removed["paths"]["/api/v2/items"]["post"]["responses"])  # type: ignore[index]
    del removed_responses["200"]

    assert governance.compare_contracts(old, added).breaking_changes == (
        "POST /api/v2/items: response status 202 was added",
    )
    assert governance.compare_contracts(old, removed).breaking_changes == (
        "POST /api/v2/items: response status 200 was removed",
    )


def test_response_media_type_addition_and_removal_are_breaking() -> None:
    old = _fixture("base.json")
    added = copy.deepcopy(old)
    added_content = cast(
        dict[str, object],
        added["paths"]["/api/v2/items"]["post"]["responses"]["200"]["content"],  # type: ignore[index]
    )
    added_content["application/problem+json"] = copy.deepcopy(added_content["application/json"])
    removed = copy.deepcopy(old)
    removed_content = cast(
        dict[str, object],
        removed["paths"]["/api/v2/items"]["post"]["responses"]["200"]["content"],  # type: ignore[index]
    )
    del removed_content["application/json"]

    assert governance.compare_contracts(old, added).breaking_changes == (
        "POST /api/v2/items: response 200 content type application/problem+json was added",
    )
    assert governance.compare_contracts(old, removed).breaking_changes == (
        "POST /api/v2/items: response 200 content type application/json was removed",
    )


def test_response_compatibility_result_is_deduplicated_sorted_and_stable() -> None:
    old = _fixture("base.json")
    new = copy.deepcopy(old)
    responses = cast(dict[str, object], new["paths"]["/api/v2/items"]["post"]["responses"])  # type: ignore[index]
    responses["202"] = {"description": "accepted"}
    content = cast(dict[str, object], responses["200"]["content"])  # type: ignore[index]
    content["application/problem+json"] = copy.deepcopy(content["application/json"])

    first = governance.compare_contracts(old, new)
    second = governance.compare_contracts(old, new)

    assert first == second
    assert first.breaking_changes == tuple(sorted(set(first.breaking_changes)))


def test_same_composition_references_compare_changed_component_semantics() -> None:
    old = _fixture("base.json")
    new = copy.deepcopy(old)
    composition = {"oneOf": [{"$ref": "#/components/schemas/Accepted"}]}
    _response_schema(old).clear()
    _response_schema(old).update(composition)
    _response_schema(new).clear()
    _response_schema(new).update(composition)
    old["components"] = {"schemas": {"Accepted": {"type": "integer", "const": 2}}}
    new["components"] = {"schemas": {"Accepted": {"type": "integer", "const": 3}}}

    assert governance.compare_contracts(old, new).change.value == "BREAKING"


def test_recursive_component_comparison_terminates_and_is_deterministic() -> None:
    old = _fixture("base.json")
    new = copy.deepcopy(old)
    root = {"$ref": "#/components/schemas/Node"}
    _response_schema(old).clear()
    _response_schema(old).update(root)
    _response_schema(new).clear()
    _response_schema(new).update(root)
    old["components"] = {
        "schemas": {
            "Node": {
                "type": "object",
                "properties": {"value": {"const": "A"}, "next": {"$ref": "#/components/schemas/Node"}},
            }
        }
    }
    new["components"] = copy.deepcopy(old["components"])
    new["components"]["schemas"]["Node"]["properties"]["value"]["const"] = "B"  # type: ignore[index]

    first = governance.compare_contracts(old, new)
    second = governance.compare_contracts(old, new)
    assert first.change.value == "BREAKING"
    assert first == second


def test_discriminator_change_fails_closed() -> None:
    old_schema: dict[str, object] = {"type": "object", "discriminator": {"propertyName": "kind"}}
    new_schema: dict[str, object] = {"type": "object", "discriminator": {"propertyName": "type"}}
    assert _comparison_with_schema(old_schema, new_schema, direction="response").change.value == "BREAKING"


def test_current_v2_schema_vocabulary_is_fully_governed() -> None:
    document = json.loads((ROOT / "contracts/product-api/v2/openapi.json").read_text(encoding="utf-8"))
    vocabulary = governance.schema_vocabulary(document)
    assert vocabulary == {
        "$ref",
        "additionalProperties",
        "anyOf",
        "const",
        "default",
        "discriminator",
        "enum",
        "items",
        "oneOf",
        "pattern",
        "properties",
        "required",
        "title",
        "type",
    }
    governance.validate_schema_vocabulary(document)


def test_unknown_schema_semantics_fail_closed() -> None:
    old = _fixture("base.json")
    new = copy.deepcopy(old)
    _response_schema(new)["contentEncoding"] = "base64"
    with pytest.raises(ValueError, match="unsupported schema compatibility keyword contentEncoding"):
        governance.compare_contracts(old, new)


def test_strategy_and_backtest_routes_declare_exact_product_errors_without_422() -> None:
    document = governance.render_document()
    operations = [
        operation
        for path, item in document["paths"].items()
        if path.startswith("/api/v2/strateg") or path.startswith("/api/v2/backtest")
        for method, operation in item.items()
        if method in governance.HTTP_METHODS
    ]
    assert operations
    for operation in operations:
        assert "422" not in operation["responses"]
        for status in ("400", "404", "409", "500", "503"):
            assert operation["responses"][status]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ProductErrorEnvelopeDto"
            }

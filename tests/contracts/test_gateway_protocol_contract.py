from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts import gateway_protocol


def _compile(tmp_path: Path, name: str, source: str):
    root = tmp_path / name
    root.mkdir()
    (root / "contract.proto").write_text(source, encoding="utf-8")
    return gateway_protocol.compile_descriptor(root, (Path("contract.proto"),))


def _contract(body: str, service: str = "") -> str:
    return f"""syntax = "proto3";
package onlyalpha.gateway.v1;
{body}
{service}
"""


@pytest.mark.contract
def test_gateway_protocol_generation_is_stable_and_current(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    gateway_protocol.compile_projection(
        gateway_protocol.CONTRACT_ROOT,
        first,
        gateway_protocol.canonical_sources(),
    )
    gateway_protocol.compile_projection(
        gateway_protocol.CONTRACT_ROOT,
        second,
        gateway_protocol.canonical_sources(),
    )
    first_files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    second_files = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    assert first_files == second_files
    assert all((first / path).read_bytes() == (second / path).read_bytes() for path in first_files)
    assert gateway_protocol.check() == "5cb5005475e24019669a8658a5189b9d6321488f3e3c675bdc0195b826dfd67e"


@pytest.mark.contract
def test_existing_field_number_change_fails(tmp_path: Path) -> None:
    baseline = _compile(tmp_path, "old", _contract("message Value { string identity = 1; }"))
    candidate = _compile(tmp_path, "new", _contract("message Value { string identity = 2; }"))
    assert "field number changed" in "\n".join(gateway_protocol.compatibility_errors(baseline, candidate))


@pytest.mark.contract
def test_existing_field_type_change_fails(tmp_path: Path) -> None:
    baseline = _compile(tmp_path, "old", _contract("message Value { string identity = 1; }"))
    candidate = _compile(tmp_path, "new", _contract("message Value { bytes identity = 1; }"))
    assert "field type changed" in "\n".join(gateway_protocol.compatibility_errors(baseline, candidate))


@pytest.mark.contract
def test_reserved_field_number_and_name_reuse_fails(tmp_path: Path) -> None:
    baseline = _compile(
        tmp_path,
        "old",
        _contract('message Value { reserved 2; reserved "retired"; string identity = 1; }'),
    )
    candidate = _compile(
        tmp_path,
        "new",
        _contract("message Value { string identity = 1; string retired = 2; }"),
    )
    errors = "\n".join(gateway_protocol.compatibility_errors(baseline, candidate))
    assert "reserved field name reused" in errors
    assert "reserved field number reused" in errors


@pytest.mark.contract
def test_existing_enum_value_removal_and_number_change_fail(tmp_path: Path) -> None:
    baseline = _compile(
        tmp_path,
        "old",
        _contract("enum Result { RESULT_UNSPECIFIED = 0; ACCEPTED = 1; REJECTED = 2; }"),
    )
    removed = _compile(
        tmp_path,
        "removed",
        _contract("enum Result { RESULT_UNSPECIFIED = 0; ACCEPTED = 1; }"),
    )
    renumbered = _compile(
        tmp_path,
        "renumbered",
        _contract("enum Result { RESULT_UNSPECIFIED = 0; ACCEPTED = 2; REJECTED = 1; }"),
    )
    assert "enum value removed" in "\n".join(gateway_protocol.compatibility_errors(baseline, removed))
    assert "enum value number changed" in "\n".join(gateway_protocol.compatibility_errors(baseline, renumbered))


@pytest.mark.contract
def test_reserved_enum_value_number_and_name_reuse_fails(tmp_path: Path) -> None:
    baseline = _compile(
        tmp_path,
        "old",
        _contract('enum Result { reserved 2; reserved "RETIRED"; RESULT_UNSPECIFIED = 0; ACCEPTED = 1; }'),
    )
    candidate = _compile(
        tmp_path,
        "new",
        _contract("enum Result { RESULT_UNSPECIFIED = 0; ACCEPTED = 1; RETIRED = 2; }"),
    )
    errors = "\n".join(gateway_protocol.compatibility_errors(baseline, candidate))
    assert "reserved enum value name reused" in errors
    assert "reserved enum value number reused" in errors


@pytest.mark.contract
def test_rpc_removal_fails(tmp_path: Path) -> None:
    body = "message Request {} message Response {}"
    baseline = _compile(
        tmp_path,
        "old",
        _contract(body, "service Gateway { rpc Execute(Request) returns (Response); }"),
    )
    candidate = _compile(tmp_path, "new", _contract(body, "service Gateway {}"))
    assert "RPC removed" in "\n".join(gateway_protocol.compatibility_errors(baseline, candidate))


@pytest.mark.contract
def test_incompatible_rpc_request_type_change_fails(tmp_path: Path) -> None:
    body = "message Request {} message OtherRequest {} message Response {}"
    baseline = _compile(
        tmp_path,
        "old",
        _contract(body, "service Gateway { rpc Execute(Request) returns (Response); }"),
    )
    candidate = _compile(
        tmp_path,
        "new",
        _contract(body, "service Gateway { rpc Execute(OtherRequest) returns (Response); }"),
    )
    assert "RPC signature changed" in "\n".join(gateway_protocol.compatibility_errors(baseline, candidate))


@pytest.mark.contract
def test_silent_protocol_package_major_change_fails(tmp_path: Path) -> None:
    baseline = _compile(tmp_path, "old", _contract("message Value { string identity = 1; }"))
    candidate = _compile(
        tmp_path,
        "new",
        'syntax = "proto3"; package onlyalpha.gateway.v2; message Value { string identity = 1; }',
    )
    assert "protocol package major changed" in "\n".join(gateway_protocol.compatibility_errors(baseline, candidate))


@pytest.mark.contract
def test_verify_requires_an_immutable_git_sha() -> None:
    with pytest.raises(ValueError, match="immutable 40-character lowercase Git SHA"):
        gateway_protocol.verify("HEAD")


def teardown_module() -> None:
    for path in Path(".").glob("contract_pb2*.py"):
        path.unlink()
    shutil.rmtree("__pycache__", ignore_errors=True)

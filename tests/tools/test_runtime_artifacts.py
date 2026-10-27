"""One artifact schema binds the exact bundled frontend/backend and contracts."""

from __future__ import annotations

import hashlib
import json
import sys

import pytest

from scripts import runtime_artifacts
from scripts.dev_verification import source_inputs


@pytest.fixture
def composition(tmp_path):
    root, artifact = tmp_path / "source", tmp_path / "artifact"
    roots = ("subscribe", "event", "temporary_subscribe", "temporary_event")
    stream_export = {
        "contract": {"components": {"schemas": {name: {"type": "object"} for name in roots}}},
        "message_roots": {name: name for name in roots},
    }
    stream_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "onlyalpha.product-api.v2.market-data-stream",
        "$defs": {name: {"type": "object"} for name in roots},
        "anyOf": [{"$ref": "#/$defs/" + name} for name in roots],
    }
    stream_schema["$defs"]["subscribe"].update(
        {
            "if": {"properties": {"resume_after_sequence": {"not": {"const": "0"}}}},
            "then": {
                "required": ["resume_plan_fingerprint"],
                "properties": {"resume_plan_fingerprint": {"type": "string"}},
            },
        }
    )
    files = {
        "packages/backend/Cargo.toml": '[package]\nversion="0.12.0"\n',
        "packages/frontend/package.json": '{"version":"0.13.0"}',
        "contracts/product-api/v2/openapi.json": '{"info":{"version":"2"},"paths":{}}',
        "contracts/product-api/v2/market-data-stream.schema.json": json.dumps(stream_schema),
    }
    for name, raw in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw)
    (artifact / "bin").mkdir(parents=True)
    executable = artifact / "bin/onlyalpha-backend"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"print({files['contracts/product-api/v2/openapi.json']!r} if sys.argv[1] == '--export-openapi' else {json.dumps(stream_export)!r})\n"
    )
    executable.chmod(0o755)
    (artifact / "web").mkdir()
    (artifact / "web/index.html").write_text("<html>Shipping UI</html>")
    (artifact / "algorithm-artifact.sha256").write_text("b" * 64 + "\n")
    return root, artifact


def test_distinct_versions_form_one_explicit_exact_bundled_pair(composition):
    root, artifact = composition
    inputs = source_inputs(root)
    manifest = runtime_artifacts.seal(root, artifact, inputs)
    assert manifest["default_pair"]["backend_version"] == "0.12.0"
    assert manifest["default_pair"]["frontend_version"] == "0.13.0"
    assert manifest["default_pair"]["api_major"] == 2
    assert (
        manifest["default_pair"]["backend_sha256"]
        == hashlib.sha256((artifact / "bin/onlyalpha-backend").read_bytes()).hexdigest()
    )
    runtime_artifacts.verify_artifacts(artifact, inputs, "0.12.0", frontend_version="0.13.0")


@pytest.mark.parametrize(
    "mutation",
    ["frontend-version", "pair-missing", "backend-bytes", "web-bytes", "contract-bytes", "algorithm-id", "api-major"],
)
def test_wrong_or_unrecorded_composition_is_rejected(composition, mutation):
    root, artifact = composition
    inputs = source_inputs(root)
    runtime_artifacts.seal(root, artifact, inputs)
    path = artifact / "manifest.json"
    manifest = json.loads(path.read_text())
    if mutation == "frontend-version":
        manifest["default_pair"]["frontend_version"] = "0.14.0"
    elif mutation == "pair-missing":
        del manifest["default_pair"]
    elif mutation == "api-major":
        manifest["default_pair"]["api_major"] = True
    elif mutation == "algorithm-id":
        manifest["algorithm_artifact"] = "c" * 64
    else:
        target = {
            "backend-bytes": "bin/onlyalpha-backend",
            "web-bytes": "web/index.html",
            "contract-bytes": "contracts/openapi.json",
        }[mutation]
        (artifact / target).write_bytes(b"replaced")
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="NATIVE_ARTIFACT"):
        runtime_artifacts.verify_artifacts(artifact, inputs, "0.12.0", frontend_version="0.13.0")


def test_compiled_contract_must_match_selected_source_before_sealing(composition):
    root, artifact = composition
    (root / "contracts/product-api/v2/openapi.json").write_text('{"paths":{"/unimplemented":{}}}')
    with pytest.raises(ValueError, match="NATIVE_ARTIFACT_CONTRACT_MISMATCH"):
        runtime_artifacts.seal(root, artifact, source_inputs(root))
    assert not (artifact / "manifest.json").exists()


def test_external_selection_digest_binds_the_manifest_bytes_actually_verified(composition):
    root, artifact = composition
    inputs = source_inputs(root)
    runtime_artifacts.seal(root, artifact, inputs)
    with pytest.raises(ValueError, match="NATIVE_ARTIFACT_SELECTION_MISMATCH"):
        runtime_artifacts.verify_artifacts(
            artifact, inputs, "0.12.0", frontend_version="0.13.0", manifest_sha256="0" * 64
        )

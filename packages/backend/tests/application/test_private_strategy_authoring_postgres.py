"""Technical Strategy authoring regressions; business acceptance uses Shipping Web UI."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from packages.backend.tests.application.support.research_admission_reference import build
from packages.backend.tests.application.test_schema_postgres import migration_backend as migration_backend
from packages.backend.tests.application.test_schema_postgres import schema_db as schema_db

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]


@pytest.fixture
def database(schema_db: str) -> str:
    return schema_db


def draft(strategy_id: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[4]
    source = json.loads((root / "test-data/strategy/product-sources-v1.jsonl").read_text().splitlines()[0])["record"]
    variable = {"kind": "VARIABLE", "instance_key": "momentum", "output_name": "value"}
    literal = {"kind": "LITERAL", "data_type": "DECIMAL", "value": {"type": "DECIMAL", "value": "0"}}
    return {
        "schema_version": 1,
        "strategy_id": strategy_id,
        "base_revision_fingerprint": None,
        "semantic_version": "1",
        "description": "BTC momentum",
        "tags": ["momentum"],
        "definition": {
            "schema_version": 1,
            "universe": source["universe"],
            "market_input": source["market_input_contract"],
            "calculations": [
                {
                    "instance_key": "momentum",
                    "type_reference": {
                        "kind": "INDICATOR",
                        "type_id": "onlyalpha.indicator.sma",
                        "semantic_version": "1",
                    },
                    "parameters": {},
                    "published_outputs": ["value"],
                    "input_bindings": [{"input_name": "close", "source": "bar.close"}],
                    "primary_output": "value",
                }
            ],
            "factor_revision_dependencies": [],
            "eligibility": {
                "kind": "COMPARISON",
                "operator": ">",
                "left": {"kind": "DATASET_FIELD", "field_name": "close"},
                "right": literal,
            },
            "signals": {
                "entry": {"kind": "COMPARISON", "operator": ">=", "left": variable, "right": literal},
                "exit": {"kind": "COMPARISON", "operator": "<=", "left": variable, "right": literal},
            },
        },
    }


def call(probe: Path, strategy_id: str, action: str, **values: Any) -> dict[str, Any]:
    request = {
        "op": "strategy-authoring",
        "action": action,
        "strategy_id": strategy_id,
        "owner": "technical-owner",
        "command_id": str(uuid4()),
        "accepted_at": "2026-11-01T00:00:00Z",
        **values,
    }
    result = subprocess.run([str(probe)], input=json.dumps(request), text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_strategy_draft_revision_and_original_command_survive_fresh_processes(
    native_probe: Path, database: str
) -> None:
    strategy_id = "private.strategy.s" + uuid4().hex
    original = draft(strategy_id)
    command = str(uuid4())
    saved = call(native_probe, strategy_id, "save", draft=original, expected=None, command_id=command)
    assert saved["result"]["draft"] == original
    assert call(native_probe, strategy_id, "read")["draft"] == original
    pin = saved["result"]["draft_fingerprint"]
    published = call(native_probe, strategy_id, "publish", expected=pin)
    revision = published["result"]["revision"]
    assert revision["parent_revision_fingerprint"] is None
    assert "strategy_fingerprint" not in revision
    current = call(native_probe, strategy_id, "read")
    assert current["current_revision_fingerprint"] == revision["revision_fingerprint"]
    assert current["revisions"] == [revision]
    assert call(native_probe, strategy_id, "command", command_id=command) == saved
    assert call(native_probe, strategy_id, "save", draft=original, expected=None, command_id=command) == saved
    changed = {**original, "description": "changed"}
    assert (
        call(native_probe, strategy_id, "save", draft=changed, expected=None, command_id=command)["error"]
        == "PRIVATE_STRATEGY_COMMAND_CONFLICT"
    )
    assert (
        call(native_probe, strategy_id, "command", command_id=command, owner="another-owner")["error"]
        == "PRIVATE_STRATEGY_ACCESS_DENIED"
    )
    assert (
        call(native_probe, strategy_id, "save", draft=original, expected=None)["error"]
        == "PRIVATE_STRATEGY_DRAFT_CONFLICT"
    )


def test_strategy_authoring_rejects_stale_base_and_keeps_two_exact_revisions(native_probe: Path, database: str) -> None:
    strategy_id = "private.strategy.s" + uuid4().hex
    original = draft(strategy_id)
    first = call(native_probe, strategy_id, "save", draft=original, expected=None)
    pin = first["result"]["draft_fingerprint"]
    revision = call(native_probe, strategy_id, "publish", expected=pin)["result"]["revision"]
    changed = {
        **original,
        "semantic_version": "2",
        "description": "second",
        "base_revision_fingerprint": revision["revision_fingerprint"],
    }
    second = call(native_probe, strategy_id, "save", draft=changed, expected=pin)
    assert second["result"]["draft"] == changed
    published = call(native_probe, strategy_id, "publish", expected=second["result"]["draft_fingerprint"])
    assert published["result"]["revision"]["parent_revision_fingerprint"] == revision["revision_fingerprint"]
    assert len(call(native_probe, strategy_id, "read")["revisions"]) == 2
    assert (
        call(native_probe, strategy_id, "save", draft=original, expected=second["result"]["draft_fingerprint"])["error"]
        == "PRIVATE_STRATEGY_DRAFT_CONFLICT"
    )


def factor_revision(probe: Path) -> dict[str, Any]:
    factor_id = "private.factor.f" + uuid4().hex
    value = {
        "schema_version": 1,
        "factor_id": factor_id,
        "base_revision_fingerprint": None,
        "semantic_version": "1",
        "source_text": "def calculate(api, inputs, parameters):\n    return {'value': inputs['close']}\n",
        "factor_api_version": 1,
        "factor_api_contract_fingerprint": "3265e2397f581705b67c1372483b6629671b68af71f69575c7bd602816d63be9",
        "input_contract": {"close": {"type": "DECIMAL"}},
        "parameter_contract": {},
        "output_contract": {"value": {"type": "DECIMAL"}},
        "description": "Fixture factor",
        "economic_rationale": "Technical fixture",
        "category": "price",
        "tags": [],
    }
    saved = call(probe, factor_id, "save", op="factor-authoring", factor_id=factor_id, draft=value, expected=None)
    return call(
        probe,
        factor_id,
        "publish",
        op="factor-authoring",
        factor_id=factor_id,
        expected=saved["result"]["draft_fingerprint"],
    )["result"]["revision"]


def bind_factor(value: dict[str, Any], revision: dict[str, Any]) -> None:
    value["definition"]["calculations"][0]["type_reference"] = {
        "kind": "FACTOR",
        "type_id": revision["factor_id"],
        "semantic_version": revision["semantic_version"],
    }
    value["definition"]["factor_revision_dependencies"] = [
        {
            "factor_id": revision["factor_id"],
            "revision_fingerprint": revision["revision_fingerprint"],
        }
    ]


def test_strategy_authoring_binds_factor_semantic_version_to_the_exact_revision(
    native_probe: Path, database: str
) -> None:
    revision = factor_revision(native_probe)
    strategy_id = "private.strategy.s" + uuid4().hex
    value = draft(strategy_id)
    bind_factor(value, revision)
    value["definition"]["calculations"][0]["type_reference"]["semantic_version"] = "2"
    assert (
        call(native_probe, strategy_id, "save", draft=value, expected=None).get("error")
        == "PRIVATE_STRATEGY_FACTOR_REVISION_MISMATCH"
    )
    assert call(native_probe, strategy_id, "read")["error"] == "PRIVATE_STRATEGY_NOT_FOUND"
    value["definition"]["calculations"][0]["type_reference"]["semantic_version"] = "1"
    assert call(native_probe, strategy_id, "save", draft=value, expected=None)["result"]["draft"] == value


def test_strategy_authoring_reuses_factor_owner_validation_of_physical_source_columns(
    native_probe: Path, database: str
) -> None:
    import hashlib

    import psycopg

    revision = factor_revision(native_probe)
    revision["factor_id"] = "private.factor.corrupt_" + uuid4().hex
    revision.pop("revision_fingerprint")
    identity = {"contract": "ONLYALPHA_PRIVATE_FACTOR_REVISION_V1", **revision}
    revision["revision_fingerprint"] = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    # Malformed append-only source precondition; no trigger or immutability guard is disabled.
    with psycopg.connect(database) as connection:
        connection.execute(
            "INSERT INTO private_factor_asset(factor_id,schema_version) VALUES(%s,1)", (revision["factor_id"],)
        )
        connection.execute(
            "INSERT INTO private_factor_revision(revision_fingerprint,factor_id,source_text,source_sha256,payload,schema_version) VALUES(%s,%s,%s,%s,%s::jsonb,1)",
            (
                revision["revision_fingerprint"],
                revision["factor_id"],
                "different source",
                revision["source_sha256"],
                json.dumps(revision),
            ),
        )
    strategy_id = "private.strategy.s" + uuid4().hex
    value = draft(strategy_id)
    bind_factor(value, revision)
    assert (
        call(native_probe, strategy_id, "save", draft=value, expected=None).get("error") == "PRIVATE_STRATEGY_CORRUPT"
    )
    assert call(native_probe, strategy_id, "read")["error"] == "PRIVATE_STRATEGY_NOT_FOUND"


def test_strategy_factor_input_budget_preserves_the_owning_readers_unavailable_state(
    native_probe: Path, database: str
) -> None:
    import hashlib

    import psycopg

    revision = factor_revision(native_probe)
    revision["factor_id"] = "private.factor.large_" + uuid4().hex
    revision["source_text"] = "x" * (8 * 1024 * 1024)
    revision["source_sha256"] = hashlib.sha256(revision["source_text"].encode()).hexdigest()
    revision.pop("revision_fingerprint")
    identity = {"contract": "ONLYALPHA_PRIVATE_FACTOR_REVISION_V1", **revision}
    revision["revision_fingerprint"] = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with psycopg.connect(database) as connection:
        connection.execute(
            "INSERT INTO private_factor_asset(factor_id,schema_version) VALUES(%s,1)", (revision["factor_id"],)
        )
        connection.execute(
            "INSERT INTO private_factor_revision(revision_fingerprint,factor_id,source_text,source_sha256,payload,schema_version) VALUES(%s,%s,%s,%s,%s::jsonb,1)",
            (
                revision["revision_fingerprint"],
                revision["factor_id"],
                revision["source_text"],
                revision["source_sha256"],
                json.dumps(revision),
            ),
        )
    owning = call(
        native_probe,
        revision["factor_id"],
        "exact",
        op="factor-authoring",
        factor_id=revision["factor_id"],
        revision_fingerprint=revision["revision_fingerprint"],
        content_fingerprint=revision["source_sha256"],
    )
    assert owning["error"] == "PRIVATE_ASSET_AUTHORITY_UNAVAILABLE"
    strategy_id = "private.strategy.s" + uuid4().hex
    value = draft(strategy_id)
    bind_factor(value, revision)
    assert (
        call(native_probe, strategy_id, "save", draft=value, expected=None).get("error")
        == "PRIVATE_STRATEGY_AUTHORITY_UNAVAILABLE"
    )


def test_strategy_command_reader_rejects_unknown_fields_even_with_self_consistent_hashes(
    native_probe: Path, database: str
) -> None:
    import hashlib

    import psycopg

    strategy_id = "private.strategy.s" + uuid4().hex
    saved = call(native_probe, strategy_id, "save", draft=draft(strategy_id), expected=None)
    with psycopg.connect(database) as connection:
        original = connection.execute(
            "SELECT payload FROM private_strategy_authoring_outcome WHERE command_id=%s", (saved["command_id"],)
        ).fetchone()[0]
        for mode in ("extra-input", "missing-revision", "invalid-expected"):
            record = json.loads(json.dumps(original))
            command = str(uuid4())
            record["command_id"] = command
            if mode == "extra-input":
                record["input"]["unknown"] = True
            elif mode == "missing-revision":
                record["result"].pop("revision")
                record["result"]["unknown"] = None
            else:
                record["input"]["expected_draft_fingerprint"] = 123

            def digest(value: dict[str, Any]) -> str:
                return hashlib.sha256(
                    json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()

            intent = digest(
                {
                    "contract": "ONLYALPHA_PRIVATE_STRATEGY_AUTHORING_INTENT_V1",
                    "owner": "technical-owner",
                    "input": record["input"],
                }
            )
            outcome = digest({"contract": "ONLYALPHA_PRIVATE_STRATEGY_AUTHORING_OUTCOME_V1", "outcome": record})
            connection.execute(
                "INSERT INTO product_command_admission(command_id,command_kind,command_fingerprint,schema_version) VALUES(%s,'SAVE_PRIVATE_STRATEGY_DRAFT',%s,1)",
                (command, intent),
            )
            connection.execute(
                "INSERT INTO product_command_receipt(command_id,command_kind,command_fingerprint,outcome_kind,outcome_id,accepted_at,schema_version) VALUES(%s,'SAVE_PRIVATE_STRATEGY_DRAFT',%s,'PRIVATE_STRATEGY_AUTHORING',%s,'2026-11-01T00:00:00Z',1)",
                (command, intent, outcome),
            )
            connection.execute(
                "INSERT INTO private_strategy_authoring_outcome(command_id,strategy_id,owner,fingerprint,payload,schema_version) VALUES(%s,%s,'technical-owner',%s,%s::jsonb,1)",
                (command, strategy_id, outcome, json.dumps(record)),
            )
        connection.commit()
        commands = connection.execute(
            "SELECT command_id::text FROM private_strategy_authoring_outcome WHERE strategy_id=%s AND command_id<>%s",
            (strategy_id, saved["command_id"]),
        ).fetchall()
    for (command,) in commands:
        assert call(native_probe, strategy_id, "command", command_id=command).get("error") == "PRIVATE_STRATEGY_CORRUPT"


def test_strategy_exact_revision_read_never_substitutes_the_current_version(native_probe: Path, database: str) -> None:
    strategy_id = "private.strategy.s" + uuid4().hex
    original = draft(strategy_id)
    saved = call(native_probe, strategy_id, "save", draft=original, expected=None)
    first = call(native_probe, strategy_id, "publish", expected=saved["result"]["draft_fingerprint"])["result"][
        "revision"
    ]
    changed = {
        **original,
        "semantic_version": "2",
        "base_revision_fingerprint": first["revision_fingerprint"],
        "description": "second",
    }
    saved = call(native_probe, strategy_id, "save", draft=changed, expected=saved["result"]["draft_fingerprint"])
    call(native_probe, strategy_id, "publish", expected=saved["result"]["draft_fingerprint"])
    assert (
        call(
            native_probe,
            strategy_id,
            "exact",
            revision_fingerprint=first["revision_fingerprint"],
            content_fingerprint=first["definition_fingerprint"],
        )
        == first
    )
    assert (
        call(
            native_probe,
            strategy_id,
            "exact",
            revision_fingerprint=first["revision_fingerprint"],
            content_fingerprint="b" * 64,
        ).get("error")
        == "PRIVATE_ASSET_EXACT_READ_MISMATCH"
    )
    assert (
        call(
            native_probe,
            strategy_id,
            "exact",
            revision_fingerprint="b" * 64,
            content_fingerprint=first["definition_fingerprint"],
        ).get("error")
        == "PRIVATE_ASSET_EXACT_REVISION_UNAVAILABLE"
    )


def research_context() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "start": "2025-01-02T12:00:00Z",
        "end": "2025-01-03T00:00:00Z",
        "targets": [
            {
                "instance_key": "forward_return",
                "type_reference": {
                    "kind": "TARGET",
                    "type_id": "onlyalpha.target.forward_return",
                    "semantic_version": "1",
                },
                "parameters": {"exit_offset": {"kind": "FIXED", "value": {"type": "INTEGER", "value": 5}}},
                "published_outputs": ["target_value"],
                "primary_output": None,
                "input_bindings": [
                    {"input_name": "entry_price", "source": "bar.close"},
                    {"input_name": "exit_price", "source": "bar.close"},
                ],
            }
        ],
        "statistics": [
            {
                "variable": {"kind": "VARIABLE", "instance_key": "momentum", "output_name": "value"},
                "target_instance_key": "forward_return",
                "definition": {
                    "schema_version": 1,
                    "method": "IC",
                    "minimum_observations": 2,
                    "pairing_policy": "PAIRWISE_COMPLETE",
                    "universe_policy": "OBSERVED_PAIRWISE",
                    "rank_tie_method": "AVERAGE",
                    "weighting": "EQUAL",
                    "numeric": {
                        "representation": "DECIMAL",
                        "precision": 38,
                        "output_quantum": "0.000000000001",
                        "rounding": "ROUND_HALF_EVEN",
                    },
                },
            }
        ],
        "display_metadata": {"title": "Technical contract comparison"},
    }


def test_native_strategy_context_matches_the_public_authoring_contract(native_probe: Path, database: str) -> None:
    # Compare the current Rust owner's exact public wire shape and semantic
    # identity behavior, rather than importing the retired Python authority.
    # Independent contract vectors are covered by strategy_research Rust tests.
    strategy_id = "private.strategy.s" + uuid4().hex
    value = draft(strategy_id)["definition"]
    exit_condition = value["signals"]["exit"]
    entry_condition = value["signals"]["entry"]
    eligibility = value["eligibility"]
    value["eligibility"] = {
        "kind": "AND",
        "operands": [exit_condition, {"kind": "AND", "operands": [entry_condition, eligibility]}],
    }
    context = research_context()
    result = call(native_probe, strategy_id, "context", definition=value, context=context)
    assert "error" not in result, result
    assert result["context"] == context
    context_identity = {"contract": "ONLYALPHA_PRIVATE_STRATEGY_RESEARCH_CONTEXT_V1", **context}
    assert (
        result["context_fingerprint"]
        == hashlib.sha256(
            json.dumps(context_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert result["definition"] == {
        "schema_version": 1,
        "dataset": {
            "universe": {
                "kind": value["universe"]["kind"],
                "instrument_ids": value["universe"]["instruments"],
                "registered_id": None,
            },
            "bar_semantic": value["market_input"]["bar_semantic"],
            "start": context["start"],
            "end": context["end"],
        },
        "calculations": value["calculations"],
        "eligibility": value["eligibility"],
        "signals": value["signals"],
        "targets": context["targets"],
        "statistics": context["statistics"],
        "display_metadata": context["display_metadata"],
    }
    assert len(result["definition_fingerprint"]) == 64
    assert call(native_probe, strategy_id, "context", definition=value, context=context) == result
    flattened = json.loads(json.dumps(value))
    flattened["eligibility"] = {"kind": "AND", "operands": [eligibility, exit_condition, entry_condition]}
    reordered = call(native_probe, strategy_id, "context", definition=flattened, context=context)
    assert reordered["definition_fingerprint"] == result["definition_fingerprint"]
    presentation = {**context, "display_metadata": {"title": "Changed presentation"}}
    renamed = call(native_probe, strategy_id, "context", definition=value, context=presentation)
    assert renamed["context_fingerprint"] != result["context_fingerprint"]
    assert renamed["definition_fingerprint"] == result["definition_fingerprint"]
    changed = json.loads(json.dumps(value))
    changed["signals"]["entry"]["right"]["value"]["value"] = "0.001"
    assert (
        call(native_probe, strategy_id, "context", definition=changed, context=context)["definition_fingerprint"]
        != result["definition_fingerprint"]
    )


def test_strategy_composition_reanchors_exact_revision_and_retains_public_context(
    native_release_probe: Path, database: str, tmp_path: Path
) -> None:
    import psycopg

    runtime = tmp_path / "runtime"
    selected = build(runtime, native_release_probe, preparation_kind="STRATEGY", work_id="work")
    executable = runtime / "native-executor"
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == selected["executor_sha256"]
    generation = selected["generation"]
    strategy_id = "private.strategy.s" + uuid4().hex
    value = draft(strategy_id)
    calculation = value["definition"]["calculations"][0]
    calculation["type_reference"] = {
        "kind": "INDICATOR",
        "type_id": "onlyalpha.operator.delay",
        "semantic_version": "2",
    }
    calculation["parameters"] = {"period": {"kind": "FIXED", "value": {"type": "INTEGER", "value": 20}}}
    calculation["input_bindings"] = [{"input_name": "value", "source": "bar.close"}]
    saved = call(executable, strategy_id, "save", draft=value, expected=None)
    revision = call(executable, strategy_id, "publish", expected=saved["result"]["draft_fingerprint"])["result"][
        "revision"
    ]
    arguments = {
        "context": research_context(),
        "runtime_root": str(runtime),
        "runtime_generation": generation,
        "revision_fingerprint": revision["revision_fingerprint"],
    }
    composition = call(executable, strategy_id, "composition", **arguments)
    assert composition["private_strategy_revision_fingerprint"] == revision["revision_fingerprint"]
    assert composition["factor_revision_bindings"] == []
    assert "strategy_fingerprint" not in composition and "runtime_generation_fingerprint" not in composition
    changed = {
        **value,
        "semantic_version": "2",
        "description": "second",
        "base_revision_fingerprint": revision["revision_fingerprint"],
    }
    saved = call(executable, strategy_id, "save", draft=changed, expected=saved["result"]["draft_fingerprint"])
    call(executable, strategy_id, "publish", expected=saved["result"]["draft_fingerprint"])
    assert call(executable, strategy_id, "composition", **arguments) == composition
    with psycopg.connect(database) as connection:
        row = connection.execute(
            "SELECT count(*),min(research_context_payload::text) FROM private_strategy_research_composition WHERE private_strategy_id=%s",
            (strategy_id,),
        ).fetchone()
        assert row[0] == 1
        assert json.loads(row[1]) == research_context()

    # Malformed append-only fixture: a self-consistent lineage identity with a
    # mismatching retained Context must be rejected, not silently reused.
    from onlyalpha.canonical import only_canonical_fingerprint

    changed_context = research_context()
    changed_context["display_metadata"] = {"title": "Different context"}
    corrupt = {
        **composition,
        "research_context_fingerprint": only_canonical_fingerprint(
            {
                "contract": "ONLYALPHA_PRIVATE_STRATEGY_RESEARCH_CONTEXT_V1",
                **changed_context,
            }
        ),
    }
    descriptor = {key: value for key, value in corrupt.items() if key != "composition_fingerprint"}
    corrupt["composition_fingerprint"] = only_canonical_fingerprint(
        {
            "contract": "ONLYALPHA_PRIVATE_STRATEGY_RESEARCH_COMPOSITION_V1",
            **descriptor,
        }
    )
    with psycopg.connect(database) as connection:
        connection.execute(
            "INSERT INTO private_strategy_research_composition(composition_fingerprint,schema_version,private_strategy_id,private_strategy_revision_fingerprint,private_strategy_definition_fingerprint,research_context_fingerprint,factor_revision_bindings,catalog_generation_fingerprint,research_definition_fingerprint,research_context_payload) VALUES(%s,1,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb)",
            (
                corrupt["composition_fingerprint"],
                strategy_id,
                revision["revision_fingerprint"],
                revision["definition_fingerprint"],
                corrupt["research_context_fingerprint"],
                "[]",
                composition["catalog_generation_fingerprint"],
                composition["research_definition_fingerprint"],
                json.dumps(research_context()),
            ),
        )
    assert (
        call(executable, strategy_id, "composition", **{**arguments, "context": changed_context})["error"]
        == "PRIVATE_STRATEGY_COMPOSITION_CORRUPT"
    )

    # A public-only Generation with no Target capability cannot substitute for
    # the originally selected generation, even with the same public Operator.
    other_root = tmp_path / "public-only"
    other = build(other_root, native_release_probe, preparation_kind="FACTOR", work_id="work")
    other_executable = other_root / "native-executor"
    assert hashlib.sha256(other_executable.read_bytes()).hexdigest() == other["executor_sha256"]
    denied = call(
        other_executable,
        strategy_id,
        "composition",
        **{**arguments, "runtime_root": str(other_root), "runtime_generation": other["generation"]},
    )
    assert denied["error"] == "PRIVATE_STRATEGY_CALCULATION_UNAVAILABLE"

    # Physical artifact loss is controlled fault injection on this fixture root.
    target_manifest = next(
        path
        for path in (runtime / "artifacts").glob("*/*/manifest.json")
        if json.loads(path.read_text())["role"] == "CALCULATION"
    )
    target_manifest.with_name("artifact.whl").unlink()
    assert (
        call(executable, strategy_id, "composition", **arguments)["error"] == "PRIVATE_STRATEGY_COMPOSITION_UNAVAILABLE"
    )


def test_strategy_calculation_resolution_uses_held_generation_and_actual_installed_math(
    native_release_probe: Path, database: str, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime"
    selected = build(runtime, native_release_probe, preparation_kind="STRATEGY", work_id="work")
    executable = runtime / "native-executor"
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == selected["executor_sha256"]
    strategy_id = "private.strategy.s" + uuid4().hex
    value = draft(strategy_id)
    calculation = value["definition"]["calculations"][0]
    calculation["type_reference"] = {
        "kind": "INDICATOR",
        "type_id": "onlyalpha.operator.delay",
        "semantic_version": "2",
    }
    calculation["parameters"] = {"period": {"kind": "FIXED", "value": {"type": "INTEGER", "value": 20}}}
    calculation["input_bindings"] = [{"input_name": "value", "source": "bar.close"}]
    saved = call(executable, strategy_id, "save", draft=value, expected=None)
    revision = call(executable, strategy_id, "publish", expected=saved["result"]["draft_fingerprint"])["result"][
        "revision"
    ]
    arguments = {
        "context": research_context(),
        "runtime_root": str(runtime),
        "runtime_generation": selected["generation"],
        "revision_fingerprint": revision["revision_fingerprint"],
        "algorithm_root": selected["installation"],
        "algorithm_artifact": selected["algorithm_artifact"],
    }
    actual = call(executable, strategy_id, "resolution", **arguments)
    assert "error" not in actual, actual
    assert actual["runtime_generation_fingerprint"] == selected["generation"]
    assert actual["composition"]["private_strategy_revision_fingerprint"] == revision["revision_fingerprint"]
    assert actual["algorithm_resolution"]["source_artifacts"] == []
    assert len(actual["decision"]["decision_graph"]["nodes"]) == 7
    assert len(actual["target_graph"]["nodes"]) == 1
    assert "run_id" not in actual and "strategy_fingerprint" not in actual and "equivalence_evidence" not in actual
    assert call(executable, strategy_id, "resolution", **arguments) == actual
    # Controlled physical loss: an installed package cannot replace changed
    # original Generation bytes. No Run/Freeze is created by this technical test.
    artifacts = list((runtime / "artifacts").glob("*/*/artifact.whl"))
    assert artifacts
    original = artifacts[0]
    original.chmod(0o644)
    original.write_bytes(original.read_bytes() + b"changed")
    assert "error" in call(executable, strategy_id, "resolution", **arguments)

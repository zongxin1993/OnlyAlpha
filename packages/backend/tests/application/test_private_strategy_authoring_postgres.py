"""Technical Strategy authoring regressions; business acceptance uses Shipping Web UI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]


@pytest.fixture
def database(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return postgres_dsn


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

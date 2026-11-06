"""Shared canonical PostgreSQL Integration test inputs and effect snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg

from .native_probe import call

__all__ = ["call"]

_TABLES = (
    "integration",
    "integration_draft",
    "integration_draft_secret_binding",
    "integration_revision",
    "integration_revision_secret_binding",
    "product_credential",
    "product_command_admission",
    "product_command_receipt",
    "research_source_history",
    "research_source_history_frontier",
)


MASTER_KEY = b"k" * 32


NOW = datetime(2026, 9, 20, tzinfo=UTC)


def create_request() -> dict[str, Any]:
    descriptor = json.loads((Path(__file__).parents[1] / "fixtures/integration_resolver.json").read_text())[0][
        "descriptor"
    ]
    return {
        "op": "integration-write",
        "action": "create",
        "command_id": str(uuid4()),
        "integration_id": str(uuid4()),
        "type_id": json.loads(descriptor)["type_id"],
        "display_name": "Data source",
        "descriptor": descriptor,
        "accepted_at": "2026-09-20T00:00:00Z",
    }


def replay_request(request: dict[str, Any], probe: Path) -> dict[str, Any]:
    admission = call(probe, {"op": "integration-command-fixture", "request": request})
    return {
        "op": "integration-write",
        "action": "replay",
        "command_id": request["command_id"],
        "integration_id": request["integration_id"],
        **admission,
    }


def descriptor(probe: Path, *, extra_secret: bool = False) -> dict[str, Any]:
    field = {
        "advanced": False,
        "default": None,
        "description": "",
        "display_name": "",
        "enum_values": [],
        "exclusive_minimum": False,
        "maximum": None,
        "minimum": None,
        "required": False,
        "secret": False,
        "value_kind": "STRING",
    }
    fields = [
        {**field, "field_id": "api_key", "required": True, "secret": True, "display_name": "API key"},
        {**field, "field_id": "name", "required": True, "display_name": "Name"},
        {
            **field,
            "field_id": "timeout_seconds",
            "value_kind": "DURATION",
            "default": 10.0,
            "minimum": 0.1,
            "display_name": "Timeout",
        },
    ]
    if extra_secret:
        fields.append({**field, "field_id": "api_secret", "secret": True, "display_name": "Second secret"})
    contract = {"schema_version": 1, "fields": sorted(fields, key=lambda value: value["field_id"])}
    probe_contract = {
        "probe_version": 1,
        "probe_mode": "DEFAULT_INSTRUMENT",
        "default_probe_instrument": "BTCUSDT",
        "user_selectable_probe_instrument": True,
        "probe_checks": ["REFERENCE_DATA"],
    }
    for component in [contract, probe_contract]:
        component["fingerprint"] = call(
            probe, {"op": "integration-fixture-fingerprint", "document": json.dumps(component)}
        )["fingerprint"]
    return {
        "schema_version": 1,
        "type_id": "binance.spot.market_data",
        "category": "DATA_SOURCE",
        "display_name": "Binance Spot",
        "description": "Binance Spot market data",
        "provider_id": "binance",
        "implementation_id": "binance",
        "implementation_version": "1.0.0",
        "public_api_version": "1.1",
        "capabilities": ["HISTORICAL_BARS"],
        "configuration_contract": contract,
        "probe_contract": probe_contract,
    }


def lifecycle_request(request: dict[str, Any], expected: str, target: str) -> dict[str, Any]:
    return dict(request, action="lifecycle", command_id=str(uuid4()), expected=expected, target=target)


def edit(
    request: dict[str, Any], *, version: int = 1, public: str = '{"count":7,"ratio":-0.0}', probe: str | None = None
) -> dict[str, Any]:
    return dict(request, action="update", command_id=str(uuid4()), expected_version=version, public=public, probe=probe)


def reset(request: dict[str, Any], version: int) -> dict[str, Any]:
    return dict(request, action="reset", command_id=str(uuid4()), expected_version=version)


def configured(probe: Path, dsn: str, *, extra_secret: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    declared = descriptor(probe, extra_secret=extra_secret)
    request = create_request()
    request.update(type_id=declared["type_id"], descriptor=json.dumps(declared))
    assert "error" not in call(probe, request, dsn=dsn)
    assert "error" not in call(probe, edit(request, public='{ "name": "Controlled name" }'), dsn=dsn)
    fields = ["api_key", "api_secret"] if extra_secret else ["api_key"]
    for version, field in enumerate(fields, start=2):
        command = dict(
            request,
            action="set-secret",
            command_id=str(uuid4()),
            expected_version=version,
            field_id=field,
            secret="controlled-test-only",
        )
        assert "error" not in call(probe, command, dsn=dsn)
    return request, declared


def publish(request: dict[str, Any], version: int = 3) -> dict[str, Any]:
    return dict(request, action="publish", command_id=str(uuid4()), expected_version=version)


def clear(request: dict[str, Any], version: int = 3, field: str = "api_key") -> dict[str, Any]:
    return dict(request, action="clear", command_id=str(uuid4()), expected_version=version, field_id=field)


def owning_facts(dsn: str) -> dict[str, list[tuple[Any, ...]]]:
    with psycopg.connect(dsn) as connection:
        return {
            name: connection.execute(
                f"SELECT row_to_json(t)::text FROM {name} t ORDER BY row_to_json(t)::text"
            ).fetchall()
            for name in _TABLES
        }

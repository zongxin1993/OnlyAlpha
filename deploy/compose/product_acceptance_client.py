#!/usr/bin/env python3
"""HTTP-only A0 Product acceptance client.

This process intentionally uses only the Python standard library. It has no
database credentials, shared Product storage, or imports from OnlyAlpha.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from threading import Event
from typing import Any


class AcceptanceFailure(RuntimeError):
    pass


_POLL_BARRIER = Event()


def _required_json(name: str) -> dict[str, Any]:
    value = os.environ.get(name)
    if value is None:
        raise AcceptanceFailure(f"{name} is required")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise AcceptanceFailure(f"{name} must contain one JSON object")
    return parsed


class ProductHttpClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        expected_status: int = 200,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        request = urllib.request.Request(self._base_url + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as error:
            status = error.code
            raw = error.read()
        if status != expected_status:
            raise AcceptanceFailure(f"{method} {path}: expected {expected_status}, got {status}: {raw!r}")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise AcceptanceFailure(f"{method} {path}: response must be a JSON object")
        return parsed


def _poll_run(
    client: ProductHttpClient,
    path: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        run = client.request("GET", path)
        state = run.get("state")
        if state == "COMPLETED":
            return run
        if state in {"FAILED", "CANCELLED", "EXHAUSTED"}:
            raise AcceptanceFailure(f"{path} reached terminal failure: {run!r}")
        if time.monotonic() >= deadline:
            raise AcceptanceFailure(f"{path} did not complete before the acceptance deadline")
        _POLL_BARRIER.wait(0.25)


def _wait_for_state(
    client: ProductHttpClient,
    path: str,
    state: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        run = client.request("GET", path)
        if run.get("state") == state:
            return run
        if run.get("state") in {"FAILED", "CANCELLED", "COMPLETED", "EXHAUSTED"}:
            raise AcceptanceFailure(f"{path} reached {run.get('state')} before {state}")
        if time.monotonic() >= deadline:
            raise AcceptanceFailure(f"{path} did not reach {state} before the acceptance deadline")
        _POLL_BARRIER.wait(0.25)


def _resume_backtest(client: ProductHttpClient, run_id: str, timeout_seconds: float) -> dict[str, str]:
    run = _poll_run(client, f"/api/v2/backtest/runs/{run_id}", timeout_seconds=timeout_seconds)
    evidence = client.request("GET", f"/api/v2/backtest/runs/{run_id}/evidence")
    manifest = evidence.get("manifest")
    if not isinstance(manifest, dict) or manifest.get("result_fingerprint") != run.get("result_fingerprint"):
        raise AcceptanceFailure("Recovered Backtest Evidence does not match the durable Run")
    return {
        "backtest_run_id": run_id,
        "result_fingerprint": str(run["result_fingerprint"]),
        "determinism_fingerprint": str(run["determinism_fingerprint"]),
        "evidence_fingerprint": str(manifest["evidence_fingerprint"]),
    }


def _require_applied_funding(result: Mapping[str, Any]) -> None:
    ledgers = result.get("final_ledgers")
    if not isinstance(ledgers, list):
        raise AcceptanceFailure("USD-M Golden result has no final Strategy ledgers")
    funding_entries = [
        entry
        for ledger in ledgers
        if isinstance(ledger, dict) and isinstance(ledger.get("cash_entries"), list)
        for entry in ledger["cash_entries"]
        if isinstance(entry, dict) and entry.get("entry_type") == "FUNDING"
    ]
    try:
        applied = any(
            isinstance(entry.get("amount"), dict)
            and Decimal(str(entry["amount"].get("amount"))) != Decimal(0)
            and isinstance(entry.get("cash_flow_id"), str)
            for entry in funding_entries
        )
    except InvalidOperation as exc:
        raise AcceptanceFailure("USD-M Golden funding amount is not canonical Decimal text") from exc
    if not applied:
        raise AcceptanceFailure("USD-M Golden result contains no non-zero applied funding cashflow")


def run() -> dict[str, str]:
    client = ProductHttpClient(os.environ.get("ONLYALPHA_PRODUCT_API_URL", "http://onlyalpha-http-server:8000"))
    timeout_seconds = float(os.environ.get("ONLYALPHA_ACCEPTANCE_TIMEOUT_SECONDS", "120"))
    resume_run_id = os.environ.get("ONLYALPHA_ACCEPTANCE_RESUME_BACKTEST_RUN_ID")
    if resume_run_id:
        return _resume_backtest(client, resume_run_id, timeout_seconds)
    definition = _required_json("ONLYALPHA_ACCEPTANCE_DEFINITION_JSON")
    backtest_request = _required_json("ONLYALPHA_ACCEPTANCE_BACKTEST_JSON")

    client.request("GET", "/health/ready")
    client.request("GET", "/health/execution")
    resolution = client.request("POST", "/api/v2/research/definitions/resolve", definition)
    candidates = resolution.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
        raise AcceptanceFailure("Golden Research definition must resolve to exactly one candidate")
    candidate_fingerprint = candidates[0].get("candidate_fingerprint")
    specification = resolution.get("exact_specification")
    if not isinstance(candidate_fingerprint, str) or not isinstance(specification, dict):
        raise AcceptanceFailure("Research resolution identity is incomplete")

    research_key = str(uuid.uuid4())
    research_submission = client.request(
        "POST",
        "/api/v2/research/runs",
        {"specification": specification},
        idempotency_key=research_key,
        expected_status=202,
    )
    research_replay = client.request(
        "POST",
        "/api/v2/research/runs",
        {"specification": specification},
        idempotency_key=research_key,
        expected_status=202,
    )
    if research_submission["run"]["run_id"] != research_replay["run"]["run_id"]:
        raise AcceptanceFailure("Research idempotent replay created a second Run")
    research_run_id = research_submission["run"]["run_id"]
    research_run = _poll_run(
        client,
        f"/api/v2/research/runs/{research_run_id}",
        timeout_seconds=timeout_seconds,
    )
    result_ref = research_run.get("result_ref")
    if not isinstance(result_ref, str):
        raise AcceptanceFailure("Completed Research Run has no immutable result identity")
    research_evidence = client.request("GET", f"/api/v2/research/artifacts/{result_ref}")

    freeze_key = str(uuid.uuid4())
    frozen = client.request(
        "POST",
        "/api/v2/strategy-freezes",
        {
            "research_run_id": research_run_id,
            "candidate_fingerprint": candidate_fingerprint,
            "actor": "compose-acceptance-client",
            "comment": "A0 deterministic Product acceptance",
        },
        idempotency_key=freeze_key,
        expected_status=202,
    )
    strategy_fingerprint = frozen.get("strategy_fingerprint")
    if not isinstance(strategy_fingerprint, str):
        raise AcceptanceFailure("Freeze did not return Strategy identity")
    strategy = client.request("GET", f"/api/v2/strategies/{strategy_fingerprint}")
    current_stage = strategy.get("current_stage")
    if current_stage not in {"RESEARCH", "BACKTEST"}:
        raise AcceptanceFailure("Frozen Strategy is not admitted to RESEARCH or BACKTEST")
    relations = strategy.get("freeze_relation_fingerprints")
    if not isinstance(relations, list) or len(relations) != 1 or not isinstance(relations[0], str):
        raise AcceptanceFailure("Strategy Freeze relation is not unique")
    if current_stage == "RESEARCH":
        promotion = client.request(
            "POST",
            f"/api/v2/strategies/{strategy_fingerprint}/promotions",
            {
                "freeze_relation_fingerprint": relations[0],
                "reason": "A0 deterministic Product acceptance",
                "actor": "compose-acceptance-client",
            },
            idempotency_key=str(uuid.uuid4()),
            expected_status=202,
        )
        if promotion.get("decision") != "APPROVED" or promotion.get("to_stage") != "BACKTEST":
            raise AcceptanceFailure("Strategy Promotion was not approved for BACKTEST")

    backtest_request = dict(backtest_request)
    backtest_request["strategy_fingerprint"] = strategy_fingerprint
    backtest_key = str(uuid.uuid4())
    submitted = client.request(
        "POST",
        "/api/v2/backtest/runs",
        backtest_request,
        idempotency_key=backtest_key,
        expected_status=202,
    )
    replayed = client.request(
        "POST",
        "/api/v2/backtest/runs",
        backtest_request,
        idempotency_key=backtest_key,
        expected_status=202,
    )
    if submitted["backtest_run_id"] != replayed["backtest_run_id"]:
        raise AcceptanceFailure("Backtest idempotent replay created a second Run")
    conflicting = dict(backtest_request)
    account = dict(conflicting["initial_account"])
    account["capital"] = "999999.99" if account.get("capital") != "999999.99" else "999999.98"
    conflicting["initial_account"] = account
    client.request(
        "POST",
        "/api/v2/backtest/runs",
        conflicting,
        idempotency_key=backtest_key,
        expected_status=409,
    )

    backtest_run_id = submitted["backtest_run_id"]
    if os.environ.get("ONLYALPHA_ACCEPTANCE_PAUSE_AT_RUNNING") == "1":
        _wait_for_state(
            client,
            f"/api/v2/backtest/runs/{backtest_run_id}",
            "RUNNING",
            timeout_seconds=timeout_seconds,
        )
        return {
            "research_run_id": research_run_id,
            "strategy_fingerprint": strategy_fingerprint,
            "backtest_run_id": backtest_run_id,
            "result_fingerprint": "PENDING",
            "evidence_fingerprint": "PENDING",
        }
    backtest_run = _poll_run(
        client,
        f"/api/v2/backtest/runs/{backtest_run_id}",
        timeout_seconds=timeout_seconds,
    )
    backtest_evidence = client.request("GET", f"/api/v2/backtest/runs/{backtest_run_id}/evidence")
    manifest = backtest_evidence.get("manifest")
    if not isinstance(manifest, dict):
        raise AcceptanceFailure("Backtest Evidence manifest is absent")
    equalities = {
        "strategy_fingerprint": strategy_fingerprint,
        "specification_fingerprint": backtest_run.get("specification_fingerprint"),
        "admission_resolution_fingerprint": backtest_run.get("admission_resolution_fingerprint"),
        "result_fingerprint": backtest_run.get("result_fingerprint"),
        "base_dataset_snapshot_fingerprint": research_evidence.get("dataset_snapshot_fingerprint"),
    }
    for field, expected in equalities.items():
        if not isinstance(expected, str) or manifest.get(field) != expected:
            raise AcceptanceFailure(f"Backtest Evidence provenance mismatch: {field}")
    if os.environ.get("ONLYALPHA_ACCEPTANCE_EXPECT_FUNDING") == "1":
        result = client.request(
            "GET",
            f"/api/v2/backtest/runs/{backtest_run_id}/evidence/artifacts/result.json",
        )
        _require_applied_funding(result)
    return {
        "research_run_id": research_run_id,
        "strategy_fingerprint": strategy_fingerprint,
        "backtest_run_id": backtest_run_id,
        "result_fingerprint": str(backtest_run["result_fingerprint"]),
        "determinism_fingerprint": str(backtest_run["determinism_fingerprint"]),
        "evidence_fingerprint": str(manifest["evidence_fingerprint"]),
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True, separators=(",", ":")))

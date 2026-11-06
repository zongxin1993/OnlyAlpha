"""Exact native node PG guard evidence, never Shipping/READY acceptance."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest

from packages.backend.tests.postgres_link import wait_no_advisory_locks

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]


def call(probe: Path, **options: object) -> dict[str, Any]:
    result = subprocess.run(
        [str(probe)], input=json.dumps({"op": "node-authority", **options}), text=True, capture_output=True, timeout=25
    )
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def test_native_guard_and_existing_guard_exclude_other_physical_sessions(
    integration_http_probe: Path, postgres_dsn: str
) -> None:
    with subprocess.Popen(
        [str(integration_http_probe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as child:
        assert child.stdin is not None and child.stdout is not None and child.stderr is not None
        try:
            child.stdin.write(json.dumps({"op": "node-authority", "action": "hold"}) + "\n")
            child.stdin.flush()
            held = json.loads(child.stdout.readline())
            assert held["guard_held"] is True
            denied = call(integration_http_probe)
            assert denied["error"] == "PRODUCT_KERNEL_AUTHORITY_ALREADY_HELD"
            again = call(integration_http_probe)
            assert again["error"] == "PRODUCT_KERNEL_AUTHORITY_ALREADY_HELD"
            child.stdin.write("release\n")
            child.stdin.flush()
            child.stdin.close()
            final = json.loads(child.stdout.read())
            assert child.wait(timeout=20) == 0, child.stderr.read()
            assert final["closed"] is True
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=20)
    assert call(integration_http_probe)["closed"] is True
    # A second actual native process owns its original physical PG session.
    # The retired Python Guard API does not own a current compatibility promise.
    with subprocess.Popen(
        [str(integration_http_probe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as owner:
        assert owner.stdin is not None and owner.stdout is not None and owner.stderr is not None
        try:
            owner.stdin.write(json.dumps({"op": "node-authority", "action": "hold"}) + "\n")
            owner.stdin.flush()
            held = json.loads(owner.stdout.readline())
            assert held["guard_held"] is True
            assert call(integration_http_probe)["error"] == "PRODUCT_KERNEL_AUTHORITY_ALREADY_HELD"
            owner.stdin.write("release\n")
            owner.stdin.flush()
            owner.stdin.close()
            final = json.loads(owner.stdout.read())
            assert owner.wait(timeout=20) == 0, owner.stderr.read()
            assert final["closed"] is True
        finally:
            if owner.poll() is None:
                owner.terminate()
                owner.wait(timeout=20)
    wait_no_advisory_locks(postgres_dsn, held["backend_pid"])
    assert call(integration_http_probe)["closed"] is True


@pytest.mark.parametrize("preheld", ["two-key", "shared-two-key"])
def test_existing_same_session_lock_is_rejected_without_reentrant_acquisition(
    integration_http_probe: Path, postgres_dsn: str, preheld: str
) -> None:
    result = call(integration_http_probe, preheld=preheld)
    assert result["error"] == "PRODUCT_KERNEL_AUTHORITY_REENTRANT"
    wait_no_advisory_locks(postgres_dsn, result["backend_pid"])
    assert call(integration_http_probe)["closed"] is True


@pytest.mark.parametrize("options", [{"preheld": "single-key"}, {"shadow_catalog": True}])
def test_exact_family_and_catalog_ownership_are_independent_of_lookalikes(
    integration_http_probe: Path, postgres_dsn: str, options: dict[str, object]
) -> None:
    result = call(integration_http_probe, **options)
    assert result["closed"] is True
    wait_no_advisory_locks(postgres_dsn, result["backend_pid"])


@pytest.mark.parametrize("action", ["replace-one-key", "abort-driver"])
def test_lost_session_or_wrong_family_cannot_recover_the_original_capability(
    integration_http_probe: Path, postgres_dsn: str, action: str
) -> None:
    result = call(integration_http_probe, action=action)
    assert result["error"] in {"PRODUCT_KERNEL_AUTHORITY_LOST", "PRODUCT_KERNEL_AUTHORITY_UNAVAILABLE"}
    assert result["second_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
    wait_no_advisory_locks(postgres_dsn, result["backend_pid"])
    assert call(integration_http_probe)["closed"] is True


def test_release_does_not_claim_success_after_a_hidden_reentrant_count(
    integration_http_probe: Path, postgres_dsn: str
) -> None:
    result = call(integration_http_probe, action="repeat-held")
    assert result["error"] == "PRODUCT_KERNEL_AUTHORITY_RELEASE_FAILED"
    wait_no_advisory_locks(postgres_dsn, result["backend_pid"])
    assert call(integration_http_probe)["closed"] is True


def test_drop_closes_owned_session_without_certifying_graceful_drain(
    integration_http_probe: Path, postgres_dsn: str
) -> None:
    result = call(integration_http_probe, action="drop")
    assert result["dropped"] is True and "closed" not in result
    wait_no_advisory_locks(postgres_dsn, result["backend_pid"])
    assert call(integration_http_probe)["closed"] is True


def test_server_termination_closes_guard_without_reconnect_or_success_claim(
    integration_http_probe: Path, postgres_dsn: str
) -> None:
    with subprocess.Popen(
        [str(integration_http_probe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as child:
        assert child.stdin is not None and child.stdout is not None and child.stderr is not None
        try:
            child.stdin.write(json.dumps({"op": "node-authority", "action": "hold"}) + "\n")
            child.stdin.flush()
            held = json.loads(child.stdout.readline())
            assert held["guard_held"] is True
            with psycopg.connect(postgres_dsn, autocommit=True) as observer:
                assert observer.execute(
                    "SELECT pg_catalog.pg_terminate_backend(%s)", (held["backend_pid"],)
                ).fetchone() == (True,)
            wait_no_advisory_locks(postgres_dsn, held["backend_pid"])
            child.stdin.write("release\n")
            child.stdin.flush()
            child.stdin.close()
            final = json.loads(child.stdout.read())
            assert child.wait(timeout=20) == 0, child.stderr.read()
            assert final["error"] in {"PRODUCT_KERNEL_AUTHORITY_LOST", "PRODUCT_KERNEL_AUTHORITY_UNAVAILABLE"}
            assert "closed" not in final
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=20)
    assert call(integration_http_probe)["closed"] is True


def test_cancelled_verification_irreversibly_revokes_the_original_session(
    integration_http_probe: Path, postgres_dsn: str
) -> None:
    result = call(integration_http_probe, action="cancel-verify")
    assert result["cancelled"] is True
    assert result["error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
    wait_no_advisory_locks(postgres_dsn, result["backend_pid"])
    assert call(integration_http_probe)["closed"] is True


def test_cancelled_close_stops_the_owned_pending_driver(integration_http_probe: Path, postgres_dsn: str) -> None:
    result = call(integration_http_probe, action="cancel-close")
    assert result["cancelled"] is True and result["driver_stopped"] is True
    assert "closed" not in result
    wait_no_advisory_locks(postgres_dsn, result["backend_pid"])
    assert call(integration_http_probe)["closed"] is True

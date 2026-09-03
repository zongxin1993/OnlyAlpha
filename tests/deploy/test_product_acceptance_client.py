from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _module():  # type: ignore[no-untyped-def]
    path = Path(__file__).parents[2] / "deploy/compose/product_acceptance_client.py"
    spec = importlib.util.spec_from_file_location("onlyalpha_product_acceptance_client", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("current_stage", ["RESEARCH", "BACKTEST"])
def test_http_only_client_executes_complete_product_chain_and_conflict_probe(  # type: ignore[no-untyped-def]
    monkeypatch, current_stage
) -> None:
    module = _module()
    calls: list[tuple[str, str, int]] = []
    fingerprint = "a" * 64
    dataset = "b" * 64
    specification = "c" * 64
    admission = "d" * 64
    result = "e" * 64

    class FakeClient:
        def __init__(self, base_url: str) -> None:
            assert base_url == "http://product.test"

        def request(self, method, path, payload=None, *, idempotency_key=None, expected_status=200):  # type: ignore[no-untyped-def]
            calls.append((method, path, expected_status))
            if path.startswith("/health/"):
                return {"status": "READY"}
            if path.endswith("/definitions/resolve"):
                return {
                    "candidates": [{"candidate_fingerprint": fingerprint}],
                    "exact_specification": {"schema_version": 2},
                }
            if path == "/api/v2/research/runs":
                return {"run": {"run_id": "research-run"}}
            if path == "/api/v2/research/runs/research-run":
                return {"state": "COMPLETED", "result_ref": "research-result"}
            if path == "/api/v2/research/artifacts/research-result":
                return {"dataset_snapshot_fingerprint": dataset}
            if path == "/api/v2/strategy-freezes":
                return {"strategy_fingerprint": fingerprint}
            if path == f"/api/v2/strategies/{fingerprint}":
                return {"current_stage": current_stage, "freeze_relation_fingerprints": ["relation"]}
            if path.endswith("/promotions"):
                return {"decision": "APPROVED", "to_stage": "BACKTEST"}
            if path == "/api/v2/backtest/runs":
                if expected_status == 409:
                    return {"error": {"code": "BACKTEST_COMMAND_CONFLICT"}}
                return {"backtest_run_id": "backtest-run"}
            if path == "/api/v2/backtest/runs/backtest-run":
                return {
                    "state": "COMPLETED",
                    "specification_fingerprint": specification,
                    "admission_resolution_fingerprint": admission,
                    "result_fingerprint": result,
                    "determinism_fingerprint": "9" * 64,
                }
            if path == "/api/v2/backtest/runs/backtest-run/evidence":
                return {
                    "manifest": {
                        "strategy_fingerprint": fingerprint,
                        "specification_fingerprint": specification,
                        "admission_resolution_fingerprint": admission,
                        "result_fingerprint": result,
                        "base_dataset_snapshot_fingerprint": dataset,
                        "evidence_fingerprint": "f" * 64,
                    }
                }
            raise AssertionError((method, path, payload, idempotency_key, expected_status))

    monkeypatch.setattr(module, "ProductHttpClient", FakeClient)
    monkeypatch.setenv("ONLYALPHA_PRODUCT_API_URL", "http://product.test")
    monkeypatch.setenv("ONLYALPHA_ACCEPTANCE_DEFINITION_JSON", '{"schema_version":2}')
    monkeypatch.setenv(
        "ONLYALPHA_ACCEPTANCE_BACKTEST_JSON",
        '{"initial_account":{"capital":"1000.00"}}',
    )

    outcome = module.run()

    assert outcome == {
        "research_run_id": "research-run",
        "strategy_fingerprint": fingerprint,
        "backtest_run_id": "backtest-run",
        "result_fingerprint": result,
        "determinism_fingerprint": "9" * 64,
        "evidence_fingerprint": "f" * 64,
    }
    assert ("POST", "/api/v2/backtest/runs", 409) in calls
    assert calls.count(("POST", "/api/v2/research/runs", 202)) == 2
    assert calls.count(("POST", "/api/v2/backtest/runs", 202)) == 2
    assert calls.count(("POST", f"/api/v2/strategies/{fingerprint}/promotions", 202)) == (
        1 if current_stage == "RESEARCH" else 0
    )


def test_usdm_acceptance_requires_a_nonzero_applied_funding_cashflow() -> None:
    module = _module()
    result = {
        "final_ledgers": [
            {
                "cash_entries": [
                    {
                        "entry_type": "FUNDING",
                        "amount": {"amount": "-0.12500000", "currency": {"code": "USDT", "precision": 8}},
                        "cash_flow_id": "funding:btc:1704096000000000000",
                    }
                ]
            }
        ]
    }

    module._require_applied_funding(result)
    result["final_ledgers"][0]["cash_entries"][0]["amount"]["amount"] = "0"
    with pytest.raises(module.AcceptanceFailure, match="non-zero applied funding"):
        module._require_applied_funding(result)

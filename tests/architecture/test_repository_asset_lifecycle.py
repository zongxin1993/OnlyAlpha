from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture
ROOT = Path(__file__).parents[2]


SEMANTIC_SUCCESSORS = {
    "tests/architecture/test_a0_product_vertical_boundaries.py": "tests/architecture/test_backtest_product_boundary.py",
    "tests/architecture/test_p9_k0_api_core_crossings.py": "tests/architecture/test_api_core_crossings.py",
    "tests/architecture/test_p9_k0_authority_contract.py": "tests/architecture/test_product_authority_contract.py",
    "tests/architecture/test_p9_k0_authority_ownership.py": "tests/architecture/test_authority_ownership.py",
    "tests/architecture/test_p9_k0_capability_reachability.py": "tests/architecture/test_capability_reachability.py",
    "tests/architecture/test_p9_k0_composition_ownership.py": "tests/architecture/test_composition_ownership.py",
    "tests/architecture/test_p9_k0_transport_boundary.py": "tests/architecture/test_transport_boundary.py",
    "tests/architecture/test_p9_k3_product_http_control_plane.py": "tests/architecture/test_product_http_control_plane.py",
    "tests/architecture/test_p9_k5_recovery_closure.py": "tests/architecture/test_kernel_recovery_authority.py",
    "tests/architecture/test_p9_k6_external_client_boundary.py": "tests/architecture/test_product_surface_retirement.py",
    "tests/architecture/test_p9_k7_remote_protocol_boundary.py": "tests/architecture/test_gateway_protocol_boundary.py",
    "tests/architecture/test_p9_k8_kernel_seal.py": "tests/architecture/test_product_authority_seal.py",
    "docs/p9_k7_remote_gateway_protocol.md": "docs/gateway_protocol.md",
}

PROCESS_SNAPSHOT_SUCCESSORS = {
    "docs/account_broker_component_analysis.md": (
        "docs/account.md",
        "docs/broker_gateway.md",
        "docs/virtual_broker.md",
    ),
    "docs/clock_analysis.md": ("docs/clock.md",),
    "docs/domain_analysis.md": ("docs/domain_model.md",),
    "docs/event_component_analysis.md": ("docs/event.md", "docs/market_data_pipeline.md"),
    "docs/execution_processor_component_analysis.md": ("docs/execution_processor.md",),
    "docs/market_data_source_component_analysis.md": ("docs/market_data_source.md",),
    "docs/order_component_analysis.md": ("docs/order.md",),
    "docs/position_component_analysis.md": ("docs/position.md",),
    "docs/risk_component_analysis.md": ("docs/risk.md",),
    "docs/runtime_context_analysis.md": ("docs/runtime_context.md",),
    "docs/strategy_ledger_component_analysis.md": ("docs/strategy_ledger.md",),
    "docs/time_model_analysis.md": ("docs/time_model.md",),
    "docs/integration_vertical_slice.md": ("docs/testing.md",),
    "docs/nautilus_research.md": (
        "docs/engineering/reference_registry.md",
        "docs/engineering/open_source_engineering_evidence.md",
        "docs/domain_model.md",
    ),
}


def test_retired_phase_coupled_assets_have_semantic_successors() -> None:
    for retired, successor in SEMANTIC_SUCCESSORS.items():
        assert not (ROOT / retired).exists(), retired
        assert (ROOT / successor).is_file(), successor


def test_process_snapshots_are_replaced_by_current_domain_documents() -> None:
    for retired, successors in PROCESS_SNAPSHOT_SUCCESSORS.items():
        assert not (ROOT / retired).exists(), retired
        for successor in successors:
            assert (ROOT / successor).is_file(), successor


def test_one_time_replay_audit_is_not_versioned_as_current_documentation() -> None:
    assert not (ROOT / "docs/replay_contract_correctness_audit.md").exists()

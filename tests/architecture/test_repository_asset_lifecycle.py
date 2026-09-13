from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture
ROOT = Path(__file__).parents[2]


SEMANTIC_SUCCESSORS = {
    "tests/architecture/test_a0_product_vertical_boundaries.py": "tests/architecture/test_backtest_product_boundary.py",
    "tests/architecture/test_p9_k3_product_http_control_plane.py": "tests/architecture/test_product_http_control_plane.py",
    "tests/architecture/test_p9_k5_recovery_closure.py": "tests/architecture/test_kernel_recovery_authority.py",
    "tests/architecture/test_p9_k6_external_client_boundary.py": "tests/architecture/test_product_surface_retirement.py",
    "tests/architecture/test_p9_k7_remote_protocol_boundary.py": "tests/architecture/test_gateway_protocol_boundary.py",
    "tests/architecture/test_p9_k8_kernel_seal.py": "tests/architecture/test_product_authority_seal.py",
    "docs/p9_k7_remote_gateway_protocol.md": "docs/gateway_protocol.md",
}


def test_retired_phase_coupled_assets_have_semantic_successors() -> None:
    for retired, successor in SEMANTIC_SUCCESSORS.items():
        assert not (ROOT / retired).exists(), retired
        assert (ROOT / successor).is_file(), successor


def test_one_time_replay_audit_is_not_versioned_as_current_documentation() -> None:
    assert not (ROOT / "docs/replay_contract_correctness_audit.md").exists()

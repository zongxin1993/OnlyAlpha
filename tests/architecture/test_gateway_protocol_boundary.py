from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

from scripts import gateway_protocol

ROOT = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _python_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts))


@pytest.mark.architecture
def test_core_business_modules_have_zero_gateway_transport_dependency() -> None:
    forbidden = ("grpc", "google.protobuf", "onlyalpha_gateway_protocol")
    roots = (ROOT / "src/onlyalpha",)
    offenders = {
        str(path.relative_to(ROOT)): sorted(
            item for item in _imports(path) if item == forbidden or item.startswith(forbidden)
        )
        for root in roots
        for path in _python_files(root)
        if any(item == forbidden or item.startswith(forbidden) for item in _imports(path))
    }
    assert offenders == {}


@pytest.mark.architecture
def test_protocol_package_is_independent_of_core_product_and_api_packages() -> None:
    package = ROOT / "packages/onlyalpha-gateway-protocol"
    metadata = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = metadata["project"]["dependencies"]
    assert all(
        not item.startswith(("onlyalpha==", "onlyalpha-http-server", "onlyalpha-client")) for item in dependencies
    )
    forbidden = ("onlyalpha", "onlyalpha_http_server", "onlyalpha_client")
    offenders = {
        str(path.relative_to(ROOT)): sorted(
            item
            for item in _imports(path)
            if item in forbidden or item.startswith(tuple(f"{name}." for name in forbidden))
        )
        for path in _python_files(package / "src")
        if any(item in forbidden or item.startswith(tuple(f"{name}." for name in forbidden)) for item in _imports(path))
    }
    assert offenders == {}


@pytest.mark.architecture
def test_test_gateway_is_fixture_infrastructure_not_product_authority() -> None:
    path = ROOT / "tests/fixtures/remote_gateway/server.py"
    imports = _imports(path)
    forbidden = (
        "onlyalpha.application",
        "onlyalpha.kernel",
        "onlyalpha.portfolio",
        "onlyalpha.research",
        "onlyalpha.risk",
        "onlyalpha.strategy",
    )
    assert not any(item == forbidden or item.startswith(forbidden) for item in imports)
    assert "TEST ONLY" in path.read_text(encoding="utf-8")


@pytest.mark.architecture
def test_product_api_and_external_client_do_not_bypass_kernel_to_gateway_rpc() -> None:
    roots = (ROOT / "packages/onlyalpha-http-server/src",)
    forbidden = ("grpc", "onlyalpha_gateway_protocol")
    assert {
        str(path.relative_to(ROOT))
        for root in roots
        for path in _python_files(root)
        if any(item == forbidden or item.startswith(forbidden) for item in _imports(path))
    } == set()


@pytest.mark.architecture
def test_gateway_v1_proto_authority_is_unique_and_provider_neutral() -> None:
    sources = gateway_protocol.canonical_sources()
    assert sources == gateway_protocol.EXPECTED_SOURCES
    all_proto = tuple(
        sorted(
            path.relative_to(ROOT)
            for search_root in (ROOT / "contracts", ROOT / "packages", ROOT / "src", ROOT / "tests")
            for path in search_root.rglob("*.proto")
        )
    )
    assert all_proto == tuple(ROOT.joinpath("contracts/gateway/v1", path).relative_to(ROOT) for path in sources)
    combined = "\n".join(
        (gateway_protocol.CONTRACT_ROOT / path).read_text(encoding="utf-8") for path in sources
    ).lower()
    for forbidden in ("xtquant", "miniqmt", "ctp", "submitorder", "cancelorder"):
        assert forbidden not in combined


@pytest.mark.architecture
def test_generated_gateway_projection_is_fresh() -> None:
    assert gateway_protocol.check() == "5cb5005475e24019669a8658a5189b9d6321488f3e3c675bdc0195b826dfd67e"

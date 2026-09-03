"""Prove stable HTTP/Core invariants without snapshotting ordinary DTO imports."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.architecture._p9_k0_authority_contract import load_authority_contract
from tests.architecture._p9_k0_guard_helpers import CanonicalImport, onlyalpha_imports, onlyalpha_imports_for_path

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
API_ROOT = ROOT / "packages/onlyalpha-http-server/src/onlyalpha_http_server"
CONTRACT = load_authority_contract(ROOT / "docs/architecture/p9_k0_authority_contract.toml")

PRIVILEGED_TRANSPORT_MODULES = (
    "onlyalpha.application.strategy_authority",
    "onlyalpha.engine",
    "onlyalpha.persistence",
    "onlyalpha.research.execution",
    "onlyalpha.runtime",
    "onlyalpha.strategy.store",
)
PRIVILEGED_TRANSPORT_SYMBOLS = {
    "OnlyEngine",
    "OnlyLiveRuntime",
    "OnlyPostgresMigrationAuthority",
    "OnlyStrategyFreezeApplicationService",
    "OnlyStrategyPromotionApplicationService",
    "OnlyStrategyFreezeService",
    "OnlyStrategyPromotionService",
}


def _api_core_crossings(root: Path) -> dict[str, frozenset[CanonicalImport]]:
    return {
        path.relative_to(root).as_posix(): imports
        for path in sorted(root.rglob("*.py"))
        if (imports := onlyalpha_imports_for_path(path, ROOT))
    }


def _privileged_transport_imports(imports: frozenset[CanonicalImport]) -> frozenset[CanonicalImport]:
    return frozenset(
        item
        for item in imports
        if any(item[1] == module or item[1].startswith(f"{module}.") for module in PRIVILEGED_TRANSPORT_MODULES)
        or (len(item) == 3 and item[2] in PRIVILEGED_TRANSPORT_SYMBOLS)
    )


def test_http_modules_are_classified_by_the_machine_readable_contract() -> None:
    for path in API_ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if CONTRACT.is_sensitive_path(relative):
            assert CONTRACT.classify_path(relative).name in {"HTTP_COMPOSITION_ROOT", "HTTP_TRANSPORT_ADAPTER"}


def test_transport_modules_cannot_obtain_persistence_engine_runtime_or_strategy_mutation() -> None:
    for relative, imports in _api_core_crossings(API_ROOT).items():
        repository_path = f"packages/onlyalpha-http-server/src/onlyalpha_http_server/{relative}"
        if CONTRACT.is_sensitive_path(repository_path) and CONTRACT.classify_path(repository_path).name == (
            "HTTP_TRANSPORT_ADAPTER"
        ):
            assert not _privileged_transport_imports(imports), relative


@pytest.mark.parametrize(
    "source",
    (
        "from onlyalpha.engine import OnlyEngine\n",
        "from onlyalpha.persistence.postgres.backtest_store import OnlyPostgresBacktestStore\n",
        "from onlyalpha.application.strategy_authority import OnlyStrategyPromotionApplicationService\n",
        "import onlyalpha.runtime.live\n",
    ),
)
def test_any_transport_filename_is_rejected_when_it_imports_privileged_authority(source: str) -> None:
    assert _privileged_transport_imports(onlyalpha_imports(source))


def test_http_composition_root_does_not_construct_engine() -> None:
    source = (API_ROOT / "main.py").read_text(encoding="utf-8")
    assert "OnlyEngine(" not in source
    assert "OnlyStrategyPromotionService(" not in source

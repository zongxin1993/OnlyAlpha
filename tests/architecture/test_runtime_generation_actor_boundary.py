"""Generation ports cannot acquire a concrete Backtest execution capability."""

from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from tests.architecture._capability_reachability import ModuleIndex
from tests.architecture._product_authority_contract import load_authority_contract

if TYPE_CHECKING:
    from onlyalpha.backtest.model import OnlyBacktestRun
    from onlyalpha.backtest.worker import OnlyBacktestRuntimeComposition

pytestmark = pytest.mark.architecture
ROOT = Path(__file__).resolve().parents[2]


def test_generic_generation_port_has_no_trading_capability() -> None:
    contract = load_authority_contract(ROOT / "docs/architecture/product_authority_contract.toml")
    path = ROOT / "src/onlyalpha/application/runtime_generation.py"
    assert ModuleIndex(ROOT).capabilities_for_file(path, contract) == frozenset()


def test_no_claim_backtest_composition_can_start_but_never_execute() -> None:
    from onlyalpha.backtest.runtime_generation import OnlyNoClaimBacktestRuntimeGenerationWorkAuthority

    authority = OnlyNoClaimBacktestRuntimeGenerationWorkAuthority()
    assert authority.work_ids_for_generation("a" * 64) == ()
    executor = authority.backtest_executor(cast("OnlyBacktestRuntimeComposition", object()))
    with pytest.raises(RuntimeError, match="RUNTIME_GENERATION_WORK_AUTHORITY_UNAVAILABLE"):
        executor.execute(cast("OnlyBacktestRun", object()), lambda: "CONTINUE")


def test_backtest_composition_rejects_an_incomplete_generation_port() -> None:
    from onlyalpha.application.runtime_generation import OnlyNoClaimRuntimeGenerationWorkAuthority
    from onlyalpha.backtest.runtime_generation import only_require_backtest_runtime_generation_work_authority

    with pytest.raises(RuntimeError, match="BACKTEST_RUNTIME_GENERATION_WORK_AUTHORITY_INVALID"):
        only_require_backtest_runtime_generation_work_authority(OnlyNoClaimRuntimeGenerationWorkAuthority())

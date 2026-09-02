from datetime import UTC, datetime

import pytest

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.backtest import (
    OnlyBacktestCommandService,
    OnlyBacktestProfileReference,
    OnlyBacktestSpecification,
    OnlyInMemoryBacktestCommandStore,
)
from onlyalpha.backtest.errors import OnlyBacktestError


class _Admission:
    def resolve(self, specification):  # type: ignore[no-untyped-def]
        from onlyalpha.backtest import OnlyBacktestAdmissionResolution

        return OnlyBacktestAdmissionResolution(
            1,
            specification.strategy_fingerprint,
            specification.dataset_binding_fingerprint,
            "1" * 64,
            specification.market_product_configuration_fingerprint,
            "2" * 64,
            "3" * 64,
            "4" * 64,
            "kernel-v1",
            (),
        )


def _spec() -> OnlyBacktestSpecification:
    ref = OnlyBacktestProfileReference("x", "1")
    return OnlyBacktestSpecification("a" * 64, "b" * 64, "c" * 64, ref, ref, ref, "USDT", "1")


def test_create_retry_converges_and_different_intent_fails() -> None:
    store = OnlyInMemoryBacktestCommandStore()
    service = OnlyBacktestCommandService(admission=_Admission(), store=store, now_utc=lambda: datetime.now(UTC))
    command_id = OnlyProductCommandId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    first = service.submit(command_id, _spec())
    second = service.submit(command_id, _spec())
    assert first.run.run_id == second.run.run_id
    changed = _spec()
    object.__setattr__(changed, "base_currency", "BTC")
    with pytest.raises(OnlyBacktestError, match="PRODUCT_COMMAND_CONFLICT"):
        service.submit(command_id, changed)

from __future__ import annotations

from pathlib import Path

import pytest

from onlyalpha.application.chart_calculation import only_normalize_chart_calculation
from onlyalpha.application.chart_calculation_preparation import only_chart_materialization_support
from onlyalpha.domain.market import OnlyBarSemantic
from onlyalpha.market_data.resolution import OnlyBarResolutionMode
from tests.application.test_chart_calculation_admission import NOW, D, request, witness
from tests.application.test_market_data_product import INSTRUMENT, _range, _reference, _service


@pytest.mark.parametrize("period", [1, 20])
def test_materialization_support_includes_exact_warmup(period: int) -> None:
    intent = only_normalize_chart_calculation(request({"period": period}), witness(), NOW)
    assert only_chart_materialization_support(intent) == (D * (20000 - period + 1), D * 20010)


def test_selection_only_plan_never_opens_provider_or_wal(tmp_path: Path) -> None:
    harness = _service(tmp_path, native_minutes=(1, 15))
    start, end = _range(60)
    selection = harness.service.plan_selection(
        _reference(harness.revision_fingerprint),
        instrument_id=str(INSTRUMENT),
        start_ns=start,
        end_ns=end,
        bar_semantic=OnlyBarSemantic.fixed_duration(15),
    )
    assert selection.scope.start_ns == start and selection.scope.end_ns == end
    assert selection.scope.bar_construction.plan.mode is OnlyBarResolutionMode.PROVIDER_NATIVE
    assert selection.source_selection.integration_revision_fingerprint == harness.revision_fingerprint
    assert harness.provider.bar_fetches == 0 and harness.catalog.mutations == 0
    assert harness.provider.sessions == harness.provider.reference_lookups == 0
    assert not harness.wal_root.exists()


def test_selection_only_rejects_derived_fifteen_minute(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    start, end = _range(60)
    with pytest.raises(RuntimeError, match="MARKET_DATA_NATIVE_SELECTION_REQUIRED"):
        harness.service.plan_selection(
            _reference(harness.revision_fingerprint),
            instrument_id=str(INSTRUMENT),
            start_ns=start,
            end_ns=end,
            bar_semantic=OnlyBarSemantic.fixed_duration(15),
        )


def test_preparation_exposes_explicit_input_selection_reference() -> None:
    from onlyalpha.application.chart_calculation_preparation import OnlyChartCalculationPreparationV1
    from onlyalpha.application.product_command_receipt import OnlyProductCommandId

    value = OnlyChartCalculationPreparationV1(
        OnlyProductCommandId("00000000-0000-4000-8000-000000000731"),
        1,
        1,
        OnlyProductCommandId("00000000-0000-4000-8000-000000000732"),
        NOW,
        "a" * 64,
        "00000000-0000-4000-8000-000000000733",
    )
    assert value.input_selection_fingerprint is None


def test_incompatible_generation_is_rejected_before_preparation_claim() -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock

    from onlyalpha.application.chart_calculation import OnlyChartCalculationOperationV1
    from onlyalpha.application.chart_calculation_preparation import (
        OnlyChartCalculationPreparationService,
        OnlyChartCalculationPreparationV1,
    )
    from onlyalpha.application.product_command_receipt import OnlyProductCommandId
    from onlyalpha.research.run.model import OnlyResearchRunId

    intent = only_normalize_chart_calculation(request(), witness(), NOW)
    command = OnlyProductCommandId("00000000-0000-4000-8000-000000000741")
    work = OnlyResearchRunId("00000000-0000-4000-8000-000000000742")
    operation = OnlyChartCalculationOperationV1(
        command, command, intent.command_fingerprint, intent.intent_fingerprint, intent, witness(), work, NOW
    )
    store = Mock()
    store.load_verified.return_value = None
    store.claim.return_value = OnlyChartCalculationPreparationV1(command, 1, 1, command, NOW, "b" * 64, work.value)
    runtime = Mock()
    runtime.require_work_binding.side_effect = ValueError("RUNTIME_WORK_GENERATION_UNBOUND")
    runtime.require_runtime_generation.return_value = SimpleNamespace(
        runtime_generation_fingerprint="b" * 64, catalog_generation_fingerprint="f" * 64
    )
    runtime.require_new_work_generation.return_value = runtime.require_runtime_generation.return_value
    service = OnlyChartCalculationPreparationService(
        store=store, runtime_generations=runtime, market_data=Mock(), catalog=Mock(), facts=Mock(), materializer=Mock()
    )
    with pytest.raises(ValueError, match="CHART_EXECUTION_GENERATION_UNAVAILABLE"):
        service.prepare(operation, worker_id=command, runtime_generation_fingerprint="b" * 64, occurred_at=NOW)
    store.claim.assert_not_called()


def test_no_claim_runtime_authority_rejects_atomic_exact_admission() -> None:
    from onlyalpha.application.runtime_generation import OnlyNoClaimRuntimeGenerationWorkAuthority

    with pytest.raises(RuntimeError, match="RUNTIME_GENERATION_WORK_AUTHORITY_UNAVAILABLE"):
        OnlyNoClaimRuntimeGenerationWorkAuthority().bind_new_work_exact(
            "chart", "b" * 64, actor="chart", occurred_at=NOW
        )

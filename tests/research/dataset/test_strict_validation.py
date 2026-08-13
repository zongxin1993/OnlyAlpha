from dataclasses import replace
from datetime import timedelta

import pytest

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyAggregationSource
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
from onlyalpha.research.dataset.strict import (
    require_bool,
    require_exact_fields,
    require_int,
    require_list,
    require_mapping,
    require_optional_str,
    require_sha256,
    require_str,
    require_utc_datetime,
)
from onlyalpha.research.dataset.validation import OnlyResearchDatasetError, only_validate_dataset_bars
from tests.domain_conformance.support.market_data import build_bar


def _definition() -> OnlyResearchDatasetDefinition:
    bar = build_bar()
    return OnlyResearchDatasetDefinition(
        (bar.instrument_id,),
        bar.bar_type.specification,
        bar.bar_type.aggregation_source,
        OnlyTimeRange(bar.bar_start, bar.ts_event + timedelta(seconds=1)),
    )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda bar: replace(bar, bar_type=replace(bar.bar_type, instrument_id=OnlyInstrumentId.parse("OTHER.XSHG"))),
        lambda bar: replace(
            bar, bar_type=replace(bar.bar_type, specification=replace(bar.bar_type.specification, step=5))
        ),
        lambda bar: replace(bar, bar_type=replace(bar.bar_type, aggregation_source=OnlyAggregationSource.INTERNAL)),
        lambda bar: replace(bar, adjustment_type=OnlyAdjustmentType.FORWARD),
        lambda bar: replace(bar, is_closed=False),
        lambda bar: replace(
            bar,
            bar_start=bar.bar_start - timedelta(days=2),
            bar_end=bar.bar_end - timedelta(days=2),
            ts_event=bar.ts_event - timedelta(days=2),
            ts_init=bar.ts_init - timedelta(days=2),
        ),
    ),
)
def test_dataset_validation_fails_closed_for_out_of_contract_rows(mutation) -> None:
    with pytest.raises(OnlyResearchDatasetError, match="DATASET_INPUT_INVALID"):
        only_validate_dataset_bars(_definition(), (mutation(build_bar()),))


def test_dataset_validation_rejects_duplicate_and_conflicting_logical_bar() -> None:
    bar = build_bar()
    with pytest.raises(OnlyResearchDatasetError, match="duplicate logical Bar"):
        only_validate_dataset_bars(_definition(), (bar, bar))
    with pytest.raises(OnlyResearchDatasetError, match="conflicting duplicate"):
        only_validate_dataset_bars(_definition(), (bar, replace(bar, revision=1)))


def test_definition_reader_rejects_wrong_scalar_types_versions_and_duplicates() -> None:
    payload = _definition().to_dict()
    for field, value in (("closed_only", 1), ("schema_version", True), ("dataset_type", "OTHER")):
        changed = dict(payload)
        changed[field] = value
        with pytest.raises((ValueError, TypeError)):
            OnlyResearchDatasetDefinition.from_dict(changed)
    duplicate = dict(payload)
    duplicate["instruments"] = [str(build_bar().instrument_id)] * 2
    with pytest.raises(ValueError, match="unique"):
        OnlyResearchDatasetDefinition.from_dict(duplicate)
    unknown = dict(payload)
    unknown["unknown"] = None
    with pytest.raises(ValueError, match="unknown"):
        OnlyResearchDatasetDefinition.from_dict(unknown)


def test_strict_primitives_reject_coercion_and_invalid_utc_sha_shapes() -> None:
    with pytest.raises(ValueError):
        require_exact_fields({"a": 1}, {"b"}, "value")
    for call in (
        lambda: require_str({"x": 1}, "x", "value"),
        lambda: require_optional_str({"x": 1}, "x", "value"),
        lambda: require_int({"x": True}, "x", "value"),
        lambda: require_bool({"x": 1}, "x", "value"),
        lambda: require_mapping([], "value"),
        lambda: require_list({}, "value"),
        lambda: require_sha256({"x": "not-a-sha"}, "x", "value"),
        lambda: require_utc_datetime({"x": "2026-01-01T00:00:00"}, "x", "value"),
        lambda: require_utc_datetime({"x": "invalid"}, "x", "value"),
    ):
        with pytest.raises(ValueError):
            call()

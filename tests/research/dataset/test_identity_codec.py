import os
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyAggregationSource
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.value import OnlyPrice
from onlyalpha.research.dataset.codec import only_bars_to_table, only_table_to_bars
from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
from onlyalpha.research.dataset.identity import only_content_fingerprint, only_snapshot_fingerprint
from onlyalpha.research.dataset.schema import RESEARCH_BAR_DATASET_SCHEMA_V1
from tests.domain_conformance.support.market_data import build_bar


def _definition(*instruments: OnlyInstrumentId) -> OnlyResearchDatasetDefinition:
    bar = build_bar()
    return OnlyResearchDatasetDefinition(
        instruments or (bar.instrument_id,),
        bar.bar_type.specification,
        OnlyAggregationSource.EXTERNAL,
        OnlyTimeRange(bar.bar_start, bar.ts_event + timedelta(seconds=1)),
    )


def test_definition_identity_is_order_independent_and_semantic() -> None:
    one = build_bar().instrument_id
    two = OnlyInstrumentId.parse("000001.XSHE")
    assert _definition(one, two).fingerprint == _definition(two, one).fingerprint
    assert _definition(one).fingerprint != _definition(two).fingerprint
    assert (
        replace(_definition(one), adjustment_type=OnlyAdjustmentType.FORWARD).fingerprint
        != _definition(one).fingerprint
    )


def test_content_identity_is_order_independent_and_preserves_semantics() -> None:
    bar = build_bar()
    later = replace(
        bar,
        bar_start=bar.bar_start + timedelta(minutes=1),
        bar_end=bar.bar_end + timedelta(minutes=1),
        ts_event=bar.ts_event + timedelta(minutes=1),
        ts_init=bar.ts_init + timedelta(minutes=1),
    )
    assert only_content_fingerprint((bar, later)) == only_content_fingerprint((later, bar))
    changed = replace(bar, close=OnlyPrice(Decimal("10.06"), 2))
    assert only_content_fingerprint((bar,)) != only_content_fingerprint((changed,))
    precision = replace(
        bar,
        close=OnlyPrice(Decimal("10.050"), 3),
        open=OnlyPrice(Decimal("10.000"), 3),
        high=OnlyPrice(Decimal("10.100"), 3),
        low=OnlyPrice(Decimal("9.900"), 3),
    )
    assert only_content_fingerprint((bar,)) != only_content_fingerprint((precision,))


def test_only_bar_arrow_parquet_round_trip_is_exact(tmp_path) -> None:
    bar = build_bar()
    path = tmp_path / "bars.parquet"
    pq.write_table(only_bars_to_table((bar,)), path)
    assert only_table_to_bars(pq.read_table(path)) == (bar,)


def test_empty_snapshot_identity_includes_definition() -> None:
    first = _definition(build_bar().instrument_id)
    second = _definition(OnlyInstrumentId.parse("000001.XSHE"))
    content = only_content_fingerprint(())
    assert only_snapshot_fingerprint(first, RESEARCH_BAR_DATASET_SCHEMA_V1, content, 0) != only_snapshot_fingerprint(
        second, RESEARCH_BAR_DATASET_SCHEMA_V1, content, 0
    )


def test_fingerprints_are_stable_in_a_fresh_process() -> None:
    expected = [_definition(build_bar().instrument_id).fingerprint, only_content_fingerprint((build_bar(),))]
    code = """
from datetime import timedelta
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
from onlyalpha.research.dataset.identity import only_content_fingerprint
from tests.domain_conformance.support.market_data import build_bar
bar = build_bar()
definition = OnlyResearchDatasetDefinition((bar.instrument_id,), bar.bar_type.specification, bar.bar_type.aggregation_source, OnlyTimeRange(bar.bar_start, bar.ts_event + timedelta(seconds=1)))
print(definition.fingerprint)
print(only_content_fingerprint((bar,)))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())
    assert subprocess.check_output([sys.executable, "-c", code], text=True, env=env).splitlines() == expected

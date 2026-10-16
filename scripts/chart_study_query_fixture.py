"""Regenerate the synthetic cross-language Chart Query mutation vector.

This uses the installed SPI and owning test service, not a production admission
or real venue certification. Its exact-byte guard binds consumers to the producer.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

import pyarrow as pa  # type: ignore[import-untyped]
from onlyalpha_http_server.chart_studies.schema import ChartStudyCapabilityDto, ChartStudyEvaluateDto
from onlyalpha_http_server.market_data.schema import MarketDataBarWindowDto

from onlyalpha.market_data.durable.range_query import OnlyBarWindowAnchorKind
from tests.application.test_chart_study_product_query import arrange
from tests.application.test_market_data_product import NOW

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test-data/web/chart-studies/query.json"
NUMERIC_CASES = FIXTURE.with_name("numeric-cases.json")


def render() -> str:
    sequence = 0

    def identity() -> UUID:
        nonlocal sequence
        sequence += 1
        return UUID(f"00000000-0000-4000-8000-{sequence:012d}")

    with TemporaryDirectory(prefix="onlyalpha-chart-query-vector-") as raw, patch("uuid.uuid4", side_effect=identity):
        h, query, request, session, _ = arrange(Path(raw), seed=False)  # type: ignore[no-untyped-call]
        h.service._now = lambda: NOW
        from dataclasses import replace

        request = replace(request, target_bar_count=2000)
        end = request.before_ns
        for offset in range(0, 2000, 500):
            result = h.service.acquire_bars(
                request.reference,
                instrument_id=request.instrument_id,
                start_ns=end - (2000 - offset) * 900_000_000_000,
                end_ns=end - (1500 - offset) * 900_000_000_000,
                bar_semantic=request.bar_semantic,
            )
            assert result.status == "COMPLETE"

        history = h.service.query_bars(
            request.reference,
            instrument_id=request.instrument_id,
            anchor_kind=OnlyBarWindowAnchorKind.BEFORE_TIME,
            before_ns=end,
            target_bar_count=request.target_bar_count,
            bar_semantic=request.bar_semantic,
            read_session=session,
        )
        assert history.history_projection_fingerprint is not None
        request = replace(request, expected_history_projection_fingerprint=history.history_projection_fingerprint)
        projection = query.evaluate(request, session)
        return (
            json.dumps(
                {
                    "capability": ChartStudyCapabilityDto.from_model(projection.admission).model_dump(mode="json"),
                    "history": MarketDataBarWindowDto.from_model(history).model_dump(mode="json"),
                    "evaluation": ChartStudyEvaluateDto.from_model(projection).model_dump(mode="json"),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )


def render_numeric_cases() -> str:
    """Real installed-backend point relations on controlled zero inputs; no owning-history claim."""
    from onlyalpha.application.chart_study_numeric import OnlyChartStudyInvocation
    from onlyalpha.quant_assets.catalog import only_discover_quant_asset_providers

    catalog = only_discover_quant_asset_providers()
    invocation = OnlyChartStudyInvocation(catalog.calculation_registry(), catalog)
    families = {"rsi", "atr", "stochastic", "roc", "vwap"}
    cases = []
    for admission in invocation.admissions:
        descriptor = admission.registration.type_definition
        if not admission.support.default_variant or descriptor.type_id.rsplit(".", 1)[-1] not in families:
            continue
        parameters = {
            field.name: Decimal(str(admission.support.default_parameters[field.name]))
            if field.parameter_type.value == "DECIMAL"
            else admission.support.default_parameters[field.name]
            for field in descriptor.parameters.fields
        }
        assert admission.registration.definition_resolver is not None
        definition = admission.registration.definition_resolver.resolve(parameters, {})
        inputs = {
            port.name: pa.array([index * 900_000_000_000 for index in range(30)], type=pa.int64())
            if port.data_type.value == "INTEGER"
            else pa.array([Decimal(0)] * 30, type=pa.decimal128(38, 18))
            for port in definition.inputs
        }
        result = invocation._invoke_numeric(
            parameters,
            inputs,
            type_id=descriptor.type_id,
            semantic_version=descriptor.semantic_version,
            capability_fingerprint=admission.fingerprint,
        )
        output = admission.support.series[0].output_name
        port = next(item for item in definition.outputs if item.name == output)
        for index in sorted({0, 29}):
            value = result.outputs[output][index].as_py()
            cases.append(
                {
                    "type_id": descriptor.type_id,
                    "semantic_version": descriptor.semantic_version,
                    "output_name": output,
                    "nullable": port.nullable,
                    "value": None if value is None else format(value, "f"),
                    "readiness": result.readiness[output].states[index].as_py(),
                    "reason": result.readiness[output].reasons[index].as_py(),
                }
            )
    assert len(cases) == 10
    return (
        json.dumps(
            {"schema_version": 1, "source_kind": "INSTALLED_CALCULATION_BACKEND", "cases": cases},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("write", "check"))
    mode = parser.parse_args().mode
    rendered = render()
    numeric_cases = render_numeric_cases()
    if mode == "write":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(rendered)
        NUMERIC_CASES.write_text(numeric_cases)
    elif FIXTURE.read_text() != rendered or NUMERIC_CASES.read_text() != numeric_cases:
        raise SystemExit("Chart Query vector stale; run scripts/chart_study_query_fixture.py write")


if __name__ == "__main__":
    main()

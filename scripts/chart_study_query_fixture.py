"""Regenerate the synthetic cross-language Chart Query mutation vector.

This uses the installed SPI and owning test service, not a production admission
or real venue certification. Its exact-byte guard binds consumers to the producer.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

from onlyalpha_http_server.chart_studies.schema import ChartStudyCapabilityDto, ChartStudyEvaluateDto
from onlyalpha_http_server.market_data.schema import MarketDataBarWindowDto

from onlyalpha.market_data.durable.range_query import OnlyBarWindowAnchorKind
from tests.application.test_chart_study_product_query import arrange
from tests.application.test_market_data_product import NOW

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test-data/web/chart-studies/query.json"


def render() -> str:
    sequence = 0

    def identity():
        nonlocal sequence
        sequence += 1
        return UUID(f"00000000-0000-4000-8000-{sequence:012d}")

    with TemporaryDirectory(prefix="onlyalpha-chart-query-vector-") as raw, patch("uuid.uuid4", side_effect=identity):
        h, query, request, session, _ = arrange(Path(raw), seed=False)
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("write", "check"))
    mode = parser.parse_args().mode
    rendered = render()
    if mode == "write":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(rendered)
    elif FIXTURE.read_text() != rendered:
        raise SystemExit("Chart Query vector stale; run scripts/chart_study_query_fixture.py write")


if __name__ == "__main__":
    main()

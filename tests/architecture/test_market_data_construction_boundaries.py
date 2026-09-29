"""Construction authority and semantic vocabulary stay on their owning boundaries."""

import json
import re
from pathlib import Path

from onlyalpha_http_server.market_data.schema import MarketDataBarSemanticDto

from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyPriceType
from onlyalpha.domain.market import OnlyBarFormationKind, OnlyBarSemantic

ROOT = Path(__file__).resolve().parents[2]


def test_backtest_loads_graph_provider_inputs_and_manager_uses_registry() -> None:
    backtest = (ROOT / "src/onlyalpha/runtime/backtest/factory.py").read_text(encoding="utf-8")
    manager = (ROOT / "src/onlyalpha/market_data/aggregation/manager.py").read_text(encoding="utf-8")
    graph = (ROOT / "src/onlyalpha/market_data/resolution.py").read_text(encoding="utf-8")
    compiler = (ROOT / "src/onlyalpha/market_data/aggregation/compiler.py").read_text(encoding="utf-8")

    assert "_configured_construction_graph" in backtest
    assert "graph.provider_inputs" in backtest
    assert "subscription.bar_types" not in backtest
    assert "OnlyTimeBarAggregator" not in manager
    assert "aggregation.time_bar" not in manager
    assert "create_executor(dependency" in manager
    assert "outgoing_by_lane" in compiler
    assert "source_lane_id" in manager
    assert "if item.accepts(fact)" not in manager
    assert "OnlyTradeInputType" in graph
    assert "class OnlyTradeInputType" in (ROOT / "src/onlyalpha/domain/market.py").read_text(encoding="utf-8")
    sim = (ROOT / "src/onlyalpha/runtime/sim/factory.py").read_text(encoding="utf-8")
    streaming = (ROOT / "src/onlyalpha/runtime/streaming/runtime.py").read_text(encoding="utf-8")
    assert "only_strategy_market_data_graph" in sim
    assert "only_project_construction_provider_requirement" in sim
    assert "instrument_ids = frozenset(item.instrument_id for item in construction_graph.provider_inputs)" in sim
    assert "only_historical_market_data_input_plan" in backtest
    assert "OnlyHistoricalTradeRequest" in streaming
    assert "load_trades(trade_request)" in streaming
    assert "OnlyTradeConstructionUpdateResult" in streaming
    assert "if item.target.semantic.is_fixed_duration" in sim
    assert "construction_graph=construction_graph" in sim
    assert "self._construction_graph.provider_inputs" in streaming
    assert "OnlyTradeProcessingConsequence.CONSTRUCTION_ONLY" in streaming
    assert "data_type is OnlyMarketDataType.TRADE" in streaming
    assert "provider-input recovery has no confirmed frontier" in streaming
    assert "_construction_recovery_inputs = construction_graph.provider_inputs" in streaming
    assert "CONSTRUCTION_EXECUTOR_RESULT_CONTRACT_VIOLATION" in manager
    assert "TRADE_CONSTRUCTION_OUTPUT_BAR_TYPE_DUPLICATE" in (ROOT / "src/onlyalpha/market_data/pipeline.py").read_text(
        encoding="utf-8"
    )


def test_transport_market_data_vocabularies_match_domain() -> None:
    long_bar = OnlyBarSemantic.fixed_duration(720)
    assert MarketDataBarSemanticDto.from_model(long_bar).to_model() == long_bar
    schema = MarketDataBarSemanticDto.model_json_schema()
    price = schema["$defs"]["OnlyPriceType"]["enum"]
    assert set(price) == {item.value for item in OnlyPriceType}
    assert MarketDataBarSemanticDto.model_fields["price_type"].annotation is OnlyPriceType

    web = (ROOT / "packages/onlyalpha-web-console/src/api/marketData/model.ts").read_text(encoding="utf-8")
    http = (ROOT / "packages/onlyalpha-web-console/src/api/marketData/http.generated.ts").read_text(encoding="utf-8")
    stream = (ROOT / "packages/onlyalpha-web-console/src/api/marketData/stream.generated.ts").read_text(
        encoding="utf-8"
    )
    for text in (web, http, stream):
        price_match = re.search(r"(?:price_type|OnlyPriceTypeSchema)\s*(?::|=)\s*z\.enum\((\[[^\]]+\])\)", text)
        adjustment_match = re.search(r"adjustment_policy:\s*z\.enum\((\[[^\]]+\])\)", text)
        assert price_match is not None and adjustment_match is not None
        assert set(json.loads(price_match.group(1))) == {item.value for item in OnlyPriceType}
        assert set(json.loads(adjustment_match.group(1))) == {item.value for item in OnlyAdjustmentType}
        assert set(re.findall(r'kind:\s*z\.literal\("([A-Z_]+)"\)', text)) == {
            item.value for item in OnlyBarFormationKind
        }

    wire = json.loads((ROOT / "contracts/product-api/v2/market-data-stream.schema.json").read_text())
    assert "INDEX" not in json.dumps(wire)

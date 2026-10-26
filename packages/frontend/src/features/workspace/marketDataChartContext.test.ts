import { marketDataBarSemantic } from "../../api/marketData/model";
import { FIXTURE_REFERENCE } from "../../test/marketDataClient";
import { onlyMarketDataChartContextKey } from "./marketDataChartContext";
it("fences context by exact Source identity including the expected type, instrument and semantic", () => {
    const semantic = marketDataBarSemantic(1),
        base = onlyMarketDataChartContextKey(FIXTURE_REFERENCE, "BTCUSDT.TEST", semantic);
    for (const reference of [
        { ...FIXTURE_REFERENCE, integration_id: "other" },
        { ...FIXTURE_REFERENCE, integration_revision_fingerprint: "b".repeat(64) },
        { ...FIXTURE_REFERENCE, expected_type_id: "another.source" }
    ])
        expect(onlyMarketDataChartContextKey(reference, "BTCUSDT.TEST", semantic)).not.toBe(base);
    expect(onlyMarketDataChartContextKey(FIXTURE_REFERENCE, "ETHUSDT.TEST", semantic)).not.toBe(
        base
    );
    expect(
        onlyMarketDataChartContextKey(FIXTURE_REFERENCE, "BTCUSDT.TEST", marketDataBarSemantic(7))
    ).not.toBe(base);
});

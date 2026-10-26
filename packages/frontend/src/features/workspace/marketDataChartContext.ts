import {
    marketDataBarSemanticSchema,
    type MarketDataBarSemantic,
    type MarketDataSourceReference
} from "../../api/marketData/model";

export const onlyMarketDataChartContextKey = (
    reference: MarketDataSourceReference,
    instrumentId: string,
    barSemantic: MarketDataBarSemantic
): string =>
    JSON.stringify([
        reference.integration_id,
        reference.integration_revision_fingerprint,
        reference.expected_type_id ?? null,
        instrumentId,
        marketDataBarSemanticSchema.parse(barSemantic)
    ]);

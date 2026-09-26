import type { MarketDataApiClient, MarketDataBarsQuery } from "../api/marketData/client";
import { MarketDataWebError } from "../api/marketData/client";
import type {
    MarketDataAcquisition,
    MarketDataBars,
    MarketDataInstrument,
    MarketDataSource,
    MarketDataSourceReference,
    MarketDataSourceSelection
} from "../api/marketData/model";

const unused = (): Promise<never> => Promise.reject(new Error("unused Market Data API method"));

export const FIXTURE_SELECTION: MarketDataSourceSelection = {
    integration_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    integration_revision_fingerprint: "a".repeat(64),
    type_id: "test.market_data",
    source_id: "test.market_data.live",
    environment: "LIVE"
};

export const FIXTURE_REFERENCE: MarketDataSourceReference = {
    integration_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    integration_revision_fingerprint: "a".repeat(64),
    expected_type_id: "test.market_data"
};

export function marketDataSource(overrides: Partial<MarketDataSource> = {}): MarketDataSource {
    return {
        integration_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        integration_revision_fingerprint: "a".repeat(64),
        display_name: "Fixture Source",
        type_id: "test.market_data",
        source_id: "test.market_data.live",
        environment: "LIVE",
        ...overrides
    };
}

/** Composed exactly like a service that publishes the fixture source. */
export const eligibleMarketDataSources = (
    sources: readonly MarketDataSource[] = [marketDataSource()]
): readonly MarketDataSource[] => sources;

export function marketDataInstrument(
    overrides: Partial<MarketDataInstrument> = {}
): MarketDataInstrument {
    return {
        instrument_id: "BTCUSDT.TEST",
        display_symbol: "BTCUSDT",
        venue: "TEST",
        market: "SPOT",
        asset_class: "CRYPTOCURRENCY",
        instrument_type: "CRYPTO_SPOT",
        status: "ACTIVE",
        market_data_capabilities: ["BAR_1M_EXTERNAL_RAW"],
        ...overrides
    };
}

export function marketDataBars(overrides: Partial<MarketDataBars> = {}): MarketDataBars {
    return {
        schema_version: 1,
        source_selection: FIXTURE_SELECTION,
        instrument_id: "BTCUSDT.TEST",
        display_symbol: "BTCUSDT",
        venue: "TEST",
        market: "SPOT",
        bar_specification: "1m",
        aggregation_source: "EXTERNAL",
        adjustment: "RAW",
        closed_only: true,
        start_ns: "1767225600000000000",
        end_ns: "1767225720000000000",
        coverage: {
            status: "COMPLETE",
            manifest_id: "manifest:" + "c".repeat(64),
            manifest_fingerprint: "c".repeat(64),
            expected_bar_count: 2,
            actual_bar_count: 2,
            issues: [],
            gaps: [],
            planned_acquisition_ranges: []
        },
        revision_id: "market-data-revision:" + "d".repeat(64),
        revision_fingerprint: "d".repeat(64),
        seal_id: "seal:" + "e".repeat(64),
        bars: [
            {
                bar_start_ns: "1767225600000000000",
                bar_end_ns: "1767225660000000000",
                open: "100.00",
                high: "102.00",
                low: "99.00",
                close: "101.00",
                volume: "2.00000",
                closed: true
            },
            {
                bar_start_ns: "1767225660000000000",
                bar_end_ns: "1767225720000000000",
                open: "101.00",
                high: "103.00",
                low: "100.00",
                close: "102.50",
                volume: "1.50000",
                closed: true
            }
        ],
        ...overrides
    };
}

export function marketDataAcquisition(
    overrides: Partial<MarketDataAcquisition> = {}
): MarketDataAcquisition {
    return {
        schema_version: 1,
        acquisition_id: "acquisition:" + "b".repeat(64),
        status: "COMPLETE",
        source_id: "test.market_data.live",
        integration_binding_fingerprint: "f".repeat(64),
        instrument_id: "BTCUSDT.TEST",
        bar_specification: "1m",
        start_ns: "1767225600000000000",
        end_ns: "1767225720000000000",
        provenance: "REST_BACKFILL",
        coverage: marketDataBars().coverage,
        revision_id: "market-data-revision:" + "d".repeat(64),
        revision_fingerprint: "d".repeat(64),
        seal_id: "seal:" + "e".repeat(64),
        failure_detail: null,
        ...overrides
    };
}

export function marketDataClient(
    overrides: Partial<MarketDataApiClient> = {}
): MarketDataApiClient {
    return {
        listSources: () => Promise.resolve([marketDataSource()]),
        listInstruments: () => Promise.resolve([]),
        queryBars: () => Promise.resolve(marketDataBars()),
        createAcquisition: () => Promise.resolve(marketDataAcquisition()),
        getAcquisition: unused,
        ...overrides
    };
}

export function incompleteBars(): MarketDataBars {
    return marketDataBars({
        coverage: {
            status: "INCOMPLETE",
            manifest_id: null,
            manifest_fingerprint: null,
            expected_bar_count: 1440,
            actual_bar_count: 0,
            issues: ["BAR_GRID_INCOMPLETE"],
            gaps: [{ start_ns: "1767225600000000000", end_ns: "1767225720000000000" }],
            planned_acquisition_ranges: [
                { start_ns: "1767225600000000000", end_ns: "1767225720000000000" }
            ]
        },
        revision_id: null,
        revision_fingerprint: null,
        seal_id: null,
        bars: []
    });
}

export { MarketDataWebError };
export type { MarketDataBarsQuery };

import type { MarketDataApiClient, MarketDataBarsQuery } from "../api/marketData/client";
import { MarketDataWebError } from "../api/marketData/client";
import type {
    MarketDataAcquisition,
    MarketDataBars,
    MarketDataInstrument,
    MarketDataSourceSelection
} from "../api/marketData/model";

const unused = (): Promise<never> => Promise.reject(new Error("unused Market Data API method"));

export const FIXTURE_SELECTION: MarketDataSourceSelection = {
    integration_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    integration_revision_fingerprint: "a".repeat(64),
    type_id: "test.market_data",
    source_id: "test.market_data"
};

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
        start_ns: 1_767_225_600_000_000_000,
        end_ns: 1_767_225_720_000_000_000,
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
                bar_start_ns: 1_767_225_600_000_000_000,
                bar_end_ns: 1_767_225_660_000_000_000,
                open: "100.00",
                high: "102.00",
                low: "99.00",
                close: "101.00",
                volume: "2.00000",
                closed: true
            },
            {
                bar_start_ns: 1_767_225_660_000_000_000,
                bar_end_ns: 1_767_225_720_000_000_000,
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
        source_id: "test.market_data",
        integration_binding_fingerprint: "f".repeat(64),
        instrument_id: "BTCUSDT.TEST",
        bar_specification: "1m",
        start_ns: 1_767_225_600_000_000_000,
        end_ns: 1_767_225_720_000_000_000,
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
            gaps: [{ start_ns: 1_767_225_600_000_000_000, end_ns: 1_767_225_720_000_000_000 }],
            planned_acquisition_ranges: [
                { start_ns: 1_767_225_600_000_000_000, end_ns: 1_767_225_720_000_000_000 }
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

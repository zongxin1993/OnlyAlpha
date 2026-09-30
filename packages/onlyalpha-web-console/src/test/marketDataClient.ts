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
import { marketDataBarSemantic } from "../api/marketData/model";

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
        time_bar_capability: {
            provider_base_semantic: marketDataBarSemantic(1),
            derived_algorithm: "TIME_BAR@1",
            minimum_window_minutes: 1,
            maximum_window_minutes: 240
        },
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
        bar_semantic: marketDataBarSemantic(1),
        closed_only: true,
        anchor_kind: "BEFORE_TIME",
        requested_before_ns: "1767225720000000000",
        requested_bar_count: 2,
        resolved_start_ns: "1767225600000000000",
        resolved_end_ns: "1767225720000000000",
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
        revision_evidence: [
            {
                revision_id: "market-data-revision:" + "d".repeat(64),
                revision_fingerprint: "d".repeat(64),
                manifest_id: "manifest:" + "c".repeat(64),
                manifest_fingerprint: "c".repeat(64),
                seal_id: "seal:" + "e".repeat(64),
                covered_start_ns: "1767225600000000000",
                covered_end_ns: "1767225720000000000"
            }
        ],
        history_projection_fingerprint: "8".repeat(64),
        derived_projection_fingerprint: null,
        aggregation_semantics_version: null,
        calendar_fingerprint: null,
        resolution_mode: "PROVIDER_NATIVE",
        resolution_plan_fingerprint: "f".repeat(64),
        resume_after_sequence: "29453761",
        resume_plan_fingerprint: "f".repeat(64),
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
        bar_semantic: marketDataBarSemantic(1),
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

/** A contract fake echoes the exact request, not a fixed BEFORE_TIME/count fixture. */
export function marketDataBarsForQuery(
    query: MarketDataBarsQuery,
    overrides: Partial<MarketDataBars> = {}
): MarketDataBars {
    return marketDataBars({
        instrument_id: query.instrument_id,
        bar_semantic: query.bar_semantic,
        anchor_kind: query.anchor_kind,
        requested_before_ns: query.before_ns ?? null,
        requested_bar_count: query.target_bar_count,
        ...overrides
    });
}

export function marketDataClient(
    overrides: Partial<MarketDataApiClient> = {}
): MarketDataApiClient {
    return {
        listSources: () => Promise.resolve([marketDataSource()]),
        listInstruments: () => Promise.resolve([]),
        queryBars: (_reference, query) => Promise.resolve(marketDataBarsForQuery(query)),
        createAcquisition: () => Promise.resolve(marketDataAcquisition()),
        getAcquisition: unused,
        ...overrides
    };
}

export function incompleteBars(overrides: Partial<MarketDataBars> = {}): MarketDataBars {
    return marketDataBars({
        anchor_kind: "LATEST_CLOSED",
        requested_before_ns: null,
        requested_bar_count: 1440,
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
        revision_evidence: [],
        history_projection_fingerprint: null,
        derived_projection_fingerprint: null,
        resume_after_sequence: null,
        resume_plan_fingerprint: null,
        bars: [],
        ...overrides
    });
}

export { MarketDataWebError };
export type { MarketDataBarsQuery };

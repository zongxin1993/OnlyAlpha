import type { z } from "zod";
import {
    marketDataAcquisitionSchema,
    marketDataBarsSchema,
    marketDataErrorSchema,
    marketDataInstrumentListSchema,
    marketDataSourceListSchema,
    type MarketDataAcquisition,
    type MarketDataBars,
    type MarketDataInstrument,
    type MarketDataSource,
    type MarketDataSourceReference
} from "./model";

export class MarketDataWebError extends Error {
    constructor(
        readonly code: string,
        message: string,
        readonly status?: number
    ) {
        super(message);
        this.name = "MarketDataWebError";
    }
}

export interface MarketDataBarsQuery {
    readonly instrument_id: string;
    /** Canonical decimal nanoseconds; never a JSON number. */
    readonly start_ns: string;
    readonly end_ns: string;
    readonly bar_specification?: string;
}

export type { MarketDataSource, MarketDataSourceReference };

export interface MarketDataApiClient {
    listSources(signal?: AbortSignal): Promise<readonly MarketDataSource[]>;
    listInstruments(
        reference: MarketDataSourceReference,
        query: string,
        signal?: AbortSignal
    ): Promise<readonly MarketDataInstrument[]>;
    queryBars(
        reference: MarketDataSourceReference,
        query: MarketDataBarsQuery,
        signal?: AbortSignal
    ): Promise<MarketDataBars>;
    createAcquisition(
        reference: MarketDataSourceReference,
        query: MarketDataBarsQuery
    ): Promise<MarketDataAcquisition>;
    getAcquisition(
        reference: MarketDataSourceReference,
        acquisitionId: string,
        signal?: AbortSignal
    ): Promise<MarketDataAcquisition>;
}

async function request<T>(schema: z.ZodType<T>, url: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body !== undefined) headers.set("Content-Type", "application/json");
    let response: Response;
    try {
        response = await fetch(url, { ...init, headers });
    } catch {
        throw new MarketDataWebError("TRANSPORT_ERROR", "Market Data API is unavailable");
    }
    let body: unknown;
    try {
        body = await response.json();
    } catch {
        throw new MarketDataWebError(
            "CONTRACT_ERROR",
            "Market Data API returned invalid JSON",
            response.status
        );
    }
    if (!response.ok) {
        const admitted = marketDataErrorSchema.safeParse(body);
        if (!admitted.success)
            throw new MarketDataWebError(
                "CONTRACT_ERROR",
                "Market Data error response violates contract",
                response.status
            );
        throw new MarketDataWebError(
            admitted.data.error.code,
            admitted.data.error.detail,
            response.status
        );
    }
    const admitted = schema.safeParse(body);
    if (!admitted.success)
        throw new MarketDataWebError(
            "CONTRACT_ERROR",
            "Market Data response violates contract",
            response.status
        );
    return admitted.data;
}

function referenceParams(reference: MarketDataSourceReference): URLSearchParams {
    const params = new URLSearchParams({
        integration_id: reference.integration_id,
        integration_revision_fingerprint: reference.integration_revision_fingerprint
    });
    if (reference.expected_type_id !== undefined)
        params.set("expected_type_id", reference.expected_type_id);
    return params;
}

function barsParams(
    reference: MarketDataSourceReference,
    query: MarketDataBarsQuery
): URLSearchParams {
    const params = referenceParams(reference);
    params.set("instrument_id", query.instrument_id);
    params.set("start_ns", query.start_ns);
    params.set("end_ns", query.end_ns);
    params.set("bar_specification", query.bar_specification ?? "1m");
    return params;
}

const read = (signal?: AbortSignal): RequestInit => (signal === undefined ? {} : { signal });

export class FetchMarketDataApiClient implements MarketDataApiClient {
    async listSources(signal?: AbortSignal) {
        const value = await request(
            marketDataSourceListSchema,
            "/api/v2/market-data/sources",
            read(signal)
        );
        return value.sources;
    }
    async listInstruments(
        reference: MarketDataSourceReference,
        query: string,
        signal?: AbortSignal
    ) {
        const params = referenceParams(reference);
        params.set("query", query);
        const value = await request(
            marketDataInstrumentListSchema,
            `/api/v2/market/instruments?${params.toString()}`,
            read(signal)
        );
        return value.instruments;
    }
    async queryBars(
        reference: MarketDataSourceReference,
        query: MarketDataBarsQuery,
        signal?: AbortSignal
    ) {
        return request(
            marketDataBarsSchema,
            `/api/v2/market-data/bars?${barsParams(reference, query).toString()}`,
            read(signal)
        );
    }
    async createAcquisition(reference: MarketDataSourceReference, query: MarketDataBarsQuery) {
        return request(marketDataAcquisitionSchema, "/api/v2/market-data/acquisitions", {
            method: "POST",
            body: JSON.stringify({
                source_reference: reference,
                instrument_id: query.instrument_id,
                start_ns: query.start_ns,
                end_ns: query.end_ns,
                bar_specification: query.bar_specification ?? "1m",
                provenance: "REST_BACKFILL"
            })
        });
    }
    async getAcquisition(
        reference: MarketDataSourceReference,
        acquisitionId: string,
        signal?: AbortSignal
    ) {
        return request(
            marketDataAcquisitionSchema,
            `/api/v2/market-data/acquisitions/${encodeURIComponent(acquisitionId)}?${referenceParams(reference).toString()}`,
            read(signal)
        );
    }
}

import type { z } from "zod";
import {
    marketDataAcquisitionSchema,
    marketDataBarsSchema,
    marketDataErrorSchema,
    marketDataInstrumentListSchema,
    type MarketDataAcquisition,
    type MarketDataBars,
    type MarketDataInstrument,
    type MarketDataSourceSelection
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
    readonly start_ns: number;
    readonly end_ns: number;
    readonly bar_specification?: string;
}

export interface MarketDataApiClient {
    listInstruments(
        selection: MarketDataSourceSelection,
        query: string,
        signal?: AbortSignal
    ): Promise<readonly MarketDataInstrument[]>;
    queryBars(
        selection: MarketDataSourceSelection,
        query: MarketDataBarsQuery,
        signal?: AbortSignal
    ): Promise<MarketDataBars>;
    createAcquisition(
        selection: MarketDataSourceSelection,
        query: MarketDataBarsQuery
    ): Promise<MarketDataAcquisition>;
    getAcquisition(
        selection: MarketDataSourceSelection,
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

function selectionParams(selection: MarketDataSourceSelection): URLSearchParams {
    return new URLSearchParams({
        integration_id: selection.integration_id,
        integration_revision_fingerprint: selection.integration_revision_fingerprint,
        type_id: selection.type_id,
        source_id: selection.source_id
    });
}

function barsParams(
    selection: MarketDataSourceSelection,
    query: MarketDataBarsQuery
): URLSearchParams {
    const params = selectionParams(selection);
    params.set("instrument_id", query.instrument_id);
    params.set("start_ns", String(query.start_ns));
    params.set("end_ns", String(query.end_ns));
    params.set("bar_specification", query.bar_specification ?? "1m");
    return params;
}

const read = (signal?: AbortSignal): RequestInit => (signal === undefined ? {} : { signal });

export class FetchMarketDataApiClient implements MarketDataApiClient {
    async listInstruments(
        selection: MarketDataSourceSelection,
        query: string,
        signal?: AbortSignal
    ) {
        const params = selectionParams(selection);
        params.set("query", query);
        const value = await request(
            marketDataInstrumentListSchema,
            `/api/v2/market/instruments?${params.toString()}`,
            read(signal)
        );
        return value.instruments;
    }
    async queryBars(
        selection: MarketDataSourceSelection,
        query: MarketDataBarsQuery,
        signal?: AbortSignal
    ) {
        return request(
            marketDataBarsSchema,
            `/api/v2/market-data/bars?${barsParams(selection, query).toString()}`,
            read(signal)
        );
    }
    async createAcquisition(selection: MarketDataSourceSelection, query: MarketDataBarsQuery) {
        return request(marketDataAcquisitionSchema, "/api/v2/market-data/acquisitions", {
            method: "POST",
            body: JSON.stringify({
                schema_version: 1,
                source_selection: selection,
                instrument_id: query.instrument_id,
                start_ns: query.start_ns,
                end_ns: query.end_ns,
                bar_specification: query.bar_specification ?? "1m",
                provenance: "REST_BACKFILL"
            })
        });
    }
    async getAcquisition(
        selection: MarketDataSourceSelection,
        acquisitionId: string,
        signal?: AbortSignal
    ) {
        return request(
            marketDataAcquisitionSchema,
            `/api/v2/market-data/acquisitions/${encodeURIComponent(acquisitionId)}?${selectionParams(selection).toString()}`,
            read(signal)
        );
    }
}

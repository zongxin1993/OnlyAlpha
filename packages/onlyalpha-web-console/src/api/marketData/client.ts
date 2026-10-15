import type { z } from "zod";
import { LocalReadCredentials } from "./localReadCredentials";
import {
    marketDataAcquisitionSchema,
    marketDataBarsSchema,
    marketDataErrorSchema,
    marketDataInstrumentListSchema,
    marketDataSourceListSchema,
    type MarketDataAcquisition,
    type MarketDataBarSemantic,
    type MarketDataBars,
    type MarketDataInstrument,
    type MarketDataSource,
    type MarketDataSourceReference
} from "./model";

export class MarketDataWebError extends Error {
    constructor(
        readonly code: string,
        message: string,
        readonly status?: number,
        readonly retryAfterSeconds: number | null = null
    ) {
        super(message);
        this.name = "MarketDataWebError";
    }
}

/** A bounded scheduling hint, never a closed-history or Source proof. */
export function windowRetryAfterSeconds(
    response: Response,
    code: string,
    phase: string
): number | null {
    if (response.status !== 503 || code !== "MARKET_DATA_WINDOW_NOT_CLOSED" || phase !== "QUERY")
        return null;
    const value = response.headers.get("Retry-After");
    if (value === null || !/^[1-9][0-9]*$/.test(value)) return null;
    const seconds = Number(value);
    // setTimeout uses signed 32-bit milliseconds; never clamp overflow to an early retry.
    return Number.isSafeInteger(seconds) && seconds * 1000 <= 2_147_483_647 ? seconds : null;
}

export interface MarketDataBarsQuery {
    readonly instrument_id: string;
    readonly anchor_kind: "LATEST_CLOSED" | "BEFORE_TIME";
    readonly before_ns?: string;
    readonly target_bar_count: number;
    readonly bar_semantic: MarketDataBarSemantic;
}

export interface MarketDataAcquisitionQuery {
    readonly instrument_id: string;
    /** Exact server-planned canonical decimal nanoseconds. */
    readonly start_ns: string;
    readonly end_ns: string;
    readonly bar_semantic: MarketDataBarSemantic;
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
        query: MarketDataAcquisitionQuery
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
            response.status,
            windowRetryAfterSeconds(response, admitted.data.error.code, admitted.data.error.phase)
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

async function protectedRead<T>(
    credentials: LocalReadCredentials,
    schema: z.ZodType<T>,
    url: string,
    signal?: AbortSignal
): Promise<T> {
    const captured = credentials.capture();
    const headers = new Headers();
    if (captured.bearer !== null) headers.set("Authorization", `Bearer ${captured.bearer}`);
    const value = await request(schema, url, {
        ...read(signal),
        headers,
        credentials: credentials.localSession ? "same-origin" : "omit"
    });
    if (!credentials.isCurrent(captured.generation))
        throw new MarketDataWebError("LOCAL_READ_GENERATION_CHANGED", "本地访问已改变");
    return value;
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
    params.set("anchor_kind", query.anchor_kind);
    params.set("target_bar_count", String(query.target_bar_count));
    if (query.before_ns !== undefined) params.set("before_ns", query.before_ns);
    params.set("bar_semantic", JSON.stringify(query.bar_semantic));
    return params;
}

const read = (signal?: AbortSignal): RequestInit => (signal === undefined ? {} : { signal });

export class FetchMarketDataApiClient implements MarketDataApiClient {
    constructor(private readonly credentials = new LocalReadCredentials()) {}

    async listSources(signal?: AbortSignal) {
        const value = await protectedRead(
            this.credentials,
            marketDataSourceListSchema,
            "/api/v2/market-data/sources",
            signal
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
        const value = await protectedRead(
            this.credentials,
            marketDataInstrumentListSchema,
            `/api/v2/market/instruments?${params.toString()}`,
            signal
        );
        if (
            value.source_selection.integration_id !== reference.integration_id ||
            value.source_selection.integration_revision_fingerprint !==
                reference.integration_revision_fingerprint ||
            (reference.expected_type_id !== undefined &&
                value.source_selection.type_id !== reference.expected_type_id)
        )
            throw new MarketDataWebError(
                "CONTRACT_ERROR",
                "Instrument response belongs to a different source reference"
            );
        return value.instruments;
    }
    async queryBars(
        reference: MarketDataSourceReference,
        query: MarketDataBarsQuery,
        signal?: AbortSignal
    ) {
        const result = await protectedRead(
            this.credentials,
            marketDataBarsSchema,
            `/api/v2/market-data/bars?${barsParams(reference, query).toString()}`,
            signal
        );
        if (JSON.stringify(result.bar_semantic) !== JSON.stringify(query.bar_semantic))
            throw new MarketDataWebError(
                "MARKET_DATA_HISTORY_RESPONSE_MISMATCH",
                "Market Data returned a different Bar Specification"
            );
        return result;
    }
    async createAcquisition(
        reference: MarketDataSourceReference,
        query: MarketDataAcquisitionQuery
    ) {
        const captured = this.credentials.capture();
        if (captured.bearer !== null)
            throw new MarketDataWebError("LOCAL_READ_FORBIDDEN", "只读凭据不能获取行情");
        const result = await request(
            marketDataAcquisitionSchema,
            "/api/v2/market-data/acquisitions",
            {
                method: "POST",
                credentials: this.credentials.localSession ? "same-origin" : "omit",
                body: JSON.stringify({
                    source_reference: reference,
                    instrument_id: query.instrument_id,
                    start_ns: query.start_ns,
                    end_ns: query.end_ns,
                    bar_semantic: query.bar_semantic,
                    provenance: "REST_BACKFILL"
                })
            }
        );
        if (!this.credentials.isCurrent(captured.generation))
            throw new MarketDataWebError("LOCAL_READ_GENERATION_CHANGED", "本地访问已改变");
        return result;
    }
    async getAcquisition(
        reference: MarketDataSourceReference,
        acquisitionId: string,
        signal?: AbortSignal
    ) {
        return protectedRead(
            this.credentials,
            marketDataAcquisitionSchema,
            `/api/v2/market-data/acquisitions/${encodeURIComponent(acquisitionId)}?${referenceParams(reference).toString()}`,
            signal
        );
    }
}

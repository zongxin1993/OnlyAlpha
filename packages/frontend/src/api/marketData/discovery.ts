import { z } from "zod";
import { MarketDataWebError, protectedRead } from "./client";
import type { LocalReadCredentials } from "./localReadCredentials";
import {
    marketDataInstrumentSchema,
    marketDataSourceSelectionSchema,
    type MarketDataSource,
    type MarketDataSourceSelection
} from "./model";

const outcome = z.enum(["COMPLETE", "TIMEOUT", "UNAVAILABLE", "UNSUPPORTED"]);
const decimal = z
    .string()
    .max(128)
    .regex(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/);
const quoteSchema = z
    .strictObject({
        instrument_id: z.string().min(1),
        status: z.enum(["AVAILABLE", "UNAVAILABLE"]),
        last_price: decimal.nullable(),
        change_pct: decimal.nullable(),
        change_basis: z.enum(["ROLLING_24H", "PREVIOUS_CLOSE"]).nullable(),
        ts_event_ns: z
            .string()
            .regex(/^[1-9][0-9]*$/)
            .max(25)
            .nullable()
    })
    .refine((item) =>
        item.status === "AVAILABLE"
            ? item.last_price !== null &&
              item.ts_event_ns !== null &&
              (item.change_pct === null) === (item.change_basis === null)
            : item.last_price === null &&
              item.change_pct === null &&
              item.change_basis === null &&
              item.ts_event_ns === null
    );

export const searchSchema = z.strictObject({
    schema_version: z.literal(1),
    results: z
        .array(
            z.strictObject({
                source_selection: marketDataSourceSelectionSchema,
                instrument: marketDataInstrumentSchema
            })
        )
        .max(100),
    sources: z.array(
        z.strictObject({
            source_selection: marketDataSourceSelectionSchema,
            status: outcome,
            asset_classes: z.array(z.string()),
            truncated: z.boolean()
        })
    ),
    truncated: z.boolean()
});
export const quotesSchema = z.strictObject({
    schema_version: z.literal(1),
    source_selection: marketDataSourceSelectionSchema,
    quotes: z.array(quoteSchema).max(25),
    status: outcome
});
export type InstrumentSearch = z.infer<typeof searchSchema>;
export type InstrumentSearchResult = InstrumentSearch["results"][number];
export type MarketQuote = z.infer<typeof quoteSchema>;
export type MarketQuotes = z.infer<typeof quotesSchema>;
export const sourceSelectionKey = (source: MarketDataSourceSelection): string =>
    JSON.stringify([
        source.integration_id,
        source.integration_revision_fingerprint,
        source.type_id,
        source.source_id,
        source.environment
    ]);
const invalid = (): never => {
    throw new MarketDataWebError("CONTRACT_ERROR", "商品或报价响应关系不完整");
};

export class FetchMarketDiscoveryClient {
    constructor(private readonly credentials: LocalReadCredentials) {}
    async search(
        query: string,
        assetClass: string,
        signal?: AbortSignal,
        instrumentTypes: readonly string[] = []
    ): Promise<InstrumentSearch> {
        const params = new URLSearchParams({ query, limit: "25" });
        if (assetClass) params.set("asset_class", assetClass);
        for (const type of instrumentTypes) params.append("instrument_types", type);
        const value = await protectedRead(
            this.credentials,
            searchSchema,
            `/api/v2/market/instruments/search?${params}`,
            signal
        );
        const sources = new Map(
            value.sources.map((item) => [sourceSelectionKey(item.source_selection), item])
        );
        if (sources.size !== value.sources.length) invalid();
        const identities = new Set<string>();
        for (const item of value.results) {
            const key = sourceSelectionKey(item.source_selection);
            const source = sources.get(key);
            const identity = key + ":" + item.instrument.instrument_id;
            if (
                source?.status !== "COMPLETE" ||
                identities.has(identity) ||
                (assetClass && item.instrument.asset_class !== assetClass) ||
                (instrumentTypes.length > 0 &&
                    !instrumentTypes.includes(item.instrument.instrument_type))
            )
                invalid();
            identities.add(identity);
        }
        return value;
    }
    async quotes(source: MarketDataSource, instrumentIds: readonly string[], signal?: AbortSignal) {
        const params = new URLSearchParams({
            integration_id: source.integration_id,
            integration_revision_fingerprint: source.integration_revision_fingerprint,
            expected_type_id: source.type_id
        });
        for (const id of instrumentIds) params.append("instrument_ids", id);
        const value = await protectedRead(
            this.credentials,
            quotesSchema,
            `/api/v2/market-data/quotes?${params}`,
            signal
        );
        const selection = value.source_selection;
        if (
            selection.integration_id !== source.integration_id ||
            selection.integration_revision_fingerprint !==
                source.integration_revision_fingerprint ||
            selection.type_id !== source.type_id ||
            selection.source_id !== source.source_id ||
            selection.environment !== source.environment ||
            value.quotes.length !== instrumentIds.length ||
            new Set(value.quotes.map((item) => item.instrument_id)).size !== instrumentIds.length ||
            value.quotes.some((item) => !instrumentIds.includes(item.instrument_id)) ||
            (value.status !== "COMPLETE" &&
                value.quotes.some((item) => item.status === "AVAILABLE"))
        )
            invalid();
        return value;
    }
}
